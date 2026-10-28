import XCTest

/// The You screens tapped through on dev. Nothing here saves a setting, sends mail, or
/// touches anyone but the `ios-test…` child and fact each test makes and removes.
final class YouUITests: XCTestCase {
    /// The random token in what a test made, removed through the API should the test stop
    /// before removing it.
    private var person: String?
    private var fact: String?

    override func setUp() {
        continueAfterFailure = false
    }

    override func tearDown() {
        if let person { YouDevCleanup.removePeople(token: person) }
        if let fact { YouDevCleanup.forgetFacts(token: fact) }
    }

    /// The made thing's title and its random token.
    private func title(_ what: String) -> (title: String, token: String) {
        let title = LuachApp.title(what)
        return (title, String(title.split(separator: " ").last ?? ""))
    }

    private func zoneAndLanguage() -> (zone: String, language: String) {
        let me = YouDevCleanup.me()
        return ((me["timezone"] as? String) ?? "UTC", (me["language"] as? String) ?? "auto")
    }

    private static let languageLabels = ["auto": "Automatic", "en": "English", "es": "Español", "he": "עברית"]

    // MARK: Profile

    @MainActor
    func testProfileZoneSearchLanguageAndModelWithoutSaving() throws {
        let (zone, language) = zoneAndLanguage()
        let app = try LuachApp.launch(["-screen", "profile"])
        app.textFields["profile.displayName"].expect()
        let save = app.buttons["profile.save"].expect()
        XCTAssertFalse(save.isEnabled, "nothing changed yet")

        // The time zone list: search finds a zone by its city, typed with a space.
        app.buttons["profile.timezone"].tap()
        let search = app.searchFields.firstMatch.expect()
        search.tap()
        search.typeText("new york")
        app.buttons["zone.America/New_York"].expect()
        XCTAssertFalse(app.buttons["zone.Europe/London"].exists, "the search filters")
        let other = zone == "Asia/Jerusalem" ? ("tokyo", "Asia/Tokyo") : ("jerusalem", "Asia/Jerusalem")
        search.replaceText(other.0)
        pick(app, zone: other.1)
        XCTAssertTrue(save.waitForEnabled(true), "another zone is a change")
        // …and back to the saved one: no change left to save.
        app.buttons["profile.timezone"].expect().tap()
        let again = app.searchFields.firstMatch.expect()
        again.tap()
        again.typeText(String(zone.split(separator: "/").last ?? "").replacingOccurrences(of: "_", with: " "))
        pick(app, zone: zone)
        XCTAssertTrue(save.waitForEnabled(false))

        // The language: another one, then the saved one again.
        let saved = Self.languageLabels[language] ?? "Automatic"
        let another = language == "en" ? "Español" : "English"
        app.buttons["profile.language"].expect().tap()
        app.buttons[another].expect().tap()
        XCTAssertTrue(save.waitForEnabled(true))
        app.buttons["profile.language"].expect().tap()
        app.buttons[saved].expect().tap()
        XCTAssertTrue(save.waitForEnabled(false))

        // The model: the ticked one is the saved pick; another, then that one again.
        let rows = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'model.'"))
        if !rows.firstMatch.waitForExistence(timeout: 5) { app.swipeUp() }
        if rows.count > 1 {
            let ticked = rows.allElementsBoundByIndex.first { $0.isSelected } ?? rows.element(boundBy: 0)
            let id = ticked.identifier
            XCTAssertTrue(rows.allElementsBoundByIndex.contains { $0.label.contains("(default)") }, "the default says so")
            let different = rows.allElementsBoundByIndex.first { $0.identifier != id }!
            different.tap()
            // A model outside the house asks first, saying what goes where.
            let ask = app.alerts.firstMatch
            if ask.waitForExistence(timeout: 3) {
                XCTAssertTrue(ask.label.hasPrefix("Send your questions to"))
                ask.buttons.element(boundBy: 0).tap()
            }
            XCTAssertTrue(save.waitForEnabled(true))
            app.buttons[id].tap()
            XCTAssertTrue(save.waitForEnabled(false), "the saved model again")
        }

        // The display name: an edit, undone.
        let name = app.textFields["profile.displayName"]
        if !name.isHittable { app.swipeDown() }
        name.tap()
        name.typeText("x")
        XCTAssertTrue(save.waitForEnabled(true))
        name.typeText(XCUIKeyboardKey.delete.rawValue)
        XCTAssertTrue(save.waitForEnabled(false))
    }

