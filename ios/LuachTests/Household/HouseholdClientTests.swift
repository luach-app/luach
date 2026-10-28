import Foundation
import Testing
@testable import Luach

/// Every call the Household area makes, against a stub luach: the path, the body it sends,
/// what it reads back, and the server's sentence when it refuses (which is what the screens show).
@MainActor
struct HouseholdClientTests {
    typealias H = HouseholdArea
    typealias F = HouseholdFixtures
    let server = StubServer()
    var client: H.Client { H.Client(api: server.api) }

    /// The call throws luach's sentence, as the screen shows it (`error.localizedDescription`).
    private func refuses(_ status: Int, _ sentence: String, _ call: () async throws -> Void) async {
        await #expect {
            try await call()
        } throws: { error in
            (error as? APIError)?.status == status && error.localizedDescription == sentence
        }
    }

    // MARK: Household

    @Test func theCalendarsAreRead() async throws {
        server.on("GET", "/api/household/calendars", json: F.calendars)
        let c = try await client.calendars()
        #expect(c.enabledList.first?.name == "Family")
        #expect(server.requests("GET", "/api/household/calendars").count == 1)
    }

    @Test func savingTheHouseholdSendsAllThree() async throws {
        server.on("PATCH", "/api/household", json: [
            "calendars": ["a"], "default_calendar": "a", "default_attendees": ["x@example.com"],
        ])
        try await client.saveHousehold(H.HouseholdPatch(calendars: ["a"], defaultCalendar: "a", defaultAttendees: ["x@example.com"]))
        let sent = try #require(server.requests("PATCH", "/api/household").first)
        #expect(sent.json["calendars"] as? [String] == ["a"])
        #expect(sent.json["default_calendar"] as? String == "a")
        #expect(sent.json["default_attendees"] as? [String] == ["x@example.com"])
        #expect(sent.headers["Content-Type"] == "application/json")
    }

    @Test func theHouseholdsRefusalsAreItsSentences() async {
        server.fail("PATCH", "/api/household", status: 400, "not an email address: bob")
        await refuses(400, "not an email address: bob") {
            try await client.saveHousehold(H.HouseholdPatch(calendars: ["a"], defaultCalendar: "a", defaultAttendees: ["bob"]))
        }
        server.fail("PATCH", "/api/household", status: 502, "the calendar could not be reached")
        await refuses(502, "the calendar could not be reached") {
            try await client.saveHousehold(H.HouseholdPatch(calendars: ["a"], defaultCalendar: "a", defaultAttendees: []))
        }
        server.fail("GET", "/api/household/calendars", status: 403, "only the owner can change the household")
        await refuses(403, "only the owner can change the household") { _ = try await client.calendars() }
    }

    // MARK: Booking

    @Test func theBookingIsRead() async throws {
        server.on("GET", "/api/booking", json: F.booking())
        let b = try await client.booking()
        #expect(b.settings.slug == "robin" && b.link.hasSuffix("/book/robin") && b.zoomReady == false)
    }

    @Test func savingTheBookingSendsEverySettingWithTheWeeklyHours() async throws {
        var settings = try F.decode(H.Booking.self, F.booking()).settings
        settings.slug = "  robin-h "
        settings.hours["sat"] = [["10:00", "12:00"]]
        settings.hours["tue"] = [["09:00", "12:00"]]
        settings.slotMinutes = 45
        server.on("PATCH", "/api/booking") { req in
            // Answer with what was sent, as luach does.
            var answer = req.json
            answer["link"] = "https://luach.example.com/book/\(answer["slug"] as? String ?? "")"
            answer["timezone"] = "America/New_York"
            answer["zoom_ready"] = true
            return .init(body: F.data(answer))
        }
        let next = try await client.saveBooking(settings)
        let sent = try #require(server.requests("PATCH", "/api/booking").first)
        #expect(sent.json["slug"] as? String == "robin-h", "the link name is sent trimmed")
        #expect(sent.json["slot_minutes"] as? Int == 45)
        let hours = try #require(sent.json["hours"] as? [String: [[String]]])
        #expect(hours["sat"] == [["10:00", "12:00"]] && hours["tue"] == [["09:00", "12:00"]] && hours["sun"] == [])
        #expect(hours.count == 7)
        #expect(sent.json["link"] == nil && sent.json["zoom_ready"] == nil && sent.json["timezone"] == nil)
        #expect(next.settings.slug == "robin-h" && next.link.hasSuffix("/book/robin-h") && next.zoomReady == true)
    }

    @Test(arguments: [
        "the link name is 2-40 chars: letters, digits and dashes",
        "another member already uses that link name",
        "the window 17:00–09:00 ends before it starts",
        "set at least one window of hours before publishing the link",
        "that calendar is not one of the household's",
    ])
    func theBookingsRefusalsAreItsSentences(_ sentence: String) async throws {
        let settings = try F.decode(H.Booking.self, F.booking()).settings
        server.fail("PATCH", "/api/booking", status: 400, sentence)
        await refuses(400, sentence) { _ = try await client.saveBooking(settings) }
    }

    @Test func theUpcomingBookingsAreRead() async throws {
        server.on("GET", "/api/booking/upcoming", json: F.upcoming)
        let rows = try await client.upcoming()
        #expect(rows.map(\.eventId) == ["ev123", "ev456"])
        server.on("GET", "/api/booking/upcoming", json: ["bookings": []])
        #expect(try await client.upcoming().isEmpty)
    }

    @Test func cancellingABookingDeletesItsEvent() async throws {
        let row = try #require(try F.decode(H.BookingRows.self, F.upcoming).bookings.first)
        server.on("DELETE", "/api/calendar/events/ev123", json: ["ok": true, "guest_told": true])
        try await client.cancel(row)
        #expect(server.requests("DELETE", "/api/calendar/events/ev123").count == 1)
        server.fail("DELETE", "/api/calendar/events/ev123", status: 404, "no such event")
        await refuses(404, "no such event") { try await client.cancel(row) }
    }

    // MARK: Busy feeds

    @Test func theFeedsAreRead() async throws {
        server.on("GET", "/api/busy", json: ["sources": [F.source()]])
        #expect(try await client.busy().map(\.name) == ["Work"])
    }

    @Test func addingAFeedSendsItsNameAndAddressTrimmed() async throws {
        server.on("POST", "/api/busy", json: ["sources": [F.source(name: "Job")]])
        let after = try await client.addBusy(name: "  Job ", url: "  https://example.com/cal.ics\n")
        #expect(after.map(\.name) == ["Job"])
        let sent = try #require(server.requests("POST", "/api/busy").first)
        #expect(sent.json["name"] as? String == "Job" && sent.json["url"] as? String == "https://example.com/cal.ics")
    }

    @Test func aFeedWithNoNameIsCalledWork() async throws {
        server.on("POST", "/api/busy", json: ["sources": [F.source()]])
        _ = try await client.addBusy(name: "   ", url: "https://example.com/cal.ics")
        #expect(server.requests("POST", "/api/busy").first?.json["name"] as? String == "Work")
    }

    @Test func aFeedIsChangedRemovedAndReadAgain() async throws {
        server.on("PATCH", "/api/busy/2", json: ["sources": [F.source()]])
        server.on("DELETE", "/api/busy/2", json: ["ok": true, "sources": []])
        server.on("POST", "/api/busy/refresh", json: ["read": 1, "sources": [F.source(blocks: 9)]])
        _ = try await client.updateBusy(2, ["enabled": false])
        _ = try await client.updateBusy(2, ["show_in_agenda": true])
        let patches = server.requests("PATCH", "/api/busy/2")
        #expect(patches.count == 2)
        #expect(patches[0].json as NSDictionary == ["enabled": false])
        #expect(patches[1].json as NSDictionary == ["show_in_agenda": true])
        #expect(try await client.refreshBusy().first?.blocks == 9)
        #expect(try await client.removeBusy(2).isEmpty)
        #expect(server.requests("POST", "/api/busy/refresh").count == 1)
    }

    @Test func theFeedsRefusalsAreItsSentences() async {
        server.fail("POST", "/api/busy", status: 400, "that is not a calendar feed address")
        await refuses(400, "that is not a calendar feed address") { _ = try await client.addBusy(name: "", url: "nope") }
        server.fail("POST", "/api/busy", status: 400, "at most 5 calendars")
        await refuses(400, "at most 5 calendars") { _ = try await client.addBusy(name: "", url: "https://example.com") }
        server.fail("DELETE", "/api/busy/9", status: 404, "that calendar is not yours")
        await refuses(404, "that calendar is not yours") { _ = try await client.removeBusy(9) }
        server.fail("PATCH", "/api/busy/9", status: 404, "that calendar is not yours")
        await refuses(404, "that calendar is not yours") { _ = try await client.updateBusy(9, ["enabled": true]) }
        server.on("POST", "/api/busy/refresh", status: 502, raw: "<html>bad gateway</html>", contentType: "text/html")
        await #expect(throws: APIError.self) { _ = try await client.refreshBusy() }
    }

    // MARK: Reminders

    @Test func remindersAreReadAndSaved() async throws {
        server.on("GET", "/api/reminders", json: F.reminders)
        var r = try await client.reminders()
        #expect(r.leadMinutes == 30 && r.weeklyDay == 6)
        r.byEmail = true
        r.eveningHour = -1
        server.on("PATCH", "/api/reminders") { req in .init(body: req.body) }
        let saved = try await client.saveReminders(r)
        #expect(saved == r)
        let sent = try #require(server.requests("PATCH", "/api/reminders").first)
        #expect(sent.json as NSDictionary == [
            "lead_minutes": 30, "evening_hour": -1, "weekly_day": 6, "weekly_hour": 18, "by_email": true,
        ])
    }

    @Test func remindersRefusalsAreTheirSentences() async {
        server.fail("PATCH", "/api/reminders", status: 400, "the warning must be between 0 and 10080")
        await refuses(400, "the warning must be between 0 and 10080") {
            _ = try await client.saveReminders(.init(leadMinutes: -5, eveningHour: -1, weeklyDay: -1, weeklyHour: 18, byEmail: false))
        }
        server.on("GET", "/api/reminders", status: 500, raw: "", contentType: "text/plain")
        await #expect { _ = try await client.reminders() } throws: { error in
            (error as? APIError)?.status == 500 && !error.localizedDescription.isEmpty
        }
    }
}
