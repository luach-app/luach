import XCTest

/// The app on the family's luach, looked at and never changed: it signs in as `ios-test`, opens
/// every tab and every settings screen it may see, and taps nothing that writes.
/// Runs only from ios/scripts/test.sh --prod.
final class ProdUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    @MainActor
    func testEveryTabOpensOnProd() throws {
        let app = try LuachApp.launchProd()
        let bar = app.tabBars.firstMatch.expect()
        XCTAssertEqual(bar.buttons.allElementsBoundByIndex.map(\.label), ["Agenda", "Board", "Approvals", "Ask"])
        for tab in ["Agenda", "Board", "Approvals", "Ask"] {
            bar.buttons[tab].tap()
            XCTAssertTrue(bar.buttons[tab].isSelected)
            // Each tab draws without an error sentence.
            XCTAssertFalse(app.staticTexts["luach is out of reach"].exists)
        }
        app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Hi '")).firstMatch.expect()
    }

    @MainActor
    func testTheMonthAndUpcomingShowOnProd() throws {
        let app = try LuachApp.launchProd(["-agendaMode", "month"])
        app.tabBars.firstMatch.expect()
        app.buttons["Upcoming"].firstMatch.expect().tap()
        app.buttons["Month"].firstMatch.expect().tap()
    }

    @MainActor
    func testEverySettingsScreenAMemberSeesOpensOnProd() throws {
        let app = try LuachApp.launchProd()
        app.buttons["Account and settings"].firstMatch.expect().tap()
        app.navigationBars["Settings"].expect()
        // Not the owner: no Members, Household or Audit trail here.
        XCTAssertFalse(app.buttons["Members"].exists)
        XCTAssertFalse(app.buttons["Audit trail"].exists)
        for name in ["Profile", "Your email addresses", "Your Gmail", "Also notify", "What luach remembers",
                     "Booking page", "Busy calendars", "Reminders", "Passkeys", "Password"] {
            let row = app.buttons[name].firstMatch
            for _ in 0..<6 where !row.isHittable { app.swipeUp() }
            row.expect().tap()
            app.navigationBars[name].expect()
            app.navigationBars[name].buttons.element(boundBy: 0).tap()
            app.navigationBars["Settings"].expect()
        }
        app.buttons["Done"].firstMatch.tap()
    }
}
