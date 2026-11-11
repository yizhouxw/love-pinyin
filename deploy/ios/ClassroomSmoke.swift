import Foundation
import SQLite3

@main
enum ClassroomSmoke {
    static func main() throws {
        let content = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let folder = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
        let database = folder.appendingPathComponent("classroom.sqlite")
        let syllabus = try json(JSONSerialization.jsonObject(with: content))
        let lessons = try rows(syllabus["lessons"])
        let lesson = try text(lessons[0]["id"])
        let eligible = try rows(syllabus["eligible"])
        let exercises = try eligible.map { try json($0["exercise"]) }
        let byId = try Dictionary(uniqueKeysWithValues: exercises.map { (try text($0["id"]), $0) })
        let expected = (lessons[0]["exerciseIds"] as? [String] ?? []).filter { byId[$0] != nil }.prefix(6)
        let clock = ISO8601DateFormatter().date(from: "2026-11-06T16:01:00Z")!
        var time = clock
        var classroom = try Classroom(content: content, database: database, now: { time })

        func request(_ method: String, _ path: String, _ body: Classroom.JSON = [:]) throws -> Classroom.JSON {
            try json(classroom.request(method: method, path: path, body: body))
        }

        let started = try request("POST", "/sessions", ["lessonId": lesson])
        let roundId = try text(started["id"])
        let tasks = try rows(started["tasks"])
        let publicQuestions = try tasks.map { try json($0["exercise"]) }
        try check(publicQuestions.compactMap { $0["id"] as? String } == Array(expected), "authored order")
        try check(publicQuestions.allSatisfy { $0["answer"] == nil && $0["hint"] == nil }, "answer projection")

        let first = try text(tasks[0]["instanceId"])
        let questionId = try text(publicQuestions[0]["id"])
        let source = try json(byId[questionId])
        let correct = try text(json(source["answer"])["optionId"])
        let hint = try request("POST", "/instances/\(first)/hint")
        try check(try text(json(hint["answer"])["optionId"]) == correct, "hint from authored answer")
        let requestId = "smoke-first-answer"
        let answer = ["requestId": requestId, "answerOptionId": correct]
        let result = try request("POST", "/instances/\(first)/answer", answer)
        try check(result["correct"] as? Bool == true && result["firstTryCorrect"] as? Bool == false, "hinted result")
        try check(result["creditedForMastery"] as? Bool == true, "first daily credit")
        let optionOrder = try rows(publicQuestions[0]["options"]).map { try text($0["id"]) }

        classroom = try Classroom(content: content, database: database, now: { time })
        let restored = try request("GET", "/sessions/current")
        try check(restored["id"] as? String == roundId, "round recovery")
        let results = try json(restored["results"])
        try check(try text(json(results[first])["attemptId"]) == text(result["attemptId"]), "saved result")
        let replay = try request("POST", "/instances/\(first)/answer", answer)
        try check(replay["attemptId"] as? String == result["attemptId"] as? String, "request replay")
        do {
            _ = try request("POST", "/instances/\(first)/answer", [
                "requestId": requestId, "answerOptionId": "different",
            ])
            throw ClassroomError("test: accepted mismatched request replay")
        } catch let error as ClassroomError where error.code == "IDEMPOTENCY_KEY_REUSED" {}

        for task in tasks.dropFirst() {
            let id = try text(task["instanceId"])
            _ = try request("POST", "/instances/\(id)/skip")
        }
        let finish = try request("POST", "/sessions/\(roundId)/finish")
        try check(finish["completedRound"] as? Bool == true, "finish a complete round")
        _ = try request("POST", "/sessions/\(roundId)/finish")
        let progress = try request("GET", "/profiles/progress")
        try check(progress["attemptCount"] as? Int == 1 && progress["completedSessions"] as? Int == 1, "durable counts")

        // Limit this scenario to the already used questions to force same-day
        // repetition independently of the size of the authored lesson.
        var repeatSyllabus = syllabus
        repeatSyllabus["eligible"] = eligible.filter { row in
            guard let exercise = row["exercise"] as? Classroom.JSON, let id = exercise["id"] as? String else { return false }
            return expected.contains(id)
        }
        classroom = try Classroom(
            content: JSONSerialization.data(withJSONObject: repeatSyllabus), database: database, now: { time }
        )
        let secondRound = try request("POST", "/sessions", ["lessonId": lesson])
        let secondTasks = try rows(secondRound["tasks"])
        guard let repeated = secondTasks.first(where: {
            ($0["exercise"] as? Classroom.JSON)?["id"] as? String == questionId
        }) else { throw ClassroomError("test: missing repeated question") }
        let repeatedId = try text(repeated["instanceId"])
        let repeatResult = try request("POST", "/instances/\(repeatedId)/answer", [
            "requestId": "smoke-repeat-answer", "answerOptionId": correct,
        ])
        try check(repeatResult["creditedForMastery"] as? Bool == false, "same-day credit deduplication")

        let untouched = try secondTasks.first(where: { try text(json($0["exercise"])["id"]) != questionId })!
        let untouchedId = try text(untouched["instanceId"])
        let option = try text(rows(json(untouched["exercise"])["options"])[0]["id"])
        time = clock.addingTimeInterval(-301)
        let pending = try request("POST", "/instances/\(untouchedId)/answer", [
            "requestId": "smoke-clock-rollback", "answerOptionId": option,
        ])
        try check(pending["clockPending"] as? Bool == true, "clock rollback recorded")
        try check(pending["creditedForMastery"] as? Bool == false, "no credit with suspect time")
        time = clock

        let archive = try classroom.exportBackup()
        let destination = folder.appendingPathComponent("restored.sqlite")
        let clean = try Classroom(content: content, database: destination, now: { time })
        let preview = try clean.previewBackup(archive)
        try check(preview.text.contains("3 条作答"), "backup preview")
        try clean.restoreBackup(archive, expectedRevision: preview.revision)
        let reopened = try Classroom(content: content, database: destination, now: { time })
        let restoredProgress = try json(reopened.request(method: "GET", path: "/profiles/progress", body: [:]))
        try check(restoredProgress["attemptCount"] as? Int == 3, "backup persisted on new installation")
        do {
            try clean.restoreBackup(archive, expectedRevision: preview.revision)
            throw ClassroomError("test: accepted stale preview")
        } catch let error as ClassroomError where error.code == "REVISION_CONFLICT" {}
        var invalid = try json(JSONSerialization.jsonObject(with: archive))
        invalid["version"] = 999
        do {
            let data = try JSONSerialization.data(withJSONObject: invalid)
            let revision = try clean.previewBackup(archive).revision
            try clean.restoreBackup(data, expectedRevision: revision)
            throw ClassroomError("test: accepted future backup version")
        } catch let error as ClassroomError where error.code == "IOS_BACKUP_VERSION_UNSUPPORTED" {}
        let unchanged = try json(clean.request(method: "GET", path: "/profiles/progress", body: [:]))
        try check(unchanged["attemptCount"] as? Int == 3, "invalid backup leaves history unchanged")

        let legacyURL = folder.appendingPathComponent("legacy.sqlite")
        let document = try json(JSONSerialization.jsonObject(with: archive))
        let legacyState = try JSONSerialization.data(withJSONObject: json(document["state"]))
        try sqlite(legacyURL, """
            CREATE TABLE classroom (id INTEGER PRIMARY KEY CHECK (id=1), state BLOB NOT NULL);
            PRAGMA user_version=1;
            INSERT INTO classroom VALUES (1, X'\(legacyState.map { String(format: "%02x", $0) }.joined())');
            """)
        for _ in 0..<2 {
            let migrated = try Classroom(content: content, database: legacyURL, now: { time })
            let stats = try json(migrated.request(method: "GET", path: "/profiles/progress", body: [:]))
            try check(stats["attemptCount"] as? Int == 3, "v1 migration retains history after reopen")
            let saved = try json(migrated.request(method: "GET", path: "/attempts/\(requestId)", body: [:]))
            try check(saved["attemptId"] as? String == result["attemptId"] as? String, "v1 migration retains receipts")
        }
        try sqlite(destination, """
            CREATE TRIGGER simulate_write_failure BEFORE UPDATE ON classroom
            BEGIN SELECT RAISE(ABORT, 'write failed'); END;
            """)
        do {
            try clean.restoreBackup(archive, expectedRevision: try clean.previewBackup(archive).revision)
            throw ClassroomError("test: backup write failure was ignored")
        } catch let error as ClassroomError where error.code == "IOS_STORAGE_UNAVAILABLE" {}
        let intact = try Classroom(content: content, database: destination, now: { time })
        let afterFailure = try json(intact.request(method: "GET", path: "/profiles/progress", body: [:]))
        try check(afterFailure["attemptCount"] as? Int == 3, "failed replacement rolls back history")
        if ProcessInfo.processInfo.environment["LP_IOS_BENCH"] == "1" {
            try benchmark(archive: archive, content: content, folder: folder, clock: time)
        }
        let output = try JSONSerialization.data(withJSONObject: [
            "lesson": lesson, "question": questionId, "instance": first, "options": optionOrder,
            "selected": publicQuestions.compactMap { $0["id"] as? String },
            "mastery": try json(result["mastery"]),
        ])
        FileHandle.standardOutput.write(output)
    }

