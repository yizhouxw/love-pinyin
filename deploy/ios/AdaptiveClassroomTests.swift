import XCTest

final class AdaptiveClassroomTests: XCTestCase {
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
    func testOfflineGameScenes() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        let device = XCUIDevice.shared
        device.orientation = .portrait
        defer { device.orientation = .portrait }
        app.launchEnvironment["LP_UI_TEST_PROFILE"] = UUID().uuidString
        app.launch()

        let hub = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "进入游戏乐园")).firstMatch
        XCTAssertTrue(hub.waitForExistence(timeout: 25), app.debugDescription)
        reveal(hub, in: app)
        assertTouchTarget(hub, within: app)
        hub.tap()

        for (title, actionLabel) in [
            ("森林跑酷", "跳跃 ↑"), ("河湾划船", "双桨前进"),
            ("节奏鼓岛", "咚！击鼓"), ("星际投递", "发射 ↑"),
        ] {
            let start = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "开始" + title)).firstMatch
            XCTAssertTrue(start.waitForExistence(timeout: 15), app.debugDescription)
            reveal(start, in: app)
            assertTouchTarget(start, within: app)
            start.tap()

            let listen = app.buttons["听拼音"]
            XCTAssertTrue(listen.waitForExistence(timeout: 15), app.debugDescription)
            reveal(listen, in: app)
            assertTouchTarget(listen, within: app)
            listen.tap()
            let action = app.buttons[actionLabel]
            XCTAssertTrue(action.waitForExistence(timeout: 15), app.debugDescription)
            XCTAssertTrue(waitUntil(action, predicate: "enabled == true"), app.debugDescription)
            reveal(action, in: app)
            assertTouchTarget(action, within: app)
            action.tap()
            addScreenshot(title)

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
