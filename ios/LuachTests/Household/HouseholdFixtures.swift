import Foundation
@testable import Luach

/// The Household area's answers, in the shapes dev gives (captured 2026-10-27), with
/// example.com addresses in place of real ones.
enum HouseholdFixtures {
    static let calendars: [String: Any] = [
        "available": [
            ["id": "family@group.calendar.google.com", "name": "Family", "color": "#16a765",
             "primary": false, "writable": true, "enabled": true, "default": true],
            ["id": "ana@example.com", "name": "Ana", "color": "#4986e7",
             "primary": true, "writable": true, "enabled": true, "default": false],
            ["id": "holidays@group.v.calendar.google.com", "name": "Holidays", "color": NSNull(),
             "primary": NSNull(), "writable": false, "enabled": true, "default": false],
            ["id": "local", "name": "luach (local)", "color": "#f4b942",
             "primary": true, "writable": true, "enabled": false, "default": false],
        ],
        "calendars": ["family@group.calendar.google.com", "ana@example.com", "holidays@group.v.calendar.google.com"],
        "default_calendar": "family@group.calendar.google.com",
        "default_attendees": ["grandma@example.com"],
    ]

    /// Dev's own household: its one visible calendar is not the one in use.
    static let devCalendars: [String: Any] = [
        "available": [["id": "local", "name": "luach (local)", "color": "#f4b942", "primary": true,
                       "writable": true, "enabled": false, "default": false]],
        "calendars": ["fake"], "default_calendar": "fake", "default_attendees": [],
    ]

    static let hours: [String: [[String]]] = [
        "mon": [["09:00", "17:00"]], "tue": [["09:00", "12:00"], ["14:00", "17:00"]], "wed": [["09:00", "17:00"]],
        "thu": [["09:00", "17:00"]], "fri": [["09:00", "13:00"]], "sat": [], "sun": [],
    ]

    static func booking(_ changes: [String: Any] = [:]) -> [String: Any] {
        var b: [String: Any] = [
            "enabled": true, "slug": "robin", "slot_minutes": 30, "max_per_day": 2, "buffer_minutes": 15,
            "lead_hours": 12, "horizon_days": 21, "calendar_id": "", "notify_host": true, "conferencing": "none",
            "title": "Meeting with {name}", "location": "", "note": "", "hours": hours,
            "link": "https://luach.example.com/book/robin", "timezone": "America/New_York", "zoom_ready": false,
        ]
        b.merge(changes) { _, new in new }
        return b
    }

    static let upcoming: [String: Any] = ["bookings": [
        ["start": "2026-11-03T10:00:00-05:00", "day": "2026-11-03", "name": "Dana Levi",
         "email": "dana@example.com", "note": "About the school trip", "event_id": "ev123"],
        ["start": "2026-11-04T15:30:00-05:00", "day": NSNull(), "name": "Sam",
         "email": "sam@example.com", "note": NSNull(), "event_id": "ev456"],
    ]]

    static func source(id: Int = 2, name: String = "Work", error: String = "", blocks: Int? = 4,
                       fetched: Any = "2026-10-27T15:25:09.777637+00:00") -> [String: Any] {
        [
            "id": id, "name": name, "url": "https://outlook.office365.com/owa/calendar/abc/reachcalendar.ics",
            "enabled": true, "show_in_agenda": true, "last_fetched": fetched, "last_error": error,
            "blocks": blocks.map { $0 as Any } ?? NSNull(),
        ]
    }

    static let reminders: [String: Any] = [
        "lead_minutes": 30, "evening_hour": 20, "weekly_day": 6, "weekly_hour": 18, "by_email": false,
    ]

    static let member: [String: Any] = [
        "id": 1, "username": "robin", "display_name": "Robin", "email": "robin@example.com",
        "timezone": "America/New_York", "language": "en", "is_owner": true,
    ]

    static func data(_ json: Any) -> Data {
        try! JSONSerialization.data(withJSONObject: json)
    }

    static func decode<T: Decodable>(_ type: T.Type, _ json: Any) throws -> T {
        try JSONDecoder.snake.decode(type, from: data(json))
    }
}
