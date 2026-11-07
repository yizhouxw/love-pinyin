import CryptoKit
import Foundation

final class Classroom {
    typealias JSON = [String: Any]

    private struct Syllabus: Decodable {
        struct Lesson: Decodable {
            let id: String
            let order: Int
            let exerciseIds: [String]
        }

        struct Knowledge: Decodable {
            let id: String
            let requiredModes: [String]
        }

        let version: String
        let lessons: [Lesson]
        let knowledgeItems: [Knowledge]
    }

    private struct Task: Codable {
        let instanceId: String
        let exerciseId: String
        let knowledgeId: String
        let mode: String
        let options: [String]
        let correctOption: String
        let explanation: String
        let publicExercise: Data
        var hintUsed = false

        var projection: JSON {
            get throws {
                ["instanceId": instanceId, "exercise": try JSONSerialization.jsonObject(with: publicExercise)]
            }
        }

        func instantiate() throws -> Task {
            let id = "op1_" + UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased().prefix(24)
            guard var exercise = try JSONSerialization.jsonObject(with: publicExercise) as? JSON,
                  let options = exercise["options"] as? [JSON]
            else { throw ClassroomError("IOS_RESOURCE_UNAVAILABLE") }
            let sorted = try options.map { option -> (String, SHA256.Digest, JSON) in
                guard let value = option["id"] as? String else { throw ClassroomError("IOS_RESOURCE_UNAVAILABLE") }
                return (value, SHA256.hash(data: Data("\(id):\(value)".utf8)), option)
            }.sorted { left, right in
                left.1 == right.1 ? left.0 < right.0 : left.1.lexicographicallyPrecedes(right.1)
            }
            exercise["options"] = sorted.map { $0.2 }
            return Task(
                instanceId: id, exerciseId: exerciseId, knowledgeId: knowledgeId, mode: mode,
                options: sorted.map { $0.0 }, correctOption: correctOption, explanation: explanation,
                publicExercise: try JSONSerialization.data(withJSONObject: exercise)
            )
        }
    }

    private struct Round: Codable {
        let id: String
        let lessonId: String
        let contentVersion: String
        let startedAt: Date
        var tasks: [Task]
        var results: [String: Data] = [:]
    }

    private struct Attempt: Codable {
        let id: String
        let exerciseId: String
        let knowledgeId: String
        let mode: String
        let day: String
        let at: Date
        let firstCorrect: Bool
        let credit: Bool
        let clockPending: Bool
    }

    private struct Exposure: Codable {
        var count = 0
        var latest: Date?
    }

    private struct State: Codable {
        var lessonId: String
        var revision = 0
        var completed = 0
        var roundsSinceBreak = 0
        var current: Round?
        var finished: [String: Round] = [:]
        var receipts: [String: Data] = [:]
        var attempts: [Attempt] = []
        var exposure: [String: Exposure] = [:]
        var lastObserved: Date?
    }

    private let syllabus: Syllabus
    private let questions: [String: Task]
    private let store: ClassroomStore
    private let now: () -> Date
    private var state: State
    private let day = DateFormatter()
    private static let objectiveModes = Set(["listen-choice", "symbol-choice", "tone-choice", "blend-choice"])

