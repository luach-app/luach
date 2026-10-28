import Foundation
import Testing
@testable import Luach

/// What holding a row does: give it to someone or move it to another day, how the board
/// shows it at once, and the Undo that puts it back. Run against a stub luach.
@MainActor
@Suite(.timeLimit(.minutes(1)))
struct BoardPlanTests {
    let server = StubServer()

    private func plan(_ move: BoardView.Move, on day: BoardDay? = nil) throws -> BoardView.Planned {
        try #require(BoardView.plan(move, try day ?? BoardFixtures.day()))
    }

    // MARK: Tasks

    @Test func givingATaskSendsTheNewPersonAndUndoSendsTheOld() async throws {
        let task = try BoardFixtures.task()
        let p = try plan(.task(task, .person("lily")))
        #expect(p.title == "Library books" && p.target == .person("lily"))

        var shown = try BoardFixtures.day()
        p.preview(&shown)
        #expect(shown.tasks.first { $0.id == 132 }?.person == "lily")
        #expect(shown.columns(withFamily: true).first { $0.key == "lily" }?.tasks.map(\.id) == [132])

        server.on("PATCH", "/api/board/tasks/132", json: BoardFixtures.todo)
        try await p.apply(server.api)
        try await p.undo(server.api)
        let sent = server.requests("PATCH", "/api/board/tasks/132").map(\.json)
        #expect(sent.count == 2)
        #expect(sent[0].count == 1 && sent[0]["person"] as? String == "lily")
        #expect(sent[1].count == 1 && sent[1]["person"] as? String == "ruby")
    }

    @Test func givingATaskToTheFamilyMakesItNobodys() async throws {
        let p = try plan(.task(try BoardFixtures.task(), .person("")))
        var shown = try BoardFixtures.day()
        p.preview(&shown)
        #expect(shown.columns(withFamily: true).last?.tasks.map(\.id) == [132, 133])
        server.on("PATCH", "/api/board/tasks/132", json: BoardFixtures.todo)
        try await p.apply(server.api)
        #expect(server.requests("PATCH", "/api/board/tasks/132").first?.json["person"] as? String == "")
    }

    @Test func movingATaskLaterTakesItOffThePage() async throws {
        let task = try BoardFixtures.task()
        let p = try plan(.task(task, .day("2026-10-29")))
        #expect(p.target == .day("2026-10-29"))
        var shown = try BoardFixtures.day()
        p.preview(&shown)
        #expect(shown.tasks.map(\.id) == [133])

        server.on("PATCH", "/api/board/tasks/132", json: BoardFixtures.todo)
        try await p.apply(server.api)
        try await p.undo(server.api)
        let sent = server.requests("PATCH", "/api/board/tasks/132").map(\.json)
        #expect(sent[0].count == 1 && sent[0]["due"] as? String == "2026-10-29")
        #expect(sent[1].count == 1 && sent[1]["due"] as? String == "2026-10-26", "undo puts back the day it had")
    }

    @Test func movingATaskEarlierKeepsItOnThePageNoLongerLate() throws {
        // Looking at the 29th, a to-do moved to today still shows there, until someone ticks it.
        let day = try BoardFixtures.day(BoardFixtures.board(day: "2026-10-29"))
        let p = try plan(.task(try BoardFixtures.task(), .day("2026-10-27")), on: day)
        var shown = day
        p.preview(&shown)
        let moved = try #require(shown.tasks.first { $0.id == 132 })
        #expect(moved.due == "2026-10-27" && !moved.overdue)
    }

    @Test func anUndatedTaskMovedAndUndoneIsUndatedAgain() async throws {
        var json = BoardFixtures.todo
        json["due"] = ""
        json["overdue"] = false
        let p = try plan(.task(try BoardFixtures.task(json), .day("2026-10-28")))
        server.on("PATCH", "/api/board/tasks/132", json: json)
        try await p.undo(server.api)
        #expect(server.requests("PATCH", "/api/board/tasks/132").first?.json["due"] as? String == "")
    }

