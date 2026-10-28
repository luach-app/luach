import Foundation
import SwiftUI
import Testing
@testable import Luach

/// What the agenda and the editor share: the household, the family, and every month looked
/// at, kept until something changes. Each test has a store of its own.
@MainActor
@Suite(.timeLimit(.minutes(1)))
struct AgendaDataTests {
    let server = StubServer()
    let data = AgendaData()
    let clock = AgendaFixtures.newYork
    typealias F = AgendaFixtures

    private func serveBasics() {
        server.on("GET", "/api/household/calendars", json: F.household)
        server.on("GET", "/api/family", json: F.family)
        server.on("GET", "/api/auth/me", json: F.me)
    }

    @Test func theBasicsLoadOnce() async throws {
        serveBasics()
        let api = server.api
        await data.loadBasics(api)
        #expect(data.basicsLoaded && data.household?.defaultCalendar == "fake")
        #expect(data.people.map(\.key) == ["robin", "ruby", "lily"])
        #expect(data.notifyEmails == ["work@example.com", "grandma@example.com"])
        await data.loadBasics(api)
        #expect(server.requests("GET", "/api/family").count == 1, "loaded: not asked again")
        await data.loadBasics(api, force: true)
        #expect(server.requests("GET", "/api/family").count == 2)
    }

    @Test func aPartThatWillNotLoadIsLeftOut() async {
        server.fail("GET", "/api/household/calendars", status: 500, "boom")
        server.on("GET", "/api/family", json: F.family)
        server.fail("GET", "/api/auth/me", status: 502, "bad gateway")
        await data.loadBasics(server.api)
        #expect(!data.basicsLoaded && data.household == nil, "without the household it is tried again")
        #expect(data.people.count == 3 && data.notifyEmails.isEmpty)
    }

    @Test func aMonthIsReadForItsWholeGridAndKept() async throws {
        server.on("GET", "/api/calendar/events", json: ["events": [F.allDay, F.occurrence]])
        let api = server.api
        await data.loadMonth("2026-11", clock: clock, api: api)
        let sent = try #require(server.requests("GET", "/api/calendar/events").first)
        // November 2026's grid runs Mon Oct 26 to Sun Dec 6; the end is the day after.
        // A day before the Monday grid, so a Sunday-first one (Hebrew) is covered too.
        #expect(sent.query == ["start": "2026-10-25", "end": "2026-12-07"])
        #expect(data.months["2026-11"]?.map(\.id) == ["b4fb50149034", "4fd5aabcaffd_20261110T150000"], "sorted by start")
        #expect(data.monthErrors["2026-11"] == nil)

        await data.loadMonth("2026-11", clock: clock, api: api)
        #expect(server.requests("GET", "/api/calendar/events").count == 1, "fresh: not asked again")
        await data.loadMonth("2026-11", clock: clock, api: api, force: true)
        #expect(server.requests("GET", "/api/calendar/events").count == 2)
    }

    @Test func aChangeMakesEveryMonthStaleButKeepsItShowing() async {
        server.on("GET", "/api/calendar/events", json: ["events": [F.allDay]])
        let api = server.api
        await data.loadMonth("2026-11", clock: clock, api: api)
        let before = data.version
        data.invalidate()
        #expect(data.version == before + 1)
        #expect(data.months["2026-11"]?.count == 1, "the grid does not blank")
        server.fail("GET", "/api/calendar/events", status: 503, "The calendar did not answer.")
        await data.loadMonth("2026-11", clock: clock, api: api)
        #expect(server.requests("GET", "/api/calendar/events").count == 2)
        #expect(data.monthErrors["2026-11"] == "The calendar did not answer.")
        #expect(data.months["2026-11"]?.count == 1, "what it had stays")
        // The next good answer clears the error.
        server.on("GET", "/api/calendar/events", json: ["events": []])
        await data.loadMonth("2026-11", clock: clock, api: api)
        #expect(data.monthErrors["2026-11"] == nil && data.months["2026-11"]?.isEmpty == true)
    }

    @Test func aMonthThatFailsIsAskedAgain() async {
        server.fail("GET", "/api/calendar/events", status: 500, "boom")
        let api = server.api
        await data.loadMonth("2026-12", clock: clock, api: api)
        await data.loadMonth("2026-12", clock: clock, api: api)
        #expect(server.requests("GET", "/api/calendar/events").count == 2)
        #expect(data.months["2026-12"] == nil && data.monthErrors["2026-12"] == "boom")
    }

    @Test func aCancelledLoadIsNotAnError() async {
        server.on("GET", "/api/calendar/events", json: ["events": [F.allDay]])
        let api = server.api
        let task = Task { await data.loadMonth("2026-11", clock: clock, api: api) }
        task.cancel()
        await task.value
        let upcoming = Task { await data.loadUpcoming(from: "2026-11-01", days: 14, clock: clock, api: api) }
        upcoming.cancel()
        await upcoming.value
        #expect(data.monthErrors["2026-11"] == nil && data.upcomingError == nil)
    }

