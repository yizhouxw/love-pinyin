import CryptoKit
import Foundation

final class Classroom {
    typealias JSON = [String: Any]

    private struct Syllabus: Decodable {
        struct Lesson: Decodable {
            let id: String
            let order: Int
            let exerciseIds: [String]
            let knowledgeIds: [String]
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

    private struct GameRound: Codable {
        let id: String
        var settings: LocalGameSettings
        let route: Data
    }

    private struct Round: Codable {
        let id: String
        let lessonId: String
        let contentVersion: String
        let startedAt: Date
        var tasks: [Task]
        var results: [String: Data] = [:]
        var game: GameRound?
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
        var gameId: String?
        var hintUsed: Bool?
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
        var gameClock: LocalGameClock?
        var gameSessionMinutes: Int?
        var gameDailyMinutes: Int?
    }

    private let syllabus: Syllabus
    private let questions: [String: Task]
    private let gameEligible: Set<String>
    private let rules: GameRules
    private let routes: GameRoutes
    private let store: ClassroomStore
    private let now: () -> Date
    private var state: State
    private let day = DateFormatter()
    private static let objectiveModes = Set(["listen-choice", "symbol-choice", "tone-choice", "blend-choice"])

    init(content: Data, database: URL, now: @escaping () -> Date = Date.init) throws {
        syllabus = try JSONDecoder().decode(Syllabus.self, from: content)
        guard let first = syllabus.lessons.first,
              let document = try JSONSerialization.jsonObject(with: content) as? JSON,
              let rows = document["eligible"] as? [JSON],
              let game = document["game"] as? JSON,
              let gameRules = game["rules"] as? JSON, let gameRoutes = game["routes"] as? JSON
        else { throw ClassroomError("IOS_RESOURCE_UNAVAILABLE") }
        rules = try JSONDecoder().decode(GameRules.self, from: JSONSerialization.data(withJSONObject: gameRules))
        routes = try GameRoutes(gameRoutes)
        var tasks: [String: Task] = [:]
        var gameIds: Set<String> = []
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
            if question["audioRef"] is String
                && options.allSatisfy({ $0["pictureId"] == nil && $0["writing"] == nil }) {
                gameIds.insert(id)
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
        gameEligible = gameIds
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
        let hasLegacyHistory = !state.attempts.isEmpty || !state.finished.isEmpty || !state.receipts.isEmpty
        if hasLegacyHistory {
            try Self.persist(state, to: store, replacing: true)
        } else {
            var loaded = state
            try store.history { row in
                switch row.kind {
                case "attempt": loaded.attempts.append(try JSONDecoder().decode(Attempt.self, from: row.payload))
                case "receipt": loaded.receipts[row.key] = row.payload
                case "finished": loaded.finished[row.key] = try JSONDecoder().decode(Round.self, from: row.payload)
                default: throw ClassroomError("IOS_STORAGE_INVALID")
                }
            }
            state = loaded
        }
        self.now = now
        day.locale = Locale(identifier: "en_US_POSIX")
        day.calendar = Calendar(identifier: .gregorian)
        day.timeZone = TimeZone(identifier: "Asia/Shanghai")
        day.dateFormat = "yyyy-MM-dd"
    }

    static let backupLimit = 64 * 1024 * 1024

    private struct Backup: Codable {
        let format: String
        let version: Int
        let contentVersion: String
        let createdAt: Date
        let state: State
    }

    func exportBackup() throws -> Data {
        let data = try JSONEncoder().encode(Backup(
            format: "love-pinyin-ios", version: 1, contentVersion: syllabus.version,
            createdAt: now(), state: state
        ))
        guard data.count <= Self.backupLimit else { throw ClassroomError("IOS_BACKUP_TOO_LARGE") }
        return data
    }

    private func readBackup(_ data: Data) throws -> Backup {
        guard data.count <= Self.backupLimit else { throw ClassroomError("IOS_BACKUP_TOO_LARGE") }
        guard let backup = try? JSONDecoder().decode(Backup.self, from: data),
              backup.format == "love-pinyin-ios" else { throw ClassroomError("IOS_BACKUP_INVALID") }
        guard backup.version == 1, backup.contentVersion == syllabus.version else {
            throw ClassroomError("IOS_BACKUP_VERSION_UNSUPPORTED")
        }
        let saved = backup.state
        let lessons = Set(syllabus.lessons.map(\.id))
        let knowledge = Set(syllabus.knowledgeItems.map(\.id))
        guard lessons.contains(saved.lessonId), saved.revision >= 0,
              saved.completed >= 0, saved.roundsSinceBreak >= 0,
              saved.attempts.allSatisfy({ knowledge.contains($0.knowledgeId) && Self.objectiveModes.contains($0.mode) }),
              saved.exposure.values.allSatisfy({ $0.count >= 0 }),
              Set(saved.attempts.map(\.id)).count == saved.attempts.count
        else { throw ClassroomError("IOS_BACKUP_INVALID") }
        for round in Array(saved.finished.values) + [saved.current].compactMap({ $0 }) {
            guard lessons.contains(round.lessonId), !round.tasks.isEmpty,
                  Set(round.tasks.map(\.instanceId)).count == round.tasks.count,
                  Set(round.results.keys).isSubset(of: Set(round.tasks.map(\.instanceId)))
            else { throw ClassroomError("IOS_BACKUP_INVALID") }
            for task in round.tasks {
                guard let source = questions[task.exerciseId], source.correctOption == task.correctOption,
                      source.mode == task.mode, source.knowledgeId == task.knowledgeId,
                      Set(source.options) == Set(task.options),
                      let exercise = try? decode(task.publicExercise),
                      exercise["id"] as? String == task.exerciseId,
                      (exercise["options"] as? [JSON])?.compactMap({ $0["id"] as? String }) == task.options
                else { throw ClassroomError("IOS_BACKUP_INVALID") }
            }
            for result in round.results.values { _ = try decode(result) }
            if let game = round.game { _ = try decode(game.route) }
        }
        for result in saved.receipts.values { _ = try decode(result) }
        return backup
    }

    func previewBackup(_ data: Data) throws -> (text: String, revision: Int) {
        let backup = try readBackup(data)
        let date = backup.createdAt.formatted(date: .abbreviated, time: .shortened)
        return ("来源：爱拼音 iOS · \(date)\n课程版本：\(backup.contentVersion)\n\(backup.state.attempts.count) 条作答，\(backup.state.completed) 轮练习。此操作将替换本机学习记录。", state.revision)
    }

    func restoreBackup(_ data: Data, expectedRevision: Int) throws {
        guard expectedRevision == state.revision else { throw ClassroomError("REVISION_CONFLICT") }
        var restored = try readBackup(data).state
        restored.revision = state.revision
        restored.gameClock?.leaseUntil = 0
        try update(replacingHistory: true) { $0 = restored }
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
        case ("GET", "/games"):
            return try gameOverview()
        case ("POST", "/games/heartbeat"):
            return try changeClock(.heartbeat)
        case ("POST", "/games/pause"):
            return try changeClock(.pause)
        case ("PUT", "/household/game-limits"):
            return try changeGameLimits(body)
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
        if method == "PATCH", segments.count == 3, segments[0] == "sessions", segments[2] == "game-settings" {
            return try changeGameSettings(String(segments[1]), body: body)
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

    private static func persist(
        _ state: State, to store: ClassroomStore, appending: [ClassroomStore.History] = [], replacing: Bool
    ) throws {
        let encoder = JSONEncoder()
        var rows = appending
        if replacing {
            rows = try state.attempts.map { ("attempt", $0.id, try encoder.encode($0)) }
            rows += state.receipts.map { ("receipt", $0.key, $0.value) }
            rows += try state.finished.map { ("finished", $0.key, try encoder.encode($0.value)) }
        }
        var snapshot = state
        snapshot.attempts = []
        snapshot.receipts = [:]
        snapshot.finished = [:]
        try store.save(encoder.encode(snapshot), history: rows, replacing: replacing)
    }

    private func update(
        appending: [ClassroomStore.History] = [], replacingHistory: Bool = false,
        _ change: (inout State) throws -> Void
    ) throws {
        var next = state
        try change(&next)
        next.revision += 1
        try Self.persist(next, to: store, appending: appending, replacing: replacingHistory)
        state = next
    }

    private func decode(_ data: Data) throws -> JSON {
        guard let value = try JSONSerialization.jsonObject(with: data) as? JSON else {
            throw ClassroomError("IOS_STORAGE_INVALID")
        }
        return value
    }

    private func project(_ round: Round) throws -> JSON {
        var value: JSON = [
            "id": round.id, "lessonId": round.lessonId, "contentVersion": round.contentVersion,
            "startedAt": ISO8601DateFormatter().string(from: round.startedAt),
            "tasks": try round.tasks.map { try $0.projection },
            "results": try round.results.mapValues(decode),
        ]
        if let game = round.game {
            value["gameId"] = game.id
            value["gameSettings"] = try decode(JSONEncoder().encode(game.settings))
            value["gameRun"] = try decode(game.route)
        }
        return value
    }

    private func start(_ body: JSON) throws -> JSON {
        let isGame = body["gameId"] != nil
        guard let id = body["lessonId"] as? String, isGame || body.count == 1 else {
            throw ClassroomError("LESSON_NOT_FOUND")
        }
        if let round = state.current {
            guard round.lessonId == id, round.game?.id == body["gameId"] as? String else {
                throw ClassroomError("SESSION_ACTIVE")
            }
            return try project(round)
        }
        guard state.roundsSinceBreak < 2 else { throw ClassroomError("REST_REQUIRED") }
        guard let current = syllabus.lessons.first(where: { $0.id == state.lessonId }) else {
            throw ClassroomError("CURRENT_LESSON_REQUIRES_SELECTION")
        }
        guard let requested = syllabus.lessons.first(where: { $0.id == id }) else {
            throw ClassroomError("LESSON_NOT_FOUND")
        }
        guard requested.order <= current.order else { throw ClassroomError("LESSON_NOT_UNLOCKED") }
        let started = now()
        var game: GameRound?
        var clock: LocalGameClock?
        let tasks: [Task]
        if isGame {
            let selected = try prepareGame(body, order: current.order)
            tasks = selected.tasks
            game = selected.game
            let (next, status) = transition(.heartbeat, at: started)
            if let reason = status.reason { throw ClassroomError(reason) }
            clock = next
        } else {
            tasks = try rank(requested.exerciseIds.compactMap { questions[$0] }).prefix(6).map { try $0.instantiate() }
            guard !tasks.isEmpty else { throw ClassroomError("LESSON_NOT_READY") }
        }
        let round = Round(
            id: UUID().uuidString, lessonId: id, contentVersion: syllabus.version,
            startedAt: started, tasks: tasks, game: game
        )
        let result = try project(round)
        try update {
            $0.current = round
            if let clock { $0.gameClock = clock }
        }
        return result
    }

    private var sessionMinutes: Int { state.gameSessionMinutes ?? rules.policy.sessionMinutes }
    private var dailyMinutes: Int { state.gameDailyMinutes ?? rules.policy.dailyMinutes }

    private func transition(_ action: LocalGameClock.Action, at: Date) -> (LocalGameClock, LocalGameClock.Status) {
        var clock = state.gameClock ?? LocalGameClock()
        let status = clock.transition(action, now: at, session: sessionMinutes, daily: dailyMinutes,
                                      policy: rules.policy, day: day)
        return (clock, status)
    }

    func pauseGameOnInterruption() throws {
        if (state.gameClock?.leaseUntil ?? 0) > (state.gameClock?.accountedAt ?? 0) {
            _ = try changeClock(.pause)
        }
    }

    private func changeClock(_ action: LocalGameClock.Action) throws -> JSON {
        let (clock, status) = transition(action, at: now())
        if clock != state.gameClock { try update { $0.gameClock = clock } }
        return status.projection
    }

    private func requireGameLease(_ round: Round, at: Date) throws {
        guard round.game != nil else { return }
        let status = transition(.status, at: at).1
        if let reason = status.reason { throw ClassroomError(reason) }
        if status.leaseSeconds <= 0 { throw ClassroomError("GAME_PAUSED") }
    }

    private func changeGameLimits(_ body: JSON) throws -> JSON {
        guard body.count == 2, let session = body["gameSessionMinutes"] as? Int,
              let daily = body["gameDailyMinutes"] as? Int,
              (1...rules.policy.sessionMaxMinutes).contains(session), (1...rules.policy.dailyMaxMinutes).contains(daily)
        else { throw ClassroomError("GAME_SETTINGS_INVALID") }
        guard state.current == nil else { throw ClassroomError("SESSION_ACTIVE") }
        let (clock, _) = transition(.pause, at: now())
        try update {
            $0.gameClock = clock
            $0.gameSessionMinutes = session
            $0.gameDailyMinutes = daily
        }
        return progress()
    }

    private func rank(_ tasks: [Task]) -> [Task] {
        tasks.enumerated().sorted { left, right in
            let a = state.exposure[left.element.exerciseId] ?? Exposure()
            let b = state.exposure[right.element.exerciseId] ?? Exposure()
            if a.count != b.count { return a.count < b.count }
            if a.latest != b.latest { return (a.latest ?? .distantPast) < (b.latest ?? .distantPast) }
            return left.offset < right.offset
        }.map(\.element)
    }

    private func gameMastery(order: Int) -> [String: JSON] {
        let keys = Set(syllabus.lessons.filter { $0.order <= order }.flatMap(\.knowledgeIds))
        return Dictionary(uniqueKeysWithValues: keys.map { ($0, mastery($0, attempts: state.attempts)) })
    }

    private func recommendation(_ mastery: [String: JSON]) -> GameRecommendation {
        let samples = mastery.values.reduce(0) { $0 + ($1["sampleSize"] as? Int ?? 0) }
        let correct = mastery.values.reduce(0) { $0 + ($1["correctCount"] as? Int ?? 0) }
        let mastered = mastery.values.filter { $0["status"] as? String == "mastered" }.count
        let accuracy = samples == 0 ? 0 : Double(correct) / Double(samples)
        let rule = rules.adaptation
        let steady = samples >= rule.steadySamples && accuracy >= rule.steadyAccuracy
        let challenge = samples >= rule.challengeSamples && accuracy >= rule.challengeAccuracy && mastered >= rule.challengeMastered
        return GameRecommendation(level: challenge ? "challenge" : steady ? "steady" : "gentle",
                                  speed: steady ? "normal" : "slow", sampleSize: samples,
                                  correctCount: correct, masteredCount: mastered)
    }

    private func prepareGame(_ body: JSON, order: Int) throws -> (tasks: [Task], game: GameRound) {
        guard let id = body["gameId"] as? String, let game = rules.games.first(where: { $0.id == id }) else {
            throw ClassroomError("GAME_NOT_FOUND")
        }
        let count = body["gameTaskCount"] as? Int ?? rules.play.defaultTasks
        guard (rules.play.minTasks...rules.play.maxTasks).contains(count) else {
            throw ClassroomError("GAME_SETTINGS_INVALID")
        }
        let mastery = gameMastery(order: order)
        let settings = try LocalGameSettings(
            difficulty: body["gameDifficulty"] as? String ?? "auto",
            speed: body["gameSpeed"] as? String ?? "auto", recommendation: recommendation(mastery)
        )
        let lessons = syllabus.lessons.filter { $0.order <= order }
        var seen: Set<String> = []
        let eligible = lessons.flatMap(\.exerciseIds).compactMap { key -> Task? in
            guard gameEligible.contains(key), let task = questions[key],
                  game.modes.contains(task.mode), seen.insert(key).inserted
            else { return nil }
            return task
        }
        guard eligible.count >= count else { throw ClassroomError("GAME_LEVEL_CONTENT_INSUFFICIENT") }
        let candidates = eligible.filter { $0.mode == game.mode } + eligible.filter { $0.mode != game.mode }
        let currentKeys = Set(lessons.first(where: { $0.id == state.lessonId })?.exerciseIds ?? [])
        let weak = rank(candidates.filter { mastery[$0.knowledgeId]?["status"] as? String == "practicing" })
        var selected = Array(weak.prefix(min(count, rules.adaptation.weakSlots)))
        var picked = Set(selected.map(\.exerciseId))
        let current = rank(candidates.filter { currentKeys.contains($0.exerciseId) && !picked.contains($0.exerciseId) })
        selected += current.prefix(count - selected.count)
        picked = Set(selected.map(\.exerciseId))
        selected += rank(candidates.filter { !picked.contains($0.exerciseId) }).prefix(count - selected.count)
        picked = Set(selected.map(\.exerciseId))
        var pending = selected + current.filter { !picked.contains($0.exerciseId) }
        var spread: [Task] = []
        while !pending.isEmpty && spread.count < count {
            var targets: Set<String> = []
            pending = pending.filter {
                guard spread.count < count, targets.insert($0.knowledgeId).inserted else { return true }
                spread.append($0)
                return false
            }
        }
        let tasks = try spread.map { try $0.instantiate() }
        let route = try routes.freeze(gameId: id, levelId: body["gameLevelId"] as? String,
                                      difficulty: settings.level, instances: tasks.map(\.instanceId))
        return (tasks, GameRound(id: id, settings: settings, route: route))
    }

    private func changeGameSettings(_ id: String, body: JSON) throws -> JSON {
        guard let round = state.current, round.id == id, let game = round.game else {
            throw ClassroomError("SESSION_NOT_FOUND")
        }
        guard let difficulty = body["difficulty"] as? String, let speed = body["speed"] as? String else {
            throw ClassroomError("GAME_SETTINGS_INVALID")
        }
        let (clock, status) = transition(.heartbeat, at: now())
        if let reason = status.reason { throw ClassroomError(reason) }
        let settings = try LocalGameSettings(difficulty: difficulty, speed: speed, recommendation: game.settings.recommendation)
        let projection = try decode(JSONEncoder().encode(settings))
        try update {
            $0.gameClock = clock
            $0.current?.game?.settings = settings
        }
        return projection
    }

    private func gameOverview() throws -> JSON {
        let at = now()
        let earliest = at.addingTimeInterval(-7 * 86400)
        let recent = state.attempts.filter { $0.gameId != nil && $0.at >= earliest }
        let iso = ISO8601DateFormatter()
        let rounds = Array(state.finished.values) + [state.current].compactMap { $0 }
        var skips = 0
        for round in rounds where round.game != nil {
            for saved in round.results.values {
                if let time = try decode(saved)["skippedAt"] as? String,
                   let date = iso.date(from: time), date >= earliest { skips += 1 }
            }
        }
        let report: JSON = [
            "answered": recent.count,
            "independentCorrect": recent.filter { $0.firstCorrect && !$0.clockPending }.count,
            "hints": recent.filter { $0.hintUsed == true }.count,
            "skipped": skips,
            "pendingClock": recent.filter(\.clockPending).count,
            "practiceKnowledgeIds": Set(recent.filter { !$0.firstCorrect && !$0.clockPending }.map(\.knowledgeId)).sorted(),
        ]
        let order = syllabus.lessons.first(where: { $0.id == state.lessonId })?.order ?? 0
        return [
            "clock": transition(.status, at: at).1.projection, "report": report,
            "recommendation": try decode(JSONEncoder().encode(recommendation(gameMastery(order: order)))),
        ]
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
        try requireGameLease(round, at: now())
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
        try requireGameLease(round, at: time)
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
        try requireGameLease(round, at: at)
        let today = day.string(from: at)
        let clockPending = clockSkew(at)
        let credit = !clockPending && !state.attempts.contains {
            $0.exerciseId == task.exerciseId && $0.knowledgeId == task.knowledgeId && $0.day == today && $0.credit
        }
        let correct = task.correctOption == option
        let attempt = Attempt(
            id: UUID().uuidString, exerciseId: task.exerciseId, knowledgeId: task.knowledgeId,
            mode: task.mode, day: today, at: at, firstCorrect: correct && !task.hintUsed, credit: credit,
            clockPending: clockPending, gameId: round.game?.id, hintUsed: task.hintUsed
        )
        let result: JSON = [
            "attemptId": attempt.id, "requestId": requestId, "instanceId": id, "answerOptionId": option,
            "correctOptionId": task.correctOption, "correct": correct, "firstTryCorrect": attempt.firstCorrect,
            "hintUsed": task.hintUsed, "creditedForMastery": credit, "clockPending": clockPending,
            "mastery": mastery(task.knowledgeId, attempts: state.attempts + [attempt]), "revision": state.revision + 1,
            "explanation": task.explanation, "explanationAudioId": "hint-\(task.exerciseId)",
        ]
        let encoded = try JSONSerialization.data(withJSONObject: result)
        try update(appending: [
            ("attempt", attempt.id, try JSONEncoder().encode(attempt)),
            ("receipt", requestId, encoded),
        ]) {
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
        let clock = round.game == nil ? nil : transition(.pause, at: now()).0
        try update(appending: [("finished", id, try JSONEncoder().encode(round))]) {
            if let clock { $0.gameClock = clock }
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
        let byKnowledge = Dictionary(grouping: state.attempts, by: \.knowledgeId)
        return [
            "revision": state.revision, "selectedLessonId": state.lessonId,
            "completedSessions": state.completed, "attemptCount": state.attempts.count,
            "clockSkewDetected": clockSkew(now()), "pendingClockAttempts": state.attempts.filter { $0.clockPending }.count,
            "settings": [
                "soundEnabled": true, "reducedMotion": false,
                "gameSessionMinutes": sessionMinutes, "gameDailyMinutes": dailyMinutes,
            ] as JSON,
            "mastery": syllabus.knowledgeItems.map { mastery($0.id, attempts: byKnowledge[$0.id] ?? []) },
        ]
    }
}