    /// Taps a zone in the list and waits to be back on Profile. With the search keyboard up,
    /// a first tap can go to putting the keyboard away; then the zone is tapped again.
    @MainActor
    private func pick(_ app: XCUIApplication, zone: String) {
        let row = app.buttons["zone.\(zone)"].expect()
        row.tap()
        if !app.navigationBars["Profile"].waitForExistence(timeout: 3), row.exists { row.tap() }
        app.navigationBars["Profile"].expect()
        let shown = app.buttons["profile.timezone"]
        let said = "\(shown.label) \((shown.value as? String) ?? "")"
        XCTAssertTrue(said.contains(zone) || app.staticTexts[zone].exists, "the zone shows on Profile: \(said)")
    }

    @MainActor
    func testTheZoneListOpensByLaunchArgument() throws {
        let app = try LuachApp.launch(["-screen", "profile", "-youPush", "timezone"])
        app.searchFields.firstMatch.expect()
        app.navigationBars["Time zone"].expect()
    }

    // MARK: Addresses and Also notify

    @MainActor
    func testAddressesListThePrimaryWithoutChangingThem() throws {
        let app = try LuachApp.launch(["-screen", "emails"])
        app.staticTexts["primary"].expect()
        let draft = app.textFields["emails.draft"].expect()
        let add = app.buttons["emails.add"]
        XCTAssertFalse(add.isEnabled)
        draft.tap()
        draft.typeText("ios-test@example.com")
        XCTAssertTrue(add.waitForEnabled(true), "typed: Add is offered (and not pressed)")
        draft.replaceText("")
        XCTAssertTrue(add.waitForEnabled(false))
        // Another address's actions open, and close without choosing one.
        let actions = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Actions for'")).firstMatch
        if actions.waitForExistence(timeout: 3) {
            actions.tap()
            app.buttons["Make primary"].expect()
            app.navigationBars.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
            XCTAssertTrue(app.buttons["Make primary"].waitForNonExistence(timeout: 5))
        }
    }

    @MainActor
    func testAlsoNotifyRowsAreCheckedAndNeverSaved() throws {
        let app = try LuachApp.launch(["-screen", "notify"])
        let draft = app.textFields["notify.draft"].expect()
        let save = app.buttons["notify.save"].expect()
        let wasEnabled = save.isEnabled
        XCTAssertFalse(wasEnabled, "nothing changed yet")
        draft.tap()
        draft.typeText("not an address\n")
        app.staticTexts["That is not an email address."].expect()
        let address = "ios-test-\(UUID().uuidString.prefix(6).lowercased())@example.com"
        draft.replaceText("  \(address.uppercased()) \n")
        let row = app.staticTexts[address].expect()
        XCTAssertTrue(save.waitForEnabled(true), "a new row is a change")
        // Swiped away again: the list is as saved, and Save never pressed.
        row.swipeLeft()
        app.buttons["Delete"].expect().tap()
        XCTAssertTrue(row.waitForNonExistence(timeout: 5))
        XCTAssertTrue(save.waitForEnabled(false))
    }

    // MARK: Memory

    @MainActor
    func testMemoryKeepsAFactAndForgetsIt() throws {
        let (text, token) = title("fact")
        fact = token
        let app = try LuachApp.launch(["-screen", "memory"])
        let draft = app.textFields["memory.draft"].expect()
        let keep = app.buttons["memory.keep"]
        XCTAssertFalse(keep.isEnabled)
        draft.tap()
        draft.typeText(text)
        keep.expect().tap()
        let row = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", token)).firstMatch
        row.expect(timeout: 20)
        XCTAssertTrue(keep.waitForEnabled(false), "the draft is cleared")
        row.swipeLeft()
        app.buttons["Forget"].expect().tap()
        XCTAssertTrue(row.waitForNonExistence(timeout: 15))
    }

