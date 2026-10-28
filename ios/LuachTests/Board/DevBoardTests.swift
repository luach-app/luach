import Foundation
import Testing
@testable import Luach

/// The board and the task list against dev: only `ios-test…` tasks and events this suite
/// makes (no one invited), each removed before its test ends.
@MainActor
@Suite(.dev, .serialized, .timeLimit(.minutes(4)))
struct DevBoardTests {
    /// Removes what a test made even when it fails half-way.
    private final class Made {
        var tasks: [Int] = []
        var events: [BoardEvent] = []
        func clean(_ api: API) async {
            for id in tasks { _ = try? await TaskRoutes.board.remove(api, id) }
            for e in events {
                let q = (e.calendarId ?? "").isEmpty ? [:] : ["calendar": e.calendarId!]
                _ = try? await api.delete("/api/board/events/\(e.id)", query: q) as API.Ignored
            }
        }
    }

    private func newEvent(_ api: API, _ title: String, start: String, end: String? = nil,
                          leaders: [String], recurrence: String? = nil) async throws -> BoardEvent {
        struct Body: Encodable {
            let title: String; let start: String; let end: String?
            let attendees: [String]; let leaders: [String]; let recurrence: String?
        }
        return try await api.post("/api/board/events", Body(title: title, start: start, end: end, attendees: [], leaders: leaders, recurrence: recurrence))
    }

    /// Two of dev's family to give things to, children first, so no test names anyone itself.
    private func twoPeople(_ api: API) async throws -> (BoardPerson, BoardPerson) {
        let family = try await api.family()
        let kids = family.filter { $0.kind == "kid" }
        let two = Array((kids.count >= 2 ? kids : family).prefix(2))
        try #require(two.count == 2, "dev's family has fewer than two people")
        return (two[0], two[1])
    }

    @Test func todaysBoardDecodes() async throws {
        let api = try Dev.api()
        let day = try await api.boardDay(nil)
        #expect(day.day == day.todayISO && day.today != nil && day.canEdit == true)
        #expect(!day.people.isEmpty && day.people.allSatisfy { !$0.key.isEmpty && !$0.name.isEmpty })
        #expect(TimeZone(identifier: day.timezone) != nil)
        let family = try await api.family()
        #expect(family.map(\.key) == day.people.map(\.key), "the board's columns are the family, in its order")
    }

