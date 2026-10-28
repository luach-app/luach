import XCTest

/// The Household UI tests' own line to the test server, beside the app: to record a setting
/// before a test changes it through the screen, check it after, and put it back if the
/// test stopped half-way. Same session as the app (LuachApp's environment).
enum HouseholdServer {
    struct Failure: Error, CustomStringConvertible { let description: String }

    /// One JSON call; the answer as a dictionary.
    @discardableResult
    static func call(_ method: String, _ path: String, _ body: [String: Any]? = nil) throws -> [String: Any] {
        guard let server = LuachApp.server, let session = LuachApp.session, !session.isEmpty,
              let url = URL(string: server + path) else {
            throw XCTSkip("set LUACH_TEST_SERVER and LUACH_TEST_SESSION (ios/scripts/test.sh does)")
        }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("luach_session=\(session)", forHTTPHeaderField: "Cookie")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        nonisolated(unsafe) var result: Result<(Int, Data), Error> = .failure(Failure(description: "no answer"))
        let done = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: req) { data, response, error in
            if let error { result = .failure(error) } else {
                result = .success(((response as? HTTPURLResponse)?.statusCode ?? 0, data ?? Data()))
            }
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + 30)
        let (status, data) = try result.get()
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        guard status < 400 else {
            throw Failure(description: "\(method) \(path): \(status) \(json["error"] ?? "")")
        }
        return json
    }

    /// The member's booking settings, without what the server owns (link, timezone, zoom_ready).
    static func bookingSettings() throws -> [String: Any] {
        var b = try call("GET", "/api/booking")
        for key in ["link", "timezone", "zoom_ready"] { b.removeValue(forKey: key) }
        return b
    }

    static func reminders() throws -> [String: Any] {
        try call("GET", "/api/reminders")
    }

    static func busyFeeds() throws -> [[String: Any]] {
        try call("GET", "/api/busy")["sources"] as? [[String: Any]] ?? []
    }

    /// Removes every feed this run's tests may have left (named `ios-test…`).
    static func removeTestFeeds() throws {
        for feed in try busyFeeds() where (feed["name"] as? String)?.hasPrefix("ios-test") == true {
            if let id = feed["id"] as? Int { try call("DELETE", "/api/busy/\(id)") }
        }
    }

    static func same(_ a: [String: Any], _ b: [String: Any]) -> Bool {
        NSDictionary(dictionary: a).isEqual(to: b)
    }
}

extension XCUIApplication {
    /// The Save button in the navigation bar.
    var saveButton: XCUIElement { navigationBars.buttons["Save"].firstMatch }

    /// Swipes the form up until the element can be tapped (lazy rows only exist once near).
    @discardableResult
    func reveal(_ element: XCUIElement, up: Bool = true, tries: Int = 12,
                file: StaticString = #filePath, line: UInt = #line) -> XCUIElement {
        var n = 0
        while !(element.exists && element.isHittable) && n < tries {
            if up { swipeUp(velocity: .slow) } else { swipeDown(velocity: .slow) }
            n += 1
        }
        XCTAssertTrue(element.waitForExistence(timeout: 3) && element.isHittable,
                      "could not scroll to \(element): \(debugDescription)", file: file, line: line)
        return element
    }

    /// A button whose label begins with `text` (a picker row reads "Title, value").
    func button(startingWith text: String) -> XCUIElement {
        buttons.matching(NSPredicate(format: "label BEGINSWITH %@", text)).firstMatch
    }

    /// Any element by its accessibility identifier, whatever kind it is.
    func element(_ id: String) -> XCUIElement {
        descendants(matching: .any).matching(identifier: id).firstMatch
    }

    /// Taps `trigger` and waits for the confirmation dialog it opens, which adds a second
    /// button named `label` (a popover on iPhone: its Cancel is a tap outside). Returns the
    /// dialog's button.
    func dialog(from trigger: XCUIElement, _ label: String,
                file: StaticString = #filePath, line: UInt = #line) -> XCUIElement {
        let all = buttons.matching(identifier: label)
        let before = all.count
        trigger.tap()
        let deadline = Date.now.addingTimeInterval(5)
        while all.count <= before && Date.now < deadline { RunLoop.current.run(until: .now + 0.2) }
        XCTAssertGreaterThan(all.count, before, "no dialog: \(debugDescription)", file: file, line: line)
        let inSheet = sheets.buttons[label]
        return inSheet.exists ? inSheet : all.element(boundBy: all.count - 1)
    }

    /// Closes an open dialog without choosing: its Cancel button, or a tap outside it.
    func dismissDialog(cancel: String) {
        let button = buttons[cancel].firstMatch
        let outside = otherElements["PopoverDismissRegion"].firstMatch
        if button.exists { button.tap() } else if outside.exists { outside.tap() } else {
            coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.9)).tap()
        }
    }

    /// A menu choice once a picker is open.
    func choose(_ label: String, file: StaticString = #filePath, line: UInt = #line) {
        let item = buttons[label].firstMatch
        XCTAssertTrue(item.waitForExistence(timeout: 5), "no \(label) in the menu", file: file, line: line)
        item.tap()
    }
}

extension XCUIElement {
    /// A SwiftUI Toggle row's switch, flipped (tapping the row's label does not flip it).
    func flip() {
        let inner = switches.firstMatch
        (inner.exists ? inner : self).tap()
    }

    var isOn: Bool { (value as? String) == "1" }

    /// Clears a text field and types into it, whatever its alignment: the tap goes to the
    /// field's far end, so the cursor is after the text (LuachApp's `replaceText` taps the
    /// middle, which in a right-aligned field lands before it).
    func retype(_ text: String) {
        // A tap can still land before a narrow last character: clear until nothing is left.
        for _ in 0..<4 {
            coordinate(withNormalizedOffset: CGVector(dx: 0.999, dy: 0.5)).tap()
            let current = (value as? String).flatMap { $0 == placeholderValue ? nil : $0 } ?? ""
            if current.isEmpty { break }
            typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: current.count + 2))
        }
        if !text.isEmpty { typeText(text) }
    }

    func waitUntil(timeout: TimeInterval = 10, _ predicate: String) -> Bool {
        let exp = XCTNSPredicateExpectation(predicate: NSPredicate(format: predicate), object: self)
        return XCTWaiter().wait(for: [exp], timeout: timeout) == .completed
    }
}
