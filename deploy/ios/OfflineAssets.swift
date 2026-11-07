import Foundation
import WebKit

@MainActor
final class OfflineAssets: NSObject, WKURLSchemeHandler {
    static let scheme = "lovepinyin"
    static let entry = URL(string: "lovepinyin://bundle/probe.html")!

    private struct Clip: Decodable {
        let file: String
    }

    private struct Curriculum: Decodable {
        let lessons: [Lesson]

        struct Lesson: Decodable {
            let id: String
        }
    }

    private let web: URL
    private let shortSample: URL
    let lesson: URL
    let lessonCount: Int
    let audioCount: Int

    init(root: URL) throws {
        let catalog = try JSONDecoder().decode(
            [String: Clip].self, from: Data(contentsOf: root.appendingPathComponent("Data/audio.json"))
        )
        let curriculum = try JSONDecoder().decode(
            Curriculum.self, from: Data(contentsOf: root.appendingPathComponent("Data/curriculum.json"))
        )
        guard let firstLesson = curriculum.lessons.first,
              let recording = catalog["voice/lesson-\(firstLesson.id)"],
              let standard = catalog.keys.sorted().first(where: { $0.hasPrefix("audio/") }),
              let sample = catalog[standard]
        else { throw CocoaError(.fileNoSuchFile) }
        let audio = root.appendingPathComponent("Audio", isDirectory: true)
        lesson = audio.appendingPathComponent(recording.file)
        shortSample = audio.appendingPathComponent(sample.file)
        web = root.appendingPathComponent("Web", isDirectory: true)
        audioCount = catalog.count
        lessonCount = curriculum.lessons.count
    }

    func webView(_ webView: WKWebView, start task: any WKURLSchemeTask) {
        guard let url = task.request.url,
              url.scheme == Self.scheme, url.host == "bundle", url.query == nil,
              task.request.httpMethod == "GET",
              let file = resource(for: url.path),
              let mimeType = Self.mimeTypes[file.pathExtension],
              let data = try? Data(contentsOf: file, options: .mappedIfSafe)
        else {
            task.didFailWithError(URLError(.resourceUnavailable))
            return
        }
        let response = HTTPURLResponse(
            url: url, statusCode: 200, httpVersion: nil,
            headerFields: ["Content-Type": mimeType, "Content-Length": String(data.count)]
        )!
        task.didReceive(response)
        task.didReceive(data)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: any WKURLSchemeTask) {
        // All reads and replies finish synchronously on the scheme handler's actor.
    }

    private func resource(for path: String) -> URL? {
        switch path {
        case "/probe-audio":
            return shortSample
        case "/probe.html", "/probe.js", "/fonts/andika/Andika-Regular.woff2":
            return web.appendingPathComponent(String(path.dropFirst()))
        default:
            return nil
        }
    }

    private static let mimeTypes = [
        "html": "text/html; charset=utf-8",
        "js": "text/javascript; charset=utf-8",
        "mp3": "audio/mpeg",
        "woff2": "font/woff2",
        "wav": "audio/wav",
    ]
}