    init(content: Data, database: URL, now: @escaping () -> Date = Date.init) throws {
        syllabus = try JSONDecoder().decode(Syllabus.self, from: content)
        guard let first = syllabus.lessons.first,
              let document = try JSONSerialization.jsonObject(with: content) as? JSON,
              let rows = document["eligible"] as? [JSON]
        else { throw ClassroomError("IOS_RESOURCE_UNAVAILABLE") }
        var tasks: [String: Task] = [:]
        for row in rows {
            guard var question = row["exercise"] as? JSON,
                  let id = question["id"] as? String,
                  let knowledge = question["primaryKnowledgeId"] as? String,
                  let mode = question["type"] as? String, Self.objectiveModes.contains(mode),
                  let options = question["options"] as? [JSON],
                  let answer = question.removeValue(forKey: "answer") as? JSON,
                  let correct = answer["optionId"] as? String,
                  let explanation = row["explanation"] as? String
            else { throw ClassroomError("IOS_RESOURCE_UNAVAILABLE") }
            let ids = options.compactMap { $0["id"] as? String }
            guard ids.count == options.count, ids.contains(correct), tasks[id] == nil else {
                throw ClassroomError("IOS_RESOURCE_UNAVAILABLE")
            }
            question.removeValue(forKey: "hint")
            question.removeValue(forKey: "reviewStatus")
            tasks[id] = Task(
                instanceId: "", exerciseId: id, knowledgeId: knowledge, mode: mode,
                options: ids, correctOption: correct, explanation: explanation,
                publicExercise: try JSONSerialization.data(withJSONObject: question)
            )
        }
        questions = tasks
        store = try ClassroomStore(url: database)
        if let raw = try store.load() {
            do {
                state = try JSONDecoder().decode(State.self, from: raw)
            } catch {
                throw ClassroomError("IOS_STORAGE_INVALID")
            }
        } else {
            state = State(lessonId: first.id)
        }
        self.now = now
        day.locale = Locale(identifier: "en_US_POSIX")
        day.calendar = Calendar(identifier: .gregorian)
        day.timeZone = TimeZone(identifier: "Asia/Shanghai")
        day.dateFormat = "yyyy-MM-dd"
    }

    func request(method: String, path: String, body: JSON) throws -> Any {
        switch (method, path) {
        case ("GET", "/bootstrap"):
            return [
                "paired": true, "isLocalHost": true,
                "device": ["label": "此设备", "isParent": true] as JSON,
                "profile": ["roundsSinceBreak": state.roundsSinceBreak],
                "attemptCount": state.attempts.count,
            ] as JSON
        case ("GET", "/profiles/progress"):
            return progress()
        case ("GET", "/sessions/current"):
            if let round = state.current { return try project(round) }
            return NSNull()
        case ("POST", "/sessions"):
            return try start(body)
        case ("POST", "/rest/complete"):
            if state.roundsSinceBreak > 0 {
                try update { $0.roundsSinceBreak = 0 }
            }
            return ["breakRequired": false]
        case ("PUT", "/household/current-lesson"):
            guard let id = body["lessonId"] as? String, syllabus.lessons.contains(where: { $0.id == id }) else {
                throw ClassroomError("LESSON_NOT_FOUND")
            }
            guard body["expectedRevision"] as? Int == state.revision else { throw ClassroomError("REVISION_CONFLICT") }
            guard state.current == nil else { throw ClassroomError("SESSION_ACTIVE") }
            if state.lessonId != id { try update { $0.lessonId = id } }
            return progress()
        default:
            break
        }
        let segments = path.split(separator: "/", omittingEmptySubsequences: true)
        if method == "GET", segments.count == 2, segments[0] == "attempts" {
            guard let saved = state.receipts[String(segments[1])] else { throw ClassroomError("ATTEMPT_NOT_FOUND") }
            return try decode(saved)
        }
        if method == "POST", segments.count == 3 {
            let id = String(segments[1])
            switch (segments[0], segments[2]) {
            case ("instances", "answer"): return try answer(id, body: body)
            case ("instances", "hint"): return try hint(id)
            case ("instances", "skip"): return try skip(id)
            case ("sessions", "finish"): return try finish(id)
            default: break
            }
        }
        throw ClassroomError("IOS_OPERATION_UNAVAILABLE")
    }

    private func update(_ change: (inout State) throws -> Void) throws {
        var next = state
        try change(&next)
        next.revision += 1
        try store.save(JSONEncoder().encode(next))
        state = next
    }

    private func decode(_ data: Data) throws -> JSON {
        guard let value = try JSONSerialization.jsonObject(with: data) as? JSON else {
            throw ClassroomError("IOS_STORAGE_INVALID")
        }
        return value
    }

    private func project(_ round: Round) throws -> JSON {
        [
            "id": round.id, "lessonId": round.lessonId, "contentVersion": round.contentVersion,
            "startedAt": ISO8601DateFormatter().string(from: round.startedAt),
            "tasks": try round.tasks.map { try $0.projection },
            "results": try round.results.mapValues(decode),
        ]
    }

