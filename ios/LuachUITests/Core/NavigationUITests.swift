import XCTest

/// The shell of the app, tapped through on the test server: the tabs in the web's order,
/// the account sheet with the web's sections, and a conversation with the real agent.
final class NavigationUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    @MainActor
    func testTheTabsAreTheWebsInItsOrder() throws {
        let app = try LuachApp.launch()
        let bar = app.tabBars.firstMatch.expect()
        XCTAssertEqual(bar.buttons.allElementsBoundByIndex.map(\.label), ["Agenda", "Board", "Approvals", "Ask"])
        for tab in ["Board", "Approvals", "Ask", "Agenda"] {
            bar.buttons[tab].tap()
            XCTAssertTrue(bar.buttons[tab].isSelected, "\(tab) did not open")
        }
    }

    @MainActor
    func testSettingsHasTheWebsSections() throws {
        let app = try LuachApp.launch()
        app.buttons["Account and settings"].firstMatch.expect().tap()
        app.navigationBars["Settings"].expect()
        // Into a screen and back, while Profile is still at the top of the list.
        app.buttons["Profile"].firstMatch.expect().tap()
        app.navigationBars["Profile"].expect()
        app.navigationBars.buttons.element(boundBy: 0).tap()
        app.navigationBars["Settings"].expect()
        for row in ["Your Gmail", "Booking page", "Reminders", "Passkeys"] {
            let cell = app.buttons[row].firstMatch
            if !cell.exists { app.swipeUp() }
            XCTAssertTrue(cell.waitForExistence(timeout: 5), "no \(row) in Settings")
        }
        app.buttons["Done"].firstMatch.tap()
        XCTAssertTrue(app.tabBars.firstMatch.waitForExistence(timeout: 5))
    }

    @MainActor
    func testAskingAnswersWithTheModelUnderneath() throws {
        let app = try LuachApp.launch(["-tab", "ask"])
        let field = app.textFields.firstMatch.expect()
        field.tap()
        let tag = LuachApp.title("ready")
        field.typeText("Say the word ready, and nothing else. (\(tag))")
        app.buttons["Send"].firstMatch.expect().tap()
        // The footer's copy button is there once the answer is complete.
        app.buttons["copy"].firstMatch.expect(timeout: 90)
        // The conversation list shows it; delete it so dev keeps no trace of the test.
        LuachApp.openConversations(app)
        let row = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", tag)).firstMatch.expect()
        row.swipeLeft()
        app.buttons["Delete"].firstMatch.expect().tap()
        row.expectGone()
        XCTAssertTrue(app.navigationBars["Conversations"].exists, "the list stays open after a delete")
    }
}