    @Test func aPreviewOfATaskNoLongerShownChangesNothing() throws {
        let p = try plan(.task(try BoardFixtures.task(), .person("lily")))
        var gone = try BoardFixtures.day(BoardFixtures.board(tasks: [BoardFixtures.chore]))
        p.preview(&gone)
        #expect(gone.tasks.map(\.person) == [""])
        let later = try plan(.task(try BoardFixtures.task(), .day("2026-10-27")), on: try BoardFixtures.day(BoardFixtures.board(day: "2026-10-29")))
        var empty = try BoardFixtures.day(BoardFixtures.board(tasks: []))
        later.preview(&empty)
        #expect(empty.tasks.isEmpty)
    }

    // MARK: Events

    @Test func givingAnEventHandsOverTheGiversPartAndUndoRestoresEveryone() async throws {
        let swim = try BoardFixtures.event()
        let p = try plan(.event(swim, from: "ruby", .person("robin")))
        var shown = try BoardFixtures.day()
        p.preview(&shown)
        #expect(shown.events[0].leaders == ["robin", "lily"] && shown.events[0].leader == "robin")

        server.on("PATCH", "/api/board/events/c6956f0a832e", json: BoardFixtures.timedEvent)
        try await p.apply(server.api)
        try await p.undo(server.api)
        let sent = server.requests("PATCH", "/api/board/events/c6956f0a832e")
        #expect(sent.allSatisfy { $0.query == ["calendar": "fake"] })
        #expect(sent[0].json["leaders"] as? [String] == ["robin", "lily"] && sent[0].json.count == 1)
        #expect(sent[1].json["leaders"] as? [String] == ["ruby", "lily"] && sent[1].json.count == 1)
    }

    @Test func givingAnEventToTheFamilyLeavesItNobodys() throws {
        let p = try plan(.event(try BoardFixtures.event(), from: "lily", .person("")))
        var shown = try BoardFixtures.day()
        p.preview(&shown)
        #expect(shown.events[0].leaders == [] && shown.events[0].leader == "")
        #expect(shown.columns(withFamily: false).last?.events.map(\.id) == ["c6956f0a832e"])
    }

    @Test func givingAnEventToWhoeverHasItAlreadyIsNothing() throws {
        let swim = try BoardFixtures.event()
        // Lily's part given to Ruby, who already has it: still the two of them.
        #expect(BoardView.plan(.event(swim, from: "lily", .person("ruby")), try BoardFixtures.day()) != nil)
        var rubys = BoardFixtures.timedEvent
        rubys["leaders"] = ["ruby"]
        let one = try BoardFixtures.event(rubys)
        #expect(BoardView.plan(.event(one, from: "robin", .person("ruby")), try BoardFixtures.day()) == nil)
        let fair = try BoardFixtures.event(BoardFixtures.allDayEvent)
        #expect(BoardView.plan(.event(fair, from: "", .person("")), try BoardFixtures.day()) == nil)
    }

    @Test func movingAnEventKeepsItsTimeOfDayAndUndoPutsItBack() async throws {
        let swim = try BoardFixtures.event()
        let p = try plan(.event(swim, from: "ruby", .day("2026-10-29")))
        var shown = try BoardFixtures.day()
        p.preview(&shown)
        #expect(shown.events.isEmpty, "it leaves the page at once")

        server.on("PATCH", "/api/board/events/c6956f0a832e", json: BoardFixtures.timedEvent)
        try await p.apply(server.api)
        try await p.undo(server.api)
        let sent = server.requests("PATCH", "/api/board/events/c6956f0a832e").map(\.json)
        let start = EventTime.parse(sent[0]["start"] as? String ?? "")
        let end = EventTime.parse(sent[0]["end"] as? String ?? "")
        #expect(start == EventTime.parse("2026-10-29T15:00:00-04:00"))
        #expect(end == EventTime.parse("2026-10-29T16:00:00-04:00"))
        #expect(sent[1]["start"] as? String == "2026-10-27T15:00:00-04:00" && sent[1]["end"] as? String == "2026-10-27T16:00:00-04:00")
    }