    static func sqlite(_ url: URL, _ sql: String) throws {
        var db: OpaquePointer?
        defer { sqlite3_close(db) }
        guard sqlite3_open(url.path, &db) == SQLITE_OK, sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK
        else { throw ClassroomError("test: sqlite fixture setup failed") }
    }

    static func benchmark(archive: Data, content: Data, folder: URL, clock: Date) throws {
        var backup = try json(JSONSerialization.jsonObject(with: archive))
        var state = try json(backup["state"])
        state.removeValue(forKey: "current")
        let sample = try rows(state["attempts"])[0]
        let receipt = try json(state["receipts"]).values.first!
        for count in [10_000, 50_000] {
            state["attempts"] = (0..<count).map { index in
                var row = sample
                row["id"] = "synthetic-attempt-\(index)"
                return row
            }
            state["receipts"] = Dictionary(uniqueKeysWithValues: (0..<count).map { ("synthetic-receipt-\($0)", receipt) })
            backup["state"] = state
            let service = try Classroom(content: content,
                database: folder.appendingPathComponent("bench-\(count).sqlite"), now: { clock })
            let data = try JSONSerialization.data(withJSONObject: backup)
            try service.restoreBackup(data, expectedRevision: 0)
            var writes: [Double] = []
            var reads: [Double] = []
            for run in 0..<20 {
                var start = ProcessInfo.processInfo.systemUptime
                _ = try service.request(method: "PUT", path: "/household/game-limits",
                    body: ["gameSessionMinutes": 12 + run % 2, "gameDailyMinutes": 60])
                writes.append((ProcessInfo.processInfo.systemUptime - start) * 1_000)
                start = ProcessInfo.processInfo.systemUptime
                _ = try service.request(method: "GET", path: "/profiles/progress", body: [:])
                reads.append((ProcessInfo.processInfo.systemUptime - start) * 1_000)
            }
            let report = "iOS snapshot benchmark: \(count) attempts/receipts, \(data.count) bytes, p95 write \(writes.sorted()[18]) ms, p95 progress \(reads.sorted()[18]) ms\n"
            FileHandle.standardError.write(Data(report.utf8))
        }
    }

    static func check(_ condition: @autoclosure () throws -> Bool, _ name: String) throws {
        if try !condition() { throw ClassroomError("test: \(name)") }
    }

    static func text(_ value: Any?) throws -> String {
        guard let value = value as? String else { throw ClassroomError("test: expected string") }
        return value
    }

    static func json(_ value: Any?) throws -> Classroom.JSON {
        guard let value = value as? Classroom.JSON else { throw ClassroomError("test: expected object") }
        return value
    }

    static func rows(_ value: Any?) throws -> [Classroom.JSON] {
        guard let value = value as? [Classroom.JSON] else { throw ClassroomError("test: expected array") }
        return value
    }
}
