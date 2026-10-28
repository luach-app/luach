import XCTest

/// The Board tab, tapped through on dev: paging days, ticking, adding and changing tasks, the
/// hold menu with Undo. Each test makes its own `ios-test…` items and the tear-down removes them.
final class BoardUITests: BoardUITestCase {
    private let everyDay = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

    @MainActor
    private func board(_ more: [String] = []) throws -> XCUIApplication {
        let app = try LuachApp.launch(["-tab", "board"] + more)
        app.navigationBars.firstMatch.expect()
        return app
    }

    @MainActor
    private func selected(_ element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        let done = NSPredicate(format: "isSelected == true")
        let end = Date().addingTimeInterval(10)
        while Date() < end, !done.evaluate(with: element) { RunLoop.current.run(until: Date().addingTimeInterval(0.25)) }
        XCTAssertTrue(element.isSelected, "not selected: \(element)", file: file, line: line)
    }


    @MainActor
    private func toTop(_ app: XCUIApplication) {
        let next = app.buttons["Next day"]
        for _ in 0..<6 where !(next.exists && next.isHittable) { app.collectionViews.firstMatch.swipeDown() }
    }

    /// A day as the app writes it in full: "Thursday, October 29".
    private func long(_ iso: String) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd"
        var style = Date.FormatStyle.dateTime.weekday(.wide).month(.wide).day()
        style.timeZone = TimeZone(identifier: "UTC")!
        return (f.date(from: iso)?.addingTimeInterval(12 * 3600) ?? Date()).formatted(style)
    }

    @MainActor
    private func dismissMenu(_ app: XCUIApplication) {
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.06)).tap()
    }

    // MARK: Paging

    @MainActor
    func testPagingDaysWithTheArrowsAndTheChips() async throws {
        let today = try await self.today()
        let app = try board()
        app.navigationBars["Today"].expect()
        selected(app.buttons["chip-\(today)"])
        XCTAssertFalse(app.buttons["Previous day"].isEnabled, "nothing before today")
        XCTAssertFalse(app.buttons["Back to today"].exists)

        app.buttons["Next day"].tap()
        app.navigationBars["Tomorrow"].expect()
        selected(app.buttons["chip-\(add(today, 1))"])
        app.buttons["Back to today"].expect()
        app.buttons["Next day"].tap()
        selected(app.buttons["chip-\(add(today, 2))"])
        app.buttons["Previous day"].tap()
        app.navigationBars["Tomorrow"].expect()
        app.buttons["Back to today"].tap()
        app.navigationBars["Today"].expect()

        // Straight to a day by its chip, and back by today's.
        app.buttons["chip-\(add(today, 3))"].expect().tap()
        selected(app.buttons["chip-\(add(today, 3))"])
        app.buttons["chip-\(today)"].tap()
        app.navigationBars["Today"].expect()
        app.buttons["Tomorrow"].firstMatch.tap()
        app.navigationBars["Tomorrow"].expect()
    }

    @MainActor
    func testTheLastDayHasNoNextAndAPageCanBeOpenedAtLaunch() async throws {
        let today = try await self.today()
        let app = try board(["-boardDay", "30"])
        selected(app.buttons["chip-\(add(today, 30))"])
        XCTAssertFalse(app.buttons["Next day"].isEnabled, "the board pages 30 days ahead, no more")
        XCTAssertTrue(app.buttons["Previous day"].isEnabled)
        app.buttons["Previous day"].tap()
        selected(app.buttons["chip-\(add(today, 29))"])
        app.buttons["Back to today"].tap()
        app.navigationBars["Today"].expect()
    }

    // MARK: Ticking

    @MainActor
    func testTickingAndUntickingTodayAndOnALaterDay() async throws {
        let (first, second) = try await twoPeople()
        let today = try await self.today()
        let tomorrow = add(today, 1)
        let todo = title("tick")
        let todoID = try await addTask(todo, person: first.key)
        let chore = title("tick chore")
        let choreID = try await addTask(chore, person: second.key, days: everyDay)

        let app = try board()
        let todoBox = reveal(box(todo, in: app), in: app)
        XCTAssertEqual(ticked(todoBox), false)
        todoBox.tap()
        expectTicked(todoBox, true)
        try await eventually("\(todo) ticked") { try await task(todoID)?["done"] as? Bool == true }
        todoBox.tap()
        expectTicked(todoBox, false)
        try await eventually("\(todo) unticked") { try await task(todoID)?["done"] as? Bool == false }

        // A chore on tomorrow's page is ticked for tomorrow, not for today.
        toTop(app)
        app.buttons["Next day"].tap()
        app.navigationBars["Tomorrow"].expect()
        let choreBox = reveal(box(chore, in: app), in: app)
        choreBox.tap()
        expectTicked(choreBox, true)
        try await eventually("\(chore) ticked for tomorrow") { try await task(choreID, on: tomorrow)?["done"] as? Bool == true }
        let todays = try await task(choreID, on: today)
        XCTAssertEqual(todays?["done"] as? Bool, false)
        choreBox.tap()
        expectTicked(choreBox, false)
        try await eventually("\(chore) unticked for tomorrow") { try await task(choreID, on: tomorrow)?["done"] as? Bool == false }
    }

    // MARK: Adding

    @MainActor
    func testAddingAChoreFromAPersonsPlus() async throws {
        let (first, _) = try await twoPeople()
        let name = title("added chore")
        let app = try board()
        reveal(app.buttons["Add for \(first.name)"], in: app).tap()
        app.buttons["Task"].firstMatch.expect().tap()
        app.navigationBars["A task for \(first.name)"].expect()
        selected(app.buttons[first.name])

        app.buttons["Add task"].tap()
        app.staticTexts["Give it a name."].expect()

        flip(app.switches["A chore that repeats"])
        XCTAssertFalse(app.switches["Due date"].exists, "a chore has days, not a due date")
        // Picked and unpicked; then Wednesday before Monday, sent in the week's order.
        app.buttons["Friday"].expect().tap()
        selected(app.buttons["Friday"])
        app.buttons["Friday"].tap()
        XCTAssertFalse(app.buttons["Friday"].isSelected)

        let titleField = field("task-title", in: app)
        titleField.tap()
        titleField.typeText(name)
        app.buttons["Add task"].tap()
        app.staticTexts["Pick the days it falls on."].expect()

        // The keyboard is up now: the form is scrolled to them.
        reveal(app.buttons["Wednesday"], in: app, sheet: true).tap()
        reveal(app.buttons["Monday"], in: app, sheet: true).tap()
        app.buttons["Add task"].tap()
        XCTAssertTrue(app.navigationBars["A task for \(first.name)"].waitForNonExistence(timeout: 10))

        try await eventually("\(name) on dev") {
            let found = try await tasks(titled: name)
            guard let t = found.first else { return false }
            return found.count == 1 && t["person"] as? String == first.key && t["days"] as? [String] == ["MO", "WE"]
                && t["chore"] as? Bool == true
        }
    }

    @MainActor
    func testAddingADatedTaskForTheFamilyAndOpeningTheEventEditor() async throws {
        let (_, second) = try await twoPeople()
        let name = title("dated")
        let app = try board()
        // The + also offers an event: the Agenda's editor opens, and is left.
        reveal(app.buttons["Add for \(second.name)"], in: app).tap()
        app.buttons["Event"].firstMatch.expect().tap()
        app.buttons["Cancel"].firstMatch.expect().tap()
        XCTAssertTrue(app.buttons["Cancel"].waitForNonExistence(timeout: 10))

        reveal(app.buttons["Add for the family"], in: app).tap()
        app.buttons["Task"].firstMatch.expect().tap()
        app.navigationBars["A task"].expect()
        selected(app.buttons["Anyone"])
        app.staticTexts["Without a date it shows at once, until someone ticks it."].expect()
        flip(app.switches["Due date"])
        app.datePickers.firstMatch.expect()
        XCTAssertFalse(app.staticTexts["Without a date it shows at once, until someone ticks it."].exists)
        let titleField = field("task-title", in: app)
        titleField.tap()
        titleField.typeText(name)
        app.buttons["Add task"].tap()
        XCTAssertTrue(app.navigationBars["A task"].waitForNonExistence(timeout: 10))

        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        let phoneToday = f.string(from: Date())
        try await eventually("\(name) due today") {
            let t = try await tasks(titled: name).first
            return t?["due"] as? String == phoneToday && t?["person"] as? String == ""
        }
        // Due today: on today's page, in the family's column.
        reveal(box(name, in: app), in: app)
    }

    // MARK: Changing and removing

    @MainActor
    func testEditingAndRemovingATaskFromTheBoard() async throws {
        let (first, second) = try await twoPeople()
        let name = title("edit")
        let renamed = title("edited")
        let id = try await addTask(name, person: first.key)
        let app = try board()

        // Opened and left as it was.
        reveal(app.buttons["Open \(name)"], in: app).tap()
        app.navigationBars["Task"].expect()
        app.buttons["Cancel"].tap()
        XCTAssertTrue(app.navigationBars["Task"].waitForNonExistence(timeout: 10))

        reveal(app.buttons["Open \(name)"], in: app).tap()
        app.navigationBars["Task"].expect()
        retype(field("task-title", in: app), renamed)
        app.buttons[second.name].tap()
        selected(app.buttons[second.name])
        app.buttons["Save"].tap()
        XCTAssertTrue(app.navigationBars["Task"].waitForNonExistence(timeout: 10))
        try await eventually("renamed and given to \(second.name)") {
            let t = try await task(id)
            return t?["title"] as? String == renamed && t?["person"] as? String == second.key
        }

        reveal(app.buttons["Open \(renamed)"], in: app).tap()
        app.buttons["Remove"].firstMatch.expect().tap()
        app.staticTexts["Remove “\(renamed)”?"].firstMatch.expect()
        confirm("Remove", in: app)
        XCTAssertTrue(app.navigationBars["Task"].waitForNonExistence(timeout: 10))
        try await eventually("removed") { try await task(id) == nil }
        XCTAssertTrue(app.buttons["Open \(renamed)"].waitForNonExistence(timeout: 10))
    }

    // MARK: The hold menu

    @MainActor
    func testGivingAndMovingATaskWithUndo() async throws {
        let (first, second) = try await twoPeople()
        let today = try await self.today()
        let later = add(today, 2)
        let name = title("hold")
        let id = try await addTask(name, person: first.key)
        let chore = title("hold chore")
        _ = try await addTask(chore, person: first.key, days: everyDay)
        let app = try board()

        hold(reveal(app.buttons["Open \(name)"], in: app), pick: ["Give to", second.name], in: app)
        app.staticTexts["\(name) is now \(second.name)’s."].expect()
        try await eventually("given to \(second.name)") { try await task(id)?["person"] as? String == second.key }
        app.buttons["Undo"].firstMatch.tap()
        app.staticTexts["\(name) is back where it was."].expect()
        try await eventually("\(first.name)'s again") { try await task(id)?["person"] as? String == first.key }

        hold(reveal(app.buttons["Open \(name)"], in: app), pick: ["Give to", "The family"], in: app)
        app.staticTexts["\(name) is now the family’s."].expect()
        try await eventually("the family's") { try await task(id)?["person"] as? String == "" }
        app.buttons["Undo"].firstMatch.tap()
        try await eventually("\(first.name)'s again") { try await task(id)?["person"] as? String == first.key }

        hold(reveal(app.buttons["Open \(name)"], in: app), pick: ["Move to", long(later)], in: app)
        app.staticTexts["\(name) moved to \(long(later))."].expect()
        try await eventually("due the day after tomorrow") { try await task(id, on: later)?["due"] as? String == later }
        XCTAssertTrue(app.buttons["Open \(name)"].waitForNonExistence(timeout: 10), "off today's page")
        app.buttons["Undo"].firstMatch.tap()
        try await eventually("undated again") { try await task(id)?["due"] as? String == "" }
        reveal(app.buttons["Open \(name)"], in: app)

        // A chore is moved in the editor, not from here.
        reveal(app.buttons["Open \(chore)"], in: app).press(forDuration: 1.2)
        anything("This one repeats — change it in the editor.", in: app).expect()
        XCTAssertFalse(app.buttons["Move to"].exists)
        dismissMenu(app)
    }

    @MainActor
    func testGivingAndMovingAnEventWithUndo() async throws {
        let (first, second) = try await twoPeople()
        let today = try await self.today()
        let later = add(today, 2)
        let name = title("event")
        let id = try await addEvent(name, start: "\(today)T09:00", end: "\(today)T09:30", leaders: [first.key])
        let series = title("series")
        try await addEvent(series, start: today, leaders: [second.key], recurrence: "FREQ=DAILY;COUNT=2")
        let app = try board()

        // A tap opens the Agenda's editor on it.
        reveal(app.buttons["Open \(name)"], in: app).tap()
        app.buttons["Cancel"].firstMatch.expect().tap()
        XCTAssertTrue(app.buttons["Cancel"].waitForNonExistence(timeout: 10))

        hold(reveal(app.buttons["Open \(name)"], in: app), pick: ["Give to", "The family"], in: app)
        app.staticTexts["\(name) is now the family’s."].expect()
        try await eventually("nobody's") { try await event(id, on: today)?["leaders"] as? [String] == [] }
        app.buttons["Undo"].firstMatch.tap()
        app.staticTexts["\(name) is back where it was."].expect()
        try await eventually("\(first.name)'s again") { try await event(id, on: today)?["leaders"] as? [String] == [first.key] }

        hold(reveal(app.buttons["Open \(name)"], in: app), pick: ["Give to", second.name], in: app)
        app.staticTexts["\(name) is now \(second.name)’s."].expect()
        try await eventually("\(second.name)'s") { try await event(id, on: today)?["leaders"] as? [String] == [second.key] }
        app.buttons["Undo"].firstMatch.tap()
        try await eventually("\(first.name)'s again") { try await event(id, on: today)?["leaders"] as? [String] == [first.key] }

        hold(reveal(app.buttons["Open \(name)"], in: app), pick: ["Move to", long(later)], in: app)
        app.staticTexts["\(name) moved to \(long(later))."].expect()
        try await eventually("two days on, at nine") {
            (try await event(id, on: later)?["start"] as? String)?.hasPrefix("\(later)T09:00") == true
        }
        app.buttons["Undo"].firstMatch.tap()
        try await eventually("back today at nine") {
            (try await event(id, on: today)?["start"] as? String)?.hasPrefix("\(today)T09:00") == true
        }

        // One day of a series is moved in the editor.
        reveal(app.buttons["Open \(series)"], in: app).press(forDuration: 1.2)
        anything("This one repeats — change it in the editor.", in: app).expect()
        app.buttons["Give to"].expect()
        XCTAssertFalse(app.buttons["Move to"].exists)
        dismissMenu(app)
    }

    // MARK: What is next

    @MainActor
    func testTheDayAfterShowsSixAndSaysHowManyMore() async throws {
        let (first, _) = try await twoPeople()
        let today = try await self.today()
        for i in 1...7 {
            try await addEvent(title("next \(i)"), start: add(today, 1), leaders: [first.key])
        }
        try await addEvent(title("after"), start: add(today, 2), leaders: [])
        let app = try board()

        let line = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'ios-test next' AND label CONTAINS %@ AND label ENDSWITH %@", tag, " (\(first.name))")).firstMatch
        reveal(line, in: app)
        reveal(app.staticTexts.matching(NSPredicate(format: "label MATCHES %@", "\\+[0-9]+ more")).firstMatch, in: app)

        toTop(app)
        app.buttons["Next day"].tap()
        app.navigationBars["Tomorrow"].expect()
        // Tomorrow's own events are in the first one's column now; the section is the day after.
        reveal(app.buttons["Open \(title("next 7"))"], in: app)
        reveal(app.staticTexts["The day after"], in: app)
        reveal(app.staticTexts[title("after")], in: app)
    }

    @MainActor
    func testATaskOpensAtLaunch() async throws {
        let (first, _) = try await twoPeople()
        let chore = title("launch chore")
        let id = try await addTask(chore, person: first.key, days: everyDay)
        var app = try board(["-boardTask", "\(id)", "-boardDay", "2"])
        app.navigationBars["Task"].expect()
        XCTAssertEqual(field("task-title", in: app).value as? String, chore)
        selected(app.buttons["Saturday"])
        app.buttons["Cancel"].tap()
        app.terminate()

        app = try board(["-boardTask", "new"])
        app.navigationBars.matching(NSPredicate(format: "identifier BEGINSWITH 'A task'")).firstMatch.expect()
        app.buttons["Cancel"].tap()
    }
}
