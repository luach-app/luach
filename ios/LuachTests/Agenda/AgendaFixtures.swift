import Foundation
@testable import Luach

/// Shapes the agenda reads, as dev's luach sends them (captured 2026-10-27; addresses
/// replaced with example.com ones).
enum AgendaFixtures {
    /// A weekly event with two leaders, HTML notes and a location (GET /api/calendar/events/{id}).
    static let timed: [String: Any] = [
        "id": "4fd5aabcaffd", "title": "Dentist", "start": "2026-11-03T15:00:00-05:00",
        "end": "2026-11-03T15:45:00-05:00", "all_day": false, "location": "Clinic",
        "description": #"<p>See <a href="https://example.com/x">the page</a></p>"#,
        "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TU"], "recurring_event_id": "", "html_link": "",
        "creator": "local@luach", "updated": "2026-10-27T15:24:42.384019+00:00", "calendar_id": "fake",
        "attendees": [], "invite_error": "", "leader": "ruby", "color_id": "2", "ical_uid": "",
        "organizer": "", "read_only": false, "leaders": ["ruby", "lily"],
    ]

    /// One occurrence of it, as a range read expands it: with its series' rule.
    static let occurrence: [String: Any] = timed.merging([
        "id": "4fd5aabcaffd_20261110T150000", "start": "2026-11-10T15:00:00-05:00",
        "end": "2026-11-10T15:45:00-05:00", "recurring_event_id": "4fd5aabcaffd", "occurrence": true,
    ]) { $1 }

    /// Two days, all day (end exclusive).
    static let allDay: [String: Any] = [
        "id": "b4fb50149034", "title": "Trip", "start": "2026-11-05", "end": "2026-11-07", "all_day": true,
        "location": "", "description": "", "recurrence": [], "recurring_event_id": "", "html_link": "",
        "creator": "local@luach", "calendar_id": "fake", "attendees": [], "invite_error": "", "leader": "",
        "color_id": "", "ical_uid": "", "organizer": "", "read_only": false, "leaders": [],
    ]

    /// An invitation someone else organised: luach may not change it.
    static let invitation: [String: Any] = [
        "id": "inv1", "title": "Board meeting", "start": "2026-11-04T09:00:00-05:00",
        "end": "2026-11-04T10:00:00-05:00", "all_day": false, "calendar_id": "family@example.com",
        "attendees": ["ana@example.com", "sam@example.com"], "organizer": "boss@example.com",
        "read_only": true, "html_link": "https://calendar.google.com/event?eid=abc",
        "invite_error": "", "leader": "", "leaders": [],
    ]

    static let family: [String: Any] = ["people": [
        ["key": "robin", "name": "Robin", "color": "7", "kind": "adult", "email": "robin@example.com",
         "user_id": 1, "position": 0, "hex": "#039be5"],
        ["key": "ruby", "name": "Ruby", "color": "2", "kind": "kid", "email": "", "user_id": NSNull(),
         "position": 2, "hex": "#33b679"],
        ["key": "lily", "name": "Lily", "color": "3", "kind": "kid", "email": "", "user_id": NSNull(),
         "position": 3, "hex": "#8e24aa"],
    ], "colors": [["id": "1", "name": "Lavender", "hex": "#7986cb"]]]

    static let household: [String: Any] = [
        "available": [
            ["id": "family@example.com", "name": "Family", "color": "#f4b942", "primary": false,
             "writable": true, "enabled": true, "default": false],
            ["id": "fake", "name": "luach (local)", "color": "#33b679", "primary": true,
             "writable": true, "enabled": true, "default": true],
            ["id": "holidays", "name": "Holidays", "color": "#0b8043", "primary": false,
             "writable": false, "enabled": true, "default": false],
            ["id": "old", "name": "Old", "color": "#000000", "primary": false,
             "writable": true, "enabled": false, "default": false],
        ],
        "calendars": ["fake", "family@example.com"], "default_calendar": "fake",
        "default_attendees": ["grandma@example.com"],
    ]

    static let me: [String: Any] = [
        "id": 1, "username": "robin", "email": "robin@example.com", "display_name": "Robin",
        "timezone": "America/New_York", "language": "auto", "is_owner": true, "model": "",
        "last_seen": "2026-10-27T15:21:43.619628+00:00", "emails": ["robin@example.com"],
        "notify_emails": ["work@example.com", "grandma@example.com"], "notify_pending": [],
    ]

    static func event(_ json: [String: Any]) throws -> AgendaEvent {
        try JSONDecoder.snake.decode(AgendaEvent.self, from: JSONSerialization.data(withJSONObject: json))
    }

    /// The smallest event: an id and the times.
    static func event(_ id: String, _ start: String, _ end: String = "", allDay: Bool = false,
                      leader: String = "", calendar: String = "") throws -> AgendaEvent {
        try event(["id": id, "title": id, "start": start, "end": end, "all_day": allDay,
                   "leader": leader, "calendar_id": calendar])
    }

    /// The clock of dev's member: New York, in English.
    static let newYork = AgendaClock(tz: TimeZone(identifier: "America/New_York")!, locale: Locale(identifier: "en_US"))
}
