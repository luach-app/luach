import XCTest

/// What the Board's UI tests share: dev's API from the test runner, to make the items a test
/// needs and read back what the app did, and a tag in every title so the tear-down removes
/// this test's items and nobody else's.
class BoardUITestCase: XCTestCase {
    private(set) var server: URL!
    private var cookie = ""
    /// In every title this test makes.
    let tag = String(UUID().uuidString.prefix(6)).lowercased()
    private var events: [(id: String, calendar: String)] = []

    override func setUpWithError() throws {
        continueAfterFailure = false
        guard let s = LuachApp.server.flatMap(URL.init(string:)), let c = LuachApp.session, !c.isEmpty else {
            throw XCTSkip("set LUACH_TEST_SERVER and LUACH_TEST_SESSION (ios/scripts/test.sh does)")
        }
        server = s
        cookie = c
    }

    /// Synchronous on purpose: when a step fails, XCTest stops the async test on the main
    /// thread and runs the tear-down there; an async (main-actor) one would wait for a main
    /// thread that never comes back, and the run would hang.
    override func tearDown() {
        guard server != nil else { return }
        for e in events {
            request("DELETE", "/api/board/events/\(e.id)", query: e.calendar.isEmpty ? [:] : ["calendar": e.calendar])
        }
        // Whatever this test made, through the API or by tapping, wherever it ended up.
        let today = request("GET", "/api/board/today")?["today"] as? String ?? ""
        var ids = Set<Int>()
        let open = request("GET", "/api/tasks/all")
        for t in open?["tasks"] as? [[String: Any]] ?? [] where mine(t) { ids.insert(t["id"] as? Int ?? 0) }
        for n in 0...3 where !today.isEmpty {
            let day = request("GET", "/api/tasks", query: ["day": add(today, n)])
            for t in day?["tasks"] as? [[String: Any]] ?? [] where mine(t) { ids.insert(t["id"] as? Int ?? 0) }
            let board = request("GET", "/api/board/today", query: ["day": add(today, n)])
            for e in board?["events"] as? [[String: Any]] ?? [] where mine(e) {
                request("DELETE", "/api/board/events/\(e["id"] as? String ?? "")",
                        query: ["calendar": e["calendar_id"] as? String ?? ""].filter { !$0.value.isEmpty })
            }
        }
        for id in ids where id != 0 { request("DELETE", "/api/tasks/\(id)") }
    }

    private func mine(_ item: [String: Any]) -> Bool {
        let title = item["title"] as? String ?? ""
        return title.hasPrefix("ios-test") && title.contains(tag)
    }

    /// A title of this test's: `ios-test <what> <tag>`.
    func title(_ what: String) -> String { "ios-test \(what) \(tag)" }

    // MARK: dev's API

