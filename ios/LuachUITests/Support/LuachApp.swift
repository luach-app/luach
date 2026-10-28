import XCTest

/// The app, opened signed in to the test server (normally dev) with the run's session.
/// ios/scripts/test.sh passes LUACH_TEST_SERVER and LUACH_TEST_SESSION; without them every
/// UI test is skipped, since there is nothing to sign in to.
///
/// What a UI test may do on that server is what the integration tests may (LuachTests' `Dev`):
/// create only `ios-test…` items, with no one invited, and remove them before it ends.
enum LuachApp {
    private static var env: [String: String] { ProcessInfo.processInfo.environment }

    /// The test server, never the family's: every helper that calls it directly gets nil for prod.
    static var server: String? {
        guard let server = env["LUACH_TEST_SERVER"], !server.isEmpty, !isProduction(server) else { return nil }
        return server
    }

    static var session: String? { env["LUACH_TEST_SESSION"] }

    /// The family's own luach, when the run names it: LUACH_PROD_HOST (test.sh passes the host of
    /// the LUACH_PROD_SERVER setting), or the server of a prod run.
    static var production: String? {
        if let host = env["LUACH_PROD_HOST"], !host.isEmpty { return host.lowercased() }
        return env["LUACH_PROD_SERVER"].flatMap { URL(string: $0)?.host()?.lowercased() }
    }

    static func isProduction(_ server: String) -> Bool {
        guard let production, let host = URL(string: server)?.host()?.lowercased() else { return false }
        return host == production
    }

    /// Launches the app; `arguments` are the app's own launch arguments (`-tab ask`, `-screen booking`).
    @MainActor
    static func launch(_ arguments: [String] = []) throws -> XCUIApplication {
        // These tests create, change and delete things: never on the family's luach.
        if let named = env["LUACH_TEST_SERVER"], isProduction(named) {
            throw XCTSkip("this test writes, and the server is prod")
        }
        guard let server, let session, !session.isEmpty else {
            throw XCTSkip("set LUACH_TEST_SERVER and LUACH_TEST_SESSION (ios/scripts/test.sh does)")
        }
        let app = XCUIApplication()
        // A fresh thread each time: no conversation carried over from the last run. The session
        // goes in the environment: a launch argument shows in `ps` to anyone on the Mac.
        app.launchArguments = ["-server", server, "-thread", ""] + arguments
        app.launchEnvironment["LUACH_SESSION_COOKIE"] = session
        app.launch()
        return app
    }

    /// Opens the conversation list from Ask. A first tap while the keyboard is still up can
    /// only put the keyboard away, so it taps again until the list is there.
    @MainActor
    static func openConversations(_ app: XCUIApplication) {
        for _ in 0..<3 {
            app.buttons["Conversations"].firstMatch.tap()
            if app.navigationBars["Conversations"].waitForExistence(timeout: 5) { return }
        }
        app.navigationBars["Conversations"].expect()
    }

    /// The app signed in to prod for the read-only check (test-prod.sh), with its own variables
    /// so no other test or helper ever sees prod.
    @MainActor
    static func launchProd(_ arguments: [String] = []) throws -> XCUIApplication {
        guard let server = env["LUACH_PROD_SERVER"], URL(string: server)?.host() != nil,
              let session = env["LUACH_PROD_SESSION"], !session.isEmpty else {
            throw XCTSkip("a read-only check against prod: ios/scripts/test-prod.sh")
        }
        let app = XCUIApplication()
        app.launchArguments = ["-server", server, "-thread", ""] + arguments
        app.launchEnvironment["LUACH_SESSION_COOKIE"] = session
        app.launch()
        return app
    }

    static func title(_ what: String) -> String {
        "ios-test \(what) \(UUID().uuidString.prefix(6).lowercased())"
    }

    /// Someone in the test server's family, as `GET /api/family` has them.
    struct Person {
        let key: String
        let name: String
        let email: String
        let kid: Bool
    }

    /// Two of the test server's family for a test to give things to, so no test names anyone
    /// itself: those with no address first (an event of theirs invites nobody), children before
    /// grown-ups, and the two in the family's own order. Fewer only when the family is smaller.
    static func twoPeople() async throws -> [Person] {
        guard let server, let session, !session.isEmpty,
              let url = URL(string: server)?.appending(path: "/api/family") else {
            throw XCTSkip("set LUACH_TEST_SERVER and LUACH_TEST_SESSION (ios/scripts/test.sh does)")
        }
        var req = URLRequest(url: url)
        req.httpShouldHandleCookies = false
        req.setValue("luach_session=\(session)", forHTTPHeaderField: "Cookie")
        let (data, _) = try await URLSession.shared.data(for: req)
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        let family = (json["people"] as? [[String: Any]] ?? []).map {
            Person(key: $0["key"] as? String ?? "", name: $0["name"] as? String ?? "",
                   email: $0["email"] as? String ?? "", kid: $0["kind"] as? String == "kid")
        }.filter { !$0.key.isEmpty && !$0.name.isEmpty }
        let rank = { (p: Person) in (p.email.isEmpty ? 0 : 2) + (p.kid ? 0 : 1) }
        let chosen = Set(family.enumerated().sorted { (rank($0.element), $0.offset) < (rank($1.element), $1.offset) }
            .prefix(2).map(\.offset))
        return family.enumerated().filter { chosen.contains($0.offset) }.map(\.element)
    }
}

extension XCUIElement {
    /// Waits for the element and fails the test, with what was looked for, when it never comes.
    @discardableResult
    func expect(timeout: TimeInterval = 30, file: StaticString = #filePath, line: UInt = #line) -> XCUIElement {
        if !waitForExistence(timeout: timeout) {
            // What was on screen instead, in the log, so a failure says why without a screenshot.
            print("── screen when \(self) never appeared ──\n\(XCUIApplication().debugDescription)")
            XCTFail("never appeared: \(self)", file: file, line: line)
        }
        return self
    }

    /// Waits for the element to go, and says what was still on screen when it does not.
    func expectGone(timeout: TimeInterval = 30, file: StaticString = #filePath, line: UInt = #line) {
        if !waitForNonExistence(timeout: timeout) {
            print("── screen when \(self) never went ──\n\(XCUIApplication().debugDescription)")
            XCTFail("never went: \(self)", file: file, line: line)
        }
    }

    /// Clears a text field and types into it.
    func replaceText(_ text: String) {
        // At the far end, so the deletes below take the whole of what is there.
        coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        if let current = value as? String, !current.isEmpty, current != placeholderValue {
            typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: current.count))
        }
        typeText(text)
    }
}