    private func start(_ body: JSON) throws -> JSON {
        guard body.count == 1, let id = body["lessonId"] as? String else {
            throw ClassroomError("LESSON_NOT_FOUND")
        }
        if let round = state.current { return try project(round) }
        guard state.roundsSinceBreak < 2 else { throw ClassroomError("REST_REQUIRED") }
        guard let current = syllabus.lessons.first(where: { $0.id == state.lessonId }) else {
            throw ClassroomError("CURRENT_LESSON_REQUIRES_SELECTION")
        }
        guard let requested = syllabus.lessons.first(where: { $0.id == id }) else {
            throw ClassroomError("LESSON_NOT_FOUND")
        }
        guard requested.order <= current.order else { throw ClassroomError("LESSON_NOT_UNLOCKED") }
        let eligible = requested.exerciseIds.enumerated().compactMap { index, id in
            questions[id].map { (index, $0, state.exposure[id] ?? Exposure()) }
        }.sorted { left, right in
            let a = left.2, b = right.2
            if a.count != b.count { return a.count < b.count }
            if a.latest != b.latest { return (a.latest ?? .distantPast) < (b.latest ?? .distantPast) }
            return left.0 < right.0
        }
        let tasks = try eligible.prefix(6).map { try $0.1.instantiate() }
        guard !tasks.isEmpty else { throw ClassroomError("LESSON_NOT_READY") }
        let round = Round(
            id: UUID().uuidString, lessonId: id, contentVersion: syllabus.version,
            startedAt: now(), tasks: tasks
        )
        let result = try project(round)
        try update { $0.current = round }
        return result
    }

    private func locate(_ id: String) throws -> (Round, Int) {
        guard let round = state.current, let index = round.tasks.firstIndex(where: { $0.instanceId == id }) else {
            throw ClassroomError("INSTANCE_NOT_FOUND")
        }
        return (round, index)
    }

    private func unresolved(_ round: Round, _ id: String) throws {
        if let existing = round.results[id] {
            let skipped = try decode(existing)["skipped"] as? Bool == true
            throw ClassroomError(skipped ? "INSTANCE_ALREADY_SKIPPED" : "INSTANCE_ALREADY_ANSWERED")
        }
    }

    private func hint(_ id: String) throws -> JSON {
        let (round, index) = try locate(id)
        try unresolved(round, id)
        let task = round.tasks[index]
        if !task.hintUsed {
            try update { $0.current?.tasks[index].hintUsed = true }
        }
        return ["hintUsed": true, "answer": ["optionId": task.correctOption], "explanation": task.explanation]
    }

    private func recordExposure(_ task: Task, at: Date, state: inout State) {
        var seen = state.exposure[task.exerciseId] ?? Exposure()
        seen.count += 1
        seen.latest = max(seen.latest ?? at, at)
        state.exposure[task.exerciseId] = seen
    }

    private func skip(_ id: String) throws -> JSON {
        let (round, index) = try locate(id)
        if let saved = round.results[id], try decode(saved)["skipped"] as? Bool == true {
            return try decode(saved)
        }
        try unresolved(round, id)
        let time = now()
        let value: JSON = ["instanceId": id, "skipped": true, "skippedAt": ISO8601DateFormatter().string(from: time)]
        let encoded = try JSONSerialization.data(withJSONObject: value)
        try update {
            $0.current?.results[id] = encoded
            recordExposure(round.tasks[index], at: time, state: &$0)
        }
        return value
    }

