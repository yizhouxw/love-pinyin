package org.lovepinyin.android

import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.time.Instant
import java.time.ZoneId

/** Pure rules checked against the Python service using the same fixture inputs. */
internal object LearningRules {
    val objectiveModes = setOf("listen-choice", "symbol-choice", "tone-choice", "blend-choice")
    private val zone = ZoneId.of("Asia/Shanghai")

    fun mastery(requiredModes: List<String>, records: List<JSONObject>): JSONObject {
        val required = requiredModes.filter { it in objectiveModes }.toSet()
        val window = records.filter { it.getBoolean("credit") && it.getString("mode") in objectiveModes }
            .sortedWith(compareBy({ it.getDouble("at") }, { it.getString("id") })).takeLast(8)
        val correct = window.filter { it.getBoolean("firstCorrect") }
        val covered = correct.map { it.getString("mode") }.toSet()
        val mastered = window.size >= 5 && correct.size * 5 >= window.size * 4 &&
            window.takeLast(2).all { it.getBoolean("firstCorrect") } &&
            required.isNotEmpty() && covered.containsAll(required)
        return obj(
            "status" to if (window.isEmpty()) "not-started" else if (mastered) "mastered" else "practicing",
            "sampleSize" to window.size, "correctCount" to correct.size,
            "accuracy" to if (window.isEmpty()) null else correct.size.toDouble()/window.size,
            "coveredModes" to JSONArray(covered.sorted()), "requiredModes" to JSONArray(required.sorted())
        )
    }

    fun order(options: List<JSONObject>, id: String): List<JSONObject> {
        if (!id.startsWith("op1_") || id.length != 28) return options
        return options.sortedWith(compareBy({ option ->
            MessageDigest.getInstance("SHA-256").digest("$id:${option.getString("id")}".toByteArray())
                .joinToString("") { "%02x".format(it) }
        }, { it.getString("id") }))
    }

    fun emptyClock() = obj("version" to 1, "days" to JSONObject(), "runSeconds" to 0.0, "accountedAt" to 0.0, "leaseUntil" to 0.0)

    fun clock(source: JSONObject, at: Double, session: Int, daily: Int, action: String, policy: JSONObject): Pair<JSONObject, JSONObject> {
        val value = copy(source)
        value.put("version", 1)
        val days = value.getJSONObject("days")
        var start = value.getDouble("accountedAt")
        val end = minOf(at, value.getDouble("leaseUntil"))
        var run = value.getDouble("runSeconds") + maxOf(0.0, end-start)
        fun instant(time: Double) = Instant.ofEpochMilli((time*1000).toLong()).atZone(zone)
        while (start < end) {
            val local = instant(start)
            val next = local.toLocalDate().plusDays(1).atStartOfDay(zone).toEpochSecond().toDouble()
            val stop = minOf(end, next)
            val key = local.toLocalDate().toString()
            days.put(key, days.optDouble(key, 0.0) + stop-start)
            start = stop
        }
        val accounted = maxOf(at, value.getDouble("accountedAt"))
        var lease = value.getDouble("leaseUntil")
        if (at >= lease + policy.getDouble("breakSeconds")) run = 0.0
        days.keys().asSequence().toList().sorted().dropLast(32).forEach { days.remove(it) }
        val day = instant(at).toLocalDate().toString()
        val used = days.optDouble(day, 0.0)
        val left = maxOf(0.0, minOf(session*60-run, daily*60-used))
        val reason = when {
            at < accounted -> "GAME_CLOCK_ROLLBACK"
            used >= daily*60 -> "GAME_DAILY_LIMIT"
            run >= session*60 -> "GAME_SESSION_LIMIT"
            else -> null
        }
        if (action == "heartbeat" && reason == null) lease = at + minOf(policy.getDouble("leaseSeconds"), left)
        if (action == "pause") lease = minOf(lease, at)
        value.put("accountedAt", accounted).put("leaseUntil", lease).put("runSeconds", run)
        val status = obj(
            "day" to day, "dailySeconds" to used, "sessionSeconds" to run,
            "remainingSeconds" to left, "reason" to reason,
            "breakRemainingSeconds" to if (reason == "GAME_SESSION_LIMIT") maxOf(0.0, lease+policy.getDouble("breakSeconds")-at) else 0.0,
            "leaseSeconds" to if (reason == null) maxOf(0.0, minOf(lease-at, left)) else 0.0,
            "sessionMinutes" to session, "dailyMinutes" to daily
        )
        return value to status
    }
}
