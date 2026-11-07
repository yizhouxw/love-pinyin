import XCTest

final class AdaptiveClassroomTests: XCTestCase {
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
