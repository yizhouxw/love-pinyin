package org.lovepinyin.android

import android.content.Context
import android.content.ContextWrapper
import android.util.Base64
import java.io.File

object RecognitionChecks {
    fun run(context: Context) {
        val pcm = ByteArray(3200) { (it%73).toByte() }
        val wav = NativeRecorder.wav(pcm)
        check(LocalRecognition.pcm(wav).size == 1600)
        for (invalid in listOf(ByteArray(0),wav.copyOf(43),wav.copyOf().apply { this[22]=8 },wav.copyOf().apply { this[24]=0 },wav+byteArrayOf(0),wav.copyOf().apply { this[40]=0 })) {
            check(runCatching { LocalRecognition.pcm(invalid) }.isFailure) { "Invalid PCM accepted" }
        }
        val folder=File(context.cacheDir,"asr-contract-${System.nanoTime()}").apply { mkdirs() }
        val isolated=object : ContextWrapper(context) { override fun getNoBackupFilesDir() = folder }
        val config=org.json.JSONObject(context.assets.open("android-asr.json").bufferedReader().use { it.readText() })
        val corrupt=File(folder,"recognition/${config.getString("revision")}/installed").apply { mkdirs() }
        File(corrupt,"conv_frontend.onnx").writeText("damaged")
        val damaged=LocalRecognition(isolated)
        try {
            check(damaged.status().getString("state") in setOf("installed","unsupported"))
            check(damaged.recognize(Base64.encodeToString(wav,Base64.NO_WRAP),damaged.generation()).getString("status")=="unavailable")
            check(damaged.status().getString("state") in setOf("failed","unsupported"))
        } finally { damaged.close(); corrupt.deleteRecursively() }
        val model=LocalRecognition(isolated)
        try {
            check(model.status().getString("state") in setOf("idle","unsupported"))
            check(model.recognize(Base64.encodeToString(wav,Base64.NO_WRAP),model.generation()).getString("status")=="unavailable")
            val old=model.generation(); model.invalidate(); check(old != model.generation())
            model.cancel(); check(model.status().getString("state") != "installed")
            val recorder=NativeRecorder(); check(recorder.snapshot("missing",true)==null); recorder.discard(); check(recorder.level("missing")==0.0)
        } finally { model.close(); folder.deleteRecursively() }
        println("ANDROID_ASR_CONTRACT_OK: bounded PCM, missing model, stale generation, isolated storage")
    }
}
