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
    private var playbackId: Int?
    private var lessonId: String?

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
            config.userContentController.addUserScript(WKUserScript(
                source: "Object.defineProperty(window, '__lovePinyinIOS', { value: true });",
                injectionTime: .atDocumentStart, forMainFrameOnly: true
            ))
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
        webView?.evaluateJavaScript("window.dispatchEvent(new Event('lp-ios-audio-interrupted'))")
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
              let body = message.body as? [String: Any], body.count <= 4,
              body["version"] as? Int == 1,
              let operation = body["operation"] as? String
        else {
            replyHandler(nil, "INVALID_BRIDGE_REQUEST")
            return
        }
        do {
            switch operation {
            case "library" where body.count == 2:
                replyHandler([
                    "curriculum": try assets.responseData("curriculum"),
                    "sounds": try assets.responseData("learning-audio"),
                ], nil)
            case "libraryReady" where body.count == 2:
                #if DEBUG
                FileHandle.standardOutput.write(Data("Offline listening library mounted\n".utf8))
                #endif
                replyHandler(true, nil)
            case "dailyReading" where body.count == 2:
                replyHandler(try assets.responseData("daily-reading"), nil)
            case "playLesson" where body.count == 4:
                guard let id = body["id"] as? Int, id > 0,
                      let audioId = body["audioId"] as? String, audioId.count < 128,
                      let file = assets.lesson(audioId),
                      view.window?.windowScene?.activationState == .foregroundActive
                else {
                    replyHandler(nil, "AUDIO_UNAVAILABLE")
                    return
                }
                let session = AVAudioSession.sharedInstance()
                try session.setCategory(.playback)
                try session.setActive(true)
                if playbackId != id || lessonId != audioId || player?.currentItem?.status == .failed {
                    player?.pause()
                    player = AVPlayer(url: file)
                    playbackId = id
                    lessonId = audioId
                }
                if let player, player.currentTime().seconds >= duration(player), duration(player) > 0 {
                    player.seek(to: .zero)
                }
                player?.play()
                replyHandler(playbackState(), nil)
            case "lessonState", "pauseLesson":
                guard body.count == 3, let id = body["id"] as? Int, id == playbackId else {
                    replyHandler(["playing": false, "position": 0, "duration": 0], nil)
                    return
                }
                if operation == "pauseLesson" { player?.pause() }
                if player?.currentItem?.status == .failed {
                    replyHandler(nil, "AUDIO_UNAVAILABLE")
                } else {
                    replyHandler(playbackState(), nil)
                }
            case "seekLesson" where body.count == 4:
                guard let id = body["id"] as? Int, id == playbackId, let player,
                      let seconds = body["seconds"] as? Double,
                      seconds.isFinite, seconds >= 0, seconds <= duration(player)
                else {
                    replyHandler(nil, "INVALID_AUDIO_POSITION")
                    return
                }
                player.seek(to: CMTime(seconds: seconds, preferredTimescale: 600)) { [weak self] finished in
                    DispatchQueue.main.async {
                        guard finished, let self, self.playbackId == id else {
                            replyHandler(nil, "SEEK_INTERRUPTED")
                            return
                        }
                        replyHandler(self.playbackState(), nil)
                    }
                }
            default:
                replyHandler(nil, "UNKNOWN_OPERATION")
            }
        } catch {
            replyHandler(nil, "IOS_RESOURCE_UNAVAILABLE")
        }
    }

    private func duration(_ player: AVPlayer) -> Double {
        let seconds = player.currentItem?.duration.seconds ?? 0
        return seconds.isFinite && seconds >= 0 ? seconds : 0
    }

    private func playbackState() -> [String: Any] {
        guard let player else { return ["playing": false, "position": 0, "duration": 0] }
        let position = player.currentTime().seconds
        let duration = duration(player)
        return [
            "playing": player.timeControlStatus != .paused && (duration == 0 || position < duration),
            "position": position.isFinite ? position : 0,
            "duration": duration,
        ]
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
