import Foundation

// The shapes the agenda and the event editor read (docs/API.md, "Calendar",
// "Family", "Household"). Every field is tolerant of an older server leaving it out.

/// The full Event object, with whom it is for and whether luach may change it.
struct AgendaEvent: Decodable, Identifiable, Hashable {
    var id: String
    var title: String
    /// `2026-09-16T15:00:00-04:00`, or `2026-09-16` for all-day (end exclusive).
    var start: String
    var end: String
    var allDay: Bool
    var location: String
    var description: String
    /// The RRULE; on one occurrence of a repeating event, its series' rule.
    var recurrence: [String]
    /// On one occurrence of a repeating event, the series' id.
    var recurringEventId: String
    /// One occurrence of a repeating event, not the series: a change or a delete asks which.
    var occurrence: Bool
    var htmlLink: String
    var calendarId: String
    /// An invitation only its organizer can change, a calendar luach only reads, or busy time from a feed.
    var readOnly: Bool
    var attendees: [String]
    /// Set when the event was saved but the invitations could not be sent.
    var inviteError: String
    var leader: String
    var leaders: [String]
    var organizer: String

    enum CodingKeys: String, CodingKey {
        case id, title, start, end, allDay, location, description, recurrence, recurringEventId, occurrence, htmlLink
        case calendarId, readOnly, attendees, inviteError, leader, leaders, organizer
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func text(_ key: CodingKeys) -> String { (try? c.decodeIfPresent(String.self, forKey: key)) ?? "" }
        func list(_ key: CodingKeys) -> [String] { (try? c.decodeIfPresent([String].self, forKey: key)) ?? [] }
        id = try c.decode(String.self, forKey: .id)
        title = text(.title)
        start = text(.start)
        end = text(.end)
        allDay = (try? c.decodeIfPresent(Bool.self, forKey: .allDay)) ?? false
        location = text(.location)
        description = text(.description)
        recurrence = list(.recurrence)
        recurringEventId = text(.recurringEventId)
        occurrence = (try? c.decodeIfPresent(Bool.self, forKey: .occurrence)) ?? false
        htmlLink = text(.htmlLink)
        calendarId = text(.calendarId)
        readOnly = (try? c.decodeIfPresent(Bool.self, forKey: .readOnly)) ?? false
        attendees = list(.attendees)
        inviteError = text(.inviteError)
        leader = text(.leader)
        leaders = list(.leaders)
        organizer = text(.organizer)
    }

    var isAllDay: Bool { allDay || AgendaClock.isDay(start) }
    var isRecurring: Bool { !recurringEventId.isEmpty || !recurrence.isEmpty }
    /// One occurrence of a repeating event (an older server says so only by the series' id).
    var isOccurrence: Bool { occurrence || !recurringEventId.isEmpty }
    var displayTitle: String { title.isEmpty ? String(localized: "(untitled)") : title }
    /// Everyone it is for, as family keys; empty when it is the whole family's.
    var leaderKeys: [String] { !leaders.isEmpty ? leaders : leader.isEmpty ? [] : [leader] }
}

/// Someone in the family (not an account: a child needs none).
struct AgendaPerson: Decodable, Identifiable, Hashable {
    var key: String
    var name: String
    var hex: String
    var email: String

    var id: String { key }

    enum CodingKeys: String, CodingKey { case key, name, hex, email }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.decode(String.self, forKey: .key)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? key
        hex = (try? c.decodeIfPresent(String.self, forKey: .hex)) ?? ""
        email = (try? c.decodeIfPresent(String.self, forKey: .email)) ?? ""
    }
}

struct AgendaCalendarInfo: Decodable, Identifiable, Hashable {
    var id: String
    var name: String
    var color: String
    var writable: Bool
    var enabled: Bool
    var isDefault: Bool

    enum CodingKeys: String, CodingKey {
        case id, name, color, writable, enabled
        case isDefault = "default"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? id
        color = (try? c.decodeIfPresent(String.self, forKey: .color)) ?? ""
        writable = (try? c.decodeIfPresent(Bool.self, forKey: .writable)) ?? false
        enabled = (try? c.decodeIfPresent(Bool.self, forKey: .enabled)) ?? false
        isDefault = (try? c.decodeIfPresent(Bool.self, forKey: .isDefault)) ?? false
    }
}

