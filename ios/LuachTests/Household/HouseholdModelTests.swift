import Foundation
import SwiftUI
import Testing
import UIKit
@testable import Luach

/// The Household area's shapes, read and written as luach sends them (docs/API.md), and the
/// small rules beside them: the address check, "read … ago", the colours.
@MainActor
struct HouseholdModelTests {
    typealias H = HouseholdArea
    typealias F = HouseholdFixtures

    // MARK: Household calendars

    @Test func theCalendarsDecodeWithEverythingTheCredentialSees() throws {
        let c = try F.decode(H.Calendars.self, F.calendars)
        #expect(c.available.count == 4)
        #expect(c.calendars.count == 3 && c.defaultCalendar == "family@group.calendar.google.com")
        #expect(c.defaultAttendees == ["grandma@example.com"])
        let holidays = try #require(c.available.first { $0.name == "Holidays" })
        #expect(holidays.color == nil && holidays.primary == nil && !holidays.writable && holidays.enabled)
        #expect(c.available[0].id == "family@group.calendar.google.com" && c.available[0].default)
    }

    @Test func theEnabledListPutsTheDefaultFirstThenByName() throws {
        let c = try F.decode(H.Calendars.self, F.calendars)
        #expect(c.enabledList.map(\.name) == ["Family", "Ana", "Holidays"])
        let dev = try F.decode(H.Calendars.self, F.devCalendars)
        #expect(dev.enabledList.isEmpty, "dev's only visible calendar is not ticked")
    }

    @Test func theHouseholdPatchIsSnakeCase() throws {
        let patch = H.HouseholdPatch(calendars: ["a", "b"], defaultCalendar: "b", defaultAttendees: ["x@example.com"])
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        let json = try #require(try JSONSerialization.jsonObject(with: e.encode(patch)) as? [String: Any])
        #expect(json["calendars"] as? [String] == ["a", "b"])
        #expect(json["default_calendar"] as? String == "b")
        #expect(json["default_attendees"] as? [String] == ["x@example.com"])
        #expect(json.count == 3)
    }

    // MARK: Booking

    @Test func theBookingDecodesItsSettingsBesideTheServersOwn() throws {
        let b = try F.decode(H.Booking.self, F.booking())
        #expect(b.link == "https://luach.example.com/book/robin")
        #expect(b.timezone == "America/New_York" && b.zoomReady == false)
        let s = b.settings
        #expect(s.enabled && s.slug == "robin" && s.slotMinutes == 30 && s.maxPerDay == 2)
        #expect(s.bufferMinutes == 15 && s.leadHours == 12 && s.horizonDays == 21)
        #expect(s.title == "Meeting with {name}" && s.location.isEmpty && s.note.isEmpty)
        #expect(s.calendarId.isEmpty && s.notifyHost && s.conferencing == "none")
        #expect(s.hours["tue"] == [["09:00", "12:00"], ["14:00", "17:00"]])
        #expect(s.hours["sat"] == [])
    }

    @Test func aBookingFromBeforeZoomHasNoZoomReady() throws {
        var json = F.booking()
        json.removeValue(forKey: "zoom_ready")
        #expect(try F.decode(H.Booking.self, json).zoomReady == nil)
    }

    @Test func aBookingWithoutItsLinkDoesNotDecode() {
        var json = F.booking()
        json.removeValue(forKey: "link")
        #expect(throws: DecodingError.self) { try F.decode(H.Booking.self, json) }
    }

