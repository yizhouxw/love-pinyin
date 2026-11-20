package org.lovepinyin.android

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Base64
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** One bounded in-memory PCM session. Never creates an audio file. */
class NativeRecorder(private val onFinished: (String) -> Unit = {}) {
    private data class Capture(val id: String, val device: AudioRecord, val limit: Int) {
        val pcm = ByteArrayOutputStream()
        @Volatile var running = true
        @Volatile var level = 0.0
        var thread: Thread? = null
        @Volatile var failed = false
    }
    private var active: Capture? = null

    @SuppressLint("MissingPermission") // Activity checks the runtime grant immediately before start.
    @Synchronized fun start(id: String, milliseconds: Int) {
        discard()
        require(id.length in 1..100 && milliseconds in 1..30000) { "ANDROID_RECORD_INVALID" }
        val minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        require(minimum > 0) { "ANDROID_AUDIO_UNAVAILABLE" }
        val device = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION,16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,maxOf(minimum,4096))
        if (device.state != AudioRecord.STATE_INITIALIZED) { device.release(); error("ANDROID_AUDIO_UNAVAILABLE") }
        val capture = Capture(id,device,milliseconds*32)
        try { device.startRecording() } catch (error: Exception) { device.release(); throw error }
        if (device.recordingState != AudioRecord.RECORDSTATE_RECORDING) { device.release(); error("ANDROID_AUDIO_UNAVAILABLE") }
        active = capture
        capture.thread = Thread({
            val buffer = ByteArray(2048)
            try {
                while (capture.running) {
                    val count = device.read(buffer,0,buffer.size)
                    if (count <= 0) { if (capture.running) capture.failed = true; break }
                    synchronized(capture) {
                        if (!capture.running) return@synchronized
                        val size = minOf(count,capture.limit-capture.pcm.size())
                        capture.pcm.write(buffer,0,size)
                        var peak = 0
                        for (i in 0 until size-1 step 2) peak = maxOf(peak,kotlin.math.abs(((buffer[i].toInt() and 255) or (buffer[i+1].toInt() shl 8)).toShort().toInt()))
                        capture.level = peak/32768.0
                        if (capture.pcm.size() >= capture.limit) capture.running = false
                    }
                }
            } catch (_: Exception) { capture.failed = true }
            finally { capture.running = false; runCatching { device.stop() }; device.release(); onFinished(id) }
        },"love-pinyin-microphone").apply { start() }
    }
    @Synchronized fun snapshot(id: String, stop: Boolean): String? {
        val capture = active?.takeIf { it.id == id } ?: return null
        if (stop) { capture.running = false; capture.thread?.join(1000); active = null }
        return synchronized(capture) {
            if (capture.failed || capture.pcm.size() < 3200) null
            else Base64.encodeToString(wav(capture.pcm.toByteArray()),Base64.NO_WRAP)
        }
    }
    @Synchronized fun level(id: String) = active?.takeIf { it.id == id }?.level ?: 0.0
    @Synchronized fun discard(id: String? = null) {
        val capture = active ?: return
        if (id != null && capture.id != id) return
        active = null; capture.running = false; capture.thread?.join(1000)
        synchronized(capture) { capture.pcm.reset() }
    }
    companion object {
        fun wav(pcm: ByteArray): ByteArray = ByteBuffer.allocate(44+pcm.size).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray()); putInt(36+pcm.size); put("WAVEfmt ".toByteArray()); putInt(16); putShort(1); putShort(1); putInt(16000); putInt(32000); putShort(2); putShort(16); put("data".toByteArray()); putInt(pcm.size); put(pcm)
        }.array()
    }
}
