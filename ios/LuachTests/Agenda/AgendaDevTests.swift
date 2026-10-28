import Foundation
import Testing
@testable import Luach

/// The agenda's real calls against dev. Events made here are `ios-test…`, invite nobody, and
/// are deleted before the test ends, whether it passed or not.
@MainActor
@Suite(.dev, .serialized, .timeLimit(.minutes(5)))
struct AgendaDevTests {
    /// dev's member's clock, as the agenda would make it.
    private func clock(_ api: API) async throws -> AgendaClock {
        AgendaClock.of(try await api.me())
    }

    /// A day well away from today, so the test's events sit alone: 40–60 days on, a random one.
    private func quietDay(_ clock: AgendaClock) -> String {
        AgendaClock.addDays(clock.today(), Int.random(in: 40...60))
    }

    /// Runs `body`, then deletes what it made — every event it names, and any event whose title
    /// starts with `title` in the days around `day` — even when it failed.
    private func cleaning(_ api: API, title: String, day: String,
                          _ body: (_ made: (AgendaEvent) -> Void) async throws -> Void) async throws {
        var made: [AgendaEvent] = []
        var failure: Error?
        do { try await body { made.append($0) } } catch { failure = error }
        for ev in made { try? await api.agendaDelete(ev.id, calendar: ev.calendarId) }
        let around = (try? await api.agendaEvents(from: AgendaClock.addDays(day, -7), to: AgendaClock.addDays(day, 60))) ?? []
        for ev in around where ev.title.hasPrefix(title) {
            let id = ev.recurringEventId.isEmpty ? ev.id : ev.recurringEventId
            try? await api.agendaDelete(id, calendar: ev.calendarId)
        }
        let left = (try? await api.agendaEvents(from: AgendaClock.addDays(day, -7), to: AgendaClock.addDays(day, 60))) ?? []
        #expect(!left.contains { $0.title.hasPrefix(title) }, "the test left \(title) behind")
        if let failure { throw failure }
    }

    // MARK: Reading

    @Test func aMonthGridIsReadAsTheAgendaReadsIt() async throws {
        let api = try Dev.api()
        let clock = try await clock(api)
        let ym = AgendaClock.ym(clock.today())
        let grid = AgendaClock.monthGrid(ym)
        let events = try await api.agendaEvents(from: grid.first, to: AgendaClock.addDays(grid.last, 1))
        #expect(events.allSatisfy { !$0.id.isEmpty && !$0.start.isEmpty })
        // Through the store, as the month view loads it.
        let data = AgendaData()
        await data.loadMonth(ym, clock: clock, api: api)
        #expect(data.monthErrors[ym] == nil)
        #expect(try Set(try #require(data.months[ym]).map(\.id)) == Set(events.map(\.id)))
        await data.loadUpcoming(from: clock.today(), days: 14, clock: clock, api: api)
        #expect(data.upcomingError == nil && data.upcoming != nil && data.upcomingFrom == clock.today())
    }

