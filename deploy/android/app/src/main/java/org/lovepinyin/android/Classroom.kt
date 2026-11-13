package org.lovepinyin.android

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.util.UUID
import java.security.MessageDigest

internal fun obj(vararg fields: Pair<String, Any?>) = JSONObject().apply { fields.forEach { put(it.first, it.second ?: JSONObject.NULL) } }
internal fun JSONArray.rows() = (0 until length()).map { getJSONObject(it) }
internal fun JSONArray.strings() = (0 until length()).map { getString(it) }
internal fun copy(value: JSONObject) = JSONObject(value.toString())
internal fun fail(code: String): Nothing = throw IllegalArgumentException(code)

/** Single serialized writer. Memory is replaced only after SQLite commits. */
class Classroom(context: Context, private val content: JSONObject, private val now: () -> Double = { System.currentTimeMillis() / 1000.0 }) {
    private val database = SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath("learning.sqlite").apply { parentFile?.mkdirs() }, null)
    private val lessons = content.getJSONArray("lessons").rows()
    private val knowledge = content.getJSONArray("knowledgeItems").rows()
    private val questions = content.getJSONArray("eligible").rows().associateBy { it.getJSONObject("exercise").getString("id") }
    private val game = content.getJSONObject("game")
    private val rules = game.getJSONObject("rules")
    private val policy = rules.getJSONObject("policy")
    private val zone = ZoneId.of("Asia/Shanghai")
    private val modes = setOf("listen-choice", "symbol-choice", "tone-choice", "blend-choice")
    private var state: JSONObject
    init {
        database.execSQL("CREATE TABLE IF NOT EXISTS snapshot(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
        val version = database.version
        if (version > 1) fail("ANDROID_STORAGE_VERSION_UNSUPPORTED")
        database.version = 1
        database.rawQuery("SELECT payload FROM snapshot WHERE id=1", null).use { cursor ->
            state = if (cursor.moveToFirst()) JSONObject(cursor.getString(0)) else obj(
                "contentVersion" to content.getString("version"), "lessonId" to lessons.first().getString("id"),
                "revision" to 0, "completed" to 0, "roundsSinceBreak" to 0, "attempts" to JSONArray(),
                "receipts" to JSONObject(), "finished" to JSONObject(), "exposure" to JSONObject()
            )
        }
        validate(state)
    }
    private fun update(change: (JSONObject) -> Unit) {
        val next = copy(state)
        change(next)
        next.put("revision", state.getInt("revision") + 1)
        database.beginTransaction()
        try {
            database.execSQL("INSERT OR REPLACE INTO snapshot(id,payload) VALUES(1,?)", arrayOf(next.toString()))
            database.setTransactionSuccessful()
        } finally { database.endTransaction() }
        state = next
    }
    private fun instant(at: Double = now()) = Instant.ofEpochMilli((at * 1000).toLong())
    private fun date(at: Double) = instant(at).atZone(zone).toLocalDate().toString()
    private fun skew() = state.optDouble("lastObserved", 0.0) - now() > 300
    private fun sessionMinutes() = state.optInt("gameSessionMinutes", policy.getInt("sessionMinutes"))
    private fun dailyMinutes() = state.optInt("gameDailyMinutes", policy.getInt("dailyMinutes"))
    private fun current() = state.optJSONObject("current")
    private fun attempts() = state.getJSONArray("attempts").rows()
    private fun mastery(id: String, records: List<JSONObject> = attempts()): JSONObject {
        val required = knowledge.first { it.getString("id") == id }.getJSONArray("requiredModes").strings().filter { it in modes }.toSet()
        val window = records.filter { it.getString("knowledgeId") == id && it.getBoolean("credit") && it.getString("mode") in modes }.sortedWith(compareBy({ it.getDouble("at") }, { it.getString("id") })).takeLast(8)
        val correct = window.filter { it.getBoolean("firstCorrect") }
        val covered = correct.map { it.getString("mode") }.toSet()
        val mastered = window.size >= 5 && correct.size * 5 >= window.size * 4 && window.takeLast(2).all { it.getBoolean("firstCorrect") } && required.isNotEmpty() && covered.containsAll(required)
        return obj("knowledgeId" to id, "status" to if (window.isEmpty()) "not-started" else if (mastered) "mastered" else "practicing", "sampleSize" to window.size, "correctCount" to correct.size, "accuracy" to if (window.isEmpty()) null else correct.size.toDouble()/window.size, "coveredModes" to JSONArray(covered.sorted()), "requiredModes" to JSONArray(required.sorted()), "reviewDue" to false, "reviewDueDate" to null)
    }
    private fun progress() = obj("revision" to state.getInt("revision"), "selectedLessonId" to state.getString("lessonId"), "completedSessions" to state.getInt("completed"), "attemptCount" to attempts().size, "clockSkewDetected" to skew(), "pendingClockAttempts" to attempts().count { it.getBoolean("clockPending") }, "settings" to obj("soundEnabled" to true, "reducedMotion" to false, "gameSessionMinutes" to sessionMinutes(), "gameDailyMinutes" to dailyMinutes()), "mastery" to JSONArray(knowledge.map { mastery(it.getString("id")) }))
    private fun project(round: JSONObject): JSONObject {
        val result = copy(round)
        result.put("tasks", JSONArray(round.getJSONArray("tasks").rows().map { obj("instanceId" to it.getString("instanceId"), "exercise" to it.getJSONObject("publicExercise")) }))
        return result
    }
    private fun rank(tasks: List<JSONObject>): List<JSONObject> = tasks.sortedWith(compareBy({ state.getJSONObject("exposure").optJSONObject(it.getJSONObject("exercise").getString("id"))?.optInt("count") ?: 0 }, { state.getJSONObject("exposure").optJSONObject(it.getJSONObject("exercise").getString("id"))?.optDouble("latest") ?: 0.0 }))
    private fun instantiate(row: JSONObject): JSONObject {
        val exercise = copy(row.getJSONObject("exercise"))
        val correct = exercise.getJSONObject("answer").getString("optionId")
        exercise.remove("answer"); exercise.remove("hint"); exercise.remove("reviewStatus")
        val id = "op1_" + UUID.randomUUID().toString().replace("-", "").take(24)
        val options = exercise.getJSONArray("options").rows().sortedBy { option -> MessageDigest.getInstance("SHA-256").digest("$id:${option.getString("id")}".toByteArray()).joinToString("") { "%02x".format(it) } }
        exercise.put("options", JSONArray(options))
        return obj("instanceId" to id, "exerciseId" to exercise.getString("id"), "knowledgeId" to exercise.getString("primaryKnowledgeId"), "mode" to exercise.getString("type"), "correctOption" to correct, "hintUsed" to false, "explanation" to row.getString("explanation"), "publicExercise" to exercise)
    }
    private fun recommendation(): JSONObject {
        val order = lessons.first { it.getString("id") == state.getString("lessonId") }.getInt("order")
        val keys = lessons.filter { it.getInt("order") <= order }.flatMap { it.getJSONArray("knowledgeIds").strings() }.toSet()
        val values = keys.map { mastery(it) }
        val samples = values.sumOf { it.getInt("sampleSize") }; val correct = values.sumOf { it.getInt("correctCount") }; val mastered = values.count { it.getString("status") == "mastered" }
        val accuracy = if (samples == 0) 0.0 else correct.toDouble()/samples
        val a = rules.getJSONObject("adaptation")
        val steady = samples >= a.getInt("steadySamples") && accuracy >= a.getDouble("steadyAccuracy")
        val challenge = samples >= a.getInt("challengeSamples") && accuracy >= a.getDouble("challengeAccuracy") && mastered >= a.getInt("challengeMastered")
        return obj("level" to if (challenge) "challenge" else if (steady) "steady" else "gentle", "speed" to if (steady) "normal" else "slow", "sampleSize" to samples, "correctCount" to correct, "masteredCount" to mastered)
    }
    private fun settings(difficulty: String, speed: String, rec: JSONObject = recommendation()): JSONObject {
        if (difficulty !in setOf("auto", "gentle", "steady", "challenge") || speed !in setOf("auto", "slow", "normal", "fast")) fail("GAME_SETTINGS_INVALID")
        return obj("version" to 1, "level" to if (difficulty == "auto") rec.getString("level") else difficulty, "speed" to if (speed == "auto") rec.getString("speed") else speed, "requestedDifficulty" to difficulty, "requestedSpeed" to speed, "recommendation" to rec)
    }
    private fun freeze(gameId: String, levelId: String?, difficulty: String, tasks: List<JSONObject>): JSONObject {
        val routes = game.getJSONObject("routes")
        val level = copy(routes.getJSONArray("levels").rows().firstOrNull { it.getString("gameId") == gameId && (if (levelId != null) it.getString("id") == levelId else it.getString("recommendedDifficulty") == difficulty) } ?: fail("GAME_LEVEL_NOT_FOUND"))
        val chapters = level.getJSONArray("chapters").rows(); val bindings = JSONArray(); val patterns = JSONObject()
        chapters.forEachIndexed { i, chapter ->
            val templates = chapter.getJSONArray("segments").rows()
            val count = tasks.size / chapters.size + if (i < tasks.size % chapters.size) 1 else 0
            chapter.put("segments", JSONArray((0 until count).map { j ->
                val key = templates[j % templates.size].getString("patternId"); val id = "play-${i+1}-${j+1}"
                bindings.put(obj("segmentId" to id, "instanceId" to tasks[bindings.length()].getString("instanceId")))
                patterns.put(key, routes.getJSONObject("patterns").get(key)); obj("id" to id, "patternId" to key)
            }))
        }
        return obj("version" to 2, "catalogVersion" to routes.getInt("version"), "level" to level, "patterns" to patterns, "theme" to routes.getJSONObject("themes").get(level.getString("themeId")), "bindings" to bindings)
    }
    private fun clock(action: String, persist: Boolean = false): JSONObject {
        val at = now(); val value = copy(state.optJSONObject("gameClock") ?: obj("days" to JSONObject(), "runSeconds" to 0.0, "accountedAt" to 0.0, "leaseUntil" to 0.0))
        val days = value.getJSONObject("days"); var start = value.getDouble("accountedAt"); val end = minOf(at, value.getDouble("leaseUntil"))
        var run = value.getDouble("runSeconds") + maxOf(0.0, end-start)
        while (start < end) {
            val next = instant(start).atZone(zone).toLocalDate().plusDays(1).atStartOfDay(zone).toEpochSecond().toDouble()
            val stop = minOf(end, next); val day = date(start)
            days.put(day, days.optDouble(day, 0.0) + stop-start); start = stop
        }
        val accounted = maxOf(at, value.getDouble("accountedAt")); var lease = value.getDouble("leaseUntil")
        if (at >= lease + policy.getDouble("breakSeconds")) run = 0.0
        days.keys().asSequence().toList().sorted().dropLast(32).forEach { days.remove(it) }
        val used = days.optDouble(date(at), 0.0); val left = maxOf(0.0, minOf(sessionMinutes()*60-run, dailyMinutes()*60-used))
        val reason = when { at < accounted -> "GAME_CLOCK_ROLLBACK"; used >= dailyMinutes()*60 -> "GAME_DAILY_LIMIT"; run >= sessionMinutes()*60 -> "GAME_SESSION_LIMIT"; else -> null }
        if (action == "heartbeat" && reason == null) lease = at + minOf(policy.getDouble("leaseSeconds"), left)
        if (action == "pause") lease = minOf(lease, at)
        value.put("accountedAt", accounted); value.put("leaseUntil", lease); value.put("runSeconds", run)
        if (persist) update { it.put("gameClock", value) }
        return obj("day" to date(at), "dailySeconds" to used, "sessionSeconds" to run, "remainingSeconds" to left, "reason" to reason, "breakRemainingSeconds" to if (reason == "GAME_SESSION_LIMIT") maxOf(0.0, lease+policy.getDouble("breakSeconds")-at) else 0.0, "leaseSeconds" to if (reason == null) maxOf(0.0, minOf(lease-at, left)) else 0.0, "sessionMinutes" to sessionMinutes(), "dailyMinutes" to dailyMinutes())
    }
    @Synchronized fun pause() { if (state.optJSONObject("gameClock") != null) clock("pause", true) }
    private fun requireLease(round: JSONObject) {
        if (!round.has("gameId")) return
        val status = clock("status"); if (!status.isNull("reason")) fail(status.getString("reason"))
        if (status.getDouble("leaseSeconds") <= 0) fail("GAME_PAUSED")
    }
    private fun start(body: JSONObject): JSONObject {
        val id = body.optString("lessonId"); val gameId = body.optString("gameId")
        current()?.let { if (it.getString("lessonId") != id || it.optString("gameId") != gameId) fail("SESSION_ACTIVE"); return project(it) }
        if (state.getInt("roundsSinceBreak") >= 2) fail("REST_REQUIRED")
        val lesson = lessons.firstOrNull { it.getString("id") == id } ?: fail("LESSON_NOT_FOUND")
        val order = lessons.first { it.getString("id") == state.getString("lessonId") }.getInt("order")
        if (lesson.getInt("order") > order) fail("LESSON_NOT_UNLOCKED")
        var prefs: JSONObject? = null
        val selected = if (gameId.isEmpty()) rank(lesson.getJSONArray("exerciseIds").strings().mapNotNull { questions[it] }).take(6) else {
            val definition = rules.getJSONArray("games").rows().firstOrNull { it.getString("id") == gameId } ?: fail("GAME_NOT_FOUND")
            val play = rules.getJSONObject("play"); val count = body.optInt("gameTaskCount", play.getInt("defaultTasks"))
            if (count !in play.getInt("minTasks")..play.getInt("maxTasks")) fail("GAME_SETTINGS_INVALID")
            prefs = settings(body.optString("gameDifficulty", "auto"), body.optString("gameSpeed", "auto"))
            val allowed = definition.getJSONArray("modes").strings()
            val eligible = lessons.filter { it.getInt("order") <= order }.flatMap { it.getJSONArray("exerciseIds").strings() }.distinct().mapNotNull { questions[it] }.filter { row ->
                val q = row.getJSONObject("exercise"); q.getString("type") in allowed && q.has("audioRef") && q.getJSONArray("options").rows().all { !it.has("pictureId") && !it.has("writing") }
            }
            if (eligible.size < count) fail("GAME_LEVEL_CONTENT_INSUFFICIENT")
            val candidates = eligible.filter { it.getJSONObject("exercise").getString("type") == definition.getString("mode") } + eligible.filter { it.getJSONObject("exercise").getString("type") != definition.getString("mode") }
            val weak = rank(candidates.filter { mastery(it.getJSONObject("exercise").getString("primaryKnowledgeId")).getString("status") == "practicing" }).take(minOf(count, rules.getJSONObject("adaptation").getInt("weakSlots")))
            val currentIds = lesson.getJSONArray("exerciseIds").strings().toSet()
            val pending = (weak + rank(candidates.filter { it.getJSONObject("exercise").getString("id") in currentIds }) + rank(candidates)).distinctBy { it.getJSONObject("exercise").getString("id") }.toMutableList()
            val spread = mutableListOf<JSONObject>()
            while (pending.isNotEmpty() && spread.size < count) {
                val targets = mutableSetOf<String>(); val iterator = pending.iterator()
                while (iterator.hasNext() && spread.size < count) { val row = iterator.next(); if (targets.add(row.getJSONObject("exercise").getString("primaryKnowledgeId"))) { spread.add(row); iterator.remove() } }
            }
            spread
        }
        if (selected.isEmpty()) fail("LESSON_NOT_READY")
        val tasks = selected.map { instantiate(it) }
        val round = obj("id" to UUID.randomUUID().toString(), "lessonId" to id, "contentVersion" to content.getString("version"), "startedAt" to instant().toString(), "tasks" to JSONArray(tasks), "results" to JSONObject())
        if (prefs != null) { round.put("gameId", gameId); round.put("gameSettings", prefs); round.put("gameRun", freeze(gameId, body.optString("gameLevelId").ifEmpty { null }, prefs.getString("level"), tasks)); val status = clock("heartbeat", true); if (!status.isNull("reason")) fail(status.getString("reason")) }
        update { it.put("current", round) }; return project(round)
    }
    private fun locate(id: String): Pair<JSONObject, JSONObject> { val round = current() ?: fail("INSTANCE_NOT_FOUND"); return round to (round.getJSONArray("tasks").rows().firstOrNull { it.getString("instanceId") == id } ?: fail("INSTANCE_NOT_FOUND")) }
    private fun unresolved(round: JSONObject, id: String) { round.getJSONObject("results").optJSONObject(id)?.let { fail(if (it.optBoolean("skipped")) "INSTANCE_ALREADY_SKIPPED" else "INSTANCE_ALREADY_ANSWERED") } }
    private fun expose(next: JSONObject, task: JSONObject) { val id = task.getString("exerciseId"); val exposure = next.getJSONObject("exposure"); val old = exposure.optJSONObject(id); exposure.put(id, obj("count" to (old?.optInt("count") ?: 0)+1, "latest" to maxOf(old?.optDouble("latest") ?: 0.0, now()))) }
    private fun answer(id: String, body: JSONObject): JSONObject {
        val request = body.optString("requestId"); val option = body.optString("answerOptionId")
        if (body.length() != 2 || request.length !in 8..80) fail("OPTION_NOT_VALID")
        state.getJSONObject("receipts").optJSONObject(request)?.let { if (it.getString("instanceId") != id || it.getString("answerOptionId") != option) fail("IDEMPOTENCY_KEY_REUSED"); return it }
        val (round, task) = locate(id); unresolved(round, id)
        if (task.getJSONObject("publicExercise").getJSONArray("options").rows().none { it.getString("id") == option }) fail("OPTION_NOT_VALID")
        requireLease(round)
        val at = now(); val pending = skew(); val credit = !pending && attempts().none { it.getString("exerciseId") == task.getString("exerciseId") && it.getString("knowledgeId") == task.getString("knowledgeId") && it.getString("day") == date(at) && it.getBoolean("credit") }
        val correct = option == task.getString("correctOption"); val first = correct && !task.getBoolean("hintUsed")
        val attempt = obj("id" to UUID.randomUUID().toString(), "exerciseId" to task.getString("exerciseId"), "knowledgeId" to task.getString("knowledgeId"), "mode" to task.getString("mode"), "day" to date(at), "at" to at, "firstCorrect" to first, "credit" to credit, "clockPending" to pending, "gameId" to round.opt("gameId"), "hintUsed" to task.getBoolean("hintUsed"))
        val result = obj("attemptId" to attempt.getString("id"), "requestId" to request, "instanceId" to id, "answerOptionId" to option, "correctOptionId" to task.getString("correctOption"), "correct" to correct, "firstTryCorrect" to first, "hintUsed" to task.getBoolean("hintUsed"), "creditedForMastery" to credit, "clockPending" to pending, "mastery" to mastery(task.getString("knowledgeId"), attempts()+attempt), "revision" to state.getInt("revision")+1, "explanation" to task.getString("explanation"), "explanationAudioId" to "hint-${task.getString("exerciseId")}")
        update { next -> next.getJSONObject("current").getJSONObject("results").put(id, result); next.getJSONObject("receipts").put(request, result); next.getJSONArray("attempts").put(attempt); next.put("lastObserved", maxOf(at, next.optDouble("lastObserved", at))); expose(next, task) }; return result
    }
    @Synchronized fun request(method: String, path: String, body: JSONObject): Any {
        when ("$method $path") {
            "GET /bootstrap" -> return obj("paired" to true, "isLocalHost" to true, "device" to obj("label" to "此设备", "isParent" to true), "profile" to obj("roundsSinceBreak" to state.getInt("roundsSinceBreak")), "attemptCount" to attempts().size)
            "GET /profiles/progress" -> return progress()
            "GET /sessions/current" -> return current()?.let { project(it) } ?: JSONObject.NULL
            "POST /sessions" -> return start(body)
            "POST /games/heartbeat" -> return clock("heartbeat", true)
            "POST /games/pause" -> return clock("pause", true)
            "GET /games" -> {
                val recent = attempts().filter { !it.isNull("gameId") && it.getDouble("at") >= now()-7*86400 }
                val rounds = state.getJSONObject("finished").let { f -> f.keys().asSequence().map { f.getJSONObject(it) }.toList() } + listOfNotNull(current())
                val skips = rounds.filter { it.has("gameId") }.sumOf { r -> r.getJSONObject("results").let { results -> results.keys().asSequence().map { results.getJSONObject(it) }.count { it.optBoolean("skipped") && Instant.parse(it.getString("skippedAt")).epochSecond >= now()-7*86400 } } }
                return obj("clock" to clock("status"), "recommendation" to recommendation(), "report" to obj("answered" to recent.size, "independentCorrect" to recent.count { it.getBoolean("firstCorrect") && !it.getBoolean("clockPending") }, "hints" to recent.count { it.optBoolean("hintUsed") }, "skipped" to skips, "pendingClock" to recent.count { it.getBoolean("clockPending") }, "practiceKnowledgeIds" to JSONArray(recent.filter { !it.getBoolean("firstCorrect") && !it.getBoolean("clockPending") }.map { it.getString("knowledgeId") }.distinct().sorted())))
            }
            "POST /rest/complete" -> { if (state.getInt("roundsSinceBreak") > 0) update { it.put("roundsSinceBreak", 0) }; return obj("breakRequired" to false) }
            "PUT /household/current-lesson" -> {
                val id = body.optString("lessonId"); if (lessons.none { it.getString("id") == id }) fail("LESSON_NOT_FOUND")
                if (body.optInt("expectedRevision", -1) != state.getInt("revision")) fail("REVISION_CONFLICT")
                if (current() != null) fail("SESSION_ACTIVE")
                if (state.getString("lessonId") != id) update { it.put("lessonId", id) }; return progress()
            }
            "PUT /household/game-limits" -> {
                val session = body.optInt("gameSessionMinutes"); val daily = body.optInt("gameDailyMinutes")
                if (body.length() != 2 || session !in 1..policy.getInt("sessionMaxMinutes") || daily !in 1..policy.getInt("dailyMaxMinutes")) fail("GAME_SETTINGS_INVALID")
                if (current() != null) fail("SESSION_ACTIVE")
                pause(); update { it.put("gameSessionMinutes", session); it.put("gameDailyMinutes", daily) }; return progress()
            }
        }
        val parts = path.trim('/').split('/')
        if (method == "GET" && parts.size == 2 && parts[0] == "attempts") return state.getJSONObject("receipts").optJSONObject(parts[1]) ?: fail("ATTEMPT_NOT_FOUND")
        if (parts.size == 3) {
            val id = parts[1]
            if (method == "PATCH" && parts[0] == "sessions" && parts[2] == "game-settings") {
                val round = current() ?: fail("SESSION_NOT_FOUND"); if (round.getString("id") != id || !round.has("gameId")) fail("SESSION_NOT_FOUND")
                val prefs = settings(body.getString("difficulty"), body.getString("speed"), round.getJSONObject("gameSettings").getJSONObject("recommendation"))
                val status = clock("heartbeat", true); if (!status.isNull("reason")) fail(status.getString("reason"))
                update { it.getJSONObject("current").put("gameSettings", prefs) }; return prefs
            }
            if (method == "POST" && parts[0] == "instances") when (parts[2]) {
                "answer" -> return answer(id, body)
                "hint" -> { val (round, task) = locate(id); unresolved(round,id); requireLease(round); if (!task.getBoolean("hintUsed")) update { n -> n.getJSONObject("current").getJSONArray("tasks").rows().first { it.getString("instanceId") == id }.put("hintUsed",true) }; return obj("hintUsed" to true, "answer" to obj("optionId" to task.getString("correctOption")), "explanation" to task.getString("explanation")) }
                "skip" -> { val (round, task) = locate(id); round.getJSONObject("results").optJSONObject(id)?.let { if (it.optBoolean("skipped")) return it }; unresolved(round,id); requireLease(round); val result = obj("instanceId" to id, "skipped" to true, "skippedAt" to instant().toString()); update { n -> n.getJSONObject("current").getJSONObject("results").put(id,result); expose(n,task) }; return result }
            }
            if (method == "POST" && parts[0] == "sessions" && parts[2] == "finish") {
                val previous = state.getJSONObject("finished").optJSONObject(id)
                val round = previous ?: current()?.takeIf { it.getString("id") == id } ?: fail("SESSION_NOT_FOUND")
                val completed = round.getJSONObject("results").length() == round.getJSONArray("tasks").length()
                if (previous == null) { if (round.has("gameId")) pause(); update { n -> n.remove("current"); n.getJSONObject("finished").put(id,round); if (completed) { n.put("completed",n.getInt("completed")+1); n.put("roundsSinceBreak", minOf(2,n.getInt("roundsSinceBreak")+1)) } } }
                return obj("finished" to true, "completedRound" to completed, "breakRequired" to (state.getInt("roundsSinceBreak") >= 2))
            }
        }
        fail("ANDROID_OPERATION_UNAVAILABLE")
    }
    @Synchronized fun exportBackup(): ByteArray = obj("format" to "love-pinyin-android", "version" to 1, "contentVersion" to content.getString("version"), "createdAt" to instant().toString(), "state" to state).toString().toByteArray().also { if (it.size > BACKUP_LIMIT) fail("ANDROID_BACKUP_TOO_LARGE") }
    private fun readBackup(bytes: ByteArray): JSONObject {
        if (bytes.size > BACKUP_LIMIT) fail("ANDROID_BACKUP_TOO_LARGE")
        val backup = try { JSONObject(bytes.toString(Charsets.UTF_8)) } catch (_: Exception) { fail("ANDROID_BACKUP_INVALID") }
        if (backup.optString("format") != "love-pinyin-android") fail("ANDROID_BACKUP_INVALID")
        if (backup.optInt("version") != 1 || backup.optString("contentVersion") != content.getString("version")) fail("ANDROID_BACKUP_VERSION_UNSUPPORTED")
        val saved = backup.getJSONObject("state"); validate(saved); return saved
    }
    private fun validate(saved: JSONObject) {
        if (saved.optString("contentVersion") != content.getString("version")) fail("ANDROID_STORAGE_VERSION_UNSUPPORTED")
        if (lessons.none { it.getString("id") == saved.getString("lessonId") } || listOf("revision","completed","roundsSinceBreak").any { saved.getInt(it) < 0 }) fail("ANDROID_STORAGE_INVALID")
        val rows = saved.getJSONArray("attempts").rows(); if (rows.map { it.getString("id") }.distinct().size != rows.size || rows.any { a -> knowledge.none { it.getString("id") == a.getString("knowledgeId") } || a.getString("mode") !in modes }) fail("ANDROID_STORAGE_INVALID")
        val finished = saved.getJSONObject("finished")
        val rounds = finished.keys().asSequence().map { finished.getJSONObject(it) }.toList() + listOfNotNull(saved.optJSONObject("current"))
        rounds.forEach { round ->
            if (round.getString("contentVersion") != content.getString("version") || lessons.none { it.getString("id") == round.getString("lessonId") }) fail("ANDROID_STORAGE_INVALID")
            val tasks = round.getJSONArray("tasks").rows(); val ids = tasks.map { it.getString("instanceId") }
            if (tasks.isEmpty() || ids.distinct().size != ids.size || round.getJSONObject("results").keys().asSequence().any { it !in ids }) fail("ANDROID_STORAGE_INVALID")
            tasks.forEach { task -> val q = questions[task.getString("exerciseId")]?.getJSONObject("exercise") ?: fail("ANDROID_STORAGE_INVALID")
                if (task.getString("correctOption") != q.getJSONObject("answer").getString("optionId") || task.getString("knowledgeId") != q.getString("primaryKnowledgeId") || task.getString("mode") != q.getString("type") || task.getJSONObject("publicExercise").getJSONArray("options").rows().map { it.getString("id") }.toSet() != q.getJSONArray("options").rows().map { it.getString("id") }.toSet()) fail("ANDROID_STORAGE_INVALID") }
        }
        saved.getJSONObject("receipts"); saved.getJSONObject("exposure")
    }
    @Synchronized fun preview(bytes: ByteArray): Pair<String,Int> { val s = readBackup(bytes); return "Android 学习备份\n${s.getJSONArray("attempts").length()} 条作答，${s.getInt("completed")} 轮练习。\n将替换此设备的学习记录；不会合并。" to state.getInt("revision") }
    @Synchronized fun restore(bytes: ByteArray, revision: Int) { if (state.getInt("revision") != revision) fail("REVISION_CONFLICT"); val saved = readBackup(bytes); saved.optJSONObject("gameClock")?.put("leaseUntil",0); update { next -> next.keys().asSequence().toList().forEach { next.remove(it) }; saved.keys().forEach { next.put(it,saved.get(it)) } } }
    companion object { const val BACKUP_LIMIT = 64*1024*1024 }
}