    private func answer(_ id: String, body: JSON) throws -> JSON {
        guard body.count == 2, let requestId = body["requestId"] as? String, (8...80).contains(requestId.count),
              let option = body["answerOptionId"] as? String
        else { throw ClassroomError("OPTION_NOT_VALID") }
        if let previous = state.receipts[requestId] {
            let result = try decode(previous)
            guard result["instanceId"] as? String == id, result["answerOptionId"] as? String == option else {
                throw ClassroomError("IDEMPOTENCY_KEY_REUSED")
            }
            return result
        }
        let (round, index) = try locate(id)
        try unresolved(round, id)
        let task = round.tasks[index]
        guard task.options.contains(option) else { throw ClassroomError("OPTION_NOT_VALID") }
        let at = now()
        let today = day.string(from: at)
        let clockPending = clockSkew(at)
        let credit = !clockPending && !state.attempts.contains {
            $0.exerciseId == task.exerciseId && $0.knowledgeId == task.knowledgeId && $0.day == today && $0.credit
        }
        let correct = task.correctOption == option
        let attempt = Attempt(
            id: UUID().uuidString, exerciseId: task.exerciseId, knowledgeId: task.knowledgeId,
            mode: task.mode, day: today, at: at, firstCorrect: correct && !task.hintUsed, credit: credit,
            clockPending: clockPending
        )
        let result: JSON = [
            "attemptId": attempt.id, "requestId": requestId, "instanceId": id, "answerOptionId": option,
            "correctOptionId": task.correctOption, "correct": correct, "firstTryCorrect": attempt.firstCorrect,
            "hintUsed": task.hintUsed, "creditedForMastery": credit, "clockPending": clockPending,
            "mastery": mastery(task.knowledgeId, attempts: state.attempts + [attempt]), "revision": state.revision + 1,
            "explanation": task.explanation, "explanationAudioId": "hint-\(task.exerciseId)",
        ]
        let encoded = try JSONSerialization.data(withJSONObject: result)
        try update {
            $0.current?.results[id] = encoded
            $0.receipts[requestId] = encoded
            $0.attempts.append(attempt)
            $0.lastObserved = max(at, $0.lastObserved ?? at)
            recordExposure(task, at: at, state: &$0)
        }
        return result
    }

    private func finish(_ id: String) throws -> JSON {
        if let previous = state.finished[id] {
            return [
                "finished": true, "completedRound": previous.results.count == previous.tasks.count,
                "breakRequired": state.roundsSinceBreak >= 2,
            ]
        }
        guard let round = state.current, round.id == id else { throw ClassroomError("SESSION_NOT_FOUND") }
        let completed = round.results.count == round.tasks.count
        try update {
            $0.current = nil
            $0.finished[id] = round
            if completed {
                $0.completed += 1
                $0.roundsSinceBreak = min(2, $0.roundsSinceBreak + 1)
            }
        }
        return ["finished": true, "completedRound": completed, "breakRequired": state.roundsSinceBreak >= 2]
    }

    private func clockSkew(_ at: Date) -> Bool {
        (state.lastObserved?.timeIntervalSince(at) ?? 0) > 300
    }

    private func mastery(_ id: String, attempts: [Attempt]) -> JSON {
        let modes = syllabus.knowledgeItems.first(where: { $0.id == id })?.requiredModes ?? []
        let required = Set(modes).intersection(Self.objectiveModes)
        let window = attempts.filter { $0.knowledgeId == id && $0.credit && Self.objectiveModes.contains($0.mode) }
            .sorted { ($0.at, $0.id) < ($1.at, $1.id) }.suffix(8)
        let correct = window.filter { $0.firstCorrect }
        let covered = Set(correct.map { $0.mode })
        let mastered = window.count >= 5 && correct.count * 5 >= window.count * 4
            && window.suffix(2).allSatisfy { $0.firstCorrect } && !required.isEmpty && required.isSubset(of: covered)
        return [
            "knowledgeId": id, "status": window.isEmpty ? "not-started" : mastered ? "mastered" : "practicing",
            "sampleSize": window.count, "correctCount": correct.count,
            "accuracy": window.isEmpty ? NSNull() as Any : Double(correct.count) / Double(window.count),
            "coveredModes": covered.sorted(), "requiredModes": required.sorted(),
            "reviewDue": false, "reviewDueDate": NSNull(),
        ]
    }

    private func progress() -> JSON {
        [
            "revision": state.revision, "selectedLessonId": state.lessonId,
            "completedSessions": state.completed, "attemptCount": state.attempts.count,
            "clockSkewDetected": clockSkew(now()), "pendingClockAttempts": state.attempts.filter { $0.clockPending }.count,
            "settings": ["soundEnabled": true, "reducedMotion": false],
            "mastery": syllabus.knowledgeItems.map { mastery($0.id, attempts: state.attempts) },
        ]
    }
}
