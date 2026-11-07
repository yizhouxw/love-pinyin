import Foundation

@main
enum GameSmoke {
    static func main() throws {
        let content = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let fixture = try json(JSONSerialization.jsonObject(with: content))
        let game = try json(fixture["game"])
        let rules = try json(game["rules"])
        let games = try rows(rules["games"])
        let questions = try rows(fixture["eligible"]).map { try json($0["exercise"]) }
        let byId = try Dictionary(uniqueKeysWithValues: questions.map { (try text($0["id"]), $0) })
        let lesson = try text(rows(fixture["lessons"])[0]["id"])
        let folder = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
        let clock = ISO8601DateFormatter().date(from: "2026-11-06T15:59:57Z")!
        var samples: [Classroom.JSON] = []
        for definition in games {
            let gameId = try text(definition["id"])
            let url = folder.appendingPathComponent("\(gameId).sqlite")
            var time = clock
            var service = try Classroom(content: content, database: url, now: { time })
            func call(_ method: String, _ path: String, _ body: Classroom.JSON = [:]) throws -> Classroom.JSON {
                try json(service.request(method: method, path: path, body: body))
            }

            _ = try call("PUT", "/household/game-limits", ["gameSessionMinutes": 1, "gameDailyMinutes": 2])
            let round = try call("POST", "/sessions", ["lessonId": lesson, "gameId": gameId, "gameTaskCount": 7])
            let roundId = try text(round["id"])
            let tasks = try rows(round["tasks"])
            try check(tasks.count == 7 && round["gameId"] as? String == gameId, "frozen game round")
            let route = try json(round["gameRun"])
            let settings = try json(round["gameSettings"])
            let first = try text(tasks[0]["instanceId"])
            let firstQuestion = try text(json(tasks[0]["exercise"])["id"])
            let firstAnswer = try text(json(json(byId[firstQuestion])["answer"])["optionId"])
            let request = ["requestId": "game-smoke-answer-0", "answerOptionId": firstAnswer]

            time = time.addingTimeInterval(5)
            try service.pauseGameOnInterruption()
            try expect("GAME_PAUSED") { _ = try call("POST", "/instances/\(first)/answer", request) }
            let paused = try json(call("GET", "/games")["clock"])
            try check(paused["sessionSeconds"] as? Double == 5, "bounded foreground time")
            try check(paused["dailySeconds"] as? Double == 2, "Shanghai midnight split")
            time = time.addingTimeInterval(10)
            let afterPause = try json(call("GET", "/games")["clock"])
            try check(afterPause["sessionSeconds"] as? Double == 5, "paused time does not accrue")

            service = try Classroom(content: content, database: url, now: { time })
            let restored = try call("GET", "/sessions/current")
            try check(restored["id"] as? String == roundId, "round survives reopen")
            try check(NSDictionary(dictionary: try json(restored["gameRun"])).isEqual(to: route), "route survives reopen")
            try expect("GAME_PAUSED") { _ = try call("POST", "/instances/\(first)/hint") }
            let resumed = try call("POST", "/games/heartbeat")
            try check((resumed["leaseSeconds"] as? Double ?? 0) > 0, "resume")
            let edited = try call("PATCH", "/sessions/\(roundId)/game-settings", ["difficulty": "steady", "speed": "fast"])
            try check(edited["level"] as? String == "steady" && edited["speed"] as? String == "fast", "in-game settings")
            let firstReceipt = try call("POST", "/instances/\(first)/answer", request)
            try check(firstReceipt["correct"] as? Bool == true, "first answer")
            time = time.addingTimeInterval(20)
            let expired = try json(call("GET", "/games")["clock"])
            try check(expired["sessionSeconds"] as? Double == 17, "kill or suspension bounded by lease")
            let replay = try call("POST", "/instances/\(first)/answer", request)
            try check(replay["attemptId"] as? String == firstReceipt["attemptId"] as? String, "receipt after lease expiry")
            let previous = time
            time = clock
            let rollback = try call("POST", "/games/heartbeat")
            try check(rollback["reason"] as? String == "GAME_CLOCK_ROLLBACK", "time rollback")
            time = previous

            _ = try call("POST", "/games/heartbeat")
            let skipId = try text(tasks[1]["instanceId"])
            _ = try call("POST", "/instances/\(skipId)/skip")
            for (index, task) in tasks.enumerated().dropFirst(2) {
                let instance = try text(task["instanceId"])
                let exercise = try text(json(task["exercise"])["id"])
                let answer = try text(json(json(byId[exercise])["answer"])["optionId"])
                _ = try call("POST", "/instances/\(instance)/answer", [
                    "requestId": "game-smoke-answer-\(index)", "answerOptionId": answer,
                ])
            }
            let finished = try call("POST", "/sessions/\(roundId)/finish")
            try check(finished["completedRound"] as? Bool == true, "whole level completed")
            let report = try json(call("GET", "/games")["report"])
            try check(report["answered"] as? Int == 6 && report["skipped"] as? Int == 1, "game report")
            samples.append(["game": gameId, "lesson": lesson, "run": route, "settings": settings,
                            "selected": try tasks.map { try text(json($0["exercise"])["id"]) }])

            for _ in 0..<4 {
                _ = try call("POST", "/games/heartbeat")
                time = time.addingTimeInterval(12)
            }
            let limited = try call("POST", "/games/heartbeat")
            try check(limited["reason"] as? String == "GAME_SESSION_LIMIT", "one-minute session limit")
            time = time.addingTimeInterval(600)
            let afterBreak = try call("POST", "/games/heartbeat")
            try check(afterBreak["sessionSeconds"] as? Double == 0, "rest restores session budget")
            _ = try call("PUT", "/household/game-limits", ["gameSessionMinutes": 1, "gameDailyMinutes": 1])
            let lastLease = try call("POST", "/games/heartbeat")
            try check(lastLease["leaseSeconds"] as? Double == 3, "lease ends at the daily budget")
            time = time.addingTimeInterval(3)
            let dailyLimit = try call("POST", "/games/heartbeat")
            try check(dailyLimit["reason"] as? String == "GAME_DAILY_LIMIT", "daily limit persists through a break")
            time = time.addingTimeInterval(86400)
            let nextDay = try call("POST", "/games/heartbeat")
            try check(nextDay["dailySeconds"] as? Double == 0 && nextDay["leaseSeconds"] as? Double == 12,
                      "the next Shanghai day restores the daily budget")
        }
        FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: samples))
    }

    static func check(_ passed: @autoclosure () throws -> Bool, _ message: String) throws {
        if try !passed() { throw ClassroomError("game test: \(message)") }
    }

    static func expect(_ code: String, _ run: () throws -> Void) throws {
        do {
            try run()
            throw ClassroomError("game test: expected \(code)")
        } catch let error as ClassroomError where error.code == code {}
    }

    static func text(_ value: Any?) throws -> String {
        guard let value = value as? String else { throw ClassroomError("game test: missing string") }
        return value
    }

    static func json(_ value: Any?) throws -> Classroom.JSON {
        guard let value = value as? Classroom.JSON else { throw ClassroomError("game test: missing object") }
        return value
    }

    static func rows(_ value: Any?) throws -> [Classroom.JSON] {
        guard let value = value as? [Classroom.JSON] else { throw ClassroomError("game test: missing array") }
        return value
    }
}