    private func urlRequest(_ method: String, _ path: String, query: [String: String], _ body: [String: Any]?) -> URLRequest {
        var parts = URLComponents(url: server.appending(path: path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { parts.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var req = URLRequest(url: parts.url!)
        req.httpMethod = method
        req.timeoutInterval = 20
        req.httpShouldHandleCookies = false
        req.setValue("luach_session=\(cookie)", forHTTPHeaderField: "Cookie")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        return req
    }

    private final class Answer: @unchecked Sendable { var json: [String: Any]? }

    /// A call that blocks this thread (URLSession answers on its own queue), for the tear-down.
    @discardableResult
    private func request(_ method: String, _ path: String, query: [String: String] = [:]) -> [String: Any]? {
        let done = DispatchSemaphore(value: 0)
        let answer = Answer()
        URLSession.shared.dataTask(with: urlRequest(method, path, query: query, nil)) { data, response, _ in
            if let data, ((response as? HTTPURLResponse)?.statusCode ?? 500) < 400 {
                answer.json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            }
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + 25)
        return answer.json
    }

    @discardableResult
    func call(_ method: String, _ path: String, query: [String: String] = [:], _ body: [String: Any]? = nil) async throws -> [String: Any] {
        let (data, response) = try await URLSession.shared.data(for: urlRequest(method, path, query: query, body))
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        if status >= 400 {
            throw NSError(domain: "dev", code: status, userInfo: [NSLocalizedDescriptionKey: "\(method) \(path) → \(status) \(json)"])
        }
        return json
    }

    /// Two of dev's family to give things to (`LuachApp.twoPeople`), in the family's order.
    func twoPeople() async throws -> (LuachApp.Person, LuachApp.Person) {
        let two = try await LuachApp.twoPeople()
        guard two.count == 2 else { throw XCTSkip("dev's family has fewer than two people") }
        return (two[0], two[1])
    }

    /// Today in the household's zone, as the board pages it.
    func today() async throws -> String {
        try await call("GET", "/api/board/today")["today"] as? String ?? ""
    }

    func addTask(_ title: String, person: String = "", due: String? = nil, days: [String]? = nil) async throws -> Int {
        var body: [String: Any] = ["title": title, "person": person]
        if let due { body["due"] = due }
        if let days { body["days"] = days }
        return try await call("POST", "/api/board/tasks", body)["id"] as? Int ?? 0
    }

    /// An event no one is invited to; removed in the tear-down.
    @discardableResult
    func addEvent(_ title: String, start: String, end: String? = nil, leaders: [String], recurrence: String? = nil) async throws -> String {
        var body: [String: Any] = ["title": title, "start": start, "attendees": [String](), "leaders": leaders]
        if let end { body["end"] = end }
        if let recurrence { body["recurrence"] = recurrence }
        let e = try await call("POST", "/api/board/events", body)
        let id = e["id"] as? String ?? ""
        events.append((id, e["calendar_id"] as? String ?? ""))
        return id
    }

    /// A task as a day's list has it (a ticked to-do stays on the day it was ticked).
    func task(_ id: Int, on day: String? = nil) async throws -> [String: Any]? {
        let list = try await call("GET", "/api/tasks", query: day.map { ["day": $0] } ?? [:])
        return (list["tasks"] as? [[String: Any]])?.first { $0["id"] as? Int == id }
    }

    /// The day's tasks and every open one, titled so.
    func tasks(titled title: String, on day: String? = nil) async throws -> [[String: Any]] {
        var found = (try await call("GET", "/api/tasks", query: day.map { ["day": $0] } ?? [:])["tasks"] as? [[String: Any]]) ?? []
        found += (try await call("GET", "/api/tasks/all")["tasks"] as? [[String: Any]]) ?? []
        var seen = Set<Int>()
        return found.filter { $0["title"] as? String == title && seen.insert($0["id"] as? Int ?? 0).inserted }
    }

    func event(_ id: String, on day: String) async throws -> [String: Any]? {
        let board = try await call("GET", "/api/board/today", query: ["day": day])
        return (board["events"] as? [[String: Any]])?.first { $0["id"] as? String == id }
    }

    /// Asks dev until it says what the test expects (the app saves in the background).
    func eventually(_ what: String, timeout: TimeInterval = 15, _ check: () async throws -> Bool) async throws {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end {
            if (try? await check()) == true { return }
            try await Task.sleep(for: .milliseconds(500))
        }
        XCTFail("dev never showed: \(what)")
    }

    func add(_ iso: String, _ days: Int) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd"
        guard let d = f.date(from: iso) else { return iso }
        return f.string(from: d.addingTimeInterval(Double(days) * 86_400 + 3600))
    }

    // MARK: The screen

    /// Scrolls whatever is in front (the list, or a sheet over it) until the element can be
    /// tapped. In a sheet only upwards: a pull down at its top would close it.
    @MainActor
    @discardableResult
    func reveal(_ element: XCUIElement, in app: XCUIApplication, sheet: Bool = false,
                file: StaticString = #filePath, line: UInt = #line) -> XCUIElement {
        for i in 0..<12 {
            if element.waitForExistence(timeout: i == 0 ? 8 : 1), element.isHittable { return element }
            if i < 6 { app.swipeUp(velocity: .slow) } else if !sheet { app.swipeDown(velocity: .slow) }
        }
        let seen = app.buttons.allElementsBoundByIndex.prefix(80).map(\.label).filter { !$0.isEmpty }
        add(XCTAttachment(screenshot: app.screenshot()))
        XCTFail("could not reach \(element) (exists: \(element.exists)); buttons on screen: \(seen)", file: file, line: line)
        return element
    }

    /// A task's tick box: a button with the toggle trait, which XCUITest may see as a switch.
    @MainActor
    func box(_ title: String, in app: XCUIApplication) -> XCUIElement {
        let types = [XCUIElement.ElementType.button, .switch, .toggle].map(\.rawValue)
        return app.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@ AND elementType IN %@", title, types)).firstMatch
    }

    /// Whether a tick box says Done (its value is the word, or 1/0 as a switch).
    @MainActor
    func ticked(_ box: XCUIElement) -> Bool? {
        switch box.value as? String {
        case "Done", "1": true
        case "Not done", "0": false
        default: nil
        }
    }

    /// Waits for a tick box to show ticked or not.
    @MainActor
    func expectTicked(_ box: XCUIElement, _ done: Bool, file: StaticString = #filePath, line: UInt = #line) {
        let end = Date().addingTimeInterval(10)
        while Date() < end, ticked(box) != done { RunLoop.current.run(until: Date().addingTimeInterval(0.25)) }
        XCTAssertEqual(ticked(box), done, "value: \(String(describing: box.value))", file: file, line: line)
    }

    /// Any element with this label (a menu's line of text is not always a static text).
    @MainActor
    func anything(_ label: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", label)).firstMatch
    }

    /// Flips a Toggle (a tap on its label does not).
    @MainActor
    func flip(_ toggle: XCUIElement) {
        toggle.expect()
        let inner = toggle.switches.firstMatch
        if inner.exists { inner.tap() } else { toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.93, dy: 0.5)).tap() }
    }

    /// The text field with an accessibility identifier.
    @MainActor
    func field(_ id: String, in app: XCUIApplication) -> XCUIElement {
        let field = app.textFields[id]
        return field.waitForExistence(timeout: 5) ? field : app.textViews[id].expect()
    }

    /// Replaces a field's text: the cursor put at its end, everything deleted, the new typed.
    @MainActor
    func retype(_ field: XCUIElement, _ text: String) {
        field.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        let current = field.value as? String ?? ""
        field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: current.count + 2))
        field.typeText(text)
    }

    /// The button of a confirmation dialog, not the one that opened it.
    @MainActor
    func confirm(_ label: String, in app: XCUIApplication) {
        let inSheet = app.sheets.buttons[label]
        if inSheet.waitForExistence(timeout: 3) { inSheet.tap(); return }
        let all = app.buttons.matching(identifier: label)
        all.element(boundBy: all.count - 1).tap()
    }

    /// Opens the hold menu on a row and picks through it: `["Give to", "Lily"]`.
    @MainActor
    func hold(_ row: XCUIElement, pick path: [String], in app: XCUIApplication) {
        row.press(forDuration: 1.2)
        for label in path {
            app.buttons[label].firstMatch.expect().tap()
        }
    }
}