/// `GET /api/household/calendars`: the calendars luach reads, and what a new event starts with.
struct AgendaHousehold: Decodable {
    var defaultCalendar: String
    var defaultAttendees: [String]
    var available: [AgendaCalendarInfo]

    enum CodingKeys: String, CodingKey { case defaultCalendar, defaultAttendees, available }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        defaultCalendar = (try? c.decodeIfPresent(String.self, forKey: .defaultCalendar)) ?? ""
        defaultAttendees = (try? c.decodeIfPresent([String].self, forKey: .defaultAttendees)) ?? []
        available = (try? c.decodeIfPresent([AgendaCalendarInfo].self, forKey: .available)) ?? []
    }
}

/// What a change or a delete of one occurrence of a repeating event acts on.
enum AgendaScope: String {
    /// That occurrence alone.
    case this
    /// Every occurrence: the series.
    case series
}

/// The body of `POST` and `PATCH /api/calendar/events`. Absent fields are left out
/// of the JSON, which matters: no `attendees` means "the household's default invitees".
struct AgendaEventInput: Encodable {
    var title: String
    var start: String
    var end: String?
    var location: String?
    var description: String?
    /// One RRULE, a word of the Repeats menu ("weekly"), which the server puts on the event's
    /// own day, or "" to stop it repeating. Sent only when the person changed how it repeats.
    var recurrence: String?
    /// Create only.
    var calendarId: String?
    var attendees: [String]?
    /// A comma list of family keys; "" makes it nobody's. Absent leaves it as it is.
    var leader: String?
}

extension API {
    /// Events whose days fall from `start` to `end` (YYYY-MM-DD, in the member's zone),
    /// plus the busy time of the member's read-only feeds that show in the agenda.
    func agendaEvents(from start: String, to end: String) async throws -> [AgendaEvent] {
        struct Page: Decodable { let events: [AgendaEvent] }
        let page: Page = try await get("/api/calendar/events", query: ["start": start, "end": end])
        return page.events
    }

    func agendaEvent(_ id: String, calendar: String?) async throws -> AgendaEvent {
        try await get("/api/calendar/events/\(id)", query: Self.calendarQuery(calendar))
    }

    func agendaCreate(_ body: AgendaEventInput) async throws -> AgendaEvent {
        try await post("/api/calendar/events", body)
    }

    /// `scope`, on one occurrence of a repeating event: that one, or the whole series.
    func agendaUpdate(_ id: String, calendar: String?, _ body: AgendaEventInput, scope: AgendaScope? = nil) async throws -> AgendaEvent {
        try await patch("/api/calendar/events/\(id)", body, query: Self.calendarQuery(calendar, scope))
    }

    func agendaDelete(_ id: String, calendar: String?, scope: AgendaScope? = nil) async throws {
        let _: Ignored = try await delete("/api/calendar/events/\(id)", query: Self.calendarQuery(calendar, scope))
    }

    func agendaHousehold() async throws -> AgendaHousehold {
        try await get("/api/household/calendars")
    }

    func agendaFamily() async throws -> [AgendaPerson] {
        struct Family: Decodable { let people: [AgendaPerson] }
        let family: Family = try await get("/api/family")
        return family.people
    }

    /// The member's own "also notify" inboxes, added to a new event's invitees.
    func agendaNotifyEmails() async throws -> [String] {
        struct Me: Decodable { let notifyEmails: [String]? }
        let me: Me = try await get("/api/auth/me")
        return me.notifyEmails ?? []
    }

    private static func calendarQuery(_ calendar: String?, _ scope: AgendaScope? = nil) -> [String: String] {
        var query: [String: String] = [:]
        if let calendar, !calendar.isEmpty { query["calendar"] = calendar }
        if let scope { query["scope"] = scope.rawValue }
        return query
    }
}
