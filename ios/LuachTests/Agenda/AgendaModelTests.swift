import Foundation
import Testing
@testable import Luach

/// The agenda's shapes, read as dev sends them and as an older server might leave them out.
@Suite(.timeLimit(.minutes(1)))
struct AgendaModelTests {
    @Test func anEventReadsEveryField() throws {
        let ev = try AgendaFixtures.event(AgendaFixtures.timed)
        #expect(ev.id == "4fd5aabcaffd" && ev.title == "Dentist")
        #expect(ev.start == "2026-11-03T15:00:00-05:00" && ev.end == "2026-11-03T15:45:00-05:00")
        #expect(!ev.allDay && !ev.isAllDay)
        #expect(ev.location == "Clinic" && ev.description.contains("<a href"))
        #expect(ev.recurrence == ["RRULE:FREQ=WEEKLY;BYDAY=TU"] && ev.recurringEventId.isEmpty)
        #expect(ev.calendarId == "fake" && ev.htmlLink.isEmpty && !ev.readOnly)
        #expect(ev.attendees.isEmpty && ev.inviteError.isEmpty && ev.organizer.isEmpty)
        #expect(ev.leader == "ruby" && ev.leaders == ["ruby", "lily"])
        #expect(ev.isRecurring && ev.displayTitle == "Dentist")
        #expect(ev.leaderKeys == ["ruby", "lily"])
        #expect(!ev.occurrence && !ev.isOccurrence, "the series itself")
    }

    @Test func anOccurrenceCarriesItsSeriesRule() throws {
        let ev = try AgendaFixtures.event(AgendaFixtures.occurrence)
        #expect(ev.recurrence == ["RRULE:FREQ=WEEKLY;BYDAY=TU"] && ev.recurringEventId == "4fd5aabcaffd")
        #expect(ev.occurrence && ev.isOccurrence && ev.isRecurring)
    }

    @Test func anOlderServersOccurrenceIsOneByItsSeries() throws {
        let ev = try AgendaFixtures.event(["id": "s_20261110T150000", "recurrence": [], "recurring_event_id": "s"])
        #expect(!ev.occurrence && ev.isOccurrence && ev.isRecurring)
    }

    @Test func anInvitationIsReadOnlyWithItsGuests() throws {
        let ev = try AgendaFixtures.event(AgendaFixtures.invitation)
        #expect(ev.readOnly && ev.organizer == "boss@example.com")
        #expect(ev.attendees == ["ana@example.com", "sam@example.com"])
        #expect(ev.htmlLink.hasPrefix("https://calendar.google.com/") && !ev.isRecurring)
        #expect(ev.leaderKeys.isEmpty)
    }

    @Test func anEventWithOnlyAnIdStillDecodes() throws {
        let ev = try AgendaFixtures.event(["id": "x"])
        #expect(ev.title.isEmpty && ev.start.isEmpty && ev.end.isEmpty && !ev.allDay)
        #expect(ev.recurrence.isEmpty && ev.attendees.isEmpty && ev.leaders.isEmpty && !ev.readOnly)
        #expect(ev.displayTitle == "(untitled)" && !ev.isRecurring && !ev.isAllDay)
    }

    @Test func fieldsOfTheWrongKindAreLeftEmpty() throws {
        let ev = try AgendaFixtures.event([
            "id": "x", "title": NSNull(), "all_day": "yes", "attendees": "a@example.com",
            "recurrence": NSNull(), "read_only": 1.5, "leaders": [1, 2],
        ])
        #expect(ev.title.isEmpty && !ev.allDay && ev.attendees.isEmpty && ev.recurrence.isEmpty)
        #expect(!ev.readOnly && ev.leaders.isEmpty)
    }

    @Test func anEventWithoutAnIdIsRefused() {
        #expect(throws: DecodingError.self) { try AgendaFixtures.event(["title": "no id"]) }
    }

    @Test func aDayShapedStartIsAllDayWhateverTheFlagSays() throws {
        let ev = try AgendaFixtures.event(["id": "x", "start": "2026-11-05", "end": "2026-11-06"])
        #expect(!ev.allDay && ev.isAllDay)
        #expect(try AgendaFixtures.event(AgendaFixtures.allDay).isAllDay)
    }

    @Test func oneLeaderIsTheWholeListWhenTheListIsMissing() throws {
        #expect(try AgendaFixtures.event(["id": "x", "leader": "ruby"]).leaderKeys == ["ruby"])
        #expect(try AgendaFixtures.event(["id": "x", "leader": "ruby", "leaders": []]).leaderKeys == ["ruby"])
        #expect(try AgendaFixtures.event(["id": "x", "leader": "", "leaders": []]).leaderKeys == [])
    }

