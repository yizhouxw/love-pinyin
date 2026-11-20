package org.lovepinyin.android

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import android.util.Base64
import com.k2fsa.sherpa.onnx.*
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.URL
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

/** Network exists only in download(); recognition uses verified local files and in-memory audio. */
class LocalRecognition(private val context: Context) {
    private val config = JSONObject(context.assets.open("android-asr.json").bufferedReader().use { it.readText() })
    private val entries = config.getJSONObject("files")
    private val names = entries.keys().asSequence().toList()
    private val root = File(context.noBackupFilesDir,"recognition/${config.getString("revision")}")
    private val installed = File(root,"installed")
    private val staging = File(root,"download")
    private val downloadWorker = Executors.newSingleThreadExecutor()
    val inferenceWorker = Executors.newSingleThreadExecutor()
    private val downloadEpoch = AtomicInteger()
    private val recognitionEpoch = AtomicInteger()
    @Volatile private var state = if (installed.isDirectory) "installed" else "idle"
    @Volatile private var received = 0L
    @Volatile private var connection: HttpURLConnection? = null
    @Volatile private var closed = false
    private var recognizer: OfflineRecognizer? = null // Only accessed on inferenceWorker.
    private var verified = false
    val supported: Boolean get() {
        val memory = ActivityManager.MemoryInfo()
        (context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager).getMemoryInfo(memory)
        return Build.VERSION.SDK_INT >= 29 && Build.SUPPORTED_ABIS.contains("arm64-v8a") && memory.totalMem >= 4_000_000_000L
    }
    private val total = names.sumOf { entries.getJSONObject(it).getLong("bytes") }
    @Synchronized fun status(): JSONObject {
        val current = if (!supported) "unsupported" else state
        return obj("state" to current,"bytes" to total,"received" to received)
    }
    @Synchronized fun download(): JSONObject {
        if (!supported || closed || state == "downloading" || state == "installed" || state == "removing") return status()
        val epoch = downloadEpoch.incrementAndGet()
        state = "downloading"
        downloadWorker.execute {
            try {
                if (installed.exists() && !installed.deleteRecursively()) throw IOException("remove incomplete model")
                staging.mkdirs()
                received = names.sumOf { minOf(File(staging,it).length(),entries.getJSONObject(it).getLong("bytes")) }
                val remaining = total-received
                if (staging.usableSpace < remaining+128L*1024*1024) throw IOException("space")
                for (name in names) {
                    checkDownload(epoch)
                    val info = entries.getJSONObject(name)
                    val destination = File(staging,name).apply { parentFile?.mkdirs() }
                    val size = info.getLong("bytes")
                    if (destination.length() > size) destination.delete()
                    while (destination.length() < size) {
                        checkDownload(epoch)
                        val start = destination.length()
                        val end = minOf(start+8L*1024*1024,size)-1
                        val url = info.getString("url")
                        val conn = URL(url).openConnection() as HttpURLConnection
                        connection = conn
                        conn.connectTimeout = 15000; conn.readTimeout = 30000
                        conn.setRequestProperty("Range","bytes=$start-$end")
                        conn.setRequestProperty("Accept-Encoding","identity")
                        try {
                            val code = conn.responseCode
                            if (conn.url.protocol != "https") throw IOException("redirect")
                            val ranged = code == 206
                            if (!ranged && (code != 200 || start != 0L)) throw IOException("range")
                            if (ranged && conn.getHeaderField("Content-Range") != "bytes $start-$end/$size") throw IOException("range")
                            val expected = if (ranged) end-start+1 else size
                            conn.inputStream.use { input ->
                                RandomAccessFile(destination,"rw").use { out ->
                                    out.seek(start)
                                    var count = 0L
                                    val buffer = ByteArray(65536)
                                    try {
                                        while (true) {
                                            checkDownload(epoch)
                                            val n = input.read(buffer)
                                            if (n < 0) break
                                            if (count+n > expected) throw IOException("length")
                                            out.write(buffer,0,n); count += n; received += n
                                        }
                                        if (count != expected) throw IOException("truncated")
                                        out.fd.sync()
                                    } catch (error: Exception) { out.setLength(start); received -= count; throw error }
                                }
                            }
                        } finally { conn.disconnect(); connection = null }
                    }
                    if (!valid(destination,info)) { received -= destination.length(); destination.delete(); throw IOException("checksum") }
                }
                synchronized(this) {
                    checkDownload(epoch)
                    if (!staging.renameTo(installed)) throw IOException("install")
                    verified = true; state = "installed"
                }
            } catch (_: Exception) { synchronized(this) { if (downloadEpoch.get() == epoch) state = "failed" } }
        }
        return status()
    }
    @Synchronized fun cancel(): JSONObject {
        downloadEpoch.incrementAndGet(); connection?.disconnect()
        if (state == "downloading") state = "idle"
        return status()
    }
    @Synchronized fun remove(): JSONObject {
        cancel(); invalidate(); state = "removing"
        // Serializing with inference ensures mapped weights are released before removal.
        downloadWorker.execute { inferenceWorker.submit {
            recognizer?.release(); recognizer = null; verified = false
            val ok = (!installed.exists() || installed.deleteRecursively()) && (!staging.exists() || staging.deleteRecursively())
            synchronized(this) { state = if (ok) "idle" else "failed"; received = 0 }
        }.get() }
        return status()
    }
    fun invalidate() { recognitionEpoch.incrementAndGet() }
    fun generation() = recognitionEpoch.get()
    private fun checkDownload(epoch: Int) { if (closed || downloadEpoch.get() != epoch) throw IOException("cancelled") }
    private fun valid(file: File, info: JSONObject): Boolean {
        if (!file.isFile || file.length() != info.getLong("bytes")) return false
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input -> val buffer=ByteArray(65536); while (true) { val n=input.read(buffer); if (n<0) break; digest.update(buffer,0,n) } }
        return digest.digest().joinToString("") { "%02x".format(it) } == info.getString("sha256")
    }
    /** Called only by inferenceWorker, with generation captured at bridge arrival. */
    fun recognize(encoded: String, generation: Int): JSONObject {
        if (!supported || closed || generation != recognitionEpoch.get() || status().getString("state") != "installed") return obj("status" to "unavailable")
        return try {
            val samples = pcm(Base64.decode(encoded,Base64.DEFAULT))
            if (samples.size < 1600 || samples.none { kotlin.math.abs(it) > 0.005f }) return obj("status" to "uncertain")
            if (!verified) {
                if (!names.all { valid(File(installed,it),entries.getJSONObject(it)) }) {
                    synchronized(this) { installed.deleteRecursively(); state = "failed" }
                    return obj("status" to "unavailable")
                }
                verified = true
            }
            if (generation != recognitionEpoch.get()) return obj("status" to "unavailable")
            if (recognizer == null) {
                val memory = ActivityManager.MemoryInfo()
                (context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager).getMemoryInfo(memory)
                if (memory.lowMemory || memory.availMem < 2_000_000_000L) return obj("status" to "unavailable")
            }
            if (recognizer == null) recognizer = OfflineRecognizer(config = OfflineRecognizerConfig(
                modelConfig = OfflineModelConfig(qwen3Asr = OfflineQwen3AsrModelConfig(
                    convFrontend = File(installed,"conv_frontend.onnx").path,
                    encoder = File(installed,"encoder.int8.onnx").path,
                    decoder = File(installed,"decoder.int8.onnx").path,
                    tokenizer = File(installed,"tokenizer").path,
                    maxNewTokens = 128,
                ),numThreads = 3,provider = "cpu")))
            val engine = recognizer!!
            val stream = engine.createStream()
            val text = try { stream.acceptWaveform(samples,16000); engine.decode(stream); engine.getResult(stream).text.trim() } finally { stream.release() }
            if (generation != recognitionEpoch.get() || closed) return obj("status" to "unavailable")
            if (text.isBlank()) obj("status" to "uncertain") else if (Build.VERSION.SDK_INT >= 29) {
                val pinyin = android.icu.text.Transliterator.getInstance("Han-Latin").transliterate(text)
                obj("status" to "recognized","transcript" to text,"pinyin" to pinyin)
            } else obj("status" to "unavailable")
        } catch (error: Exception) { android.util.Log.w("LovePinyinASR","recognition unavailable: ${error.javaClass.simpleName}"); obj("status" to "unavailable") } catch (_: OutOfMemoryError) { obj("status" to "unavailable") } catch (_: LinkageError) { obj("status" to "unavailable") }
    }
    fun close() { closed=true; cancel(); invalidate(); downloadWorker.shutdown(); inferenceWorker.execute { recognizer?.release(); recognizer=null }; inferenceWorker.shutdown() }
    companion object {
        /** Strict bounded RIFF parser; skips metadata chunks, never accepts compressed audio. */
        fun pcm(bytes: ByteArray): FloatArray {
            require(bytes.size in 44..960044) { "ANDROID_AUDIO_INVALID" }
            val b = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            fun tag(at: Int) = String(bytes,at,4,Charsets.US_ASCII)
            require(tag(0)=="RIFF" && tag(8)=="WAVE" && b.getInt(4).toLong()+8 == bytes.size.toLong())
            var pos=12; var format=false; var samples: FloatArray? = null
            while (pos+8 <= bytes.size) {
                val length=b.getInt(pos+4); require(length >= 0 && length.toLong()+pos+8 <= bytes.size)
                when (tag(pos)) {
                    "fmt " -> { require(!format && length >= 16 && b.getShort(pos+8).toInt()==1 && b.getShort(pos+10).toInt()==1 && b.getInt(pos+12)==16000 && b.getInt(pos+16)==32000 && b.getShort(pos+20).toInt()==2 && b.getShort(pos+22).toInt()==16); format=true }
                    "data" -> { require(format && samples == null && length%2==0); samples=FloatArray(length/2) { b.getShort(pos+8+it*2)/32768f } }
                }
                pos += 8+length+(length%2)
            }
            require(pos==bytes.size)
            return samples ?: throw IllegalArgumentException("ANDROID_AUDIO_INVALID")
        }
    }
}
