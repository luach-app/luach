import XCTest

/// The Household area's screens, tapped through on the test server (dev). Whatever a test
/// changes through a screen it records first, puts back, and checks; a test that stops
/// half-way is put right in its teardown. The household's calendars and default invitees
/// are never saved: those are ticked and unticked without Save.
final class HouseholdUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    // MARK: Booking page

    @MainActor
    func testBookingEditsAreSeenAsChangesAndUndoneWithoutSaving() throws {
        let original = try HouseholdServer.bookingSettings()
        let app = try LuachApp.launch(["-screen", "booking"])
        app.staticTexts["Your link"].expect()
        let save = app.saveButton.expect()
        XCTAssertFalse(save.isEnabled, "nothing changed yet")

        // The link: copy it.
        app.buttons["Copy link"].expect().tap()
        app.buttons["Copied"].expect(timeout: 5)

        // A switch: Save follows it there and back.
        let live = app.switches["The link is live"].expect()
        let wasLive = live.isOn
        live.flip()
        XCTAssertTrue(live.waitUntil("value == '\(wasLive ? "0" : "1")'"))
        XCTAssertTrue(save.isEnabled)
        live.flip()
        XCTAssertTrue(save.waitUntil("isEnabled == false"))

        // A menu: another length, then the one it was.
        let slot = original["slot_minutes"] as? Int ?? 30
        app.reveal(app.button(startingWith: "Meeting length")).tap()
        app.choose(slot == 45 ? "60 minutes" : "45 minutes")
        XCTAssertTrue(save.waitUntil("isEnabled == true"))
        app.button(startingWith: "Meeting length").tap()
        app.choose("\(slot) minutes")
        XCTAssertTrue(save.waitUntil("isEnabled == false"))

        // The hours: a second window on Monday, then swiped away.
        let hours = original["hours"] as? [String: [[String]]] ?? [:]
        let mondayWindows = hours["mon"]?.count ?? 0
        if mondayWindows > 0 {
            let add = app.reveal(app.buttons["booking.add.mon"])
            add.tap()
            let added = app.element("booking.from.mon.\(mondayWindows)").expect()
            XCTAssertTrue(save.isEnabled, "a new window is a change")
            added.swipeLeft()
            app.buttons["Remove"].firstMatch.expect().tap()
            XCTAssertTrue(added.waitForNonExistence(timeout: 5))
            XCTAssertTrue(save.waitUntil("isEnabled == false"), "back to the saved hours")
        }

        // A day with no hours switched on gets nine to five, and off again.
        if let free = ["sat", "sun"].first(where: { hours[$0]?.isEmpty ?? true }) {
            let name = free == "sat" ? "Saturday" : "Sunday"
            let day = app.reveal(app.switches[name])
            day.flip()
            app.element("booking.from.\(free).0").expect()
            XCTAssertTrue(save.isEnabled)
            app.reveal(app.switches[name]).flip()
            XCTAssertTrue(app.element("booking.from.\(free).0").waitForNonExistence(timeout: 5))
            XCTAssertTrue(save.waitUntil("isEnabled == false"))
        }

        // The page's words: typed, then taken back.
        let location = app.reveal(app.textFields["booking.location"])
        location.retype("ios-test office")
        XCTAssertTrue(save.waitUntil("isEnabled == true"))
        location.retype(original["location"] as? String ?? "")
        XCTAssertTrue(save.waitUntil("isEnabled == false"))

        XCTAssertTrue(HouseholdServer.same(try HouseholdServer.bookingSettings(), original), "nothing was saved")
    }

    @MainActor
    func testBookingSavesAChangeRefusesABadLinkNameAndIsPutBack() throws {
        let original = try HouseholdServer.bookingSettings()
        addTeardownBlock {
            if let now = try? HouseholdServer.bookingSettings(), !HouseholdServer.same(now, original) {
                try? HouseholdServer.call("PATCH", "/api/booking", original)
            }
        }
        let app = try LuachApp.launch(["-screen", "booking", "-householdScroll", "where"])
        let notify = app.switches["Email me when someone books"].expect()
        let save = app.saveButton

        // Saved, read back, and saved back as it was.
        notify.flip()
        XCTAssertTrue(save.waitUntil("isEnabled == true"))
        save.tap()
        app.staticTexts["Saved."].expect()
        XCTAssertFalse(save.isEnabled)
        let changed = try HouseholdServer.bookingSettings()
        XCTAssertEqual(changed["notify_host"] as? Bool, !(original["notify_host"] as? Bool ?? false))
        app.reveal(app.switches["Email me when someone books"], up: false).flip()
        XCTAssertTrue(save.waitUntil("isEnabled == true"))
        save.tap()
        XCTAssertTrue(save.waitUntil("isEnabled == false"))
        app.staticTexts["Saved."].expect()
        XCTAssertTrue(HouseholdServer.same(try HouseholdServer.bookingSettings(), original), "dev's booking page is as it was")

        // A link name luach refuses: its sentence, and nothing stored.
        let slug = app.reveal(app.textFields["booking.slug"], up: false)
        // Not a link name however it lands in the field: nothing can be stored.
        slug.retype("bad name!")
        save.tap()
        // The sentence is at the foot of the form.
        app.reveal(app.staticTexts["the link name is 2-40 chars: letters, digits and dashes"])
        app.reveal(slug, up: false).retype(original["slug"] as? String ?? "")
        XCTAssertEqual(slug.value as? String, original["slug"] as? String)
        XCTAssertTrue(save.waitUntil("isEnabled == false"))
        XCTAssertTrue(HouseholdServer.same(try HouseholdServer.bookingSettings(), original))
    }

    @MainActor
    func testBookingScrollsToItsLowerParts() throws {
        for part in ["hours", "page"] {
            let app = try LuachApp.launch(["-screen", "booking", "-householdScroll", part])
            let landmark = part == "hours" ? app.switches["Monday"] : app.textFields["booking.title"]
            XCTAssertTrue(landmark.waitForExistence(timeout: 15), "\(part) was not shown")
            app.terminate()
        }
    }

    // MARK: Reminders

    @MainActor
    func testRemindersAreChangedSavedAndPutBack() throws {
        let original = try HouseholdServer.reminders()
        addTeardownBlock {
            if let now = try? HouseholdServer.reminders(), !HouseholdServer.same(now, original) {
                try? HouseholdServer.call("PATCH", "/api/reminders", original)
            }
        }
        let app = try LuachApp.launch(["-screen", "reminders"])
        let byEmail = app.switches["Email them to me as well"].expect()
        let save = app.saveButton
        XCTAssertFalse(save.isEnabled)

        // A menu, there and back without saving.
        let days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        let weekly = original["weekly_day"] as? Int ?? -1
        let wasDay = (0..<7).contains(weekly) ? days[weekly] : "Never"
        app.button(startingWith: "The week ahead, on").tap()
        app.choose(wasDay == "Friday" ? "Tuesday" : "Friday")
        XCTAssertTrue(save.waitUntil("isEnabled == true"))
        app.button(startingWith: "The week ahead, on").tap()
        app.choose(wasDay)
        XCTAssertTrue(save.waitUntil("isEnabled == false"))

        // A switch, saved, then saved back.
        byEmail.flip()
        XCTAssertTrue(save.waitUntil("isEnabled == true"))
        save.tap()
        app.staticTexts["Saved."].expect()
        answerNotificationsPrompt()
        XCTAssertEqual(try HouseholdServer.reminders()["by_email"] as? Bool, !(original["by_email"] as? Bool ?? false))
        byEmail.flip()
        XCTAssertTrue(save.waitUntil("isEnabled == true"))
        save.tap()
        XCTAssertTrue(save.waitUntil("isEnabled == false"))
        app.staticTexts["Saved."].expect()
        answerNotificationsPrompt()
        XCTAssertTrue(HouseholdServer.same(try HouseholdServer.reminders(), original), "dev's reminders are as they were")
    }

    // MARK: Busy calendars

    @MainActor
    func testABusyFeedIsAddedChangedReadAndRemoved() throws {
        let before = try HouseholdServer.busyFeeds().count
        addTeardownBlock { try? HouseholdServer.removeTestFeeds() }
        let app = try LuachApp.launch(["-screen", "busy"])
        let name = LuachApp.title("feed")
        app.textFields["busy.name"].expect().retype(name)

        // An address luach will not read: its sentence, and no feed.
        let url = app.textFields["busy.url"].expect()
        url.retype("not a feed")
        app.buttons["Add"].firstMatch.tap()
        app.staticTexts["that is not a calendar feed address"].expect()

        url.retype("https://calendar.google.com/calendar/ical/en.usa%23holiday%40group.v.calendar.google.com/public/basic.ics")
        app.buttons["Add"].firstMatch.tap()
        app.staticTexts[name].expect(timeout: 30)
        XCTAssertTrue(app.staticTexts["that is not a calendar feed address"].waitForNonExistence(timeout: 5))
        XCTAssertEqual(try HouseholdServer.busyFeeds().count, before + 1)

        // Its switches write straight away.
        let agenda = app.switches["Show in the agenda"].firstMatch.expect()
        XCTAssertTrue(agenda.isOn)
        agenda.flip()
        XCTAssertTrue(agenda.waitUntil(timeout: 15, "value == '0'"))
        let feed = try HouseholdServer.busyFeeds().first { $0["name"] as? String == name }
        XCTAssertEqual(feed?["show_in_agenda"] as? Bool, false)

        // Read now, then remove it.
        let readNow = app.reveal(app.buttons["Read them now"])
        readNow.tap()
        XCTAssertTrue(readNow.waitUntil(timeout: 30, "isEnabled == true"))
        let remove = app.reveal(app.buttons["Remove"].firstMatch, up: false)
        app.dialog(from: remove, "Remove").tap()
        XCTAssertTrue(app.staticTexts[name].waitForNonExistence(timeout: 15))
        XCTAssertEqual(try HouseholdServer.busyFeeds().count, before)
    }

    @MainActor
    func testARemovalCanBeKept() throws {
        addTeardownBlock { try? HouseholdServer.removeTestFeeds() }
        let name = LuachApp.title("keep")
        try HouseholdServer.call("POST", "/api/busy", [
            "name": name,
            "url": "https://calendar.google.com/calendar/ical/en.usa%23holiday%40group.v.calendar.google.com/public/basic.ics",
        ])
        let app = try LuachApp.launch(["-screen", "busy"])
        app.staticTexts[name].expect()
        let block = app.switches["Block bookings"].firstMatch.expect()
        block.flip()
        XCTAssertTrue(block.waitUntil(timeout: 15, "value == '0'"))
        let remove = app.reveal(app.buttons["Remove"].firstMatch)
        _ = app.dialog(from: remove, "Remove")
        app.dismissDialog(cancel: "Keep")
        let removes = app.buttons.matching(identifier: "Remove")
        let deadline = Date.now.addingTimeInterval(5)
        while removes.count > 1 && Date.now < deadline { RunLoop.current.run(until: .now + 0.2) }
        XCTAssertEqual(removes.count, 1, "the dialog closed")
        XCTAssertTrue(app.staticTexts[name].exists, "kept")
        XCTAssertTrue(try HouseholdServer.busyFeeds().contains { $0["name"] as? String == name })
    }

    // MARK: Household

    @MainActor
    func testHouseholdCalendarsAndInviteesAreEditedButNeverSaved() throws {
        let original = try HouseholdServer.call("GET", "/api/household")
        let app = try LuachApp.launch(["-screen", "household"])
        let save = app.saveButton.expect()
        let first = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Use '")).firstMatch.expect()
        XCTAssertFalse(save.isEnabled)

        // Ticked and unticked: a change, then none.
        let wasOn = first.isSelected
        first.tap()
        XCTAssertTrue(first.waitUntil("isSelected == \(wasOn ? "false" : "true")"))
        XCTAssertTrue(save.isEnabled)
        first.tap()
        XCTAssertTrue(first.waitUntil("isSelected == \(wasOn ? "true" : "false")"))
        XCTAssertTrue(save.waitUntil("isEnabled == false"))

        // Not an address: said so. An address: listed, then swiped away.
        let invite = app.reveal(app.textFields["household.invite"])
        invite.retype("not-an-address")
        app.buttons["Add"].firstMatch.tap()
        app.staticTexts["That is not an email address."].expect()
        let address = "ios-test-\(UUID().uuidString.prefix(6).lowercased())@example.com"
        invite.retype(address)
        XCTAssertTrue(save.waitUntil("isEnabled == true"), "a whole address is a change")
        app.buttons["Add"].firstMatch.tap()
        let row = app.staticTexts[address].expect()
        row.swipeLeft()
        app.buttons["Delete"].firstMatch.expect().tap()
        XCTAssertTrue(row.waitForNonExistence(timeout: 5))
        XCTAssertTrue(save.waitUntil("isEnabled == false"))

        XCTAssertTrue(HouseholdServer.same(try HouseholdServer.call("GET", "/api/household"), original), "never saved")
    }

    @MainActor
    func testHouseholdLinksToTheFamilyAndTheBoards() throws {
        let app = try LuachApp.launch(["-screen", "household"])
        for link in ["Family", "House boards"] {
            app.reveal(app.buttons[link].firstMatch).tap()
            app.navigationBars[link].expect()
            app.navigationBars.buttons.element(boundBy: 0).tap()
            app.navigationBars["Household"].expect()
        }
    }

    @MainActor
    func testHouseholdOpensASubScreenFromLaunch() throws {
        for (push, title) in [("family", "Family"), ("boards", "House boards")] {
            let app = try LuachApp.launch(["-screen", "household", "-householdPush", push])
            app.navigationBars[title].expect()
            app.terminate()
        }
    }

    /// Saving with a reminder on asks iOS whether luach may notify (once per install): allowed.
    private func answerNotificationsPrompt() {
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
    }

    // MARK: Reminders on this iPhone

    @MainActor
    func testRemindersSayWhatThisPhoneDoes() throws {
        let app = try LuachApp.launch(["-screen", "reminders"])
        app.switches["Email them to me as well"].expect()
        app.swipeUp()
        XCTAssertTrue(app.staticTexts["On this iPhone"].exists || app.staticTexts["ON THIS IPHONE"].exists)
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "worked out from the calendar")).firstMatch.exists)
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Sent to each device")).firstMatch.exists)
    }
}