    // MARK: Family

    @MainActor
    func testFamilyAddsAChildChangesTheirColourAndRemovesThem() throws {
        let (typed, token) = title("child")
        person = token
        // As a person gets there: Members, then Family.
        let app = try LuachApp.launch(["-screen", "members"])
        app.buttons["Family"].expect().tap()
        app.navigationBars["Family"].expect()
        let field = app.textFields["family.name"].expect()
        field.tap()
        field.typeText(typed)
        let kid = app.switches["family.kid"].expect()
        // The switch itself, at the row's trailing end (the row's middle is its label).
        kid.coordinate(withNormalizedOffset: CGVector(dx: 0.92, dy: 0.5)).tap()
        if kid.value as? String != "1" { kid.switches.firstMatch.tap() }
        XCTAssertEqual(kid.value as? String, "1", "a child")
        app.buttons["family.add"].tap()
        let row = app.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@", token)).firstMatch.expect(timeout: 20)
        XCTAssertTrue(row.label.hasSuffix(", child"), "listed as a child: \(row.label)")
        // As dev named them (the keyboard may have autocorrected what was typed).
        let made = try XCTUnwrap(YouDevCleanup.person(token: token), "not on dev")
        let name = made.name
        XCTAssertEqual(made.kind, "kid")

        // Open them, change the colour, and remove them.
        row.tap()
        app.navigationBars[name].expect()
        let colours = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'colour.'"))
        colours.firstMatch.expect()
        let next = try XCTUnwrap(colours.allElementsBoundByIndex.first { !$0.isSelected })
        let picked = next.identifier
        next.tap()
        XCTAssertTrue(app.buttons[picked].waitForSelected(), "the colour picked is ticked")
        app.buttons["person.remove"].expect().tap()
        let confirm = app.buttons.matching(NSPredicate(format: "label == %@ AND identifier != 'person.remove'", "Remove \(name)")).firstMatch
        confirm.expect().tap()
        app.navigationBars["Family"].expect()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@", token)).firstMatch.waitForNonExistence(timeout: 15))
        XCTAssertNil(YouDevCleanup.person(token: token), "removed on dev too")
        app.navigationBars.buttons.element(boundBy: 0).tap()
        app.navigationBars["Members"].expect()
    }

    @MainActor
    func testAPersonOpensByLaunchArgument() throws {
        // A child already in dev's family, only looked at.
        let child = try XCTUnwrap(YouDevCleanup.people().first { $0.kind == "kid" && !$0.name.lowercased().hasPrefix("ios-test") })
        let app = try LuachApp.launch(["-screen", "members", "-youPush", "family", "-youPerson", child.key])
        app.navigationBars[child.name].expect()
        app.buttons["person.remove"].expect()
    }

    // MARK: Members, boards

    @MainActor
    func testMembersListTheHouseholdAndInviteNoOne() throws {
        let app = try LuachApp.launch(["-screen", "members"])
        app.staticTexts["owner"].expect()
        app.buttons["Family"].expect()
        app.buttons["House boards"].expect()
        let invite = app.textFields["members.invite"].expect()
        let send = app.buttons["Send invitation"]
        XCTAssertFalse(send.isEnabled)
        invite.tap()
        invite.typeText("ios-test@example.com")
        XCTAssertTrue(send.waitForEnabled(true), "typed: Send is offered (and not pressed)")
        invite.replaceText("")
        XCTAssertTrue(send.waitForEnabled(false))
        // Into the boards by tapping, and back.
        app.buttons["House boards"].tap()
        app.navigationBars["House boards"].expect()
        app.navigationBars.buttons.element(boundBy: 0).tap()
        app.navigationBars["Members"].expect()
    }

