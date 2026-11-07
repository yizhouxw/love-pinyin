import Foundation

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

        let output = try JSONSerialization.data(withJSONObject: [
            "lesson": lesson, "question": questionId, "instance": first, "options": optionOrder,
            "selected": publicQuestions.compactMap { $0["id"] as? String },
            "mastery": try json(result["mastery"]),
        ])
        FileHandle.standardOutput.write(output)
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
