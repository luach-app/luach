import XCTest

/// Tasks (from the Board's toolbar), tapped through on dev: a day's list paged, everything
/// open, ticking, adding, changing and removing. Only `ios-test…` tasks this test made.
final class TasksUITests: BoardUITestCase {
    private let everyDay = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

    @MainActor
    private func tasks(_ more: [String] = []) throws -> XCUIApplication {
        let app = try LuachApp.launch(["-tab", "board"] + more)
        app.buttons["Tasks"].firstMatch.expect().tap()
        app.navigationBars["Tasks"].expect()
        return app
    }


    @MainActor
    func testADaysListIsPagedAndTicked() async throws {
        let (first, second) = try await twoPeople()
        let today = try await self.today()
        let tomorrow = add(today, 1)
        let todo = title("list tick")
        let todoID = try await addTask(todo, person: first.key)
        let chore = title("list chore")
        let choreID = try await addTask(chore, person: second.key, days: everyDay)
        let app = try tasks()

        XCTAssertEqual(app.staticTexts["tasks-day"].expect().label, "Today")
        XCTAssertFalse(app.buttons["tasks-today"].exists, "already on today")
        let todoBox = reveal(box(todo, in: app), in: app)
        XCTAssertEqual(ticked(todoBox), false)
        todoBox.tap()
        expectTicked(todoBox, true)
        try await eventually("\(todo) ticked") { try await task(todoID)?["done"] as? Bool == true }
        todoBox.tap()
        expectTicked(todoBox, false)
        try await eventually("\(todo) unticked") { try await task(todoID)?["done"] as? Bool == false }

        reveal(app.buttons["Next day"], in: app).tap()
        app.buttons["tasks-today"].expect()
        let choreBox = reveal(box(chore, in: app), in: app)
        choreBox.tap()
        expectTicked(choreBox, true)
        try await eventually("\(chore) ticked for tomorrow") { try await task(choreID, on: tomorrow)?["done"] as? Bool == true }
        let todays = try await task(choreID, on: today)
        XCTAssertEqual(todays?["done"] as? Bool, false, "a chore is done for a day")
        choreBox.tap()
        expectTicked(choreBox, false)
        try await eventually("\(chore) unticked") { try await task(choreID, on: tomorrow)?["done"] as? Bool == false }

        reveal(app.buttons["Previous day"], in: app).tap()
        XCTAssertEqual(app.staticTexts["tasks-day"].expect().label, "Today")
        app.buttons["Previous day"].tap()
        app.buttons["tasks-today"].expect().tap()
        XCTAssertEqual(app.staticTexts["tasks-day"].expect().label, "Today")
    }

    @MainActor
    func testEverythingAndChangingAndRemovingThere() async throws {
        let (first, _) = try await twoPeople()
        let name = title("list edit")
        let renamed = title("list edited")
        let id = try await addTask(name, person: first.key, due: add(try await today(), 5))
        let app = try tasks()

        // Due in five days: not on today's list, but open, so in Everything.
        XCTAssertFalse(app.buttons["Open \(name)"].waitForExistence(timeout: 3))
        app.buttons["Everything"].tap()
        reveal(app.buttons["Open \(name)"], in: app).tap()
        app.navigationBars["Task"].expect()
        XCTAssertTrue(app.switches["Due date"].expect().value as? String == "1")
        retype(field("task-title", in: app), renamed)
        app.buttons["Save"].tap()
        XCTAssertTrue(app.navigationBars["Task"].waitForNonExistence(timeout: 10))
        try await eventually("renamed") { try await tasks(titled: renamed).first?["id"] as? Int == id }

        let row = reveal(app.buttons["Open \(renamed)"], in: app)
        row.swipeLeft()
        app.buttons["Remove"].firstMatch.expect().tap()
        XCTAssertTrue(app.buttons["Open \(renamed)"].waitForNonExistence(timeout: 10))
        try await eventually("removed") { try await tasks(titled: renamed).isEmpty }

        app.buttons["Day"].tap()
        XCTAssertEqual(app.staticTexts["tasks-day"].expect().label, "Today")
    }

    @MainActor
    func testANewTaskFromTheList() async throws {
        let (_, second) = try await twoPeople()
        let name = title("list new")
        let app = try tasks()
        app.buttons["New task"].expect().tap()
        app.navigationBars["A task"].expect()
        app.buttons[second.name].expect().tap()
        app.navigationBars["A task for \(second.name)"].expect()
        let titleField = field("task-title", in: app)
        titleField.tap()
        titleField.typeText(name)
        app.buttons["Add task"].tap()
        XCTAssertTrue(app.navigationBars["A task for \(second.name)"].waitForNonExistence(timeout: 10))
        try await eventually("\(name) is \(second.name)'s") { try await tasks(titled: name).first?["person"] as? String == second.key }
        reveal(app.buttons["Open \(name)"], in: app)
    }

    @MainActor
    func testTheListOpensAsLaunchedAndATaskWithIt() async throws {
        let chore = title("list launch")
        let id = try await addTask(chore, person: "", days: everyDay)
        let app = try tasks(["-tasksMode", "all", "-tasksEdit", "\(id)"])
        app.navigationBars["Task"].expect()
        XCTAssertEqual(field("task-title", in: app).value as? String, chore)
        app.buttons["Cancel"].tap()
        XCTAssertTrue(app.buttons["Everything"].expect().isSelected)
        reveal(app.buttons["Open \(chore)"], in: app)
        app.terminate()

        let later = try LuachApp.launch(["-tab", "board", "-tasksDay", "1", "-tasksEdit", "new"])
        later.buttons["Tasks"].firstMatch.expect().tap()
        later.navigationBars["A task"].expect()
        later.buttons["Cancel"].tap()
        // A day ahead: the way back to today is offered.
        later.buttons["tasks-today"].expect()
    }
}