    @Test func anEventWithoutAnEndIsMovedAndUndoneWithoutOne() async throws {
        var json = BoardFixtures.timedEvent
        json["end"] = ""
        let p = try plan(.event(try BoardFixtures.event(json), from: "ruby", .day("2026-10-28")))
        server.on("PATCH", "/api/board/events/c6956f0a832e", json: json)
        try await p.apply(server.api)
        try await p.undo(server.api)
        let sent = server.requests("PATCH", "/api/board/events/c6956f0a832e").map(\.json)
        #expect(sent[0]["end"] == nil && sent[0]["start"] != nil)
        #expect(sent[1]["end"] == nil && sent[1]["start"] as? String == "2026-10-27T15:00:00-04:00")
    }

    // MARK: The pure parts

    @Test func handingOver() {
        #expect(BoardView.handOver(["ruby", "lily"], from: "ruby", to: "robin") == ["robin", "lily"])
        #expect(BoardView.handOver(["ruby", "lily"], from: "ruby", to: "lily") == ["lily"])
        #expect(BoardView.handOver(["ruby"], from: "ruby", to: "") == [])
        #expect(BoardView.handOver([], from: "", to: "lily") == ["lily"])
        #expect(BoardView.handOver(["someone-gone"], from: "", to: "lily") == ["lily"], "the family's is nobody's")
        #expect(BoardView.handOver(["lily"], from: "ruby", to: "robin") == ["lily", "robin"], "a giver not on it still hands it over")
    }

    @Test func shiftingKeepsTheWallClockTimeThroughTheClocksChanging() throws {
        // Saturday 31 October 3pm in New York is EDT (-4); Monday 2 November 3pm is EST (-5).
        var json = BoardFixtures.timedEvent
        json["start"] = "2026-10-31T15:00:00-04:00"
        json["end"] = "2026-10-31T16:30:00-04:00"
        let ny = try #require(TimeZone(identifier: "America/New_York"))
        let patch = BoardView.shift(try BoardFixtures.event(json), days: 2, zone: ny)
        #expect(EventTime.parse(patch.start ?? "") == EventTime.parse("2026-11-02T15:00:00-05:00"))
        #expect(EventTime.parse(patch.end ?? "") == EventTime.parse("2026-11-02T16:30:00-05:00"))
        #expect(patch.leaders == nil)
        let back = BoardView.shift(try BoardFixtures.event(json), days: -1, zone: ny)
        #expect(EventTime.parse(back.start ?? "") == EventTime.parse("2026-10-30T15:00:00-04:00"))
    }

    @Test func shiftingAnAllDayEventMovesItsDays() throws {
        let fair = try BoardFixtures.event(BoardFixtures.allDayEvent)
        let p = BoardView.shift(fair, days: 3, zone: .current)
        #expect(p.start == "2026-10-31" && p.end == "2026-11-01")
        var open = BoardFixtures.allDayEvent
        open["end"] = ""
        let q = BoardView.shift(try BoardFixtures.event(open), days: 1, zone: .current)
        #expect(q.start == "2026-10-29" && q.end == "2026-10-30", "no end: a one-day event")
    }

    @Test func aTimeThatCannotBeReadIsSentBackAsItWas() throws {
        var json = BoardFixtures.timedEvent
        json["start"] = "sometime soon"
        json["end"] = "later"
        let p = BoardView.shift(try BoardFixtures.event(json), days: 1, zone: .current)
        #expect(p.start == "sometime soon" && p.end == nil)
    }