    @Test func aPersonIsCalledByTheirKeyWithoutAName() throws {
        let p = try JSONDecoder.snake.decode(AgendaPerson.self, from: Data(#"{"key":"ruby"}"#.utf8))
        #expect(p.id == "ruby" && p.name == "ruby" && p.hex.isEmpty && p.email.isEmpty)
        #expect(throws: DecodingError.self) {
            try JSONDecoder.snake.decode(AgendaPerson.self, from: Data(#"{"name":"Ruby"}"#.utf8))
        }
    }

    @Test func theHouseholdReadsItsCalendars() throws {
        let h = try JSONDecoder.snake.decode(AgendaHousehold.self,
                                             from: JSONSerialization.data(withJSONObject: AgendaFixtures.household))
        #expect(h.defaultCalendar == "fake" && h.defaultAttendees == ["grandma@example.com"])
        #expect(h.available.map(\.id) == ["family@example.com", "fake", "holidays", "old"])
        let fake = h.available[1]
        #expect(fake.isDefault && fake.writable && fake.enabled && fake.color == "#33b679" && fake.name == "luach (local)")
        #expect(!h.available[2].writable && !h.available[3].enabled)
    }

    @Test func anEmptyHouseholdIsEmptyNotAnError() throws {
        let h = try JSONDecoder.snake.decode(AgendaHousehold.self, from: Data("{}".utf8))
        #expect(h.defaultCalendar.isEmpty && h.defaultAttendees.isEmpty && h.available.isEmpty)
        let c = try JSONDecoder.snake.decode(AgendaCalendarInfo.self, from: Data(#"{"id":"c1"}"#.utf8))
        #expect(c.name == "c1" && c.color.isEmpty && !c.writable && !c.enabled && !c.isDefault)
    }

    @Test func theSheetsHaveIdsOfTheirOwn() throws {
        let ev = try AgendaFixtures.event(AgendaFixtures.timed)
        #expect(AgendaSheet.view(ev).id == "view-4fd5aabcaffd")
        #expect(AgendaSheet.edit(ev).id == "edit-4fd5aabcaffd")
        #expect(AgendaSheet.create("2026-11-03").id == "create-2026-11-03")
    }
}

/// The calls the agenda makes, as luach receives them.
@MainActor
@Suite(.timeLimit(.minutes(1)))
struct AgendaAPITests {
    let server = StubServer()

    @Test func eventsAreReadForADayRange() async throws {
        server.on("GET", "/api/calendar/events", json: [
            "events": [AgendaFixtures.occurrence, AgendaFixtures.allDay],
            "timezone": "America/New_York", "start": "2026-11-01", "end": "2026-11-30",
        ])
        let events = try await server.api.agendaEvents(from: "2026-11-01", to: "2026-11-30")
        #expect(events.map(\.id) == ["4fd5aabcaffd_20261110T150000", "b4fb50149034"])
        let sent = try #require(server.requests("GET", "/api/calendar/events").first)
        #expect(sent.query == ["start": "2026-11-01", "end": "2026-11-30"])
    }

    @Test func oneEventIsReadFromItsCalendarWhenItIsKnown() async throws {
        server.on("GET", "/api/calendar/events/4fd5aabcaffd", json: AgendaFixtures.timed)
        let ev = try await server.api.agendaEvent("4fd5aabcaffd", calendar: "fake")
        _ = try await server.api.agendaEvent("4fd5aabcaffd", calendar: nil)
        _ = try await server.api.agendaEvent("4fd5aabcaffd", calendar: "")
        #expect(ev.title == "Dentist")
        let sent = server.requests("GET", "/api/calendar/events/4fd5aabcaffd").map(\.query)
        #expect(sent == [["calendar": "fake"], [:], [:]])
    }

    @Test func creatingSendsOnlyWhatIsSet() async throws {
        server.on("POST", "/api/calendar/events", json: AgendaFixtures.timed)
        let body = AgendaEventInput(title: "Dentist", start: "2026-11-03T15:00", end: "2026-11-03T15:45",
                                    location: "Clinic", description: nil, recurrence: "RRULE:FREQ=WEEKLY;BYDAY=TU",
                                    calendarId: "fake", attendees: [], leader: "ruby,lily")
        let ev = try await server.api.agendaCreate(body)
        #expect(ev.id == "4fd5aabcaffd")
        let sent = try #require(server.requests("POST", "/api/calendar/events").first)
        #expect(Set(sent.json.keys) == ["title", "start", "end", "location", "recurrence", "calendar_id", "attendees", "leader"])
        #expect(sent.json["calendar_id"] as? String == "fake")
        #expect(sent.json["attendees"] as? [String] == [], "an empty list is sent: it means nobody")
        #expect(sent.json["leader"] as? String == "ruby,lily")
        #expect(sent.headers["Content-Type"] == "application/json")
    }

    @Test func noAttendeesKeyLeavesTheHouseholdsDefault() async throws {
        server.on("POST", "/api/calendar/events", json: AgendaFixtures.allDay)
        _ = try await server.api.agendaCreate(AgendaEventInput(title: "Trip", start: "2026-11-05"))
        let sent = try #require(server.requests("POST", "/api/calendar/events").first)
        #expect(Set(sent.json.keys) == ["title", "start"])
    }

    @Test func updatingPatchesTheEventInItsCalendar() async throws {
        server.on("PATCH", "/api/calendar/events/4fd5aabcaffd", json: AgendaFixtures.timed)
        let body = AgendaEventInput(title: "Dentist", start: "2026-11-03T16:00", end: "2026-11-03T16:45", recurrence: "")
        _ = try await server.api.agendaUpdate("4fd5aabcaffd", calendar: "fake", body)
        _ = try await server.api.agendaUpdate("4fd5aabcaffd", calendar: nil, body)
        _ = try await server.api.agendaUpdate("4fd5aabcaffd", calendar: "fake", body, scope: .this)
        _ = try await server.api.agendaUpdate("4fd5aabcaffd", calendar: nil, body, scope: .series)
        let sent = server.requests("PATCH", "/api/calendar/events/4fd5aabcaffd")
        #expect(sent.map(\.query) == [["calendar": "fake"], [:], ["calendar": "fake", "scope": "this"], ["scope": "series"]])
        #expect(sent[0].json["recurrence"] as? String == "", "an empty rule removes the repeat")
        #expect(sent[0].json["start"] as? String == "2026-11-03T16:00")
    }

    @Test func deletingAnswersOk() async throws {
        server.on("DELETE", "/api/calendar/events/b4fb50149034", json: ["ok": true, "guest_told": false])
        try await server.api.agendaDelete("b4fb50149034", calendar: "fake")
        try await server.api.agendaDelete("b4fb50149034", calendar: nil, scope: .this)
        try await server.api.agendaDelete("b4fb50149034", calendar: "fake", scope: .series)
        #expect(server.requests("DELETE", "/api/calendar/events/b4fb50149034").map(\.query)
                == [["calendar": "fake"], ["scope": "this"], ["calendar": "fake", "scope": "series"]])
    }

    @Test func theServersSentenceIsTheError() async {
        server.fail("POST", "/api/calendar/events", status: 400, "FREQ=NOPE is not a repeat rule, e.g. FREQ=WEEKLY;BYDAY=TU")
        server.fail("DELETE", "/api/calendar/events/gone", status: 404, "no such event")
        server.fail("GET", "/api/calendar/events", status: 400, "at most 400 days at a time")
        await #expect {
            _ = try await server.api.agendaCreate(AgendaEventInput(title: "x", start: "2026-11-03T15:00", recurrence: "FREQ=NOPE"))
        } throws: { ($0 as? APIError)?.status == 400 && $0.localizedDescription.hasPrefix("FREQ=NOPE is not a repeat rule") }
        await #expect {
            try await server.api.agendaDelete("gone", calendar: nil)
        } throws: { ($0 as? APIError)?.status == 404 && $0.localizedDescription == "no such event" }
        await #expect {
            _ = try await server.api.agendaEvents(from: "2026-01-01", to: "2028-01-01")
        } throws: { $0.localizedDescription == "at most 400 days at a time" }
    }

    @Test func theHouseholdAndTheFamilyAreRead() async throws {
        server.on("GET", "/api/household/calendars", json: AgendaFixtures.household)
        server.on("GET", "/api/family", json: AgendaFixtures.family)
        let h = try await server.api.agendaHousehold()
        let people = try await server.api.agendaFamily()
        #expect(h.defaultCalendar == "fake" && h.available.count == 4)
        #expect(people.map(\.key) == ["robin", "ruby", "lily"])
        #expect(people[1].hex == "#33b679" && people[1].email.isEmpty && people[0].email == "robin@example.com")
    }

    @Test func theMembersAlsoNotifyInboxesAreRead() async throws {
        server.on("GET", "/api/auth/me", json: AgendaFixtures.me)
        #expect(try await server.api.agendaNotifyEmails() == ["work@example.com", "grandma@example.com"])
        // An older server's member carries none.
        server.on("GET", "/api/auth/me", json: ["id": 1, "username": "robin"])
        #expect(try await server.api.agendaNotifyEmails() == [])
    }
}
