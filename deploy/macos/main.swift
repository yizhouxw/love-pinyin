import AppKit
import WebKit

final class App: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var port: UInt16 = 0

    func applicationDidFinishLaunching(_ notification: Notification) {
        let socketFD = socket(AF_INET, SOCK_STREAM, 0)
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = UInt16(18765).bigEndian
        address.sin_addr = in_addr(s_addr: in_addr_t(0x0100007f))
        let bound = withUnsafePointer(to: &address) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(socketFD, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        var size = socklen_t(MemoryLayout<sockaddr_in>.size)
        _ = withUnsafeMutablePointer(to: &address) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(socketFD, $0, &size) }
        }
        close(socketFD)
        guard bound == 0 else { fail("本机端口 18765 已被占用，请关闭占用该端口的程序后重试。") ; return }
        port = UInt16(bigEndian: address.sin_port)
        let root = Bundle.main.resourceURL!.appendingPathComponent("app")
        let data = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("LovePinyin")
        do { try FileManager.default.createDirectory(at: data, withIntermediateDirectories: true) }
        catch { fail("无法创建应用数据目录：\(error.localizedDescription)"); return }
        let process = Process()
        process.executableURL = Bundle.main.resourceURL!.appendingPathComponent("python/bin/python3")
        process.currentDirectoryURL = root
        process.arguments = ["-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", String(port), "--no-proxy-headers"]
        var env = ProcessInfo.processInfo.environment
        env["LOVE_PINYIN_DATA_DIR"] = data.appendingPathComponent("data").path
        env["LOVE_PINYIN_MODEL_PATH"] = data.appendingPathComponent("models/whisper-small/ggml-small.bin").path
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = env
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do { try process.run(); server = process } catch { fail("无法启动本地服务：\(error.localizedDescription)"); return }
        let config = WKWebViewConfiguration()
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1100, height: 800), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "爱拼音"
        window.contentView = web
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        awaitReady(attempt: 0)
    }
    func awaitReady(attempt: Int) {
        guard let server = server, server.isRunning else { fail("本地服务启动失败，请重新打开应用。"); return }
        let url = URL(string: "http://127.0.0.1:\(port)/api/v1/health")!
        URLSession.shared.dataTask(with: url) { _, response, _ in
            DispatchQueue.main.async {
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    self.web.load(URLRequest(url: URL(string: "http://127.0.0.1:\(self.port)/")!))
                } else if attempt < 100 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.awaitReady(attempt: attempt + 1) }
                } else { self.fail("本地服务未能就绪，请重新打开应用。") }
            }
        }.resume()
    }
    func fail(_ message: String) { let alert = NSAlert(); alert.messageText = "爱拼音无法启动"; alert.informativeText = message; alert.runModal(); NSApp.terminate(nil) }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { if server?.isRunning == true { server?.terminate(); server?.waitUntilExit() } }
}
let app = NSApplication.shared
let delegate = App()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