    @Test func theTimeColumnAndTheNames() throws {
        let ny = try #require(TimeZone(identifier: "America/New_York"))
        let swim = try BoardFixtures.event()
        var style = Date.FormatStyle(date: .omitted, time: .shortened)
        style.timeZone = ny
        #expect(BoardView.timeOf(swim, ny) == EventTime.parse("2026-10-27T15:00:00-04:00")!.formatted(style))
        #expect(BoardView.timeOf(try BoardFixtures.event(BoardFixtures.allDayEvent), ny) == String(localized: "All day"))
        var bad = BoardFixtures.timedEvent
        bad["start"] = "sometime soon"
        #expect(BoardView.timeOf(try BoardFixtures.event(bad), ny) == "")

        let people = try BoardFixtures.day().people
        let names = BoardView.names(swim, people)
        #expect(names.hasPrefix(" (") && names.contains("Ruby") && names.contains("Lily") && names.hasSuffix(")"))
        if Locale.current.language.languageCode == .english { #expect(names == " (Ruby and Lily)") }
        #expect(BoardView.names(try BoardFixtures.event(BoardFixtures.allDayEvent), people) == "")
    }

    @Test func theDateLineIsTheClockTodayAndTheDateOtherwise() throws {
        let today = try BoardFixtures.day()
        let now = try #require(EventTime.parse("2026-10-27T11:25:00-04:00"))
        let line = BoardView.dateLine(today, now: now, isToday: true)
        #expect(line.contains(" · ") && line.contains("27"))
        if Locale.current.language.languageCode == .english { #expect(line.hasPrefix("Tuesday, October 27 · 11:25")) }
        let later = try BoardFixtures.day(BoardFixtures.board(day: "2026-10-29"))
        #expect(BoardView.dateLine(later, now: now, isToday: false) == ISODay.long("2026-10-29"))
    }

    @Test func plusSoManyMore() {
        #expect(BoardView.more(0) == nil)
        #expect(BoardView.more(6) == nil, "six fit")
        #expect(BoardView.more(7) == 1)
        #expect(BoardView.more(20) == 14)
    }

    // MARK: The task editor's rules

    @Test func aTaskNeedsANameAndAChoreItsDays() {
        #expect(TaskEditor.problem(title: "  \n", chore: false, days: []) == String(localized: "Give it a name."))
        #expect(TaskEditor.problem(title: "Bins", chore: true, days: []) == String(localized: "Pick the days it falls on."))
        #expect(TaskEditor.problem(title: "Bins", chore: true, days: ["TU"]) == nil)
        #expect(TaskEditor.problem(title: "Bins", chore: false, days: []) == nil)
    }

    @Test func saveSendsEveryFieldTrimmed() throws {
        let due = try #require(ISODay.local("2026-10-30"))
        let todo = TaskEditor.input(title: "  Bins \n", person: "ruby", chore: false, days: ["MO"], hasDue: true, due: due, notes: " green one ")
        #expect(todo.title == "Bins" && todo.person == "ruby" && todo.due == "2026-10-30" && todo.days == [] && todo.notes == "green one")
        let undated = TaskEditor.input(title: "Bins", person: "", chore: false, days: [], hasDue: false, due: due, notes: "")
        #expect(undated.due == "" && undated.days == [] && undated.notes == "")
        let chore = TaskEditor.input(title: "Bins", person: "", chore: true, days: ["TH", "MO"], hasDue: true, due: due, notes: "")
        #expect(chore.due == "" && chore.days == ["MO", "TH"], "a chore has no due day, its days in the week's order")
    }

    @Test func theEditorsHeading() throws {
        let people = try BoardFixtures.day().people
        let task = try BoardFixtures.task()
        #expect(TaskEditor.heading(task: task, canEdit: true, person: "ruby", people: people) == String(localized: "Task"))
        #expect(TaskEditor.heading(task: task, canEdit: false, person: "ruby", people: people) == "Library books")
        #expect(TaskEditor.heading(task: nil, canEdit: true, person: "lily", people: people) == String(localized: "A task for \("Lily")"))
        #expect(TaskEditor.heading(task: nil, canEdit: true, person: "", people: people) == String(localized: "A task"))
    }
}
