import XCTest

/// The Agenda tab, tapped through on the test server: Month and Upcoming, changing month,
/// picking a day, and an event made, opened, edited and deleted. Every event a test makes is
/// `ios-test…`, invites nobody, and is swept away in tearDown whatever happened.
final class AgendaUITests: XCTestCase {
    /// Titles to sweep after the test, with a day they sit near.
    private var made: [(title: String, day: String)] = []

    override func setUp() {
        continueAfterFailure = false
    }

    /// Swept off the main actor and waited for here: an async tearDown waiting on the main
    /// actor hung the run.
    override func tearDown() {
        let jobs = made
        made = []
        guard !jobs.isEmpty else { return }
        let swept = expectation(description: "swept")
        Task.detached {
            for (title, day) in jobs { await AgendaDevAPI.sweep(title, around: day) }
            swept.fulfill()
        }
        wait(for: [swept], timeout: 90)
    }

    // MARK: Helpers

    @MainActor private func row(_ app: XCUIApplication, _ title: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", title)).firstMatch
    }

    @MainActor private func text(_ app: XCUIApplication, _ words: String) -> XCUIElement {
        app.staticTexts.matching(NSPredicate(format: "label ==[c] %@", words)).firstMatch
    }

    @MainActor private func monthTitle(_ app: XCUIApplication, _ day: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label == %@", "\(AgendaDevAPI.monthYear(day)), choose month")).firstMatch
    }

    /// Scrolls the screen until `element` can be tapped.
    @MainActor @discardableResult
    private func reach(_ app: XCUIApplication, _ element: XCUIElement, up: Bool = true) -> XCUIElement {
        // The keyboard covers the lower half of a form: put it away first.
        if !(element.exists && element.isHittable), app.keyboards.count > 0 {
            let done = app.keyboards.buttons.matching(NSPredicate(format: "label IN[c] {'done', 'return'}")).firstMatch
            if done.exists { done.tap() }
        }
        for _ in 0..<8 where !(element.exists && element.isHittable) {
            up ? app.swipeUp() : app.swipeDown()
        }
        XCTAssertTrue(element.waitForExistence(timeout: 5) && element.isHittable, "could not reach \(element)")
        return element
    }

