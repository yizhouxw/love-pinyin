import AVFoundation
import CryptoKit
import MLX
import MLXAudioSTT
import Foundation
import OSLog
import UIKit

private let recognitionLog = Logger(subsystem: "app.lovepinyin.ios", category: "Recognition")

private struct IOSModelManifest: Decodable {
    struct File: Decodable {
        let bytes: Int
        let sha256: String
    }
    let repository: String
    let revision: String
    let modelScopeRevision: String
    let files: [String: File]
}

private enum IOSRecognitionError: Error {
    case unavailable, storage, download, integrity, microphone, cancelled
}

actor IOSRecognition {
    private typealias Asset = (path: String, bytes: Int, sha256: String)
    private let manifest: IOSModelManifest
    private let directory: URL
    private let entries: [Asset]
    private var downloadTask: Task<Void, Never>?
    private var failed = false
    private var received = 0
    private var busy = false
    private var manager: Qwen3ASRModel?
    private var total: Int { entries.reduce(0) { $0 + $1.bytes } }

    init(manifestData: Data, directory: URL) throws {
        manifest = try JSONDecoder().decode(IOSModelManifest.self, from: manifestData)
        self.directory = directory
        entries = manifest.files.sorted { $0.key < $1.key }.map { ($0.key, $0.value.bytes, $0.value.sha256) }
    }

    func status() -> [String: any Sendable] {
        let state = downloadTask != nil ? "downloading" : installed ? "installed" : failed ? "failed" : "idle"
        return ["state": state, "bytes": total, "received": received]
    }

    func startDownload() -> [String: any Sendable] {
        if downloadTask == nil && !installed {
            failed = false
            received = 0
            downloadTask = Task { await download() }
        }
        return status()
    }

    func waitForDownload() async {
        await downloadTask?.value
    }

    private var installed: Bool {
        guard (try? String(contentsOf: directory.appendingPathComponent("verified"), encoding: .utf8)) ==
            manifest.revision else { return false }
        return entries.allSatisfy { entry in
            let url = directory.appendingPathComponent(entry.path)
            return (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) == entry.bytes
        }
    }

    private func verify(_ file: URL, entry: Asset) throws {
        guard try file.resourceValues(forKeys: [.fileSizeKey]).fileSize == entry.bytes else {
            throw IOSRecognitionError.integrity
        }
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var hash = SHA256()
        while let data = try handle.read(upToCount: 1_048_576), !data.isEmpty {
            hash.update(data: data)
        }
        guard hash.finalize().map({ String(format: "%02x", $0) }).joined() == entry.sha256 else {
            throw IOSRecognitionError.integrity
        }
    }

    private func download() async {
        let files = FileManager.default
        let parent = directory.deletingLastPathComponent()
        let staging = parent.appendingPathComponent(".qwen-\(manifest.revision)", isDirectory: true)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 45
        configuration.timeoutIntervalForResource = 900
        configuration.httpMaximumConnectionsPerHost = 6
        configuration.urlCache = nil
        let session = URLSession(configuration: configuration)
        defer {
            session.finishTasksAndInvalidate()
            downloadTask = nil
        }
        do {
            try files.createDirectory(at: staging, withIntermediateDirectories: true)
            var excluded = staging
            var properties = URLResourceValues()
            properties.isExcludedFromBackup = true
            try excluded.setResourceValues(properties)
            var remaining: [Asset] = []
            for entry in entries {
                let staged = staging.appendingPathComponent(entry.path)
                do {
                    try verify(staged, entry: entry)
                    received += entry.bytes
                } catch {
                    try? files.removeItem(at: staged)
                    remaining.append(entry)
                }
            }
            if let capacity = try? parent.resourceValues(
                forKeys: [.volumeAvailableCapacityForImportantUsageKey]
            ).volumeAvailableCapacityForImportantUsage, capacity < total - received + 100_000_000 {
                throw IOSRecognitionError.storage
            }
            var hosts = ["huggingface.co", "modelscope.cn", "hf-mirror.com"]
            if Locale.current.region?.identifier == "CN" { hosts.swapAt(0, 1) }
            for entry in remaining {
                let destination = staging.appendingPathComponent(entry.path)
                try files.createDirectory(at: destination.deletingLastPathComponent(),
                                          withIntermediateDirectories: true)
                let preferred = try await transfer(entry, to: destination, using: session, hosts: hosts)
                hosts = [preferred] + hosts.filter { $0 != preferred }
            }
            try manifest.revision.write(to: staging.appendingPathComponent("verified"),
                                        atomically: true, encoding: .utf8)
            if files.fileExists(atPath: directory.path) {
                try files.removeItem(at: directory)
            }
            try files.moveItem(at: staging, to: directory)
        } catch {
            failed = true
        }
    }

    private func transfer(
        _ entry: Asset, to destination: URL, using session: URLSession, hosts: [String]
    ) async throws -> String {
        let chunkSize = 8 * 1024 * 1024
        let partial = destination.appendingPathExtension("partial")
        let files = FileManager.default
        var offset = (try? partial.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        if offset > entry.bytes || (offset != entry.bytes && offset % chunkSize != 0) {
            try files.removeItem(at: partial)
            offset = 0
        }
        if offset == 0 { files.createFile(atPath: partial.path, contents: nil) }
        var preferred = hosts
        received += offset
        while offset < entry.bytes {
            let ranges = stride(from: offset, to: min(offset + 6 * chunkSize, entry.bytes), by: chunkSize)
                .map { $0..<min($0 + chunkSize, entry.bytes) }
            let chunks = try await withThrowingTaskGroup(of: (Int, Data, String).self) { group in
                let currentHosts = preferred
                for range in ranges {
                    group.addTask {
                        let (data, host) = try await self.fetch(
                            entry, range: entry.bytes > chunkSize ? range : nil,
                            using: session, hosts: currentHosts
                        )
                        return (range.lowerBound, data, host)
                    }
                }
                var chunks: [(Int, Data, String)] = []
                for try await chunk in group { chunks.append(chunk) }
                return chunks.sorted { $0.0 < $1.0 }
            }
            let handle = try FileHandle(forWritingTo: partial)
            defer { try? handle.close() }
            try handle.seek(toOffset: UInt64(offset))
            for (_, data, host) in chunks {
                try handle.write(contentsOf: data)
                received += data.count
                offset += data.count
                preferred = [host] + preferred.filter { $0 != host }
            }
        }
        do {
            try verify(partial, entry: entry)
        } catch {
            try? files.removeItem(at: partial)
            throw error
        }
        try files.moveItem(at: partial, to: destination)
        return preferred[0]
    }

    private func fetch(
        _ entry: Asset, range: Range<Int>?, using session: URLSession, hosts: [String]
    ) async throws -> (Data, String) {
        for (attempt, host) in (hosts + hosts).enumerated() {
            var components = URLComponents()
            components.scheme = "https"
            components.host = host
            let modelScope = host == "modelscope.cn"
            components.path = modelScope
                ? "/models/\(manifest.repository)/resolve/\(manifest.modelScopeRevision)/\(entry.path)"
                : "/\(manifest.repository)/resolve/\(manifest.revision)/\(entry.path)"
            var query = modelScope ? [] : [URLQueryItem(name: "download", value: "true")]
            if attempt >= hosts.count { query.append(URLQueryItem(name: "request", value: UUID().uuidString)) }
            components.queryItems = query
            guard let url = components.url else { throw IOSRecognitionError.download }
            var request = URLRequest(url: url)
            if let range {
                request.setValue("bytes=\(range.lowerBound)-\(range.upperBound - 1)", forHTTPHeaderField: "Range")
            }
            do {
                let (temp, response) = try await session.download(for: request)
                defer { try? FileManager.default.removeItem(at: temp) }
                guard let http = response as? HTTPURLResponse, http.url?.scheme == "https" else {
                    throw IOSRecognitionError.download
                }
                if let range {
                    let expected = "bytes \(range.lowerBound)-\(range.upperBound - 1)/\(entry.bytes)"
                    guard http.statusCode == 206, http.value(forHTTPHeaderField: "Content-Range") == expected else {
                        recognitionLog.notice("Model range \(entry.path, privacy: .public) from \(host, privacy: .public): HTTP \(http.statusCode)")
                        continue
                    }
                } else if http.statusCode != 200 {
                    recognitionLog.notice("Model file \(entry.path, privacy: .public) from \(host, privacy: .public): HTTP \(http.statusCode)")
                    continue
                }
                guard try temp.resourceValues(forKeys: [.fileSizeKey]).fileSize == (range?.count ?? entry.bytes)
                else { throw IOSRecognitionError.integrity }
                return (try Data(contentsOf: temp), host)
            } catch {
                let failure = error as NSError
                recognitionLog.notice("Model download from \(host, privacy: .public): \(failure.domain, privacy: .public) \(failure.code)")
            }
        }
        throw IOSRecognitionError.download
    }

    func prepare() async throws {
        if manager != nil { return }
        guard installed && !busy else { throw IOSRecognitionError.unavailable }
        busy = true
        defer { busy = false }
        do {
            for entry in entries {
                try verify(directory.appendingPathComponent(entry.path), entry: entry)
            }
        } catch {
            try? FileManager.default.removeItem(at: directory.appendingPathComponent("verified"))
            failed = true
            throw error
        }
        Memory.cacheLimit = 64 * 1024 * 1024
        let loaded = try await Qwen3ASRModel.fromModelDirectory(directory)
        // Compile the first Metal kernels before starting the shop's five-second window.
        _ = loaded.generate(audio: MLXArray([Float](repeating: 0, count: 12_800)),
                            maxTokens: 2, language: "Chinese")
        manager = loaded
    }

    func recognize(_ data: Data, forShop: Bool) async throws -> [String: String] {
        guard let samples = IOSPCM.decode(data, maxFrames: (forShop ? 5 : 30) * 16_000) else {
            return ["status": "uncertain"]
        }
        let rms = sqrt(samples.reduce(Float(0)) { $0 + $1 * $1 } / Float(samples.count))
        guard rms >= 0.002, samples.lazy.filter({ abs($0) > 0.005 }).prefix(1600).count == 1600 else {
            return ["status": "uncertain"]
        }
        try await prepare()
        guard !busy, let manager else { throw IOSRecognitionError.unavailable }
        busy = true
        defer { busy = false }
        let output = manager.generate(
            audio: MLXArray(samples), maxTokens: forShop ? 24 : 192, language: "Chinese"
        )
        let transcript = output.text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty,
              let pinyin = transcript.applyingTransform(.mandarinToLatin, reverse: false) else {
            return ["status": "uncertain"]
        }
        return ["status": "recognized", "transcript": transcript, "pinyin": pinyin]
    }
}

enum IOSPCM {
    static func encode(_ samples: [Float], rate: Double) -> Data {
        let frames = Int(Double(samples.count) * 16_000 / rate)
        var data = Data(capacity: 44 + 2 * frames)
        func append<T: FixedWidthInteger>(_ value: T) {
            var little = value.littleEndian
            withUnsafeBytes(of: &little) { data.append(contentsOf: $0) }
        }
        data.append(contentsOf: "RIFF".utf8)
        append(UInt32(36 + frames * 2))
        data.append(contentsOf: "WAVEfmt ".utf8)
        append(UInt32(16))
        append(UInt16(1))
        append(UInt16(1))
        append(UInt32(16_000))
        append(UInt32(32_000))
        append(UInt16(2))
        append(UInt16(16))
        data.append(contentsOf: "data".utf8)
        append(UInt32(frames * 2))
        for index in 0..<frames {
            let start = Int(Double(index) * rate / 16_000)
            let end = min(samples.count, max(start + 1, Int(Double(index + 1) * rate / 16_000)))
            let average = samples[start..<end].reduce(0, +) / Float(end - start)
            let value = average.isFinite ? min(1, max(-1, average)) : 0
            append(Int16(value * (value < 0 ? 32_768 : 32_767)))
        }
        return data
    }

    static func decode(_ data: Data, maxFrames: Int) -> [Float]? {
        guard data.count >= 44 + 4_800, data.count <= 44 + maxFrames * 2,
              (data.count - 44).isMultiple(of: 2),
              data.prefix(4) == Data("RIFF".utf8),
              data[8..<16] == Data("WAVEfmt ".utf8),
              data[36..<40] == Data("data".utf8) else { return nil }
        return data.withUnsafeBytes { bytes in
            func read<T: FixedWidthInteger>(_ offset: Int, as type: T.Type) -> T {
                T(littleEndian: bytes.loadUnaligned(fromByteOffset: offset, as: type))
            }
            guard read(4, as: UInt32.self) == data.count - 8,
                  read(16, as: UInt32.self) == 16, read(20, as: UInt16.self) == 1,
                  read(22, as: UInt16.self) == 1, read(24, as: UInt32.self) == 16_000,
                  read(34, as: UInt16.self) == 16, read(40, as: UInt32.self) == data.count - 44
            else { return nil }
            return stride(from: 44, to: data.count, by: 2).map {
                Float(read($0, as: Int16.self)) / 32_768
            }
        }
    }
}

private final class IOSPCMBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private var samples = [Float]()
    let rate: Double
    let limit: Int

    init(rate: Double, maximumMs: Int) {
        self.rate = rate
        limit = Int(rate * Double(maximumMs) / 1000)
        samples.reserveCapacity(limit)
    }

    func append(_ buffer: AVAudioPCMBuffer) {
        guard let channel = buffer.floatChannelData?[0] else { return }
        lock.lock()
        defer { lock.unlock() }
        let count = min(Int(buffer.frameLength), limit - samples.count)
        samples.append(contentsOf: UnsafeBufferPointer(start: channel, count: count))
    }

    func snapshot() -> Data? {
        lock.lock()
        let copy = samples
        lock.unlock()
        return copy.isEmpty ? nil : IOSPCM.encode(copy, rate: rate)
    }

    func level() -> Double {
        lock.lock()
        defer { lock.unlock() }
        let window = samples.suffix(2048)
        guard !window.isEmpty else { return 0 }
        return sqrt(window.reduce(0) { $0 + Double($1) * Double($1) } / Double(window.count))
    }
}

