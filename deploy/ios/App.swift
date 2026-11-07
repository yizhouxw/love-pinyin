import AVFoundation
import UIKit
import WebKit

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        configurationForConnecting connectingSceneSession: UISceneSession,
        options: UIScene.ConnectionOptions
    ) -> UISceneConfiguration {
        let config = UISceneConfiguration(name: nil, sessionRole: connectingSceneSession.role)
        config.delegateClass = LearningSceneDelegate.self
        return config
    }
}

final class LearningSceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(
        _ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions
    ) {
        guard let scene = scene as? UIWindowScene else { return }
        let window = UIWindow(windowScene: scene)
        window.rootViewController = LearningViewController()
        window.makeKeyAndVisible()
        self.window = window
    }
}

@MainActor
final class LearningViewController: UIViewController, WKNavigationDelegate, WKScriptMessageHandlerWithReply {
    private var webView: WKWebView?
    private var assets: OfflineAssets?
    private var player: AVPlayer?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        do {
            guard let resources = Bundle.main.resourceURL else { throw CocoaError(.fileNoSuchFile) }
            let assets = try OfflineAssets(root: resources.appendingPathComponent("Offline"))
            self.assets = assets
            let config = WKWebViewConfiguration()
            config.setURLSchemeHandler(assets, forURLScheme: OfflineAssets.scheme)
            config.mediaTypesRequiringUserActionForPlayback = []
            config.userContentController.addScriptMessageHandler(
                LearningBridge(controller: self), contentWorld: .page, name: "learning"
            )
            let webView = WKWebView(frame: .zero, configuration: config)
            webView.navigationDelegate = self
            self.webView = webView
            install(webView)
            webView.load(URLRequest(url: OfflineAssets.entry))
            NotificationCenter.default.addObserver(
                self, selector: #selector(stopPlayback),
                name: UIScene.willDeactivateNotification, object: nil
            )
            NotificationCenter.default.addObserver(
                self, selector: #selector(stopPlayback),
                name: AVAudioSession.interruptionNotification, object: nil
            )
            NotificationCenter.default.addObserver(
                self, selector: #selector(audioRouteChanged),
                name: AVAudioSession.routeChangeNotification, object: nil
            )
        } catch {
            showFailure("离线资源读取失败，请重新构建测试版。")
        }
    }

    private func install(_ child: UIView) {
        child.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(child)
        let area = view.safeAreaLayoutGuide
        NSLayoutConstraint.activate([
            child.topAnchor.constraint(equalTo: area.topAnchor),
            child.bottomAnchor.constraint(equalTo: area.bottomAnchor),
            child.leadingAnchor.constraint(equalTo: area.leadingAnchor),
            child.trailingAnchor.constraint(equalTo: area.trailingAnchor),
        ])
    }

    private func showFailure(_ message: String) {
        webView?.removeFromSuperview()
        let label = UILabel()
        label.text = message
        label.numberOfLines = 0
        label.textAlignment = .center
        install(label)
    }

    @objc private func stopPlayback() {
        player?.pause()
        webView?.evaluateJavaScript("document.querySelector('audio')?.pause()")
    }

    @objc private func audioRouteChanged(_ notification: Notification) {
        if notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
            == AVAudioSession.RouteChangeReason.oldDeviceUnavailable.rawValue {
            stopPlayback()
        }
    }

    func webView(
        _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        let allowed = navigationAction.targetFrame?.isMainFrame == true
            && navigationAction.request.url == OfflineAssets.entry
        decisionHandler(allowed ? .allow : .cancel)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        showFailure("离线页面启动失败，请退出后重试。")
    }

    func userContentController(
        _ userContentController: WKUserContentController, didReceive message: WKScriptMessage,
        replyHandler: @escaping (Any?, String?) -> Void
    ) {
        guard message.frameInfo.isMainFrame,
              message.frameInfo.request.url == OfflineAssets.entry,
              let assets,
              let body = message.body as? [String: Any], body.count == 2,
              body["version"] as? Int == 1,
              let operation = body["operation"] as? String
        else {
            replyHandler(nil, "INVALID_BRIDGE_REQUEST")
            return
        }
        switch operation {
        case "bootstrap":
            replyHandler(["lessonCount": assets.lessonCount, "audioCount": assets.audioCount], nil)
        case "playLesson":
            do {
                let session = AVAudioSession.sharedInstance()
                try session.setCategory(.playback)
                try session.setActive(true)
                player?.pause()
                let player = AVPlayer(url: assets.lesson)
                self.player = player
                player.play()
                replyHandler(true, nil)
            } catch {
                replyHandler(nil, "AUDIO_UNAVAILABLE")
            }
        case "seekLesson":
            guard let player else {
                replyHandler(nil, "LESSON_NOT_STARTED")
                return
            }
            player.seek(to: CMTime(seconds: 10, preferredTimescale: 600)) { finished in
                DispatchQueue.main.async {
                    replyHandler(finished ? true : nil, finished ? nil : "SEEK_INTERRUPTED")
                }
            }
        case "stop":
            player?.pause()
            replyHandler(true, nil)
        default:
            replyHandler(nil, "UNKNOWN_OPERATION")
        }
    }
}

@MainActor
private final class LearningBridge: NSObject, WKScriptMessageHandlerWithReply {
    private weak var controller: LearningViewController?

    init(controller: LearningViewController) {
        self.controller = controller
    }

    func userContentController(
        _ userContentController: WKUserContentController, didReceive message: WKScriptMessage,
        replyHandler: @escaping (Any?, String?) -> Void
    ) {
        guard let controller else {
            replyHandler(nil, "BRIDGE_UNAVAILABLE")
            return
        }
        controller.userContentController(userContentController, didReceive: message, replyHandler: replyHandler)
    }
}
