import Foundation
import Testing
@testable import Luach

/// Every board and task call, against a stub luach: the path, the query and the body sent.
@MainActor
@Suite(.timeLimit(.minutes(1)))
struct BoardAPITests {
    let server = StubServer()

    @Test func theBoardDayIsTodayUnlessAPageIsAsked() async throws {
        server.on("GET", "/api/board/today", json: BoardFixtures.board())
        let today = try await server.api.boardDay(nil)
        #expect(today.day == "2026-10-27" && today.tasks.count == 2)
        #expect(server.requests("GET", "/api/board/today").first?.query.isEmpty == true)

        server.on("GET", "/api/board/today", json: BoardFixtures.board(day: "2026-10-29"))
        let later = try await server.api.boardDay("2026-10-29")
        #expect(later.day == "2026-10-29" && later.todayISO == "2026-10-27")
        #expect(server.requests("GET", "/api/board/today").last?.query == ["day": "2026-10-29"])
    }

    @Test func aDayPastTheMonthIsRefusedInTheServersWords() async {
        server.fail("GET", "/api/board/today", status: 400, "the board shows today and the 30 days after it")
        await #expect {
            _ = try await server.api.boardDay("2027-01-29")
        } throws: { error in
            (error as? APIError)?.status == 400 && error.localizedDescription == "the board shows today and the 30 days after it"
        }
    }

    @Test func aTickTodaySendsNoDayAndALaterOneSendsIts() async throws {
        server.on("POST", "/api/board/tasks/133/done", json: BoardFixtures.chore)
        try await server.api.boardTick(133, done: true, day: nil)
        try await server.api.boardTick(133, done: false, day: "2026-10-29")
        let sent = server.requests("POST", "/api/board/tasks/133/done").map(\.json)
        #expect(sent.count == 2)
        #expect(sent[0]["done"] as? Bool == true && sent[0]["day"] == nil && sent[0].count == 1)
        #expect(sent[1]["done"] as? Bool == false && sent[1]["day"] as? String == "2026-10-29")
    }

    @Test func movingAnEventNamesItsCalendar() async throws {
        let swim = try BoardFixtures.event()
        server.on("PATCH", "/api/board/events/c6956f0a832e", json: BoardFixtures.timedEvent)
        try await server.api.boardMoveEvent(swim, EventPatch(leaders: ["lily"]))
        let sent = try #require(server.requests("PATCH", "/api/board/events/c6956f0a832e").first)
        #expect(sent.query == ["calendar": "fake"])
        #expect(sent.json["leaders"] as? [String] == ["lily"] && sent.json.count == 1)
    }

    @Test func anEventWithoutACalendarIsLookedForEverywhere() async throws {
        var json = BoardFixtures.allDayEvent
        json["calendar_id"] = ""
        let fair = try BoardFixtures.event(json)
        server.on("PATCH", "/api/board/events/d3cfd3f1ce66", json: json)
        try await server.api.boardMoveEvent(fair, EventPatch(start: "2026-10-30", end: "2026-10-31"))
        json["calendar_id"] = nil
        try await server.api.boardMoveEvent(try BoardFixtures.event(json), EventPatch(start: "2026-10-30"))
        let sent = server.requests("PATCH", "/api/board/events/d3cfd3f1ce66")
        #expect(sent.count == 2 && sent.allSatisfy { $0.query.isEmpty })
        #expect(sent[0].json["start"] as? String == "2026-10-30" && sent[0].json["end"] as? String == "2026-10-31")
        #expect(sent[1].json["end"] == nil)
    }

    @Test func anEventIdIsSentAsItIs() async throws {
        // Google's ids are letters, digits and `_`; a stranger one must still reach the same event.
        var json = BoardFixtures.timedEvent
        json["id"] = "abc_20261027T150000Z x"
        let odd = try BoardFixtures.event(json)
        server.on("PATCH", "/api/board/events/abc_20261027T150000Z x", json: json)
        try await server.api.boardMoveEvent(odd, EventPatch(leaders: []))
        #expect(server.requests.last?.path == "/api/board/events/abc_20261027T150000Z x")
        #expect(server.requests("PATCH", "/api/board/events/abc_20261027T150000Z x").count == 1)
    }

    @Test func theTaskListForADayAndForEverything() async throws {
        server.on("GET", "/api/tasks", json: ["day": "2026-10-27", "tasks": [BoardFixtures.todo], "may_assign": true])
        server.on("GET", "/api/tasks/all", json: ["tasks": [BoardFixtures.chore], "may_assign": false])
        let today = try await server.api.tasksDay(nil)
        let later = try await server.api.tasksDay("2026-10-30")
        let all = try await server.api.tasksAll()
        #expect(today.day == "2026-10-27" && today.mayAssign && later.tasks.map(\.id) == [132])
        #expect(all.day == nil && !all.mayAssign && all.tasks.map(\.id) == [133])
        let asked = server.requests("GET", "/api/tasks").map(\.query)
        #expect(asked == [[:], ["day": "2026-10-30"]])
    }

    @Test func aTickFromTheListAlwaysNamesTheDay() async throws {
        server.on("POST", "/api/tasks/133/done", json: BoardFixtures.chore)
        try await server.api.tick(133, done: true, day: "2026-10-27")
        let sent = try #require(server.requests("POST", "/api/tasks/133/done").first)
        #expect(sent.json["day"] as? String == "2026-10-27" && sent.json["done"] as? Bool == true)
    }

    @Test func theFamilyIsItsPeople() async throws {
        server.on("GET", "/api/family", json: BoardFixtures.family)
        let people = try await server.api.family()
        #expect(people.map(\.key) == ["robin", "ruby"] && people[0].hex == "#039be5")
    }

    @Test(arguments: [TaskRoutes.board, TaskRoutes.tasks])
    func tasksAreAddedChangedAndRemovedOnTheirRoutes(_ routes: TaskRoutes) async throws {
        let base = routes == .board ? "/api/board/tasks" : "/api/tasks"
        #expect(routes.base == base)
        server.on("POST", base, json: BoardFixtures.todo)
        server.on("PATCH", "\(base)/132", json: BoardFixtures.todo)
        server.on("DELETE", "\(base)/132", json: ["ok": true])

        let made = try await routes.add(server.api, TaskInput(title: "Library books", person: "ruby", due: "2026-10-26", notes: "the blue bag"))
        #expect(made.id == 132)
        let added = try #require(server.requests("POST", base).first?.json)
        #expect(added["title"] as? String == "Library books" && added["person"] as? String == "ruby")
        #expect(added["due"] as? String == "2026-10-26" && added["notes"] as? String == "the blue bag" && added["days"] == nil)

        _ = try await routes.update(server.api, 132, TaskInput(days: ["MO", "TH"]))
        let changed = try #require(server.requests("PATCH", "\(base)/132").first?.json)
        #expect(changed.count == 1 && changed["days"] as? [String] == ["MO", "TH"])

        try await routes.remove(server.api, 132)
        #expect(server.requests("DELETE", "\(base)/132").count == 1)
    }

    @Test func aChildsAccountIsToldWhyItMayNotChangeTasks() async {
        server.fail("POST", "/api/tasks", status: 403, "a child's account cannot hand out tasks")
        await #expect {
            _ = try await TaskRoutes.tasks.add(server.api, TaskInput(title: "x"))
        } throws: { error in
            (error as? APIError)?.status == 403 && error.localizedDescription == "a child's account cannot hand out tasks"
        }
    }
}