    @Test func aLaterDayAndTheEdgeOfTheMonth() async throws {
        let api = try Dev.api()
        let today = try await api.boardDay(nil).todayISO
        let later = try await api.boardDay(ISODay.add(today, 3))
        #expect(later.day == ISODay.add(today, 3) && later.todayISO == today)
        let last = try await api.boardDay(ISODay.add(today, 30))
        #expect(last.day == ISODay.add(today, 30))
        await #expect {
            _ = try await api.boardDay(ISODay.add(today, 31))
        } throws: { ($0 as? APIError)?.status == 400 }
    }

    @Test func aToDoIsAddedTickedChangedGivenAndRemovedFromTheBoard() async throws {
        let api = try Dev.api()
        let (first, second) = try await twoPeople(api)
        let made = Made()
        do {
            let title = Dev.title("board todo")
            let task = try await TaskRoutes.board.add(api, TaskInput(title: title, person: first.key, notes: "from the tests"))
            made.tasks.append(task.id)
            #expect(task.title == title && task.person == first.key && task.due == "" && !task.chore && !task.done)

            var day = try await api.boardDay(nil)
            #expect(day.tasks.first { $0.id == task.id }?.done == false, "undated: on today's board at once")
            #expect(day.columns(withFamily: true).first { $0.key == first.key }?.tasks.contains { $0.id == task.id } == true)

            try await api.boardTick(task.id, done: true, day: nil)
            day = try await api.boardDay(nil)
            #expect(day.tasks.first { $0.id == task.id }?.done == true)
            try await api.boardTick(task.id, done: false, day: nil)
            day = try await api.boardDay(nil)
            #expect(day.tasks.first { $0.id == task.id }?.done == false)

            let renamed = Dev.title("board todo renamed")
            let tomorrow = ISODay.add(day.todayISO, 1)
            let changed = try await TaskRoutes.board.update(api, task.id, TaskInput(title: renamed, due: tomorrow, notes: ""))
            #expect(changed.title == renamed && changed.due == tomorrow && changed.notes ?? "" == "")
            #expect(try await api.boardDay(nil).tasks.contains { $0.id == task.id } == false, "dated tomorrow: not today")
            #expect(try await api.boardDay(tomorrow).tasks.contains { $0.id == task.id })

            // Given to the other from the board and back, as the hold menu does.
            let tomorrowsPage = try await api.boardDay(tomorrow)
            let given = try #require(BoardView.plan(.task(changed, .person(second.key)), tomorrowsPage))
            try await given.apply(api)
            #expect(try await api.boardDay(tomorrow).tasks.first { $0.id == task.id }?.person == second.key)
            try await given.undo(api)
            #expect(try await api.boardDay(tomorrow).tasks.first { $0.id == task.id }?.person == first.key)

            try await TaskRoutes.board.remove(api, task.id)
            made.tasks.removeAll()
            #expect(try await api.tasksAll().tasks.contains { $0.id == task.id } == false)
        } catch {
            await made.clean(api)
            throw error
        }
        await made.clean(api)
    }

    @Test func aChoreIsTickedForADayNotForEver() async throws {
        let api = try Dev.api()
        let made = Made()
        do {
            let today = try await api.tasksDay(nil)
            let todayISO = try #require(today.day)
            let later = ISODay.add(todayISO, 2)
            let title = Dev.title("board chore")
            let chore = try await TaskRoutes.tasks.add(api, TaskInput(title: title, person: "", days: Weekday.codes))
            made.tasks.append(chore.id)
            #expect(chore.chore && chore.days == Weekday.codes && chore.person == "")
            #expect(try await api.tasksAll().tasks.contains { $0.id == chore.id })

            // Ticked for the later day from the list: done there, not today.
            try await api.tick(chore.id, done: true, day: later)
            #expect(try await api.tasksDay(later).tasks.first { $0.id == chore.id }?.done == true)
            #expect(try await api.tasksDay(nil).tasks.first { $0.id == chore.id }?.done == false)
            #expect(try await api.boardDay(later).tasks.first { $0.id == chore.id }?.done == true)
            // And unticked from the board's page for that day.
            try await api.boardTick(chore.id, done: false, day: later)
            #expect(try await api.boardDay(later).tasks.first { $0.id == chore.id }?.done == false)

            // A chore on one weekday is on that weekday only.
            var utc = Calendar(identifier: .gregorian)
            utc.timeZone = try #require(TimeZone(identifier: "UTC"))
            // Foundation counts from Sunday (1); the codes from Monday.
            let code = Weekday.codes[(utc.component(.weekday, from: try #require(ISODay.date(later))) + 5) % 7]
            let narrowed = try await TaskRoutes.tasks.update(api, chore.id, TaskInput(days: [code]))
            #expect(narrowed.days == [code])
            #expect(try await api.tasksDay(later).tasks.contains { $0.id == chore.id })
            #expect(try await api.tasksDay(ISODay.add(later, 1)).tasks.contains { $0.id == chore.id } == false)

            try await TaskRoutes.tasks.remove(api, chore.id)
            made.tasks.removeAll()
        } catch {
            await made.clean(api)
            throw error
        }
        await made.clean(api)
    }

    @Test func anEventIsGivenAndMovedWithUndo() async throws {
        let api = try Dev.api()
        let (first, _) = try await twoPeople(api)
        let made = Made()
        do {
            let today = try await api.boardDay(nil)
            let tomorrow = ISODay.add(today.todayISO, 1)
            let made1 = try await newEvent(api, Dev.title("board event"), start: "\(today.todayISO)T09:00", end: "\(today.todayISO)T09:30", leaders: [first.key])
            made.events.append(made1)
            var day = try await api.boardDay(nil)
            let event = try #require(day.events.first { $0.id == made1.id })
            #expect(event.people == [first.key] && event.readOnly == false && event.recurring == false)

            // To the family and back.
            let given = try #require(BoardView.plan(.event(event, from: first.key, .person("")), day))
            try await given.apply(api)
            day = try await api.boardDay(nil)
            #expect(day.events.first { $0.id == event.id }?.people == [])
            try await given.undo(api)
            day = try await api.boardDay(nil)
            #expect(day.events.first { $0.id == event.id }?.people == [first.key])

            // To tomorrow, at the same time, and back.
            let moved = try #require(BoardView.plan(.event(event, from: first.key, .day(tomorrow)), day))
            try await moved.apply(api)
            #expect(try await api.boardDay(nil).events.contains { $0.id == event.id } == false)
            let there = try #require(try await api.boardDay(tomorrow).events.first { $0.id == event.id })
            #expect(there.start.hasPrefix("\(tomorrow)T09:00"))
            try await moved.undo(api)
            let back = try #require(try await api.boardDay(nil).events.first { $0.id == event.id })
            #expect(back.start == event.start && back.end == event.end)
        } catch {
            await made.clean(api)
            throw error
        }
        await made.clean(api)
    }

    @Test func aRepeatingEventSaysSo() async throws {
        let api = try Dev.api()
        let made = Made()
        do {
            let today = try await api.boardDay(nil).todayISO
            let e = try await newEvent(api, Dev.title("board series"), start: today, leaders: [], recurrence: "FREQ=DAILY;COUNT=2")
            made.events.append(e)
            let shown = try await api.boardDay(nil).events.filter { $0.title == e.title }
            #expect(shown.count == 1 && shown.allSatisfy { $0.recurring == true && $0.isAllDay })
        } catch {
            await made.clean(api)
            throw error
        }
        await made.clean(api)
    }

    @Test func someoneNotInTheFamilyIsRefused() async throws {
        // A child's 403 needs a child's session, which dev has no way to mint without
        // changing members; the family check is the refusal the owner's session can see.
        let api = try Dev.api()
        let made = Made()
        do {
            let task = try await TaskRoutes.tasks.add(api, TaskInput(title: Dev.title("board refusal")))
            made.tasks.append(task.id)
            await #expect {
                _ = try await TaskRoutes.board.update(api, task.id, TaskInput(person: "ios-test-nobody"))
            } throws: { error in
                (error as? APIError)?.status == 400 && error.localizedDescription == "that is not someone in the family"
            }
            await #expect {
                _ = try await TaskRoutes.tasks.update(api, 999_999_999, TaskInput(title: "x"))
            } throws: { ($0 as? APIError)?.status == 404 }
        } catch {
            await made.clean(api)
            throw error
        }
        await made.clean(api)
    }

    @Test func theMemberMayAssign() async throws {
        let api = try Dev.api()
        #expect(try await api.tasksDay(nil).mayAssign, "dev's session is the owner's")
        #expect(try await api.tasksAll().mayAssign)
    }
}
