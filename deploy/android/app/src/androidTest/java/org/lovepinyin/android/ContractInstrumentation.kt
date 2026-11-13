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
            val fixture = JSONObject(context.assets.open("contracts.json").bufferedReader().use { it.readText() })
            fun same(actual: Any?, expected: Any?, path: String = "result") {
                when {
                    actual is JSONObject && expected is JSONObject -> {
                        check(actual.keys().asSequence().toSet() == expected.keys().asSequence().toSet()) { "$path fields differ" }
                        expected.keys().forEach { same(actual.get(it), expected.get(it), "$path.$it") }
                    }
                    actual is org.json.JSONArray && expected is org.json.JSONArray -> {
                        check(actual.length() == expected.length()) { "$path length differs" }
                        for (i in 0 until actual.length()) same(actual.get(i),expected.get(i),"$path[$i]")
                    }
                    actual is Number && expected is Number -> check(kotlin.math.abs(actual.toDouble()-expected.toDouble()) < 0.000001) { "$path: $actual != $expected" }
                    else -> check(actual == expected) { "$path: $actual != $expected" }
                }
            }
            fixture.getJSONArray("mastery").rows().forEach { sample ->
                same(LearningRules.mastery(sample.getJSONArray("required").strings(),sample.getJSONArray("records").rows()), sample.getJSONObject("expected"), "mastery")
            }
            fixture.getJSONArray("clocks").rows().forEach { sample ->
                val (clock,status) = LearningRules.clock(sample.getJSONObject("state"),sample.getDouble("at"),sample.getInt("session"),sample.getInt("daily"),sample.getString("action"),fixture.getJSONObject("policy"))
                same(clock,sample.getJSONObject("expectedState"),"clock")
                same(status,sample.getJSONObject("expected"),"status")
            }
            fixture.getJSONArray("orders").rows().forEach { sample -> same(org.json.JSONArray(LearningRules.order(sample.getJSONArray("options").rows(),sample.getString("id"))),sample.getJSONArray("expected"),"order") }
            val folder = File(targetContext.cacheDir,"contract-${System.nanoTime()}").apply { mkdirs() }
            val isolated = object : ContextWrapper(targetContext) { override fun getDatabasePath(name: String) = File(folder,name) }
            val content = JSONObject(targetContext.assets.open("pack/Data/classroom.json").bufferedReader().use { it.readText() })
            fixture.getJSONArray("games").rows().forEach { sample ->
                val gameContext = object : ContextWrapper(targetContext) { override fun getDatabasePath(name: String) = File(folder,"${sample.getString("gameId")}/$name").apply { parentFile?.mkdirs() } }
                val gameService = Classroom(gameContext,content) { 1800000000.0 }
                val round = gameService.request("POST","/sessions",obj("lessonId" to sample.getString("lessonId"),"gameId" to sample.getString("gameId"),"gameTaskCount" to sample.getInt("count"))) as JSONObject
                same(org.json.JSONArray(round.getJSONArray("tasks").rows().map { it.getJSONObject("exercise").getString("id") }),sample.getJSONArray("selected"),"game selection")
                same(round.getJSONObject("gameSettings"),sample.getJSONObject("settings"),"game settings")
                val route = copy(round.getJSONObject("gameRun"))
                route.getJSONArray("bindings").rows().forEachIndexed { i,binding -> binding.put("instanceId","task-$i") }
                same(route,sample.getJSONObject("route"),"game route")
                gameService.close()
            }
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
            service.practiceProgress("word:original","[\"word-02:read\"]")
            service.practiceProgress("daily:original","{\"daily-test-item\":\"practiced\"}")
            val backup=service.exportBackup(); val (_,revision)=service.preview(backup)
            try { service.restore("{}".toByteArray(),revision); error("invalid backup accepted") } catch (_: IllegalArgumentException) {}
            val corrupt = JSONObject(backup.toString(Charsets.UTF_8))
            corrupt.getJSONObject("state").getJSONObject("current").getJSONArray("tasks").getJSONObject(0).getJSONObject("publicExercise").put("prompt","篡改题目")
            try { service.preview(corrupt.toString().toByteArray()); error("altered frozen question accepted") } catch (_: IllegalArgumentException) {}
            val badClock = JSONObject(backup.toString(Charsets.UTF_8))
            badClock.getJSONObject("state").put("gameClock",obj("days" to JSONObject(),"accountedAt" to at,"leaseUntil" to at+3600,"runSeconds" to 0))
            try { service.preview(badClock.toString().toByteArray()); error("unbounded lease accepted") } catch (_: IllegalArgumentException) {}
            val beforeFailure = (call("GET","/profiles/progress") as JSONObject).toString()
            val db = android.database.sqlite.SQLiteDatabase.openDatabase(isolated.getDatabasePath("learning.sqlite").path,null,android.database.sqlite.SQLiteDatabase.OPEN_READWRITE)
            db.execSQL("CREATE TRIGGER simulate_full BEFORE INSERT ON snapshot BEGIN SELECT RAISE(ABORT,'test storage full'); END")
            val nextId=round.getJSONArray("tasks").getJSONObject(1).getString("instanceId")
            try { call("POST","/instances/$nextId/skip"); error("failed write returned success") } catch (_: android.database.sqlite.SQLiteException) {}
            check((call("GET","/profiles/progress") as JSONObject).toString()==beforeFailure)
            db.execSQL("DROP TRIGGER simulate_full"); db.close()
            check(!(call("GET","/sessions/current") as JSONObject).getJSONObject("results").has(nextId))
            service.restore(backup,revision)
            check((call("GET","/profiles/progress") as JSONObject).getInt("attemptCount")==1)
            check((service.practiceProgress("word:original","") as org.json.JSONArray).getString(0)=="word-02:read")
            check((service.practiceProgress("daily:original","") as JSONObject).getString("daily-test-item")=="practiced")
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
            results.putString("stream","ANDROID_CONTRACT_OK: Python shared mastery/clock/ordering cases; first-answer, idempotency, restart, backup corruption/lease rejection, failed SQLite write rollback, restore, four game routes, pause lease\n")
            finish(RESULT_OK,results)
        } catch (error: Throwable) { results.putString("stream",error.stackTraceToString()); finish(0,results) }
    }
    companion object { const val RESULT_OK = -1 }
}
