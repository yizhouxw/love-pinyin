import Foundation

struct GameRules: Decodable {
    struct Policy: Decodable {
        let sessionMinutes: Int
        let dailyMinutes: Int
        let sessionMaxMinutes: Int
        let dailyMaxMinutes: Int
        let breakSeconds: Double
        let leaseSeconds: Double
    }

    struct Adaptation: Decodable {
        let steadySamples: Int
        let steadyAccuracy: Double
        let challengeSamples: Int
        let challengeAccuracy: Double
        let challengeMastered: Int
        let weakSlots: Int
    }

    struct Play: Decodable {
        let minTasks: Int
        let maxTasks: Int
        let defaultTasks: Int
    }

    struct Game: Decodable {
        let id: String
        let mode: String
        let modes: Set<String>
    }

    let policy: Policy
    let adaptation: Adaptation
    let play: Play
    let games: [Game]
}

struct GameRecommendation: Codable {
    let level: String
    let speed: String
    let sampleSize: Int
    let correctCount: Int
    let masteredCount: Int
}

struct LocalGameSettings: Codable {
    var version = 1
    let level: String
    let speed: String
    let requestedDifficulty: String
    let requestedSpeed: String
    let recommendation: GameRecommendation

    init(difficulty: String, speed: String, recommendation: GameRecommendation) throws {
        guard ["auto", "gentle", "steady", "challenge"].contains(difficulty),
              ["auto", "slow", "normal", "fast"].contains(speed)
        else { throw ClassroomError("GAME_SETTINGS_INVALID") }
        level = difficulty == "auto" ? recommendation.level : difficulty
        self.speed = speed == "auto" ? recommendation.speed : speed
        requestedDifficulty = difficulty
        requestedSpeed = speed
        self.recommendation = recommendation
    }
}

struct LocalGameClock: Codable, Equatable {
    enum Action { case status, heartbeat, pause }

    struct Status: Encodable {
        let day: String
        let dailySeconds: Double
        let sessionSeconds: Double
        let remainingSeconds: Double
        let reason: String?
        let breakRemainingSeconds: Double
        let leaseSeconds: Double
        let sessionMinutes: Int
        let dailyMinutes: Int

        var projection: Classroom.JSON {
            [
                "day": day, "dailySeconds": dailySeconds, "sessionSeconds": sessionSeconds,
                "remainingSeconds": remainingSeconds, "reason": reason as Any? ?? NSNull(),
                "breakRemainingSeconds": breakRemainingSeconds, "leaseSeconds": leaseSeconds,
                "sessionMinutes": sessionMinutes, "dailyMinutes": dailyMinutes,
            ]
        }
    }

    var days: [String: Double] = [:]
    var runSeconds = 0.0
    var accountedAt = 0.0
    var leaseUntil = 0.0

    mutating func transition(
        _ action: Action, now: Date, session: Int, daily: Int,
        policy: GameRules.Policy, day: DateFormatter
    ) -> Status {
        let instant = now.timeIntervalSince1970
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = day.timeZone
        var start = accountedAt
        let end = min(instant, leaseUntil)
        if end > start { runSeconds += end - start }
        while start < end {
            let date = Date(timeIntervalSince1970: start)
            let next = calendar.dateInterval(of: .day, for: date)?.end.timeIntervalSince1970 ?? end
            let stop = next > start ? min(end, next) : end
            days[day.string(from: date), default: 0] += stop - start
            start = stop
        }
        accountedAt = max(instant, accountedAt)
        if instant >= leaseUntil + policy.breakSeconds { runSeconds = 0 }
        for key in days.keys.sorted().dropLast(32) { days.removeValue(forKey: key) }

        let dateKey = day.string(from: now)
        let usedToday = days[dateKey, default: 0]
        let left = max(0, min(Double(session * 60) - runSeconds, Double(daily * 60) - usedToday))
        let reason: String?
        if instant < accountedAt { reason = "GAME_CLOCK_ROLLBACK" }
        else if usedToday >= Double(daily * 60) { reason = "GAME_DAILY_LIMIT" }
        else if runSeconds >= Double(session * 60) { reason = "GAME_SESSION_LIMIT" }
        else { reason = nil }

        if action == .heartbeat && reason == nil { leaseUntil = instant + min(policy.leaseSeconds, left) }
        if action == .pause { leaseUntil = min(leaseUntil, instant) }
        return Status(
            day: dateKey, dailySeconds: usedToday, sessionSeconds: runSeconds, remainingSeconds: left, reason: reason,
            breakRemainingSeconds: reason == "GAME_SESSION_LIMIT" ? max(0, leaseUntil + policy.breakSeconds - instant) : 0,
            leaseSeconds: reason == nil ? max(0, min(leaseUntil - instant, left)) : 0,
            sessionMinutes: session, dailyMinutes: daily
        )
    }
}

struct GameRoutes {
    private let version: Int
    private let levels: [Classroom.JSON]
    private let patterns: Classroom.JSON
    private let themes: Classroom.JSON

    init(_ value: Classroom.JSON) throws {
        guard let version = value["version"] as? Int, let levels = value["levels"] as? [Classroom.JSON],
              let patterns = value["patterns"] as? Classroom.JSON, let themes = value["themes"] as? Classroom.JSON
        else { throw ClassroomError("IOS_RESOURCE_UNAVAILABLE") }
        self.version = version
        self.levels = levels
        self.patterns = patterns
        self.themes = themes
    }

    func freeze(gameId: String, levelId: String?, difficulty: String, instances: [String]) throws -> Data {
        guard var level = levels.first(where: {
            $0["gameId"] as? String == gameId
                && (levelId != nil ? $0["id"] as? String == levelId : $0["recommendedDifficulty"] as? String == difficulty)
        }) else { throw ClassroomError("GAME_LEVEL_NOT_FOUND") }
        guard var chapters = level["chapters"] as? [Classroom.JSON], chapters.count == 3,
              let themeId = level["themeId"] as? String, let theme = themes[themeId]
        else { throw ClassroomError("IOS_RESOURCE_UNAVAILABLE") }

        var bindings: [[String: String]] = []
        var used: Classroom.JSON = [:]
        for i in chapters.indices {
            guard let templates = chapters[i]["segments"] as? [Classroom.JSON], !templates.isEmpty else {
                throw ClassroomError("IOS_RESOURCE_UNAVAILABLE")
            }
            let count = instances.count / chapters.count + (i < instances.count % chapters.count ? 1 : 0)
            chapters[i]["segments"] = try (0..<count).map { j in
                guard let key = templates[j % templates.count]["patternId"] as? String, let pattern = patterns[key] else {
                    throw ClassroomError("IOS_RESOURCE_UNAVAILABLE")
                }
                let id = "play-\(i + 1)-\(j + 1)"
                bindings.append(["segmentId": id, "instanceId": instances[bindings.count]])
                used[key] = pattern
                return ["id": id, "patternId": key]
            }
        }
        level["chapters"] = chapters
        return try JSONSerialization.data(withJSONObject: [
            "version": 2, "catalogVersion": version, "level": level, "patterns": used,
            "theme": theme, "bindings": bindings,
        ])
    }
}