    /// A finger dragged from one element to another, as a person swipes.
    @MainActor private func drag(_ from: XCUIElement, to: XCUIElement) {
        let start = from.expect().coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        let end = to.expect().coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .default, thenHoldForDuration: 0)
    }

    /// Turns a SwiftUI toggle in a form on or off.
    @MainActor private func toggle(_ app: XCUIApplication, _ label: String) {
        let sw = app.switches[label].firstMatch.expect()
        let inner = sw.switches.firstMatch
        (inner.exists ? inner : sw).tap()
    }

    /// Chooses `option` in a form's menu picker.
    @MainActor private func choose(_ app: XCUIApplication, _ picker: String, _ option: String) {
        reach(app, app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", picker)).firstMatch).tap()
        app.buttons[option].firstMatch.expect().tap()
    }

    // MARK: Month and Upcoming

    @MainActor
    func testMonthAndUpcomingAreTheTwoViewsAndTheChoiceIsKept() async throws {
        let tz = try await AgendaDevAPI.zone()
        let today = AgendaDevAPI.day(0, in: tz)
        var app = try LuachApp.launch(["-agendaMode", "month"])
        let views = app.segmentedControls.firstMatch.expect()
        XCTAssertEqual(views.buttons.allElementsBoundByIndex.map(\.label), ["Month", "Upcoming"])
        monthTitle(app, today).expect()
        let todayCell = app.buttons["agenda.day.\(today)"].expect()
        XCTAssertTrue(todayCell.isSelected, "the month opens on today")
        text(app, "\(AgendaDevAPI.long(today)) · today").expect()
        // Pulled to refresh, the month stays.
        app.swipeDown()
        monthTitle(app, today).expect()

        views.buttons["Upcoming"].tap()
        let chip = app.buttons["agenda.chip.\(today)"].expect()
        XCTAssertTrue(chip.isSelected)
        XCTAssertTrue(app.buttons["agenda.chip.\(AgendaDevAPI.day(13, in: tz))"].exists, "two weeks of days")
        XCTAssertFalse(app.buttons["agenda.chip.\(AgendaDevAPI.day(14, in: tz))"].exists)
        XCTAssertFalse(app.buttons["agenda.day.\(today)"].exists, "no month grid in Upcoming")
        let comingUp = text(app, "Coming up")
        reach(app, comingUp)
        app.swipeDown()
        app.swipeDown()

        // Remembered across launches.
        app.terminate()
        app = try LuachApp.launch()
        app.buttons["agenda.chip.\(today)"].expect()
        // Away to another tab and back: the agenda reloads, and stays where it was.
        app.tabBars.buttons["Board"].tap()
        app.tabBars.buttons["Agenda"].tap()
        app.buttons["agenda.chip.\(today)"].expect()

        app.segmentedControls.buttons["Month"].tap()
        monthTitle(app, today).expect()
    }

    @MainActor
    func testChangingMonthAndPickingADay() async throws {
        let today = AgendaDevAPI.day(0, in: try await AgendaDevAPI.zone())
        let app = try LuachApp.launch(["-agendaMode", "month", "-agendaDay", "2031-03-12"])
        monthTitle(app, "2031-03-12").expect()
        XCTAssertTrue(app.buttons["agenda.day.2031-03-12"].expect().isSelected)
        text(app, AgendaDevAPI.long("2031-03-12")).expect()

        // A new month opens on its first day.
        app.buttons["Next month"].tap()
        monthTitle(app, "2031-04-01").expect()
        XCTAssertTrue(app.buttons["agenda.day.2031-04-01"].expect().isSelected)
        text(app, AgendaDevAPI.long("2031-04-01")).expect()
        app.buttons["Previous month"].tap()
        app.buttons["Previous month"].tap()
        monthTitle(app, "2031-02-01").expect()

        // A day of the month, then one of the next month's shown in the last row.
        let day = app.buttons["agenda.day.2031-02-17"].expect()
        day.tap()
        XCTAssertTrue(day.isSelected)
        let heading = text(app, AgendaDevAPI.long("2031-02-17")).expect()
        XCTAssertTrue(heading.exists)
        let add = app.buttons["Add something"]
        if add.waitForExistence(timeout: 5) {
            text(app, "Nothing on Monday.").expect()
        }
        app.buttons["agenda.day.2031-03-02"].tap()
        monthTitle(app, "2031-03-02").expect()

        // A drag across the grid changes month.
        drag(app.buttons["agenda.day.2031-03-13"], to: app.buttons["agenda.day.2031-03-10"])
        monthTitle(app, "2031-04-01").expect()
        drag(app.buttons["agenda.day.2031-04-14"], to: app.buttons["agenda.day.2031-04-17"])
        monthTitle(app, "2031-03-01").expect()

        // The title opens a picker of any month of any year.
        monthTitle(app, "2031-03-01").tap()
        app.navigationBars["Go to"].expect()
        let year = app.textFields["agenda.picker.year"].expect()
        XCTAssertEqual(year.value as? String, "2031")
        XCTAssertTrue(app.buttons["agenda.picker.2031-03"].isSelected)
        app.buttons["Next year"].tap()
        XCTAssertEqual(year.value as? String, "2032")
        app.buttons["Previous year"].tap()
        app.buttons["Previous year"].tap()
        XCTAssertEqual(year.value as? String, "2030")
        app.buttons["agenda.picker.2030-11"].tap()
        monthTitle(app, "2030-11-01").expect()
        XCTAssertTrue(app.buttons["agenda.day.2030-11-01"].expect().isSelected)

        // Cancel leaves it.
        monthTitle(app, "2030-11-01").tap()
        app.navigationBars["Go to"].buttons["Cancel"].expect().tap()
        XCTAssertTrue(app.navigationBars["Go to"].waitForNonExistence(timeout: 5))
        monthTitle(app, "2030-11-01").expect()

        // Today brings it back, and then has nothing more to do.
        app.buttons["Today"].tap()
        monthTitle(app, today).expect()
        XCTAssertTrue(app.buttons["agenda.day.\(today)"].expect().isSelected)
        XCTAssertFalse(app.buttons["Today"].isEnabled)
    }

    @MainActor
    func testTheMonthPickerOpensFromItsLaunchArgument() throws {
        // It opens before the launch's day is read: on the year it opened on.
        let app = try LuachApp.launch(["-agendaMode", "month", "-monthPicker", "YES"])
        app.navigationBars["Go to"].expect()
        let year = try XCTUnwrap(app.textFields["agenda.picker.year"].expect().value as? String)
        app.buttons["agenda.picker.\(year)-09"].expect().tap()
        monthTitle(app, "\(year)-09-01").expect()
    }

    // MARK: An event, start to end

    @MainActor
    func testAnEventIsMadeSeenEditedAndDeleted() async throws {
        let tz = try await AgendaDevAPI.zone()
        let day = AgendaDevAPI.day(2, in: tz)
        let title = LuachApp.title("agenda")
        made.append((title, day))

        let app = try LuachApp.launch(["-agendaMode", "month", "-agendaDay", day])
        XCTAssertTrue(app.buttons["agenda.day.\(day)"].expect().isSelected)
        app.buttons["Add event"].firstMatch.expect().tap()
        let bar = app.navigationBars["New event"].expect()
        XCTAssertFalse(app.buttons["Delete event"].exists, "nothing to delete yet")

        let titleField = app.textFields["Title"].expect()
        titleField.tap()
        titleField.typeText(title)

        // For two of the family who have no address (the children): nobody is invited by it.
        let pair = try await LuachApp.twoPeople().filter(\.email.isEmpty)
        let names = pair.map(\.name), keys = pair.map(\.key)
        let one = app.buttons[names.first ?? "-"].firstMatch, other = app.buttons[names.last ?? "-"].firstMatch
        let kids = pair.count == 2 && one.waitForExistence(timeout: 5) && other.exists
        if kids {
            one.tap()
            other.tap()
            XCTAssertTrue(one.isSelected && other.isSelected)
            app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "On \(names[0]) and \(names[1])’s board")).firstMatch.expect()
            // Everyone, then the two again.
            app.buttons["Everyone"].firstMatch.tap()
            XCTAssertFalse(one.isSelected)
            one.tap()
            other.tap()
        }

        reach(app, app.textFields["Location"]).tap()
        app.textFields["Location"].typeText("ios-test place")
        text(app, "Times are in \(tz.identifier).").expect()

        // An address that is not one is refused; one that is becomes a row, and is removed again.
        let invite = reach(app, app.textFields["editor.invite"])
        invite.tap()
        invite.typeText("not-an-address")
        app.buttons["editor.invite.add"].tap()
        text(app, "That is not an email address.").expect()
        invite.replaceText("ios-test-guest@example.com")
        app.buttons["editor.invite.add"].tap()
        let guest = text(app, "ios-test-guest@example.com").expect()
        guest.swipeLeft()
        app.buttons["Delete"].firstMatch.expect().tap()
        XCTAssertTrue(guest.waitForNonExistence(timeout: 5), "the guest is still invited")

        let notes = reach(app, app.descendants(matching: .any)["editor.notes"].firstMatch)
        notes.tap()
        notes.typeText("Bring https://example.com/ios-test")

        bar.buttons["Add"].tap()
        XCTAssertTrue(bar.waitForNonExistence(timeout: 15), "the editor did not close")

        // It is on the day, as the server keeps it.
        row(app, title).expect()
        let saved = try await AgendaDevAPI.find(title, around: day)
        XCTAssertEqual(saved.count, 1)
        let ev = try XCTUnwrap(saved.first)
        XCTAssertEqual(ev.attendees, [], "an event made by a test invites nobody")
        XCTAssertEqual(ev.location, "ios-test place")
        XCTAssertTrue(ev.recurrence.isEmpty && !ev.allDay)
        if kids { XCTAssertEqual(ev.leaders, keys) }
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier == %@ AND label CONTAINS %@",
                                                        "agenda.day.\(day)", "event")).firstMatch.exists,
                      "the day says it has events")

        // In Upcoming too: under its day in Coming up, and on its day.
        app.segmentedControls.buttons["Upcoming"].tap()
        app.buttons["agenda.chip.\(AgendaDevAPI.day(0, in: tz))"].expect().tap()
        let comingUp = app.buttons[AgendaDevAPI.long(day)].firstMatch
        reach(app, comingUp).tap()
        app.swipeDown()
        app.swipeDown()
        XCTAssertTrue(app.buttons["agenda.chip.\(day)"].expect().isSelected)
        row(app, title).expect().tap()

        // Open: what it is, whose, where, the notes.
        app.navigationBars["Event"].expect()
        XCTAssertEqual(app.staticTexts["event.title"].expect().label, title)
        if kids { text(app, "For \(names[0]) and \(names[1])").expect() }
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "ios-test place")).firstMatch.expect()
        app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "Bring https://example.com/ios-test")).firstMatch.expect()

        // Edit: a new title, and all day.
        app.navigationBars["Event"].buttons["Edit"].tap()
        let editBar = app.navigationBars["Edit event"].expect()
        app.textFields["Title"].expect().replaceText("\(title) edited")
        toggle(app, "All day")
        app.datePickers.firstMatch.expect()
        reach(app, text(app, "Everyone here gets a Google Calendar invitation."))
        reach(app, app.textFields["Title"], up: false)
        editBar.buttons["Save"].tap()
        XCTAssertTrue(editBar.waitForNonExistence(timeout: 15), "the editor did not close")
        let edited = row(app, "\(title) edited").expect()
        XCTAssertTrue(edited.label.contains("All day"), edited.label)
        let after = try await AgendaDevAPI.find(title, around: day)
        XCTAssertEqual(after.map(\.title), ["\(title) edited"])
        XCTAssertTrue(after.first?.allDay == true)

        // Deleted from its sheet, once it is sure.
        edited.tap()
        app.navigationBars["Event"].expect()
        reach(app, app.buttons["Delete"].firstMatch).tap()
        app.buttons["Delete for real"].firstMatch.expect().tap()
        XCTAssertTrue(app.navigationBars["Event"].waitForNonExistence(timeout: 15))
        XCTAssertTrue(row(app, "\(title) edited").waitForNonExistence(timeout: 15))
        let (status, _) = try await AgendaDevAPI.event(ev.id)
        XCTAssertEqual(status, 404)
    }

    @MainActor
    func testARowSwipesToEditAndToDelete() async throws {
        let tz = try await AgendaDevAPI.zone()
        let day = AgendaDevAPI.day(3, in: tz)
        let title = LuachApp.title("swipe")
        made.append((title, day))
        let ev = try await AgendaDevAPI.create(title, on: day)

        let app = try LuachApp.launch(["-agendaMode", "month", "-agendaDay", day])
        let listed = row(app, title).expect()

        // Edit from the swipe opens the editor with it; cancel changes nothing.
        listed.swipeLeft()
        app.buttons["Edit"].firstMatch.expect().tap()
        let editBar = app.navigationBars["Edit event"].expect()
        XCTAssertEqual(app.textFields["Title"].expect().value as? String, title)
        editBar.buttons["Cancel"].tap()
        XCTAssertTrue(editBar.waitForNonExistence(timeout: 10))

        // Delete from the swipe asks first.
        row(app, title).swipeLeft()
        app.buttons["Delete"].firstMatch.expect().tap()
        app.staticTexts[title].firstMatch.expect()
        app.buttons["Delete for real"].firstMatch.expect().tap()
        XCTAssertTrue(row(app, title).waitForNonExistence(timeout: 15))
        let (status, _) = try await AgendaDevAPI.event(ev.id)
        XCTAssertEqual(status, 404)
    }

    @MainActor
    func testOneOccurrenceIsChangedOrDeletedAloneOrTheWholeSeries() async throws {
        let tz = try await AgendaDevAPI.zone()
        let day = AgendaDevAPI.day(4, in: tz)
        let title = LuachApp.title("occurrence")
        made.append((title, day))

        // Every day at 10:00 from `day`, as the Repeats menu sends it: the server writes the rule.
        let (status, series) = try await AgendaDevAPI.call("POST", "/api/calendar/events", body: [
            "title": title, "start": "\(day)T10:00", "end": "\(day)T10:30", "recurrence": "daily",
            "attendees": [String](),
        ])
        XCTAssertEqual(status, 200, "\(series)")
        let seriesId = try XCTUnwrap(series["id"] as? String)
        XCTAssertEqual(series["recurrence"] as? [String], ["RRULE:FREQ=DAILY"])
        func on(_ n: Int) async throws -> [AgendaDevAPI.Event] {
            let d = AgendaDevAPI.shift(day, n)
            return try await AgendaDevAPI.events(from: d, to: d).filter { $0.title.hasPrefix(title) }
        }

        // One occurrence renamed, for this event only: the series still repeats, the rest as they were.
        let on1 = try await on(1)
        let second = try XCTUnwrap(on1.first)
        XCTAssertEqual(second.json["occurrence"] as? Bool, true)
        XCTAssertEqual(second.recurrence, ["RRULE:FREQ=DAILY"], "an occurrence carries its series' rule")
        var app = try LuachApp.launch(["-agendaMode", "month", "-agendaDay", AgendaDevAPI.shift(day, 1), "-openEvent", second.id])
        app.navigationBars["Event"].expect().buttons["Edit"].tap()
        let bar = app.navigationBars["Edit event"].expect()
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@ AND label CONTAINS %@", "Repeats", "Every day"))
            .firstMatch.expect()
        app.textFields["Title"].expect().replaceText("\(title) moved")
        bar.buttons["Save"].tap()
        app.buttons["This event"].firstMatch.expect().tap()
        XCTAssertTrue(bar.waitForNonExistence(timeout: 15), "the editor did not close")
        let renamed = try await on(1).map(\.title)
        XCTAssertEqual(renamed, ["\(title) moved"])
        let first = try await on(0).map(\.title)
        let third = try await on(2).map(\.title)
        XCTAssertEqual(first + third, [title, title], "the others are as they were")
        let (_, kept) = try await AgendaDevAPI.event(seriesId)
        XCTAssertEqual(kept.recurrence, ["RRULE:FREQ=DAILY"], "the series still repeats")

        // Another deleted alone, from its sheet.
        let on2 = try await on(2)
        let gone = try XCTUnwrap(on2.first)
        app.terminate()
        app = try LuachApp.launch(["-agendaMode", "month", "-agendaDay", AgendaDevAPI.shift(day, 2), "-openEvent", gone.id])
        app.navigationBars["Event"].expect()
        reach(app, app.buttons["Delete"].firstMatch).tap()
        app.buttons["This event"].firstMatch.expect().tap()
        XCTAssertTrue(app.navigationBars["Event"].waitForNonExistence(timeout: 15))
        let afterDelete = try await on(2)
        XCTAssertTrue(afterDelete.isEmpty, "\(afterDelete.map(\.id))")
        let next = try await on(3).map(\.title)
        XCTAssertEqual(next, [title], "the day after still has it")

        // And then every one, from another.
        let on3 = try await on(3)
        let last = try XCTUnwrap(on3.first)
        app.terminate()
        app = try LuachApp.launch(["-agendaMode", "month", "-agendaDay", AgendaDevAPI.shift(day, 3), "-openEvent", last.id])
        app.navigationBars["Event"].expect()
        reach(app, app.buttons["Delete"].firstMatch).tap()
        app.buttons["All events"].firstMatch.expect().tap()
        XCTAssertTrue(app.navigationBars["Event"].waitForNonExistence(timeout: 15))
        let (status404, _) = try await AgendaDevAPI.event(seriesId)
        XCTAssertEqual(status404, 404)
    }

    @MainActor
    func testARepeatIsChosenChangedForTheSeriesAndTheSeriesDeleted() async throws {
        let tz = try await AgendaDevAPI.zone()
        let day = AgendaDevAPI.day(4, in: tz)
        let title = LuachApp.title("repeat")
        made.append((title, day))

        // Made weekly in the editor.
        var app = try LuachApp.launch(["-agendaMode", "month", "-agendaDay", day])
        app.buttons["Add event"].firstMatch.expect().tap()
        let bar = app.navigationBars["New event"].expect()
        app.textFields["Title"].expect().tap()
        app.textFields["Title"].typeText(title)
        // The keyboard away first, as a person would: a row half under it can be found but not tapped.
        app.textFields["Title"].typeText("\n")
        choose(app, "Repeats", "Every week")
        bar.buttons["Add"].tap()
        XCTAssertTrue(bar.waitForNonExistence(timeout: 15))

        // An occurrence opens, and closes with Done.
        row(app, title).expect().tap()
        app.navigationBars["Event"].expect()
        XCTAssertEqual(app.staticTexts["event.title"].expect().label, title)
        app.navigationBars["Event"].buttons["Done"].tap()
        XCTAssertTrue(app.navigationBars["Event"].waitForNonExistence(timeout: 10))

        let found = try await AgendaDevAPI.find(title, around: day)
        let series = try XCTUnwrap(found.first?.series)
        let (_, master) = try await AgendaDevAPI.event(series)
        XCTAssertEqual(master.recurrence.count, 1)
        XCTAssertTrue(master.recurrence.first?.contains("FREQ=WEEKLY") == true, "\(master.recurrence)")
        XCTAssertEqual(master.attendees, [])

        // The series itself, in the editor: every two weeks now.
        app.terminate()
        app = try LuachApp.launch(["-agendaMode", "month", "-agendaDay", day, "-editEvent", series])
        let editBar = app.navigationBars["Edit event"].expect()
        reach(app, text(app, "Changing this changes every occurrence, past and future."))
        choose(app, "Repeats", "Every two weeks")
        editBar.buttons["Save"].tap()
        XCTAssertTrue(editBar.waitForNonExistence(timeout: 15))
        let (_, biweekly) = try await AgendaDevAPI.event(series)
        XCTAssertTrue(biweekly.recurrence.first?.contains("INTERVAL=2") == true, "\(biweekly.recurrence)")

        // Opened, it says so in words; deleted from its editor, the whole series goes.
        app.terminate()
        app = try LuachApp.launch(["-agendaMode", "month", "-agendaDay", day, "-openEvent", series])
        app.navigationBars["Event"].expect()
        text(app, "Every 2 weeks on \(AgendaDevAPI.weekday(day))").expect()
        app.navigationBars["Event"].buttons["Edit"].tap()
        let again = app.navigationBars["Edit event"].expect()
        reach(app, app.buttons["Delete event"]).tap()
        app.buttons["Delete for real"].firstMatch.expect().tap()
        XCTAssertTrue(again.waitForNonExistence(timeout: 15))
        let (status, _) = try await AgendaDevAPI.event(series)
        XCTAssertEqual(status, 404)
        XCTAssertTrue(row(app, title).waitForNonExistence(timeout: 15))
    }
}
