import XCTest

/// The rest of the shell, tapped through on the test server: every settings screen opens from
/// the account sheet, the Gmail screen connects and disconnects, Ask's cards and controls, and
/// a luach that cannot be reached.
final class CoreMoreUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    // MARK: Settings

    @MainActor
    func testEverySettingsScreenOpens() throws {
        let app = try LuachApp.launch()
        app.buttons["Account and settings"].firstMatch.expect().tap()
        app.navigationBars["Settings"].expect()
        let screens = ["Profile", "Your email addresses", "Your Gmail", "Also notify", "What luach remembers",
                       "Members", "Household", "Booking page", "Busy calendars", "Reminders",
                       "Passkeys", "Password", "Audit trail", "Delete account"]
        for name in screens {
            let row = app.buttons[name].firstMatch
            var tries = 0
            while !row.isHittable && tries < 6 { app.swipeUp(); tries += 1 }
            row.expect().tap()
            app.navigationBars[name].expect()
            app.navigationBars[name].buttons.element(boundBy: 0).tap()
            app.navigationBars["Settings"].expect()
        }
        // The web app (a link, not a button) and the server line are there too, and Done closes the sheet.
        let web = app.descendants(matching: .any).matching(NSPredicate(format: "label == 'Open the web app'")).firstMatch
        for _ in 0..<6 where !web.isHittable { app.swipeUp() }
        XCTAssertTrue(web.exists, "no link to the web app")
        app.buttons["Done"].firstMatch.tap()
        app.tabBars.firstMatch.expect()
    }

    // MARK: Your Gmail

    /// Connects through the API the way the app's browser sheet ends (dev's stand-in plays Google),
    /// so the screen has an own connection to show and to disconnect.
    private func connectThroughTheStandIn() throws -> Bool {
        guard let server = LuachApp.server, let session = LuachApp.session else { return false }
        func call(_ method: String, _ path: String, follow: Bool = true, body: [String: Any] = [:]) -> (Int, [String: Any]?, String?) {
            var req = URLRequest(url: URL(string: server + path)!)
            req.httpMethod = method
            req.setValue("luach_session=\(session)", forHTTPHeaderField: "Cookie")
            if method != "GET" {
                req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                req.httpBody = try? JSONSerialization.data(withJSONObject: body)
            }
            let done = expectation(description: path)
            var out: (Int, [String: Any]?, String?) = (0, nil, nil)
            let delegate = follow ? nil : NoFollow()
            URLSession(configuration: .ephemeral, delegate: delegate, delegateQueue: nil).dataTask(with: req) { data, response, _ in
                let http = response as? HTTPURLResponse
                out = (http?.statusCode ?? 0, data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] },
                       http?.value(forHTTPHeaderField: "Location"))
                done.fulfill()
            }.resume()
            wait(for: [done], timeout: 30)
            return out
        }
        let (_, status, _) = call("GET", "/api/mail")
        guard status?["can_connect"] as? Bool == true, status?["via"] as? String != "own" else { return false }
        let (_, consent, _) = call("POST", "/api/mail/connect/app")
        guard let url = (consent?["url"] as? String).flatMap(URLComponents.init(string:)),
              let state = url.queryItems?.first(where: { $0.name == "state" })?.value,
              let encoded = state.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed.subtracting(["+", "&", "="]))
        else { return false }
        // The stand-in signs in as whoever the code names: luach connects only the member's own.
        let (_, me, _) = call("GET", "/api/auth/me")
        guard let email = me?["email"] as? String,
              let mailbox = "fixture-code~\(email)".addingPercentEncoding(withAllowedCharacters: .alphanumerics)
        else { return false }
        let (code, _, location) = call("GET", "/api/mail/callback?code=\(mailbox)&state=\(encoded)", follow: false)
        guard code == 302, let back = location.flatMap(URLComponents.init(string:)) else { return false }
        let items = back.queryItems ?? []
        if items.first(where: { $0.name == "mail" })?.value == "connected" { return true }  // a luach from before the nonce
        // The way back carries a one-time nonce, claimed with this member's session as the app does.
        guard let nonce = items.first(where: { $0.name == "nonce" })?.value else { return false }
        let (claimed, _, _) = call("POST", "/api/mail/connect/app/finish", body: ["nonce": nonce])
        return claimed == 200
    }

    @MainActor
    func testGmailConnectedHereIsDisconnectedHere() throws {
        guard try connectThroughTheStandIn() else {
            throw XCTSkip("dev does not offer connecting, or this member's own mailbox is already connected")
        }
        let app = try LuachApp.launch(["-screen", "mailbox"])
        app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'Connected as'")).firstMatch.expect()
        // The scan's switch is offered, but not flipped: even a moment on would let dev's scan
        // read the stand-in's inbox and propose events from it.
        XCTAssertTrue(app.switches.firstMatch.waitForExistence(timeout: 5))
        app.buttons["Disconnect"].firstMatch.expect().tap()
        app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'household mailbox'")).firstMatch.expect()
        app.buttons["Connect my own Gmail"].firstMatch.expect()
    }

    @MainActor
    func testConnectingOpensGooglesSheetAndCancelling() throws {
        let app = try LuachApp.launch(["-screen", "mailbox"])
        let connect = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Connect my'")).firstMatch
        guard connect.waitForExistence(timeout: 20) else { throw XCTSkip("connecting is not offered here") }
        connect.tap()
        // The system asks before a sign-in sheet opens; saying no is a cancel, and nothing is said.
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let cancel = springboard.buttons["Cancel"]
        if cancel.waitForExistence(timeout: 10) { cancel.tap() }
        XCTAssertTrue(connect.waitForExistence(timeout: 10))
        XCTAssertFalse(app.staticTexts["Your email is connected."].exists)
    }

    // MARK: Ask

    @MainActor
    func testAskShowsTheCalendarAsCardsAndTheStepsBehindThem() throws {
        let app = try LuachApp.launch(["-tab", "ask"])
        let tag = LuachApp.title("cards")
        let field = app.textFields.firstMatch.expect()
        field.tap()
        field.typeText("What is on the calendar in September 2026? Also, is Saturday 19 September 2026 at 4pm free? (\(tag))")
        app.buttons["Send"].firstMatch.tap()
        app.buttons["copy"].firstMatch.expect(timeout: 120)
        // The steps fold to one line; opening it shows each.
        let steps = app.buttons.matching(NSPredicate(format: "label ENDSWITH 'steps' OR label ENDSWITH 'step'")).firstMatch.expect()
        steps.tap()
        app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Reading the calendar' OR label BEGINSWITH 'Checking'")).firstMatch.expect()
        app.buttons["copy"].firstMatch.tap()
        app.buttons["copied"].firstMatch.expect()
        tidy(app, tag)
    }

    @MainActor
    func testStoppingAnAnswerSaysSo() throws {
        let app = try LuachApp.launch(["-tab", "ask"])
        let tag = LuachApp.title("stop")
        let field = app.textFields.firstMatch.expect()
        field.tap()
        field.typeText("Write me a long, careful paragraph about planning a family week. (\(tag))")
        app.buttons["Send"].firstMatch.tap()
        app.buttons["Stop"].firstMatch.expect(timeout: 10).tap()
        app.staticTexts["stopped"].firstMatch.expect()
        XCTAssertTrue(app.buttons["Speak"].waitForExistence(timeout: 10) || app.buttons["Send"].exists)
        tidy(app, tag)
    }

    @MainActor
    func testAHoldInTheChatIsDeniedThere() throws {
        let app = try LuachApp.launch(["-tab", "ask"])
        let title = LuachApp.title("past")
        let field = app.textFields.firstMatch.expect()
        field.tap()
        field.typeText("Put \"\(title)\" on the calendar yesterday at 3pm for one hour, for nobody, with no one invited.")
        app.buttons["Send"].firstMatch.tap()
        app.buttons["copy"].firstMatch.expect(timeout: 120)
        let waiting = app.staticTexts["Waiting for a yes"].firstMatch
        guard waiting.waitForExistence(timeout: 5) else {
            tidy(app, title)
            throw XCTSkip("the model did not propose the event, so there was nothing to decide")
        }
        app.buttons["Deny"].firstMatch.tap()
        app.staticTexts["Denied"].firstMatch.expect()
        tidy(app, title)
    }

    /// Deletes the conversation a test left, so dev keeps no trace of it.
    @MainActor
    private func tidy(_ app: XCUIApplication, _ tag: String) {
        LuachApp.openConversations(app)
        let row = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", tag)).firstMatch
        guard row.waitForExistence(timeout: 10) else { return }
        row.swipeLeft()
        app.buttons["Delete"].firstMatch.tap()
        row.expectGone()
        app.buttons["Done"].firstMatch.tap()
    }

    // MARK: Out of reach

    /// Not a dead end: it retries, and offers another address and signing out.
    @MainActor
    func testALuachThatCannotBeReachedSaysSoAndOffersAWayOut() throws {
        guard LuachApp.session != nil else { throw XCTSkip("no test server") }
        let app = XCUIApplication()
        app.launchArguments = ["-server", "https://nothing.invalid", "-sessionCookie", "x"]
        app.launch()
        app.staticTexts["luach is out of reach"].expect()
        app.buttons["Try again"].firstMatch.tap()
        app.staticTexts["luach is out of reach"].expect()

        app.buttons["Use another address"].firstMatch.tap()
        app.staticTexts["Your luach's address"].expect()
        let address = app.textFields["luach.example.com"].expect()
        XCTAssertEqual(address.value as? String, "nothing.invalid", "starts from the one that did not answer")

        app.terminate()
        app.launch()
        app.staticTexts["luach is out of reach"].expect()
        app.buttons["Sign out"].firstMatch.tap()
        app.textFields["Username or email"].expect()
        XCTAssertFalse(app.staticTexts["luach is out of reach"].exists)
    }
}

/// Stops at the first redirect, so a test reads where luach sends the browser.
final class NoFollow: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
