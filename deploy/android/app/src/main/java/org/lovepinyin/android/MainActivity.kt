package org.lovepinyin.android

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.TextView
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.util.concurrent.Executors

/** Only installed, allowlisted resources are served. No INTERNET or microphone permission. */
class MainActivity : Activity() {
    private lateinit var page: WebView
    private lateinit var classroom: Classroom
    private lateinit var audio: JSONObject
    private lateinit var webFiles: Set<String>
    private val worker = Executors.newSingleThreadExecutor()
    private var foreground = false
    private var player: MediaPlayer? = null
    private var playbackId = -1
    private var audioId = ""
    private var pendingFile: Pair<String, ByteArray?>? = null
    private var audioFocus: AudioFocusRequest? = null
    private fun data(name: String) = JSONObject(assets.open("pack/Data/$name.json").bufferedReader().use { it.readText() })
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        try {
            audio = data("audio")
            webFiles = org.json.JSONArray(assets.open("pack/Data/web-files.json").bufferedReader().use { it.readText() }).strings().toSet()
            classroom = Classroom(this, data("classroom"))
        } catch (_: Exception) {
            setContentView(TextView(this).apply { text = "本机学习资料暂时无法读取。请保留应用数据，重新安装完整安装包后重试。"; textSize = 22f; setPadding(32,64,32,32) }); return
        }
        page = WebView(this)
        page.settings.javaScriptEnabled = true
        page.settings.domStorageEnabled = true
        page.settings.allowFileAccess = false
        page.settings.allowContentAccess = false
        page.settings.mediaPlaybackRequiresUserGesture = true
        page.settings.setSupportMultipleWindows(false)
        page.addJavascriptInterface(Bridge(), "LovePinyinAndroid")
        page.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest) = request.url.toString() != ENTRY
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse {
                val uri = request.url
                val path = uri.path.orEmpty().removePrefix("/").ifEmpty { "index.html" }
                if (request.method != "GET" || uri.scheme != "https" || uri.host != HOST || uri.port != -1 || uri.userInfo != null || path.split('/').any { it == ".." || it == "." } || path.contains('\\')) return failure()
                val relative = if (path.startsWith("api/v1/")) {
                    val clip = audio.optJSONObject(path.removePrefix("api/v1/")) ?: return failure()
                    val file = clip.getString("file"); if (file.contains('/')) return failure(); "Audio/$file"
                } else { if (path !in webFiles) return failure(); "Web/$path" }
                return try {
                    val extension = relative.substringAfterLast('.')
                    val mime = when (extension) { "html" -> "text/html"; "js" -> "text/javascript"; "css" -> "text/css"; "json" -> "application/json"; "svg" -> "image/svg+xml"; "png" -> "image/png"; "jpg", "jpeg" -> "image/jpeg"; "webp" -> "image/webp"; "mp3" -> "audio/mpeg"; "m4a" -> "audio/mp4"; "wav" -> "audio/wav"; "woff2" -> "font/woff2"; "woff" -> "font/woff"; else -> return failure() }
                    val stream = assets.open("pack/$relative")
                    val body = if (path == "index.html") stream.bufferedReader().use { it.readText() }.replace("<head>", "<head><script>window.__lovePinyinAndroid=true;</script>").byteInputStream() else stream
                    WebResourceResponse(mime, if (extension in setOf("html","js","css","json","svg")) "UTF-8" else null, 200, "OK", mapOf("Content-Security-Policy" to "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; object-src 'none'; frame-src 'none'; base-uri 'none'; connect-src 'self'", "X-Content-Type-Options" to "nosniff"), body)
                } catch (_: java.io.IOException) { failure() }
            }
        }
        val container = android.widget.FrameLayout(this)
        container.addView(page, android.widget.FrameLayout.LayoutParams(-1,-1))
        @Suppress("DEPRECATION")
        container.setOnApplyWindowInsetsListener { view, insets ->
            view.setPadding(insets.systemWindowInsetLeft,insets.systemWindowInsetTop,insets.systemWindowInsetRight,insets.systemWindowInsetBottom)
            insets
        }
        setContentView(container)
        page.loadUrl(ENTRY)
    }
    inner class Bridge {
        @JavascriptInterface fun postMessage(raw: String) {
            if (raw.length > 1024*1024) return
            worker.execute {
                var id = ""
                try {
                    val message = JSONObject(raw); id = message.getString("requestId")
                    if (id.length !in 1..80 || message.getInt("version") != 1) fail("ANDROID_BRIDGE_INVALID")
                    val op = message.getString("operation")
                    if (op in setOf("backupExport","backupImport","playLesson","pauseLesson","seekLesson","lessonState")) {
                        val requestId = id
                        runOnUiThread { try { uiOperation(requestId,op,message) } catch (error: Exception) { reply(requestId,null,errorCode(error)) } }
                    } else {
                        val result: Any = when (op) {
                            "classroom" -> {
                                val method = message.getString("method"); val path = message.getString("path")
                                if (!foreground && (path == "/games/heartbeat" || (path == "/sessions" && JSONObject(message.getString("payload")).has("gameId")))) fail("GAME_PAUSED")
                                when (path) { "/curriculum" -> data("curriculum"); "/learning-audio" -> data("learning-audio"); "/practice-packs" -> data("practice-packs"); else -> classroom.request(method,path,JSONObject(message.optString("payload","{}"))) }
                            }
                            "practicePacks" -> data("practice-packs")
                            "classroomReady" -> obj("ready" to true)
                            "modelStatus", "modelCancel", "modelRemove" -> obj("state" to "unsupported")
                            "recognizeAudio" -> obj("status" to "unavailable")
                            else -> fail("ANDROID_OPERATION_UNAVAILABLE")
                        }
                        reply(id,result)
                    }
                } catch (error: Exception) { reply(id,null,errorCode(error)) }
            }
        }
    }
    private fun errorCode(error: Exception) = if (error is IllegalArgumentException && error.message?.matches(Regex("[A-Z][A-Z0-9_]+")) == true) error.message!! else "ANDROID_OPERATION_FAILED"
    private fun reply(id: String, result: Any?, error: String? = null) {
        val response = obj("requestId" to id, "result" to result, "error" to error)
        runOnUiThread { if (::page.isInitialized && !isDestroyed) page.evaluateJavascript("window.__lovePinyinAndroidReply?.(${response});",null) }
    }
    private fun uiOperation(id: String, op: String, message: JSONObject) {
        when (op) {
            "backupExport", "backupImport" -> {
                if (pendingFile != null) fail("ANDROID_FILE_BUSY")
                pauseMedia(); worker.execute {
                    try {
                        classroom.pause()
                        val bytes = if (op == "backupExport") classroom.exportBackup() else null
                        runOnUiThread {
                            pendingFile = id to bytes
                            try {
                                val intent = if (bytes != null) Intent(Intent.ACTION_CREATE_DOCUMENT).apply { addCategory(Intent.CATEGORY_OPENABLE); type="application/json"; putExtra(Intent.EXTRA_TITLE,"爱拼音-Android-${java.time.LocalDate.now()}.json") } else Intent(Intent.ACTION_OPEN_DOCUMENT).apply { addCategory(Intent.CATEGORY_OPENABLE); type="application/json" }
                                @Suppress("DEPRECATION")
                                startActivityForResult(intent, if (bytes != null) 101 else 102)
                            } catch (error: Exception) { pendingFile = null; reply(id,null,errorCode(error)) }
                        }
                    } catch (error: Exception) { reply(id,null,errorCode(error)) }
                }
            }
            "playLesson" -> {
                if (!foreground) fail("GAME_PAUSED")
                val wanted = message.getString("audioId"); val token = message.getInt("id")
                if (!wanted.startsWith("lesson-")) fail("ANDROID_RESOURCE_UNAVAILABLE")
                val file = audio.optJSONObject("voice/$wanted")?.getString("file") ?: fail("ANDROID_RESOURCE_UNAVAILABLE")
                if (player == null || audioId != wanted || playbackId != token) {
                    player?.release(); player = null
                    val attributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
                    val manager = getSystemService(AUDIO_SERVICE) as AudioManager
                    audioFocus?.let { manager.abandonAudioFocusRequest(it) }
                    audioFocus = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT).setAudioAttributes(attributes).setOnAudioFocusChangeListener { change -> if (change != AudioManager.AUDIOFOCUS_GAIN) interrupt() }.build()
                    if (manager.requestAudioFocus(audioFocus!!) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) fail("ANDROID_AUDIO_UNAVAILABLE")
                    player = MediaPlayer().apply { setAudioAttributes(attributes); assets.openFd("pack/Audio/$file").use { setDataSource(it.fileDescriptor,it.startOffset,it.length) }; prepare() }
                    audioId=wanted; playbackId=token
                }
                player!!.start(); reply(id,mediaState())
            }
            "pauseLesson" -> { if (message.optInt("id") == playbackId) pauseMedia(); reply(id,mediaState()) }
            "seekLesson" -> { if (message.getInt("id") != playbackId) fail("ANDROID_AUDIO_UNAVAILABLE"); val seconds = message.getDouble("seconds"); if (!seconds.isFinite() || seconds < 0 || seconds*1000 > (player?.duration ?: 0)) fail("ANDROID_AUDIO_UNAVAILABLE"); player?.seekTo((seconds*1000).toLong(),MediaPlayer.SEEK_CLOSEST); reply(id,mediaState()) }
            "lessonState" -> reply(id,if (message.optInt("id") == playbackId) mediaState() else obj("playing" to false,"position" to 0,"duration" to 0))
        }
    }
    private fun mediaState() = obj("playing" to (player?.isPlaying ?: false), "position" to ((player?.currentPosition ?: 0)/1000.0), "duration" to ((player?.duration ?: 0)/1000.0))
    private fun pauseMedia() { if (player?.isPlaying == true) player?.pause() }
    private fun interrupt() { pauseMedia(); if (::page.isInitialized) page.evaluateJavascript("window.dispatchEvent(new Event('lp-native-audio-interrupted'));",null); if (::classroom.isInitialized) worker.execute { try { classroom.pause() } catch (_: Exception) { /* Next API reports the storage error; never reset the archive. */ } } }
    @Deprecated("Android activity result compatibility")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode,resultCode,data)
        if (requestCode !in setOf(101,102)) return
        val pending = pendingFile ?: return; pendingFile=null
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null) { reply(pending.first,obj("state" to "cancelled")); return }
        worker.execute {
            try {
                if (requestCode == 101) {
                    contentResolver.openOutputStream(uri,"wt")?.use { it.write(pending.second ?: fail("ANDROID_BACKUP_INVALID")) } ?: fail("ANDROID_BACKUP_UNAVAILABLE")
                    reply(pending.first,obj("state" to "exported"))
                } else {
                    val bytes = contentResolver.openInputStream(uri)?.use { input ->
                        val output = java.io.ByteArrayOutputStream()
                        val buffer = ByteArray(8192)
                        while (true) { val count = input.read(buffer); if (count < 0) break; if (output.size()+count > Classroom.BACKUP_LIMIT) fail("ANDROID_BACKUP_TOO_LARGE"); output.write(buffer,0,count) }
                        output.toByteArray() } ?: fail("ANDROID_BACKUP_INVALID")
                    val (preview,revision) = classroom.preview(bytes)
                    runOnUiThread {
                        AlertDialog.Builder(this).setTitle("恢复此设备的学习记录？").setMessage(preview)
                            .setNegativeButton("取消") { _,_ -> reply(pending.first,obj("state" to "cancelled")) }
                            .setOnCancelListener { reply(pending.first,obj("state" to "cancelled")) }
                            .setPositiveButton("替换并恢复") { _,_ -> worker.execute { try { classroom.restore(bytes,revision); reply(pending.first,obj("state" to "restored")) } catch(error: Exception) { reply(pending.first,null,errorCode(error)) } } }.show()
                    }
                }
            } catch(error: Exception) { reply(pending.first,null,errorCode(error)) }
        }
    }
    private fun failure() = WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", emptyMap(), ByteArrayInputStream("Offline resource unavailable".toByteArray()))
    override fun onPause() { foreground=false; interrupt(); if (::page.isInitialized) { page.onPause(); page.pauseTimers() }; super.onPause() }
    override fun onResume() { super.onResume(); foreground=true; if (::page.isInitialized) { page.onResume(); page.resumeTimers() } }
    override fun onDestroy() { player?.release(); audioFocus?.let { (getSystemService(AUDIO_SERVICE) as AudioManager).abandonAudioFocusRequest(it) }; if (::page.isInitialized) { page.removeJavascriptInterface("LovePinyinAndroid"); page.destroy() }; worker.shutdown(); super.onDestroy() }
    companion object { const val HOST="app.lovepinyin.invalid"; const val ENTRY="https://app.lovepinyin.invalid/" }
}
