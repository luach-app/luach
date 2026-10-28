import Foundation
import SwiftUI

/// The Household area's own shapes (docs/API.md), kept under one name so they
/// never collide with another area's. Decoded and encoded snake_case by `API`.
enum HouseholdArea {
    // MARK: Household calendars (`/api/household`)

    struct CalendarInfo: Decodable, Identifiable, Hashable {
        let id: String
        let name: String
        let color: String?
        let primary: Bool?
        let writable: Bool
        let enabled: Bool
        let `default`: Bool
    }

    struct Calendars: Decodable {
        let available: [CalendarInfo]
        let calendars: [String]
        let defaultCalendar: String
        let defaultAttendees: [String]

        /// The calendars the household uses, default first (the web's `enabledCalendars`).
        var enabledList: [CalendarInfo] {
            available.filter(\.enabled).sorted { a, b in
                if a.default != b.default { return a.default }
                return a.name.localizedCompare(b.name) == .orderedAscending
            }
        }
    }

    struct HouseholdPatch: Encodable {
        let calendars: [String]
        let defaultCalendar: String
        let defaultAttendees: [String]
    }

    // MARK: Booking (`/api/booking`)

    /// The settings a member may change. `link`, `timezone` and `zoomReady` are the
    /// server's, read here and never sent back.
    struct BookingSettings: Codable, Equatable {
        var enabled: Bool
        var slug: String
        var slotMinutes: Int
        var maxPerDay: Int
        var bufferMinutes: Int
        var leadHours: Int
        var horizonDays: Int
        var title: String
        var location: String
        var note: String
        var calendarId: String
        var notifyHost: Bool
        var conferencing: String
        var hours: [String: [[String]]]
    }

    struct Booking: Decodable {
        let settings: BookingSettings
        let link: String
        let timezone: String
        let zoomReady: Bool?

        enum CodingKeys: String, CodingKey { case link, timezone, zoomReady }

        init(from decoder: Decoder) throws {
            settings = try BookingSettings(from: decoder)
            let c = try decoder.container(keyedBy: CodingKeys.self)
            link = try c.decode(String.self, forKey: .link)
            timezone = try c.decode(String.self, forKey: .timezone)
            zoomReady = try c.decodeIfPresent(Bool.self, forKey: .zoomReady)
        }
    }

    struct BookingRow: Decodable, Identifiable, Hashable {
        let start: String
        let day: String?
        let name: String
        let email: String
        let note: String?
        let eventId: String

        var id: String { eventId + start + email }
    }

    struct BookingRows: Decodable {
        let bookings: [BookingRow]
    }

    static let weekdays: [(key: String, label: LocalizedStringKey)] = [
        ("mon", "Monday"), ("tue", "Tuesday"), ("wed", "Wednesday"), ("thu", "Thursday"),
        ("fri", "Friday"), ("sat", "Saturday"), ("sun", "Sunday"),
    ]

    // MARK: Busy feeds (`/api/busy`)

    struct BusySource: Decodable, Identifiable, Hashable {
        let id: Int
        let name: String
        let url: String
        let enabled: Bool
        let showInAgenda: Bool
        let lastFetched: String?
        let lastError: String?
        let blocks: Int?
    }

    struct BusyList: Decodable {
        let sources: [BusySource]
    }

    // MARK: Reminders (`/api/reminders`)

    struct ReminderSettings: Codable, Equatable {
        var leadMinutes: Int
        var eveningHour: Int
        /// 0 = Monday … 6, −1 = never.
        var weeklyDay: Int
        var weeklyHour: Int
        var byEmail: Bool
    }

    // MARK: Helpers

    /// The web's address check (EmailChips): something@something.something, no spaces.
    static func isEmail(_ s: String) -> Bool {
        s.range(of: #"^[^@\s]+@[^@\s]+\.[^@\s]+$"#, options: .regularExpression) != nil
    }

    /// luach's stored times: with an offset (`…+00:00`) or, from older rows, naive UTC.
    static func parseInstant(_ s: String?) -> Date? {
        guard let s, !s.isEmpty else { return nil }
        if let d = EventTime.parse(s) { return d }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: s + "Z") { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: s + "Z")
    }

    static func relative(_ s: String?) -> String? {
        guard let date = parseInstant(s) else { return nil }
        if abs(date.timeIntervalSinceNow) < 60 { return String(localized: "just now") }
        return date.formatted(.relative(presentation: .named))
    }
}

extension Color {
    /// `#rrggbb` from the server; nil for anything else.
    init?(householdHex hex: String?) {
        guard var s = hex?.trimmingCharacters(in: .whitespaces), s.hasPrefix("#") else { return nil }
        s.removeFirst()
        guard s.count == 6, let v = UInt32(s, radix: 16) else { return nil }
        self.init(
            red: Double((v >> 16) & 0xFF) / 255, green: Double((v >> 8) & 0xFF) / 255, blue: Double(v & 0xFF) / 255
        )
    }
}

extension HouseholdArea {
    /// A small capsule beside a row: "live", "read only", "could not read".
    struct Tag: View {
        let text: LocalizedStringKey
        var tint: Color = .secondary

        var body: some View {
            Text(text)
                .font(.caption)
                .padding(.horizontal, 7)
                .padding(.vertical, 2)
                .foregroundStyle(tint)
                .background(tint.opacity(0.12), in: Capsule())
        }
    }
}