    @Test func aWholeYearIsReadAndMoreIsRefused() async throws {
        let api = try Dev.api()
        let clock = try await clock(api)
        let today = clock.today()
        _ = try await api.agendaEvents(from: today, to: AgendaClock.addDays(today, 365))
        await #expect {
            _ = try await api.agendaEvents(from: today, to: AgendaClock.addDays(today, 500))
        } throws: { ($0 as? APIError)?.status == 400 && !$0.localizedDescription.isEmpty }
    }

    @Test func theHouseholdTheFamilyAndTheInboxesDecode() async throws {
        let api = try Dev.api()
        let household = try await api.agendaHousehold()
        #expect(!household.defaultCalendar.isEmpty || !household.available.isEmpty)
        let people = try await api.agendaFamily()
        #expect(!people.isEmpty && people.allSatisfy { !$0.key.isEmpty && !$0.name.isEmpty })
        #expect(people.allSatisfy { $0.hex.isEmpty || AgendaPalette.color($0.hex) != nil }, "every colour reads")
        _ = try await api.agendaNotifyEmails()
        let data = AgendaData()
        await data.loadBasics(api)
        #expect(data.basicsLoaded && data.people.map(\.key) == people.map(\.key))
    }

    @Test func anEventThatIsNotThereIsASentence() async throws {
        let api = try Dev.api()
        await #expect {
            _ = try await api.agendaEvent("ios-test-no-such-event", calendar: nil)
        } throws: { ($0 as? APIError)?.status == 404 && $0.localizedDescription == "no such event" }
    }

    // MARK: Writing

    @Test func anEventIsCreatedReadUpdatedAndDeleted() async throws {
        let api = try Dev.api()
        let clock = try await clock(api)
        let day = quietDay(clock)
        let title = Dev.title("crud")
        try await cleaning(api, title: title, day: day) { made in
            let created = try await api.agendaCreate(AgendaEventInput(
                title: title, start: "\(day)T15:00", end: "\(day)T15:45", location: "Clinic",
                description: "Bring the forms.", recurrence: "", attendees: []))
            made(created)
            #expect(created.title == title && created.attendees.isEmpty && !created.readOnly && !created.isAllDay)
            let start = try #require(clock.instant(created.start)), end = try #require(clock.instant(created.end))
            #expect(clock.startDay(created) == day)
            #expect(clock.input(start) == "\(day)T15:00", "the wall clock is read in the member's zone")
            #expect(clock.input(end) == "\(day)T15:45")

            let read = try await api.agendaEvent(created.id, calendar: created.calendarId)
            #expect(read.id == created.id && read.location == "Clinic" && read.description == "Bring the forms.")
            #expect(try await api.agendaEvent(created.id, calendar: nil).id == created.id)

            let listed = try await api.agendaEvents(from: day, to: AgendaClock.addDays(day, 1))
            #expect(listed.contains { $0.id == created.id })
            #expect(clock.byDay(listed, from: day, to: day)[day]?.contains { $0.id == created.id } == true)

            let updated = try await api.agendaUpdate(created.id, calendar: created.calendarId, AgendaEventInput(
                title: title + " moved", start: "\(day)T16:00", end: "\(day)T17:30", location: "Home", description: ""))
            #expect(updated.title == title + " moved" && updated.location == "Home" && updated.description.isEmpty)
            let moved = try #require(clock.instant(updated.start))
            #expect(clock.input(moved) == "\(day)T16:00")

            try await api.agendaDelete(created.id, calendar: created.calendarId)
            await #expect {
                _ = try await api.agendaEvent(created.id, calendar: nil)
            } throws: { ($0 as? APIError)?.status == 404 }
        }
    }

    @Test func anAllDayEventCoversItsDaysAndNoMore() async throws {
        let api = try Dev.api()
        let clock = try await clock(api)
        let day = quietDay(clock)
        let title = Dev.title("all-day")
        try await cleaning(api, title: title, day: day) { made in
            let created = try await api.agendaCreate(AgendaEventInput(
                title: title, start: day, end: AgendaClock.addDays(day, 2), attendees: []))
            made(created)
            #expect(created.isAllDay && created.start == day && created.end == AgendaClock.addDays(day, 2))
            let listed = try await api.agendaEvents(from: AgendaClock.addDays(day, -1), to: AgendaClock.addDays(day, 4))
            let mine = try #require(listed.first { $0.id == created.id })
            #expect(clock.days(mine, from: AgendaClock.addDays(day, -1), to: AgendaClock.addDays(day, 4))
                    == [day, AgendaClock.addDays(day, 1)])
            #expect(clock.range(mine).contains(" – "))
        }
    }

    @Test func theEditorsFormRoundTripsThroughTheServer() async throws {
        // What the editor would send for an event it opened, unchanged, leaves it as it was.
        let api = try Dev.api()
        let clock = try await clock(api)
        let day = quietDay(clock)
        let title = Dev.title("form")
        let people = try await api.agendaFamily()
        let kids = people.filter(\.email.isEmpty).prefix(2).map(\.key)
        try await cleaning(api, title: title, day: day) { made in
            var f = EventForm.new(on: day, clock: clock)
            f.title = title
            f.repeats = .weekly
            f.leaders = kids
            f.description = "Notes with https://example.com/page"
            let body = try f.input(clock: clock, isEdit: false, seeded: true, original: nil).get()
            let created = try await api.agendaCreate(body)
            made(created)
            #expect(created.leaderKeys == kids && created.attendees.isEmpty)
            #expect(AgendaRepeat.of(created.recurrence) == .weekly)
            #expect(clock.startDay(created) == day)

            let reopened = EventForm(created, clock: clock)
            #expect(reopened.start == f.start && reopened.end == f.end && reopened.leaders == kids)
            let same = try reopened.input(clock: clock, isEdit: true, seeded: false, original: created).get()
            #expect(same.leader == nil)
            let saved = try await api.agendaUpdate(created.id, calendar: created.calendarId, same)
            #expect(saved.start == created.start && saved.end == created.end && saved.recurrence == created.recurrence)
            #expect(saved.leaderKeys == kids && saved.description == created.description)
        }
    }

    @Test func everyOfferedRepeatRoundTrips() async throws {
        let api = try Dev.api()
        let clock = try await clock(api)
        let day = quietDay(clock)
        let title = Dev.title("repeats")
        try await cleaning(api, title: title, day: day) { made in
            let created = try await api.agendaCreate(AgendaEventInput(
                title: title, start: "\(day)T09:00", end: "\(day)T09:30",
                recurrence: AgendaRepeat.daily.word, attendees: []))
            made(created)
            #expect(AgendaRepeat.of(created.recurrence) == .daily)
            for choice in AgendaRepeat.offered {
                let saved = try await api.agendaUpdate(created.id, calendar: created.calendarId, AgendaEventInput(
                    title: title, start: "\(day)T09:00", end: "\(day)T09:30", recurrence: choice.word))
                #expect(AgendaRepeat.of(saved.recurrence) == choice, "\(choice) was saved as \(saved.recurrence)")
                let read = try await api.agendaEvent(created.id, calendar: created.calendarId)
                #expect(AgendaRepeat.of(read.recurrence) == choice)
                if choice == .weekly {
                    #expect(AgendaRepeat.describe(read.recurrence, locale: Locale(identifier: "en_US"))
                            == "Every week on \(AgendaFixtures.newYork.dayName(day, long: true))")
                }
            }
        }
    }

    @Test func aKeptRuleRepeatsAsItSaysAndItsOccurrencesKnowTheirSeries() async throws {
        let api = try Dev.api()
        let clock = try await clock(api)
        let day = quietDay(clock)
        let title = Dev.title("custom")
        try await cleaning(api, title: title, day: day) { made in
            let created = try await api.agendaCreate(AgendaEventInput(
                title: title, start: "\(day)T09:00", end: "\(day)T09:30",
                recurrence: "FREQ=DAILY;COUNT=3", attendees: []))
            made(created)
            #expect(AgendaRepeat.of(created.recurrence) == .custom)
            #expect(AgendaRepeat.describe(created.recurrence, locale: Locale(identifier: "en_US")) == "Every day, 3 times")
            let listed = try await api.agendaEvents(from: day, to: AgendaClock.addDays(day, 7))
                .filter { $0.title == title }
            #expect(listed.count == 3)
            #expect(listed.allSatisfy { $0.isRecurring && $0.recurringEventId == created.id })
            #expect(clock.sorted(listed).map(clock.startDay) == [day, AgendaClock.addDays(day, 1), AgendaClock.addDays(day, 2)])
            // The editor leaves a kept rule out of what it sends: it stays.
            var f = EventForm(created, clock: clock)
            f.title = title + " renamed"
            let saved = try await api.agendaUpdate(created.id, calendar: created.calendarId,
                                                   try f.input(clock: clock, isEdit: true, seeded: false, original: created).get())
            #expect(saved.recurrence == created.recurrence && saved.title == title + " renamed")
        }
    }

    @Test func anOccurrenceChangesAndGoesAloneOrWithItsSeries() async throws {
        let api = try Dev.api()
        let clock = try await clock(api)
        let day = quietDay(clock)
        let title = Dev.title("occurrence")
        try await cleaning(api, title: title, day: day) { made in
            let created = try await api.agendaCreate(AgendaEventInput(
                title: title, start: "\(day)T09:00", end: "\(day)T09:30", recurrence: "daily", attendees: []))
            made(created)
            func listed() async throws -> [AgendaEvent] {
                clock.sorted(try await api.agendaEvents(from: day, to: AgendaClock.addDays(day, 3)).filter { $0.title.hasPrefix(title) })
            }
            let before = try await listed()
            #expect(before.count == 4 && before.allSatisfy { $0.occurrence && $0.recurrence == created.recurrence },
                    "each occurrence carries its series' rule")
            // As the editor sends it: the repeat it showed is not sent back.
            var f = EventForm(before[1], clock: clock)
            f.title = title + " alone"
            _ = try await api.agendaUpdate(before[1].id, calendar: before[1].calendarId,
                                           try f.input(clock: clock, isEdit: true, seeded: false, original: before[1]).get(),
                                           scope: .this)
            try await api.agendaDelete(before[2].id, calendar: before[2].calendarId, scope: .this)
            let after = try await listed()
            #expect(after.map(\.title) == [title, title + " alone", title])
            #expect(try await api.agendaEvent(created.id, calendar: created.calendarId).recurrence == created.recurrence)
            try await api.agendaDelete(after[2].id, calendar: after[2].calendarId, scope: .series)
            #expect(try await listed().isEmpty)
        }
    }

    @Test func aRuleTheServerCannotReadIsRefusedWithASentence() async throws {
        let api = try Dev.api()
        let clock = try await clock(api)
        let day = quietDay(clock)
        let title = Dev.title("bad-rule")
        try await cleaning(api, title: title, day: day) { made in
            do {
                made(try await api.agendaCreate(AgendaEventInput(
                    title: title, start: "\(day)T09:00", end: "\(day)T09:30", recurrence: "FREQ=NOPE", attendees: [])))
                Issue.record("an unreadable rule was accepted")
            } catch {
                #expect((error as? APIError)?.status == 400 && error.localizedDescription.contains("is not a repeat rule"),
                        "\(error)")
            }
        }
    }
}