    @Test func cancellationIsKnownInBothShapes() {
        #expect(AgendaData.cancelled(CancellationError()))
        #expect(AgendaData.cancelled(URLError(.cancelled)))
        #expect(!AgendaData.cancelled(URLError(.timedOut)))
        #expect(!AgendaData.cancelled(APIError(status: 500, message: "x")))
    }

    @Test func upcomingIsTheNextDaysFromToday() async throws {
        server.on("GET", "/api/calendar/events", json: ["events": [F.occurrence, F.allDay]])
        await data.loadUpcoming(from: "2026-11-01", days: 14, clock: clock, api: server.api)
        #expect(server.requests("GET", "/api/calendar/events").first?.query == ["start": "2026-11-01", "end": "2026-11-15"])
        #expect(data.upcoming?.map(\.id) == ["b4fb50149034", "4fd5aabcaffd_20261110T150000"])
        #expect(data.upcomingFrom == "2026-11-01" && data.upcomingError == nil)

        server.fail("GET", "/api/calendar/events", status: 500, "The calendar is down.")
        await data.loadUpcoming(from: "2026-11-02", days: 14, clock: clock, api: server.api)
        #expect(data.upcomingError == "The calendar is down.")
        #expect(data.upcomingFrom == "2026-11-01" && data.upcoming?.count == 2, "what it had stays")
    }

    @Test func someoneElseSigningInForgetsEverything() async throws {
        serveBasics()
        server.on("GET", "/api/calendar/events", json: ["events": [F.allDay]])
        let api = server.api
        let robin = Member(id: 1, username: "robin", displayName: "Robin", email: nil, timezone: nil, language: nil, isOwner: true)
        data.bind(robin)
        await data.loadBasics(api)
        await data.loadMonth("2026-11", clock: clock, api: api)
        await data.loadUpcoming(from: "2026-11-01", days: 14, clock: clock, api: api)
        server.fail("GET", "/api/calendar/events", status: 500, "boom")
        await data.loadUpcoming(from: "2026-11-01", days: 14, clock: clock, api: api)
        #expect(data.upcomingError == "boom")

        data.bind(robin)
        #expect(data.basicsLoaded && data.months["2026-11"] != nil, "the same member keeps it all")

        let ana = Member(id: 2, username: "ana", displayName: nil, email: nil, timezone: nil, language: nil, isOwner: false)
        data.bind(ana)
        #expect(!data.basicsLoaded && data.household == nil && data.people.isEmpty && data.notifyEmails.isEmpty)
        #expect(data.months.isEmpty && data.monthErrors.isEmpty && data.upcoming == nil)
        #expect(data.upcomingError == nil && data.upcomingFrom.isEmpty, "no error of the last member's")

        // Nothing is fresh any more: the month is asked for again.
        server.on("GET", "/api/calendar/events", json: ["events": []])
        await data.loadMonth("2026-11", clock: clock, api: api)
        #expect(server.requests("GET", "/api/calendar/events").count == 4)
    }

    @Test func peopleAndCalendarsAreLookedUp() async throws {
        serveBasics()
        await data.loadBasics(server.api)
        #expect(data.person("ruby")?.name == "Ruby")
        #expect(data.person("") == nil && data.person("nobody") == nil)
        #expect(try data.leaders(of: try F.event(F.timed)).map(\.name) == ["Ruby", "Lily"])
        #expect(try data.leaders(of: try F.event(["id": "x", "leaders": ["ghost", "lily"]])).map(\.key) == ["lily"])
        #expect(data.calendar("fake")?.name == "luach (local)")
        #expect(data.calendar("") == nil && data.calendar("missing") == nil)
        // Enabled only, the default first, then by name.
        #expect(data.enabledCalendars.map(\.id) == ["fake", "family@example.com", "holidays"])
    }

    @Test func anEventWearsItsLeadersColourThenItsCalendars() async throws {
        serveBasics()
        await data.loadBasics(server.api)
        #expect(try data.color(try F.event(F.timed)) == AgendaPalette.color("#33b679"), "Ruby's")
        #expect(try data.color(try F.event("x", "2026-11-03", calendar: "family@example.com")) == AgendaPalette.color("#f4b942"))
        #expect(try data.color(try F.event("x", "2026-11-03", leader: "ghost", calendar: "fake")) == AgendaPalette.color("#33b679"))
        #expect(try data.color(try F.event("x", "2026-11-03")) == .accentColor)
        #expect(try data.color(try F.event("x", "2026-11-03", calendar: "nowhere")) == .accentColor)
    }

    @Test func withNothingLoadedThereIsNothingToFind() throws {
        #expect(data.enabledCalendars.isEmpty && data.calendar("fake") == nil && data.person("ruby") == nil)
        #expect(try data.color(try F.event(F.timed)) == .accentColor)
    }
}
