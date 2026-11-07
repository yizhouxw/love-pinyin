import Foundation
import WebKit

@MainActor
final class OfflineAssets: NSObject, WKURLSchemeHandler {
    static let scheme = "lovepinyin"
    static let entry = URL(string: "lovepinyin://bundle/index.html")!

    private struct Clip: Decodable {
        let file: String
    }

    private let web: URL
    private let audio: URL
    private let data: URL
    private let catalog: [String: Clip]
    private let webFiles: Set<String>

    init(root: URL) throws {
        web = root.appendingPathComponent("Web", isDirectory: true)
        audio = root.appendingPathComponent("Audio", isDirectory: true)
        data = root.appendingPathComponent("Data", isDirectory: true)
        let decoder = JSONDecoder()
        catalog = try decoder.decode(
            [String: Clip].self, from: Data(contentsOf: data.appendingPathComponent("audio.json"))
        )
        webFiles = Set(try decoder.decode(
            [String].self, from: Data(contentsOf: data.appendingPathComponent("web-files.json"))
        ))
        guard webFiles.contains("index.html") else { throw CocoaError(.fileNoSuchFile) }
    }

    func responseData(_ name: String) throws -> Any {
        try JSONSerialization.jsonObject(with: dataFile(name))
    }

    func dataFile(_ name: String) throws -> Data {
        try Data(contentsOf: data.appendingPathComponent("\(name).json"))
    }

    func lesson(_ id: String) -> URL? {
        guard id.hasPrefix("lesson-") else { return nil }
        return clip("voice/\(id)")
    }

    func webView(_ webView: WKWebView, start task: any WKURLSchemeTask) {
        guard let url = task.request.url,
              url.scheme == Self.scheme, url.host == "bundle", url.port == nil, url.user == nil,
              task.request.httpMethod == "GET",
              let file = resource(for: url.path),
              let mimeType = Self.mimeTypes[file.pathExtension],
              let bytes = try? Data(contentsOf: file, options: .mappedIfSafe)
        else {
            task.didFailWithError(URLError(.resourceUnavailable))
            return
        }
        var headers = ["Content-Type": mimeType, "Content-Length": String(bytes.count)]
        if url == Self.entry {
            headers["Content-Security-Policy"] = """
                default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; object-src 'none'; frame-src 'none'
                """
        }
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: headers)!
        task.didReceive(response)
        task.didReceive(bytes)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: any WKURLSchemeTask) {
        // All reads and replies finish synchronously on the scheme handler's actor.
    }

    private func clip(_ key: String) -> URL? {
        guard let entry = catalog[key], !entry.file.contains("/") else { return nil }
        return audio.appendingPathComponent(entry.file)
    }

    private func resource(for path: String) -> URL? {
        if path.hasPrefix("/api/v1/") {
            let key = String(path.dropFirst("/api/v1/".count))
            guard !key.hasPrefix("voice/lesson-") else { return nil }
            return clip(key)
        }
        let relative = String(path.dropFirst())
        guard webFiles.contains(relative) else { return nil }
        return web.appendingPathComponent(relative)
    }

    private static let mimeTypes = [
        "html": "text/html; charset=utf-8",
        "js": "text/javascript; charset=utf-8",
        "css": "text/css; charset=utf-8",
        "svg": "image/svg+xml",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "woff2": "font/woff2",
        "wav": "audio/wav",
    ]
}