    @Test func theSettingsAreSentWithoutTheServersFields() throws {
        let s = try F.decode(H.Booking.self, F.booking()).settings
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        let json = try #require(try JSONSerialization.jsonObject(with: e.encode(s)) as? [String: Any])
        #expect(json["link"] == nil && json["timezone"] == nil && json["zoom_ready"] == nil)
        #expect(json["slot_minutes"] as? Int == 30 && json["max_per_day"] as? Int == 2)
        #expect(json["buffer_minutes"] as? Int == 15 && json["lead_hours"] as? Int == 12)
        #expect(json["horizon_days"] as? Int == 21 && json["notify_host"] as? Bool == true)
        #expect(json["calendar_id"] as? String == "" && json["conferencing"] as? String == "none")
        #expect((json["hours"] as? [String: [[String]]])?["tue"] == [["09:00", "12:00"], ["14:00", "17:00"]])
        #expect(Set(json.keys) == ["enabled", "slug", "slot_minutes", "max_per_day", "buffer_minutes", "lead_hours",
                                   "horizon_days", "title", "location", "note", "calendar_id", "notify_host",
                                   "conferencing", "hours"])
        // And round-trips to the same settings.
        let back = try JSONDecoder.snake.decode(H.BookingSettings.self, from: e.encode(s))
        #expect(back == s)
    }

    @Test func bookingRowsDecodeWithAndWithoutTheirOptionalParts() throws {
        let rows = try F.decode(H.BookingRows.self, F.upcoming).bookings
        #expect(rows.count == 2)
        #expect(rows[0].name == "Dana Levi" && rows[0].email == "dana@example.com" && rows[0].eventId == "ev123")
        #expect(rows[0].day == "2026-11-03" && rows[0].note == "About the school trip")
        #expect(rows[1].day == nil && rows[1].note == nil)
        #expect(rows[0].id == "ev1232026-11-03T10:00:00-05:00dana@example.com")
        #expect(Set(rows.map(\.id)).count == 2)
    }

    @Test func theWeekdaysAreTheServersKeysMondayFirst() {
        #expect(H.weekdays.map(\.key) == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
    }

    // MARK: Busy feeds

    @Test func aBusyFeedDecodesAsDevSendsIt() throws {
        let list = try F.decode(H.BusyList.self, ["sources": [F.source(), F.source(id: 3, name: "Old", error: "403 Forbidden", blocks: nil, fetched: NSNull())]])
        #expect(list.sources.map(\.id) == [2, 3])
        let a = list.sources[0]
        #expect(a.name == "Work" && a.enabled && a.showInAgenda && a.blocks == 4 && a.lastError == "")
        #expect(a.lastFetched == "2026-10-27T15:25:09.777637+00:00")
        let b = list.sources[1]
        #expect(b.lastFetched == nil && b.blocks == nil && b.lastError == "403 Forbidden")
    }

    // MARK: Reminders

    @Test func remindersDecodeAndEncodeSnakeCase() throws {
        let r = try F.decode(H.ReminderSettings.self, F.reminders)
        #expect(r == H.ReminderSettings(leadMinutes: 30, eveningHour: 20, weeklyDay: 6, weeklyHour: 18, byEmail: false))
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        let json = try #require(try JSONSerialization.jsonObject(with: e.encode(r)) as? [String: Any])
        #expect(json["lead_minutes"] as? Int == 30 && json["evening_hour"] as? Int == 20)
        #expect(json["weekly_day"] as? Int == 6 && json["weekly_hour"] as? Int == 18 && json["by_email"] as? Bool == false)
        let off = try F.decode(H.ReminderSettings.self, [
            "lead_minutes": 0, "evening_hour": -1, "weekly_day": -1, "weekly_hour": 18, "by_email": false,
        ])
        #expect(off.eveningHour == -1 && off.weeklyDay == -1)
    }

    // MARK: The address check

    @Test(arguments: ["ana@example.com", "a.b+c@sub.example.co.uk", "x@y.z"])
    func anAddressPasses(_ s: String) {
        #expect(H.isEmail(s))
    }

    @Test(arguments: ["", "ana", "ana@example", "@example.com", "ana@@example.com", "ana @example.com",
                      "ana@exa mple.com", "ana@example.com ", "ana@.com."])
    func notAnAddressFails(_ s: String) {
        #expect(!H.isEmail(s), "\(s)")
    }

    // MARK: Times

    @Test func instantsReadWithAnOffsetWithMicrosecondsAndNaive() throws {
        let plain = try #require(H.parseInstant("2026-10-27T15:25:09+00:00"))
        #expect(plain == Date(timeIntervalSince1970: 1_793_114_709))
        let micro = try #require(H.parseInstant("2026-10-27T15:25:09.777637+00:00"), "dev's last_fetched")
        #expect(abs(micro.timeIntervalSince(plain) - 0.777) < 0.01)
        #expect(H.parseInstant("2026-10-27T15:25:09") == plain, "older rows are naive UTC")
        #expect(abs((H.parseInstant("2026-10-27T15:25:09.5") ?? .distantPast).timeIntervalSince(plain) - 0.5) < 0.01)
        #expect(H.parseInstant(nil) == nil && H.parseInstant("") == nil && H.parseInstant("yesterday") == nil)
    }

    @Test func readAgoSaysJustNowThenHowLongAgo() {
        let f = ISO8601DateFormatter()
        #expect(H.relative(f.string(from: .now.addingTimeInterval(-20))) == String(localized: "just now"))
        let twoHours = Date.now.addingTimeInterval(-7200)
        let said = H.relative(f.string(from: twoHours))
        #expect(said == twoHours.formatted(.relative(presentation: .named)))
        #expect(said?.contains("2") == true)
        #expect(H.relative(nil) == nil)
        #expect(H.readAgo(nil) == String(localized: "not read yet"))
        #expect(H.readAgo("garbage") == String(localized: "not read yet"))
        #expect(H.readAgo(f.string(from: .now)) == String(localized: "just now"))
    }

    // MARK: Colours

    @Test func aHexColourIsReadAndAnythingElseIsNot() throws {
        let c = try #require(Color(householdHex: "#16a765"))
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        UIColor(c).getRed(&r, green: &g, blue: &b, alpha: &a)
        #expect(abs(r - 0x16 / 255.0) < 0.01 && abs(g - 0xa7 / 255.0) < 0.01 && abs(b - 0x65 / 255.0) < 0.01 && a == 1)
        #expect(Color(householdHex: " #FFFFFF ") != nil)
        for bad in [nil, "", "16a765", "#16a76", "#16a7655", "#zzzzzz", "red"] as [String?] {
            #expect(Color(householdHex: bad) == nil, "\(bad ?? "nil")")
        }
    }

    @Test func aTagDraws() {
        // The capsule beside a row; its body is plain views.
        _ = H.Tag(text: "live", tint: .green).body
        _ = H.Tag(text: "read only").body
    }
}
