import XCTest
import UIKit

final class AdaptiveClassroomTests: XCTestCase {
    @MainActor
    func testQuickSettingsDismissAndRotate() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["LP_UI_TEST_PROFILE"] = UUID().uuidString
        XCUIDevice.shared.orientation = .portrait
        app.launch()
        let entry = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "进入词语天天练")).firstMatch
        XCTAssertTrue(entry.waitForExistence(timeout: 25), app.debugDescription)
        entry.tap()
        let settings = labeled("播放设置", in: app)
        XCTAssertTrue(settings.waitForExistence(timeout: 15), app.debugDescription)
        reveal(settings, in: app)
        settings.tap()
        let done = app.buttons["完成"]
        XCTAssertTrue(done.waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertTrue(done.isHittable)
        addScreenshot("快捷设置竖屏")
        done.tap()
        XCTAssertFalse(done.exists)
        reveal(settings, in: app)
        settings.tap()
        XCUIDevice.shared.orientation = .landscapeLeft
        XCTAssertTrue(done.waitForExistence(timeout: 10))
        reveal(done, in: app)
        XCTAssertTrue(done.isHittable)
        addScreenshot("快捷设置横屏")
        done.tap()
        XCUIDevice.shared.orientation = .portrait
    }

    @MainActor
    func testHomeShowsLearningDestinations() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        XCUIDevice.shared.orientation = .portrait
        app.launchEnvironment["LP_UI_TEST_PROFILE"] = UUID().uuidString
        app.launch()

        let start = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "开始今天的练习")).firstMatch
        XCTAssertTrue(start.waitForExistence(timeout: 25), app.debugDescription)
        for label in ["课堂学习", "进入天天练拼音", "进入词语天天练", "进入游戏乐园", "家长管理"] {
            let entry = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", label)).firstMatch
            XCTAssertTrue(entry.isHittable, app.debugDescription)
            assertTouchTarget(entry, within: app)
        }
        XCTAssertTrue(start.isHittable)
        assertTouchTarget(start, within: app)
        addScreenshot("学习首页")

        for (label, back) in [
            ("进入天天练拼音", "返回小岛"), ("进入词语天天练", "返回首页"),
            ("进入游戏乐园", "回到学习"),
        ] {
            let entry = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", label)).firstMatch
            entry.tap()
            let backButton = app.buttons.matching(NSPredicate(format: "label ENDSWITH %@", back)).firstMatch
            XCTAssertTrue(backButton.waitForExistence(timeout: 15), app.debugDescription)
            backButton.tap()
            XCTAssertTrue(entry.waitForExistence(timeout: 15), app.debugDescription)
            XCTAssertTrue(entry.isHittable)
        }
    }

    @MainActor
    func testParentVersionFollowsSettingsAndCredits() {
        continueAfterFailure = false
        let app = XCUIApplication()
        XCUIDevice.shared.orientation = .portrait
        app.launchEnvironment["LP_UI_TEST_PROFILE"] = UUID().uuidString
        app.launch()

        let parent = app.buttons["家长管理"]
        XCTAssertTrue(parent.waitForExistence(timeout: 25), app.debugDescription)
        parent.tap()
        let confirm = app.buttons["我是家长，继续"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 12))
        confirm.tap()

        let version = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "版本 ")).firstMatch
        XCTAssertTrue(version.waitForExistence(timeout: 12), app.debugDescription)
        let credits = labeled("音频来源与许可", in: app)
        reveal(credits, in: app)
        XCTAssertLessThan(credits.frame.midY, version.frame.midY)
        let advanced = labeled("高级设置", in: app)
        if advanced.exists {
            XCTAssertLessThan(advanced.frame.midY, credits.frame.midY)
            XCTAssertFalse(labeled("学习素材", in: app).exists)
        }
        XCTAssertFalse(labeled("CC-BY-SA-3.0", in: app).exists)
        addScreenshot("家长设置顺序")

        credits.tap()
        let license = labeled("CC-BY-SA-3.0", in: app)
        XCTAssertTrue(license.waitForExistence(timeout: 12), app.debugDescription)
        reveal(license, in: app)
        addScreenshot("新版音源许可")
    }

    @MainActor
    func testOnDeviceQwenDownloadAndShopMatch() {
        runOnDeviceQwenShop(seeded: false)
    }

    @MainActor
    func testOnDeviceQwenShopWithVerifiedFixture() throws {
        guard ProcessInfo.processInfo.environment["LP_RUN_SEEDED_QWEN_TEST"] == "1" else {
            throw XCTSkip("Requires a verified model in the isolated device test sandbox")
        }
        runOnDeviceQwenShop(seeded: true)
    }

    @MainActor
    private func runOnDeviceQwenShop(seeded: Bool) {
        continueAfterFailure = false
        let app = XCUIApplication()
        XCUIDevice.shared.orientation = .portrait
        app.launchEnvironment["LP_UI_TEST_PROFILE"] = UUID().uuidString
        app.launchEnvironment["LP_UI_TEST_RECOGNITION_SAMPLE"] = "1"
        if seeded { app.launchEnvironment["LP_UI_TEST_RECOGNITION_SEEDED"] = "1" }
        app.launch()

        let parent = app.buttons["家长管理"]
        XCTAssertTrue(parent.waitForExistence(timeout: 25), app.debugDescription)
        parent.tap()
        let confirm = app.buttons["我是家长，继续"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 12))
        confirm.tap()

        let model = labeled("本地语音识别模型", in: app)
        XCTAssertTrue(model.waitForExistence(timeout: 12), app.debugDescription)
        let installed = labeled("模型已安装", in: app)
        if seeded { XCTAssertTrue(installed.waitForExistence(timeout: 12), app.debugDescription) }
        if !installed.exists {
            let download = app.buttons.matching(NSPredicate(
                format: "label IN %@", ["下载模型", "重试下载"]
            )).firstMatch
            reveal(download, in: app)
            download.tap()
            let progress = labeled("正在下载并校验", in: app)
            XCTAssertTrue(progress.waitForExistence(timeout: 15), app.debugDescription)
            let failed = labeled("下载或校验失败", in: app)
            let stopped = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                installed.exists || failed.exists
            }, object: app)
            XCTAssertEqual(XCTWaiter.wait(for: [stopped], timeout: 900), .completed)
            XCTAssertTrue(installed.exists, app.debugDescription)
        }
        addScreenshot("iPhone-device-model-installed")

        let back = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "返回学习")).firstMatch
        if !back.isHittable { app.swipeDown(velocity: .fast) }
        for _ in 0..<4 where !back.isHittable { app.swipeDown(velocity: .fast) }
        XCTAssertTrue(back.isHittable, app.debugDescription)
        back.tap()
        let hub = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "进入游戏乐园")).firstMatch
        XCTAssertTrue(hub.waitForExistence(timeout: 15), app.debugDescription)
        reveal(hub, in: app)
        hub.tap()
        let shop = app.buttons["进入拼音小卖部"]
        XCTAssertTrue(shop.waitForExistence(timeout: 15), app.debugDescription)
        reveal(shop, in: app)
        XCUIDevice.shared.orientation = .portrait
        shop.tap()
        let auto = labeled("本地语音识别", in: app)
        XCTAssertTrue(auto.waitForExistence(timeout: 15), app.debugDescription)
        let goods = app.switches["选择薯片"]
        XCTAssertTrue(goods.waitForExistence(timeout: 12), app.debugDescription)
        for _ in 0..<4 where !app.frame.contains(goods.frame) { app.swipeUp() }
        XCTAssertTrue(app.frame.contains(goods.frame), app.debugDescription)
        goods.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        // A bundled licensed sample replaces microphone input in this Debug test.
        // The production Core ML model and native bridge still perform the inference.
        let match = labeled("读音匹配，商品已自动加入购物车", in: app)
        XCTAssertTrue(match.waitForExistence(timeout: 45), app.debugDescription)
        addScreenshot("iPhone-on-device-Qwen-match")
    }

    @MainActor
    func testFlightDragOnPhysicalDevice() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["LP_UI_TEST_PROFILE"] = UUID().uuidString
        XCUIDevice.shared.orientation = .portrait
        app.launch()
        let hub = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "进入游戏乐园")).firstMatch
        XCTAssertTrue(hub.waitForExistence(timeout: 30), app.debugDescription)
        hub.tap()
        let start = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "开始星际投递")).firstMatch
        XCTAssertTrue(start.waitForExistence(timeout: 20))
        reveal(start, in: app)
        start.tap()
        let begin = app.buttons["▶ 开始游戏"]
        XCTAssertTrue(begin.waitForExistence(timeout: 15))
        begin.tap()
        let fire = app.buttons["发射 · 空格"]
        XCTAssertTrue(fire.waitForExistence(timeout: 15))
        XCTAssertTrue(waitUntil(fire, predicate: "enabled == true"))
        let scene = app.otherElements.matching(NSPredicate(format: "label == %@", "星际飞行射击")).firstMatch
        XCTAssertTrue(scene.waitForExistence(timeout: 15), app.debugDescription)
        addScreenshot("ACTION-flight-before-drag")
        scene.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.82)).press(
            forDuration: 0.1,
            thenDragTo: scene.coordinate(withNormalizedOffset: CGVector(dx: 0.73, dy: 0.73))
        )
        addScreenshot("ACTION-flight-after-drag")
        assertTouchTarget(fire, within: app)
        fire.press(forDuration: 1.2)
        addScreenshot("ACTION-flight-held-fire")
        app.terminate()
    }

    @MainActor
    func testActionGamesOnPhysicalDevice() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        let device = XCUIDevice.shared
        app.launchEnvironment["LP_UI_TEST_PROFILE"] = UUID().uuidString
        device.orientation = .portrait
        defer { device.orientation = .portrait }
        app.launch()
        let hub = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "进入游戏乐园")).firstMatch
        XCTAssertTrue(hub.waitForExistence(timeout: 30), app.debugDescription)
        hub.tap()
        for (title, prefix) in [("森林跑酷", "摘 "), ("节奏鼓岛", "敲响 "), ("星际投递", "投递到 ")] {
            let start = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "开始" + title)).firstMatch
            XCTAssertTrue(start.waitForExistence(timeout: 20), app.debugDescription)
            reveal(start, in: app)
            start.tap()
            let begin = app.buttons["▶ 开始游戏"]
            XCTAssertTrue(begin.waitForExistence(timeout: 20), app.debugDescription)
            begin.tap()
            let listen = app.buttons["听拼音"]
            XCTAssertTrue(listen.waitForExistence(timeout: 15), app.debugDescription)
            let choices = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", prefix))
            XCTAssertTrue(choices.firstMatch.waitForExistence(timeout: 20), app.debugDescription)
            XCTAssertTrue(waitUntil(choices.firstMatch, predicate: "enabled == true"), app.debugDescription)
            if title == "森林跑酷" {
                let jump = app.buttons["跳起来 ↑"]
                assertTouchTarget(jump, within: app)
                jump.tap()
                addScreenshot("ACTION-runner-touch-jump")
            }
            // All answers are chosen through visible controls; no answer or physics injection.
            // The random test profile may record first errors while cycling candidates.
            for checkpoint in 1...2 {
                let progress = app.otherElements["关卡完成进度"]
                for attempt in 0..<160 {
                    if (Double(progress.value as? String ?? "0") ?? 0) >= Double(checkpoint) { break }
                    let count = choices.count
                    if count > 0 {
                        let lane: Int? = title == "节奏鼓岛" ? visibleDrumLane(in: app, count: count) : attempt % count
                        if let lane {
                        let option = choices.element(boundBy: lane)
                        if option.isEnabled && option.isHittable {
                            option.tap()
                            if title == "星际投递" {
                                let fire = app.buttons["发射 · 空格"]
                                if fire.isEnabled && fire.isHittable { fire.tap() }
                            }
                        }
                    }
                    }
                    Thread.sleep(forTimeInterval: title == "节奏鼓岛" ? 0.12 : (attempt % 2 == 0 ? 0.31 : 0.47))
                }
                let advanced = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                    (Double(progress.value as? String ?? "0") ?? 0) >= Double(checkpoint)
                }, object: nil)
                XCTAssertEqual(XCTWaiter.wait(for: [advanced], timeout: 15), .completed, app.debugDescription)
                XCTAssertFalse(begin.exists, "A checkpoint must not restart the scene")
                addScreenshot("ACTION-" + title + "-checkpoint-\(checkpoint + 1)")
            }
            device.orientation = .landscapeLeft
            waitForRotation(app, landscape: true)
            addScreenshot("ACTION-" + title + "-landscape")
            device.orientation = .portrait
            waitForRotation(app, landscape: false)
            device.press(.home)
            app.activate()
            let resume = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "继续游戏")).firstMatch
            XCTAssertTrue(resume.waitForExistence(timeout: 20), app.debugDescription)
            resume.tap()
            XCTAssertTrue(listen.waitForExistence(timeout: 15), app.debugDescription)
            let exit = app.buttons.matching(NSPredicate(format: "label ENDSWITH %@", "保存并退出游戏")).firstMatch
            XCTAssertTrue(exit.waitForExistence(timeout: 15), app.debugDescription)
            reveal(exit, in: app)
            exit.tap()
        }
        app.terminate()
    }

    @MainActor
    func testOfflineGameScenes() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        let device = XCUIDevice.shared
        device.orientation = .portrait
        defer { device.orientation = .portrait }
        app.launchEnvironment["LP_UI_TEST_PROFILE"] = UUID().uuidString
        app.launch()
        waitForRotation(app, landscape: false)

        let hub = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "进入游戏乐园")).firstMatch
        XCTAssertTrue(hub.waitForExistence(timeout: 25), app.debugDescription)
        reveal(hub, in: app)
        assertTouchTarget(hub, within: app)
        hub.tap()

        for (title, actionLabel) in [
            ("森林跑酷", "跳起来 ↑"), ("河湾划船", "停船"),
            ("节奏鼓岛", "敲响 "), ("星际投递", "投递到 "),
        ] {
            let start = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "开始" + title)).firstMatch
            XCTAssertTrue(start.waitForExistence(timeout: 15), app.debugDescription)
            reveal(start, in: app)
            assertTouchTarget(start, within: app)
            start.tap()
            let begin = app.buttons["▶ 开始游戏"]
            XCTAssertTrue(begin.waitForExistence(timeout: 15), app.debugDescription)
            assertTouchTarget(begin, within: app)
            begin.tap()

            let listen = app.buttons["听拼音"]
            XCTAssertTrue(listen.waitForExistence(timeout: 15), app.debugDescription)
            reveal(listen, in: app)
            assertTouchTarget(listen, within: app)
            listen.tap()
            let action = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", actionLabel)).firstMatch
            XCTAssertTrue(action.waitForExistence(timeout: 15), app.debugDescription)
            XCTAssertTrue(waitUntil(action, predicate: "enabled == true"), app.debugDescription)
            reveal(action, in: app)
            assertTouchTarget(action, within: app)
            action.tap()
            let sceneNames = ["森林跑酷": "森林跳跃冒险", "河湾划船": "河湾救援航行", "节奏鼓岛": "鼓岛动物乐队", "星际投递": "星际包裹弹射"]
            let scene = labeled(sceneNames[title]!, in: app)
            XCTAssertTrue(scene.waitForExistence(timeout: 10), app.debugDescription)
            XCTAssertGreaterThan(scene.frame.height, 120)
            if title == "河湾划船" || title == "星际投递" {
                let startPoint = scene.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.8))
                let endPoint = scene.coordinate(withNormalizedOffset: CGVector(dx: 0.62, dy: 0.94))
                startPoint.press(forDuration: 0.2, thenDragTo: endPoint)
            }
            addScreenshot(title)
            device.orientation = .landscapeLeft
            waitForRotation(app, landscape: true)
            reveal(action, in: app)
            XCTAssertTrue(waitUntil(action, predicate: "hittable == true"), app.debugDescription)
            assertTouchTarget(action, within: app)
            addScreenshot(title + "横屏")
            device.orientation = .portrait
            waitForRotation(app, landscape: false)

            let pause = app.buttons.matching(NSPredicate(format: "label ENDSWITH %@", "暂停")).firstMatch
            for _ in 0..<3 where !pause.isHittable { app.swipeDown() }
            XCTAssertTrue(pause.isHittable, app.debugDescription)
            assertTouchTarget(pause, within: app)
            pause.tap()
            let resume = app.buttons["继续游戏"]
            XCTAssertTrue(resume.waitForExistence(timeout: 12), app.debugDescription)
            XCTAssertTrue(labeled("游戏先暂停一下", in: app).exists, app.debugDescription)
            resume.tap()
            XCTAssertTrue(listen.waitForExistence(timeout: 12), app.debugDescription)

            if title == "森林跑酷" {
                device.press(.home)
                app.activate()
                XCTAssertTrue(resume.waitForExistence(timeout: 12), app.debugDescription)
                resume.tap()
                XCTAssertTrue(listen.waitForExistence(timeout: 12), app.debugDescription)
                app.terminate()
                app.launch()
                XCTAssertTrue(listen.waitForExistence(timeout: 25), app.debugDescription)
            }

            let exit = app.buttons.matching(NSPredicate(format: "label ENDSWITH %@", "保存并退出游戏")).firstMatch
            XCTAssertTrue(exit.isHittable, app.debugDescription)
            exit.tap()
            XCTAssertTrue(start.waitForExistence(timeout: 12), app.debugDescription)
        }
    }

    @MainActor
    func testWordReadingWorkspace() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        let device = XCUIDevice.shared
        device.orientation = .portrait
        defer { device.orientation = .portrait }
        app.launchEnvironment["LP_UI_TEST_PROFILE"] = UUID().uuidString
        app.launch()
        let entry = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "进入词语天天练")).firstMatch
        XCTAssertTrue(entry.waitForExistence(timeout: 25))
        reveal(entry, in: app)
        entry.tap()
        let list = labeled("本课词语", in: app)
        XCTAssertTrue(list.waitForExistence(timeout: 15), app.debugDescription)
        let words = app.descendants(matching: .any).matching(NSPredicate(format: "label BEGINSWITH %@", "听读"))
        XCTAssertTrue(words.firstMatch.waitForExistence(timeout: 15), app.debugDescription)
        XCTAssertGreaterThan(words.count, 2, app.debugDescription)
        let last = words.element(boundBy: words.count - 1)
        for _ in 0..<5 where !last.isHittable { list.swipeUp() }
        XCTAssertTrue(last.isHittable, app.debugDescription)
        last.tap()
        let illustration = labeled("词语图片：", in: app)
        XCTAssertTrue(illustration.exists, app.debugDescription)
        XCTAssertTrue(illustration.frame.intersects(app.windows.firstMatch.frame))
        addScreenshot("词语拼读独立滚动")
        let read = labeled("连读本课", in: app)
        reveal(read, in: app)
        read.tap()
        XCTAssertTrue(words.firstMatch.waitForExistence(timeout: 10))
        device.orientation = .landscapeLeft
        waitForRotation(app, landscape: true)
        addScreenshot("词语连读横屏跟随")
        let stop = app.buttons["停止播放"]
        reveal(stop, in: app)
        stop.tap()
        device.orientation = .portrait
        waitForRotation(app, landscape: false)
        let nextLesson = app.buttons["下一课"]
        reveal(nextLesson, in: app)
        nextLesson.tap()
        nextLesson.tap()
        labeled("词语听写", in: app).tap()
        let revealAnswer = app.buttons["揭晓答案"]
        XCTAssertTrue(revealAnswer.waitForExistence(timeout: 10), app.debugDescription)
        reveal(revealAnswer, in: app)
        revealAnswer.tap()
        addScreenshot("听写逐字拼音对齐")
    }

    @MainActor
    func testClassroomAcrossRotationAndRelaunch() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        let device = XCUIDevice.shared
        device.orientation = .portrait
        defer { device.orientation = .portrait }
        app.launchEnvironment["LP_UI_TEST_PROFILE"] = UUID().uuidString
        app.launch()

        let start = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "开始今天的练习")).firstMatch
        XCTAssertTrue(start.waitForExistence(timeout: 25), app.debugDescription)
        assertTouchTarget(start, within: app)
        addScreenshot("学习首页")
        start.tap()

        let first = labeled("第 1 / 6 关", in: app)
        if !first.waitForExistence(timeout: 4), start.exists { start.tap() }
        XCTAssertTrue(first.waitForExistence(timeout: 12), app.debugDescription)
        let listen = app.buttons["听拼音"]
        XCTAssertTrue(listen.waitForExistence(timeout: 12), app.debugDescription)
        assertTouchTarget(listen, within: app)
        listen.tap()
        let correct = app.buttons.matching(NSPredicate(format: "label ENDSWITH %@", "，a")).firstMatch
        XCTAssertTrue(correct.exists)
        // An automatic prompt can already be playing when the first tap lands.
        if !waitUntil(correct, predicate: "enabled == true"), listen.exists { listen.tap() }
        XCTAssertTrue(waitUntil(correct, predicate: "enabled == true"), app.debugDescription)

        device.orientation = .landscapeLeft
        let landscape = XCTNSPredicateExpectation(predicate: NSPredicate { object, _ in
            guard let element = object as? XCUIElement else { return false }
            return element.frame.width > element.frame.height
        }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [landscape], timeout: 12), .completed, app.debugDescription)
        XCTAssertTrue(first.exists, "Rotation must preserve the current question")
        reveal(correct, in: app)
        assertTouchTarget(correct, within: app)
        addScreenshot("横屏课堂")
        correct.tap()
        let next = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "继续")).firstMatch
        XCTAssertTrue(next.waitForExistence(timeout: 12), app.debugDescription)
        reveal(next, in: app)
        next.tap()
        let second = labeled("第 2 / 6 关", in: app)
        XCTAssertTrue(second.waitForExistence(timeout: 12), app.debugDescription)

        app.terminate()
        device.orientation = .portrait
        app.launch()
        XCTAssertTrue(second.waitForExistence(timeout: 25), app.debugDescription)
        addScreenshot("重启恢复第二题")

        app.buttons["退出练习"].tap()
        let parent = app.buttons["家长管理"]
        XCTAssertTrue(parent.waitForExistence(timeout: 12))
        parent.tap()
        let confirm = app.buttons["我是家长，继续"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 12), app.debugDescription)
        confirm.tap()
        let count = app.descendants(matching: .any).matching(NSPredicate(
            format: "label BEGINSWITH %@", "已作答 1 题"
        )).firstMatch
        XCTAssertTrue(count.waitForExistence(timeout: 12), app.debugDescription)
    }

    @MainActor
    private func waitForRotation(_ app: XCUIApplication, landscape: Bool) {
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let frame = app.windows.firstMatch.frame
            return landscape ? frame.width > frame.height : frame.height > frame.width
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 12), .completed)
    }

    // Read actual device pixels to time a visible note approaching the strike line.
    // No WebView state, answer lookup, clock change or injected action is used.
    @MainActor
    private func visibleDrumLane(in app: XCUIApplication, count: Int) -> Int? {
        let scene = app.otherElements.matching(NSPredicate(format: "label == %@", "拼音节奏轨道")).firstMatch
        guard scene.exists, let image = XCUIScreen.main.screenshot().image.cgImage else { return nil }
        let w = image.width, h = image.height
        var bytes = [UInt8](repeating: 0, count: w * h * 4)
        guard let context = CGContext(data: &bytes, width: w, height: h,
            bitsPerComponent: 8, bytesPerRow: w * 4, space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        context.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
        let frame = scene.frame
        for lane in 0..<count {
            let x = frame.minX + frame.width * (60 + CGFloat(lane) * 360 / CGFloat(max(1, count - 1)) + 22) / 480
            let y = frame.minY + frame.height * 260 / 400
            let px = Int(x * CGFloat(w) / app.frame.width), py = Int(y * CGFloat(h) / app.frame.height)
            if px < 0 || px >= w || py < 0 || py >= h { continue }
            let offset = (py * w + px) * 4
            if bytes[offset] < 160 && bytes[offset + 1] > 170 && bytes[offset + 2] > 170 { return lane }
        }
        return nil
    }

    @MainActor
    private func labeled(_ name: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label BEGINSWITH %@", name)).firstMatch
    }

    @MainActor
    private func waitUntil(_ element: XCUIElement, predicate: String) -> Bool {
        XCTWaiter.wait(for: [XCTNSPredicateExpectation(
            predicate: NSPredicate(format: predicate), object: element
        )], timeout: 12) == .completed
    }

    @MainActor
    private func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        for _ in 0..<3 where !element.isHittable { app.swipeUp() }
        XCTAssertTrue(element.isHittable, app.debugDescription)
    }

    @MainActor
    private func assertTouchTarget(_ element: XCUIElement, within app: XCUIApplication,
                                   file: StaticString = #filePath, line: UInt = #line) {
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let frame = element.frame
            return frame.width >= 44 && frame.height >= 44 && app.frame.contains(frame)
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 12), .completed, file: file, line: line)
        let frame = element.frame
        XCTAssertGreaterThanOrEqual(frame.width, 44, file: file, line: line)
        XCTAssertGreaterThanOrEqual(frame.height, 44, file: file, line: line)
        XCTAssertTrue(app.frame.contains(frame), file: file, line: line)
    }

    @MainActor
    private func addScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
