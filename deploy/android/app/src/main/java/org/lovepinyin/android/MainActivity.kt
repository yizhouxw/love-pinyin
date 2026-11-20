package org.lovepinyin.android

import android.app.Activity
import android.app.AlertDialog
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.res.Configuration
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.os.Build
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.util.concurrent.Executors

/** WebView serves only installed resources. Model networking and microphone stay native. */
class MainActivity : Activity() {
    @Volatile private var page: WebView? = null
    private lateinit var container: FrameLayout
    @Volatile private var fontScale = 1f
    private var restoreDialog: AlertDialog? = null
    private val noisyAudio = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == AudioManager.ACTION_AUDIO_BECOMING_NOISY) interrupt()
        }
    }
    private lateinit var classroom: Classroom
    private lateinit var audio: JSONObject
    private lateinit var webFiles: Set<String>
    private val worker = Executors.newSingleThreadExecutor()
    @Volatile private var foreground = false
    private var player: MediaPlayer? = null
    private var playbackId = -1
    private var audioId = ""
    private var pendingFile: Pair<String, ByteArray?>? = null
    private var activeFileId: String? = null
    private var audioFocus: AudioFocusRequest? = null
    private var pauseNeedsRetry = false
    private lateinit var recognition: LocalRecognition
    private var recordingId: String? = null
    private val recorder = NativeRecorder { id -> runOnUiThread {
        if (recordingId == id) { recordingId = null; audioFocus?.let { (getSystemService(AUDIO_SERVICE) as AudioManager).abandonAudioFocusRequest(it) }; audioFocus = null }
    } }
    private var microphonePermissionInFlight = false
    private var pendingRecord: Pair<String, JSONObject>? = null
    private fun data(name: String) = JSONObject(assets.open("pack/Data/$name.json").bufferedReader().use { it.readText() })
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val debug = applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE != 0
        val requestedVerification = if (debug) intent.getStringExtra("verificationId")?.takeIf {
            runCatching { java.util.UUID.fromString(it).toString() == it }.getOrDefault(false)
        } else null
        if (!storageProfileInitialized) {
            processVerification = requestedVerification
            if (processVerification != null && android.os.Build.VERSION.SDK_INT >= 28)
                WebView.setDataDirectorySuffix("verification-$processVerification")
            storageProfileInitialized = true
        }
        val verification = processVerification
        val storageContext = if (verification != null) object : android.content.ContextWrapper(this) {
            override fun getDatabasePath(name: String) = java.io.File(filesDir,"verification/$verification/$name").apply { parentFile?.mkdirs() }
        } else this
        try {
            recognition = LocalRecognition(this)
            audio = data("audio")
            webFiles = org.json.JSONArray(assets.open("pack/Data/web-files.json").bufferedReader().use { it.readText() }).strings().toSet()
            classroom = Classroom(storageContext, data("classroom"))
        } catch (_: Exception) {
            setContentView(TextView(this).apply { text = "本机学习资料暂时无法读取。请保留应用数据，重新安装完整安装包后重试。"; textSize = 22f; setPadding(32,64,32,32) }); return
        }
        WebView.setWebContentsDebuggingEnabled(applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE != 0)
        fontScale = resources.configuration.fontScale
        container = FrameLayout(this)
        @Suppress("DEPRECATION")
        container.setOnApplyWindowInsetsListener { view, insets ->
            view.setPadding(insets.systemWindowInsetLeft,insets.systemWindowInsetTop,insets.systemWindowInsetRight,insets.systemWindowInsetBottom)
            insets
        }
        setContentView(container)
        installPage()
    }

    private fun typographyScript(): String {
        val scale = fontScale
        return """
            document.documentElement.style.setProperty('--ios-body-size', '${17 * scale}px');
            document.documentElement.toggleAttribute('data-ios-large-text', ${scale >= 1.3f});
        """.trimIndent()
    }

    override fun onConfigurationChanged(configuration: Configuration) {
        super.onConfigurationChanged(configuration)
        fontScale = configuration.fontScale
        page?.evaluateJavascript(typographyScript(), null)
    }

    private fun installPage() {
        val view = WebView(this)
        page = view
        view.settings.javaScriptEnabled = true
        view.settings.domStorageEnabled = true
        view.settings.allowFileAccess = false
        view.settings.allowContentAccess = false
        view.settings.mediaPlaybackRequiresUserGesture = true
        view.settings.setSupportMultipleWindows(false)
        view.addJavascriptInterface(Bridge(view), "LovePinyinAndroid")
        view.webViewClient = object : WebViewClient() {
            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                if (view !== page) return true
                page = null
                container.removeView(view)
                view.destroy()
                pendingRecord = null
                activeFileId = null
                restoreDialog?.dismiss()
                interrupt()
                val recovery = LinearLayout(this@MainActivity).apply {
                    orientation = LinearLayout.VERTICAL
                    gravity = android.view.Gravity.CENTER
                    addView(TextView(context).apply {
                        text = "学习页面已暂停。恢复后可从已保存的位置继续。"
                        textSize = 17f
                        gravity = android.view.Gravity.CENTER
                    })
                    addView(Button(context).apply {
                        text = "恢复学习"
                        setOnClickListener {
                            container.removeAllViews()
                            installPage()
                        }
                    })
                }
                container.addView(recovery, FrameLayout.LayoutParams(-1, -1))
                return true
            }

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
                    val body = if (path == "index.html") stream.bufferedReader().use { it.readText() }.replace("<head>", "<head><script>window.__lovePinyinAndroid=true;${typographyScript()}</script>").byteInputStream() else stream
                    WebResourceResponse(mime, if (extension in setOf("html","js","css","json","svg")) "UTF-8" else null, 200, "OK", mapOf("Content-Security-Policy" to "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; object-src 'none'; frame-src 'none'; base-uri 'none'; connect-src 'self'", "X-Content-Type-Options" to "nosniff"), body)
                } catch (_: java.io.IOException) { failure() }
            }
        }
        container.addView(view, FrameLayout.LayoutParams(-1, -1))
        view.loadUrl(ENTRY)
    }

    inner class Bridge(private val owner: WebView) {
        @JavascriptInterface fun practiceProgress(key: String, payload: String): String = try {
            if (page !== owner) fail("ANDROID_BRIDGE_UNAVAILABLE")
            obj("result" to classroom.practiceProgress(key,payload),"error" to null).toString()
        } catch (error: Exception) { obj("result" to null,"error" to errorCode(error)).toString() }

        @JavascriptInterface fun postMessage(raw: String) {
            if (page !== owner || raw.length > 2*1024*1024) return
            worker.execute {
                if (page !== owner) return@execute
                var id = ""
                try {
                    val message = JSONObject(raw); id = message.getString("requestId")
                    if (id.length !in 1..80 || message.getInt("version") != 1) fail("ANDROID_BRIDGE_INVALID")
                    val op = message.getString("operation")
                    if (op in setOf("recordStart","recordStop","recordSnapshot","recordLevel","recordDiscard","backupExport","backupImport","playLesson","pauseLesson","seekLesson","lessonState")) {
                        val requestId = id
                        runOnUiThread { if (page !== owner) return@runOnUiThread; try { uiOperation(requestId,op,message) } catch (error: Exception) { reply(requestId,null,errorCode(error)) } }
                    } else {
                        val result: Any = when (op) {
                            "classroom" -> {
                                if (pauseNeedsRetry) { classroom.pause(); pauseNeedsRetry = false }
                                val method = message.getString("method"); val path = message.getString("path")
                                if (!foreground && (path == "/games/heartbeat" || (path == "/sessions" && JSONObject(message.getString("payload")).has("gameId")))) fail("GAME_PAUSED")
                                when (path) { "/curriculum" -> data("curriculum"); "/learning-audio" -> data("learning-audio"); "/practice-packs" -> data("practice-packs"); else -> classroom.request(method,path,JSONObject(message.optString("payload","{}"))) }
                            }
                            "practicePacks" -> data("practice-packs")
                            "classroomReady" -> obj("ready" to true)
                            "modelStatus" -> recognition.status()
                            "modelDownload" -> recognition.download()
                            "modelCancel" -> recognition.cancel()
                            "modelRemove" -> recognition.remove()
                            "recognitionCancel" -> { recognition.invalidate(); obj("cancelled" to true) }
                            "recognizeAudio" -> {
                                if (!foreground) { reply(id,obj("status" to "unavailable")); return@execute }
                                val requestId = id
                                val generation = recognition.generation()
                                recognition.inferenceWorker.execute {
                                    reply(requestId,recognition.recognize(message.optString("audio"),generation))
                                }
                                return@execute
                            }
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
        runOnUiThread { if (activeFileId == id) activeFileId = null; if (!isDestroyed) page?.evaluateJavascript("window.__lovePinyinAndroidReply?.(${response});",null) }
    }
    private fun uiOperation(id: String, op: String, message: JSONObject) {
        when (op) {
            "recordStart" -> {
                if (!foreground) fail("ANDROID_AUDIO_UNAVAILABLE")
                if (microphonePermissionInFlight) fail("ANDROID_RECORD_BUSY")
                if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                    pendingRecord = id to message
                    microphonePermissionInFlight = true
                    requestPermissions(arrayOf(android.Manifest.permission.RECORD_AUDIO),103)
                } else startRecording(id,message)
            }
            "recordStop", "recordSnapshot" -> reply(id,recorder.snapshot(message.getString("id"),op == "recordStop"))
            "recordLevel" -> reply(id,recorder.level(message.getString("id")))
            "recordDiscard" -> {
                recorder.discard(message.getString("id"))
                pendingRecord?.takeIf { it.second.optString("id") == message.optString("id") }?.let { reply(it.first,null,"ANDROID_RECORD_CANCELLED"); pendingRecord=null }
                recognition.invalidate(); reply(id,obj("discarded" to true))
            }
            "backupExport", "backupImport" -> {
                if (activeFileId != null || pendingFile != null) fail("ANDROID_FILE_BUSY")
                activeFileId = id
                pauseMedia(); worker.execute {
                    try {
                        classroom.pause()
                        val bytes = if (op == "backupExport") classroom.exportBackup() else null
                        runOnUiThread {
                            if (activeFileId != id || isDestroyed) return@runOnUiThread
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
                recordingId = null; recorder.discard()
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
            "seekLesson" -> { if (message.getInt("id") != playbackId) fail("ANDROID_AUDIO_UNAVAILABLE"); val seconds = message.getDouble("seconds"); if (!seconds.isFinite() || seconds < 0 || seconds*1000 > (player?.duration ?: 0)) fail("ANDROID_AUDIO_UNAVAILABLE"); val activePlayer = player ?: fail("ANDROID_AUDIO_UNAVAILABLE"); activePlayer.setOnSeekCompleteListener { it.setOnSeekCompleteListener(null); reply(id,mediaState()) }; activePlayer.seekTo((seconds*1000).toLong(),MediaPlayer.SEEK_CLOSEST) }
            "lessonState" -> reply(id,if (message.optInt("id") == playbackId) mediaState() else obj("playing" to false,"position" to 0,"duration" to 0))
        }
    }
    private fun startRecording(id: String, message: JSONObject) {
        if (!foreground) fail("ANDROID_AUDIO_UNAVAILABLE")
        pauseMedia()
        val manager = getSystemService(AUDIO_SERVICE) as AudioManager
        audioFocus?.let { manager.abandonAudioFocusRequest(it) }
        audioFocus = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .setOnAudioFocusChangeListener { change -> if (change != AudioManager.AUDIOFOCUS_GAIN) interrupt() }.build()
        if (manager.requestAudioFocus(audioFocus!!) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) fail("ANDROID_AUDIO_UNAVAILABLE")
        recordingId = message.getString("id")
        recorder.start(recordingId!!,message.getInt("limit"))
        reply(id,obj("recording" to true))
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode,permissions,grantResults)
        if (requestCode != 103) return
        microphonePermissionInFlight = false
        val pending = pendingRecord ?: return
        pendingRecord = null
        page?.post {
            if (grantResults.firstOrNull() != android.content.pm.PackageManager.PERMISSION_GRANTED) reply(pending.first,null,"ANDROID_MICROPHONE_DENIED")
            else try { startRecording(pending.first,pending.second) } catch (error: Exception) { reply(pending.first,null,errorCode(error)) }
        }
    }
    private fun mediaState() = obj("playing" to (player?.isPlaying ?: false), "position" to ((player?.currentPosition ?: 0)/1000.0), "duration" to ((player?.duration ?: 0)/1000.0))
    private fun pauseMedia() { if (player?.isPlaying == true) player?.pause() }
    private fun interrupt() { recorder.discard(); if (::recognition.isInitialized) recognition.invalidate(); pauseMedia(); page?.evaluateJavascript("window.dispatchEvent(new Event('lp-native-audio-interrupted'));",null); if (::classroom.isInitialized) worker.execute { try { classroom.pause(); pauseNeedsRetry = false } catch (_: Exception) { pauseNeedsRetry = true } } }
    @Deprecated("Android activity result compatibility")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode,resultCode,data)
        if (requestCode !in setOf(101,102)) return
        val pending = pendingFile ?: return; pendingFile=null
        if (pending.first != activeFileId) return
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
                        if (activeFileId != pending.first || isDestroyed) return@runOnUiThread
                        restoreDialog = AlertDialog.Builder(this).setTitle("恢复此设备的学习记录？").setMessage(preview)
                            .setNegativeButton("取消") { _,_ -> reply(pending.first,obj("state" to "cancelled")) }
                            .setOnCancelListener { reply(pending.first,obj("state" to "cancelled")) }
                            .setOnDismissListener { restoreDialog = null }
                            .setPositiveButton("替换并恢复") { _,_ -> worker.execute { try { classroom.restore(bytes,revision); reply(pending.first,obj("state" to "restored")) } catch(error: Exception) { reply(pending.first,null,errorCode(error)) } } }.show()
                    }
                }
            } catch(error: Exception) { reply(pending.first,null,errorCode(error)) }
        }
    }
    private fun failure() = WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", emptyMap(), ByteArrayInputStream("Offline resource unavailable".toByteArray()))
    override fun onStart() {
        super.onStart()
        val filter = IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY)
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(noisyAudio, filter, Context.RECEIVER_NOT_EXPORTED)
        else registerReceiver(noisyAudio, filter)
    }

    override fun onStop() {
        unregisterReceiver(noisyAudio)
        super.onStop()
    }

    override fun onPause() { foreground=false; interrupt(); page?.onPause(); super.onPause() }
    override fun onResume() { super.onResume(); foreground=true; page?.onResume() }
    override fun onDestroy() { recorder.discard(); if (::recognition.isInitialized) recognition.close(); player?.release(); audioFocus?.let { (getSystemService(AUDIO_SERVICE) as AudioManager).abandonAudioFocusRequest(it) }; page?.let { container.removeView(it); it.removeJavascriptInterface("LovePinyinAndroid"); it.destroy() }; page = null; if (::classroom.isInitialized) worker.execute { classroom.close() }; worker.shutdown(); super.onDestroy() }
    companion object { private var storageProfileInitialized = false; private var processVerification: String? = null; const val HOST="app.lovepinyin.invalid"; const val ENTRY="https://app.lovepinyin.invalid/" }
}