    @MainActor
    func testHouseBoardsTakeACodeInCapitalsWithoutPairing() throws {
        let app = try LuachApp.launch(["-screen", "members", "-youPush", "boards"])
        app.navigationBars["House boards"].expect()
        let code = app.textFields["boards.code"].expect()
        let pair = app.buttons["boards.pair"]
        XCTAssertFalse(pair.isEnabled)
        code.tap()
        // A key at a time: the field turns each into a capital as it comes.
        for key in ["k", "7", "p"] { code.typeText(key) }
        XCTAssertEqual(code.value as? String, "K7P")
        XCTAssertTrue(pair.waitForEnabled(true), "a code: Pair is offered (and not pressed)")
        code.replaceText("")
        XCTAssertTrue(pair.waitForEnabled(false))
    }

    // MARK: Security

    @MainActor
    func testAuditTrailVerifiesAndAnEntryOpens() throws {
        let app = try LuachApp.launch(["-screen", "audit"])
        let chain = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS 'verified ✓' OR label CONTAINS 'broken ✗'")).firstMatch
        chain.expect(timeout: 20)
        XCTAssertTrue(chain.label.contains("verified ✓"), "dev's chain verifies: \(chain.label)")
        let entries = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'audit.'"))
        let first = entries.firstMatch.expect()
        first.tap()
        app.staticTexts["Payload"].expect()
        app.staticTexts["Hash"].expect()
        app.navigationBars.buttons.element(boundBy: 0).tap()
        first.expect()
        // Older entries, at the bottom.
        let older = app.buttons["Show older"]
        for _ in 0..<25 where !older.exists { app.swipeUp() }
        if older.exists {
            older.tap()
            // The count is in the chain's footer, back at the top of a now longer list.
            let footer = app.staticTexts.matching(NSPredicate(format: "label ENDSWITH 'showing the last 100'")).firstMatch
            for _ in 0..<30 where !footer.waitForExistence(timeout: 1) { app.swipeDown() }
            XCTAssertTrue(footer.exists, "fifty more entries")
        }
    }

    @MainActor
    func testPasswordFormChecksBeforeSending() throws {
        let app = try LuachApp.launch(["-screen", "password"])
        let current = app.secureTextFields["password.current"].expect()
        let next = app.secureTextFields["password.new"]
        let repeated = app.secureTextFields["password.repeat"]
        let submit = app.buttons["password.submit"]
        XCTAssertFalse(submit.isEnabled)
        current.tap()
        current.typeText("not-the-password")
        next.tap()
        next.typeText("ios-test-one")
        repeated.tap()
        repeated.typeText("ios-test-two")
        submit.tap()
        app.staticTexts["The two new passwords do not match."].expect()
        // Matching but short: still refused by the form, nothing sent.
        next.replaceText("short")
        repeated.replaceText("short")
        submit.tap()
        app.staticTexts["The new password must be at least 8 characters."].expect()
    }

    @MainActor
    func testPasskeysListOrSayNone() throws {
        let app = try LuachApp.launch(["-screen", "passkeys"])
        app.descendants(matching: .any).matching(NSPredicate(format: "label == 'Add a passkey'")).firstMatch.expect()
        let none = app.staticTexts["No passkeys yet."]
        let rows = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Added '")).firstMatch
        XCTAssertTrue(none.waitForExistence(timeout: 15) || rows.exists, "the list, or that there is none")
    }
}

extension XCUIElement {
    /// Waits until the element is (or is not) enabled.
    func waitForEnabled(_ enabled: Bool, timeout: TimeInterval = 5) -> Bool {
        let done = XCTNSPredicateExpectation(predicate: NSPredicate(format: "isEnabled == %@", NSNumber(value: enabled)), object: self)
        return XCTWaiter().wait(for: [done], timeout: timeout) == .completed
    }

    /// Waits until the element is selected.
    func waitForSelected(timeout: TimeInterval = 10) -> Bool {
        let done = XCTNSPredicateExpectation(predicate: NSPredicate(format: "isSelected == true"), object: self)
        return XCTWaiter().wait(for: [done], timeout: timeout) == .completed
    }
}
