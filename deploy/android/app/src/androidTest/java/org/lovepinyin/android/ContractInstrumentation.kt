package org.lovepinyin.android

import android.app.Instrumentation
import android.os.Bundle
import android.content.ContextWrapper
import java.io.File
import org.json.JSONObject

/** Runs against a disposable database; never uses the family's learning archive. */
class ContractInstrumentation : Instrumentation() {
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    override fun onStart() {
        val results = Bundle()
        try {
            val folder = File(targetContext.cacheDir,"contract-${System.nanoTime()}").apply { mkdirs() }
            val isolated = object : ContextWrapper(targetContext) { override fun getDatabasePath(name: String) = File(folder,name) }
            val content = JSONObject(targetContext.assets.open("pack/Data/classroom.json").bufferedReader().use { it.readText() })
            var at = 1800000000.0
            var service = Classroom(isolated,content) { at }
            fun call(method: String,path: String,body: JSONObject = JSONObject()) = service.request(method,path,body)
            val lesson = content.getJSONArray("lessons").getJSONObject(0).getString("id")
            val round = call("POST","/sessions",obj("lessonId" to lesson)) as JSONObject
            val task = round.getJSONArray("tasks").getJSONObject(0); val id=task.getString("instanceId")
            check(!task.getJSONObject("exercise").has("answer"))
            val option = task.getJSONObject("exercise").getJSONArray("options").getJSONObject(0).getString("id")
            val answer = obj("requestId" to "contract-answer-0001","answerOptionId" to option)
            val result = call("POST","/instances/$id/answer",answer).toString()
            check(call("POST","/instances/$id/answer",answer).toString()==result)
            service=Classroom(isolated,content) { at }
            check(call("GET","/attempts/contract-answer-0001").toString()==result)
            val recovered = call("GET","/sessions/current") as JSONObject
            check(recovered.getString("id")==round.getString("id"))
            check(recovered.getJSONObject("results").has(id))
            val backup=service.exportBackup(); val (_,revision)=service.preview(backup)
            try { service.restore("{}".toByteArray(),revision); error("invalid backup accepted") } catch (_: IllegalArgumentException) {}
            service.restore(backup,revision)
            check((call("GET","/profiles/progress") as JSONObject).getInt("attemptCount")==1)
            call("POST","/sessions/${round.getString("id")}/finish")
            val last=content.getJSONArray("lessons").getJSONObject(content.getJSONArray("lessons").length()-1).getString("id")
            val progress=call("GET","/profiles/progress") as JSONObject
            call("PUT","/household/current-lesson",obj("lessonId" to last,"expectedRevision" to progress.getInt("revision")))
            for (gameId in listOf("sound","tone","shape","blend")) {
                val game=call("POST","/sessions",obj("lessonId" to last,"gameId" to gameId)) as JSONObject
                check(game.getJSONObject("gameRun").getJSONArray("bindings").length()==game.getJSONArray("tasks").length())
                at+=3
                service.pause()
                val status=call("GET","/games") as JSONObject
                check(status.getJSONObject("clock").getDouble("dailySeconds")>=3)
                val item=game.getJSONArray("tasks").getJSONObject(0)
                try { call("POST","/instances/${item.getString("instanceId")}/skip"); error("paused game allowed write") } catch (_: IllegalArgumentException) {}
                call("POST","/sessions/${game.getString("id")}/finish")
            }
            results.putString("stream","ANDROID_CONTRACT_OK: first-answer, idempotency, restart, backup rejection/restore, four game routes, pause lease\n")
            finish(RESULT_OK,results)
        } catch (error: Throwable) { results.putString("stream",error.stackTraceToString()); finish(0,results) }
    }
    companion object { const val RESULT_OK = -1 }
}