@MainActor
final class IOSRecognitionRecorder {
    private var engine: AVAudioEngine?
    private var buffer: IOSPCMBuffer?
    private var current: String?
    private var watchdog: Task<Void, Never>?
    private(set) var requestingPermission = false

    func start(_ id: String, maximumMs: Int) async throws {
        discard()
        current = id
        let permitted: Bool
        if #available(iOS 17.0, *) {
            requestingPermission = AVAudioApplication.shared.recordPermission == .undetermined
            permitted = await AVAudioApplication.requestRecordPermission()
            requestingPermission = false
        } else {
            permitted = false
        }
        guard current == id else { throw IOSRecognitionError.cancelled }
        guard permitted else { discard(); throw IOSRecognitionError.microphone }
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
            try session.setActive(true)
            let engine = AVAudioEngine()
            let input = engine.inputNode
            let format = input.outputFormat(forBus: 0)
            guard format.sampleRate >= 16_000, format.channelCount > 0 else {
                throw IOSRecognitionError.microphone
            }
            let buffer = IOSPCMBuffer(rate: format.sampleRate, maximumMs: maximumMs)
            input.installTap(onBus: 0, bufferSize: 1024, format: format) { samples, _ in
                buffer.append(samples)
            }
            self.engine = engine
            self.buffer = buffer
            try engine.start()
            watchdog = Task { [weak self] in
                try? await Task.sleep(for: .milliseconds(maximumMs + 150))
                if !Task.isCancelled { self?.stopEngine() }
            }
        } catch {
            discard()
            try? session.setActive(false, options: .notifyOthersOnDeactivation)
            throw error
        }
    }

    func snapshot(_ id: String, stop: Bool) -> String? {
        guard current == id else { return nil }
        if stop { stopEngine() }
        let snapshot = buffer?.snapshot()?.base64EncodedString()
        if stop { discard(id) }
        return snapshot
    }

    func level(_ id: String) -> Double {
        current == id && engine != nil ? buffer?.level() ?? 0 : 0
    }

    func discard(_ id: String? = nil) {
        guard id == nil || current == id else { return }
        stopEngine()
        current = nil
        buffer = nil
    }

    private func stopEngine() {
        watchdog?.cancel()
        watchdog = nil
        if let engine {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
            self.engine = nil
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }
}
