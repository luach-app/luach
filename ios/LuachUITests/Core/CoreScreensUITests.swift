import XCTest

/// Sign-in, Approvals and the conversation list, tapped through on the test server.
final class CoreScreensUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    // MARK: Sign-in

    @MainActor
    func testAWrongPasswordIsRefusedInTheServersWords() throws {
        let app = try LuachApp.launch(["-signedOut", "YES"])
        let user = app.textFields["Username or email"].expect()
        let signIn = app.buttons["Sign in"].firstMatch
        XCTAssertFalse(signIn.isEnabled, "nothing typed, nothing to send")
        user.tap()
        user.typeText("ios-test-nobody")
        let password = app.secureTextFields["Password"]
        password.tap()
        password.typeText("not-a-password")
        signIn.tap()
        // The server's sentence, whatever it is, in red under the fields; still on the form.
        let refused = app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] 'password' OR label CONTAINS[c] 'match' OR label CONTAINS[c] 'wait'")).firstMatch
        XCTAssertTrue(refused.waitForExistence(timeout: 15))
        XCTAssertTrue(user.exists)
        XCTAssertFalse(app.tabBars.firstMatch.exists)
    }

    /// The server the app knows is shown under the sign-in; Change asks for an address again, takes
    /// a bare name, checks that it is a luach, and comes back to the sign-in for it.
    @MainActor
    func testChangingTheServerTakesABareName() throws {
        let app = try LuachApp.launch(["-signedOut", "YES"])
        let host = try XCTUnwrap(LuachApp.server.flatMap { URL(string: $0)?.host() })
        app.textFields["Username or email"].expect()
        app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", host)).firstMatch.expect()
        app.buttons["Change"].firstMatch.tap()
        let field = app.textFields["luach.example.com"].expect()
        XCTAssertEqual(field.value as? String, host, "the address so far, to correct")
        XCTAssertFalse(app.textFields["Username or email"].exists, "no password before the address is checked")

        field.replaceText("example.com")
        app.buttons["Continue"].firstMatch.tap()
        let refused = app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] 'not a luach' OR label CONTAINS[c] 'Could not reach'")).firstMatch
        XCTAssertTrue(refused.waitForExistence(timeout: 30), "a web server that is not a luach is turned away")
        XCTAssertFalse(app.textFields["Username or email"].exists)

        field.replaceText(host)
        app.buttons["Continue"].firstMatch.tap()
        app.textFields["Username or email"].expect()
        app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", host)).firstMatch.expect()
    }

    // MARK: Approvals

    /// Makes a hold of our own on the test server: an event yesterday is always held ("past").
    private func makeHold(_ title: String) throws -> Bool {
        guard let server = LuachApp.server, let session = LuachApp.session,
              let url = URL(string: server + "/api/agent") else { return false }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 120
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("luach_session=\(session)", forHTTPHeaderField: "Cookie")
        req.httpBody = try JSONSerialization.data(withJSONObject: [
            "text": "Put \"\(title)\" on the calendar yesterday at 3pm for one hour, for nobody, with no one invited.",
        ])
        let done = expectation(description: "turn")
        var held = false
        var thread: String?
        URLSession.shared.dataTask(with: req) { data, _, _ in
            let reply = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            held = !((reply?["held"] as? [Any]) ?? []).isEmpty
            thread = reply?["thread_id"] as? String
            done.fulfill()
        }.resume()
        wait(for: [done], timeout: 130)
        if let thread, let del = URL(string: server + "/api/threads/\(thread)") {
            var r = URLRequest(url: del)
            r.httpMethod = "DELETE"
            r.setValue("luach_session=\(session)", forHTTPHeaderField: "Cookie")
            URLSession.shared.dataTask(with: r).resume()
        }
        return held
    }

    @MainActor
    func testAHoldIsDeniedFromApprovals() throws {
        let title = LuachApp.title("dentist")
        let app = try LuachApp.launch(["-tab", "approvals"])
        app.tabBars.firstMatch.expect()
        guard try makeHold(title) else {
            throw XCTSkip("the model did not propose the event, so there was no hold to decide")
        }
        app.swipeDown() // pull to refresh
        let card = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", title)).firstMatch
        if !card.waitForExistence(timeout: 10) {
            app.tabBars.buttons["Agenda"].tap()
            app.tabBars.buttons["Approvals"].tap()
        }
        card.expect()
        // The Deny next to our own hold, nobody else's.
        let row = app.cells.containing(.staticText, identifier: card.label).firstMatch
        (row.exists ? row.buttons["Deny"] : app.buttons["Deny"].firstMatch).tap()
        card.expectGone()
    }

    // MARK: Conversations

    @MainActor
    func testAConversationIsRenamedAndDeleted() throws {
        let app = try LuachApp.launch(["-tab", "ask"])
        let field = app.textFields.firstMatch.expect()
        field.tap()
        let tag = LuachApp.title("ready")
        field.typeText("Say the word ready, and nothing else. (\(tag))")
        app.buttons["Send"].firstMatch.tap()
        app.buttons["copy"].firstMatch.expect(timeout: 90)

        LuachApp.openConversations(app)
        let row = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", tag)).firstMatch.expect()
        row.press(forDuration: 1.0)
        app.buttons["Rename"].firstMatch.expect().tap()
        let name = LuachApp.title("chat")
        let title = app.navigationBars["Rename"].expect()
        app.textFields["Title"].firstMatch.expect().replaceText(name)
        app.navigationBars["Rename"].buttons["Save"].tap()
        title.expectGone()
        let renamed = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", name)).firstMatch.expect()

        renamed.swipeLeft()
        app.buttons["Delete"].firstMatch.expect().tap()
        renamed.expectGone()
        app.buttons["Done"].firstMatch.tap()
        // The open conversation was the one deleted: Ask is empty again.
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Hi '")).firstMatch.waitForExistence(timeout: 10))
    }

    @MainActor
    func testNewStartsAnEmptyConversation() throws {
        let app = try LuachApp.launch(["-tab", "ask"])
        let field = app.textFields.firstMatch.expect()
        field.tap()
        let tag = LuachApp.title("ready")
        field.typeText("Say the word ready, and nothing else. (\(tag))")
        app.buttons["Send"].firstMatch.tap()
        app.buttons["copy"].firstMatch.expect(timeout: 90)
        app.buttons["New"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Hi '")).firstMatch.waitForExistence(timeout: 5))
        // Tidy: the conversation it left behind.
        LuachApp.openConversations(app)
        let row = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", tag)).firstMatch.expect()
        row.swipeLeft()
        app.buttons["Delete"].firstMatch.expect().tap()
    }
}
