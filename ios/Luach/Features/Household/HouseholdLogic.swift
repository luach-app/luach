import Foundation

/// What the Household area's screens do that is not drawing: every call they make and the
/// editing rules behind them, kept apart from the views so each can be tested on its own.
extension HouseholdArea {
    // MARK: The calls (docs/API.md)

    /// Every request the area sends. Writes to busy feeds answer with the listing that is left.
    struct Client {
        let api: API

        func calendars() async throws -> Calendars {
            try await api.get("/api/household/calendars")
        }

        func saveHousehold(_ patch: HouseholdPatch) async throws {
            let _: API.Ignored = try await api.patch("/api/household", patch)
        }

        func booking() async throws -> Booking {
            try await api.get("/api/booking")
        }

        /// Sends every setting (the server takes any of them); the link name without the
        /// spaces a phone keyboard leaves around it.
        func saveBooking(_ settings: BookingSettings) async throws -> Booking {
            var changes = settings
            changes.slug = changes.slug.trimmingCharacters(in: .whitespaces)
            return try await api.patch("/api/booking", changes)
        }

        func upcoming() async throws -> [BookingRow] {
            let rows: BookingRows = try await api.get("/api/booking/upcoming")
            return rows.bookings
        }

        /// The host calling one off: removing the event tells the guest, server-side.
        func cancel(_ row: BookingRow) async throws {
            let _: API.Ignored = try await api.delete("/api/calendar/events/\(row.eventId)")
        }

        func busy() async throws -> [BusySource] {
            let list: BusyList = try await api.get("/api/busy")
            return list.sources
        }

        /// A feed with no name is called "Work", as on the web.
        func addBusy(name: String, url: String) async throws -> [BusySource] {
            struct Body: Encodable { let name: String; let url: String }
            let n = name.trimmingCharacters(in: .whitespaces)
            let body = Body(name: n.isEmpty ? "Work" : n, url: url.trimmingCharacters(in: .whitespacesAndNewlines))
            let list: BusyList = try await api.post("/api/busy", body)
            return list.sources
        }

        func updateBusy(_ id: Int, _ changes: [String: Bool]) async throws -> [BusySource] {
            let list: BusyList = try await api.patch("/api/busy/\(id)", changes)
            return list.sources
        }

        func removeBusy(_ id: Int) async throws -> [BusySource] {
            let list: BusyList = try await api.delete("/api/busy/\(id)")
            return list.sources
        }

        func refreshBusy() async throws -> [BusySource] {
            let list: BusyList = try await api.post("/api/busy/refresh")
            return list.sources
        }

        func reminders() async throws -> ReminderSettings {
            try await api.get("/api/reminders")
        }

        func saveReminders(_ settings: ReminderSettings) async throws -> ReminderSettings {
            try await api.patch("/api/reminders", settings)
        }
    }

    // MARK: Household

    /// The Household screen's edits, before they are saved.
    struct HouseholdForm: Equatable {
        var enabled: [String] = []
        var defaultCalendar = ""
        var attendees: [String] = []
        /// The address being typed into "Always invite".
        var draft = ""
        /// The draft was offered and is not an address.
        var draftBad = false

        init() {}

        init(_ data: Calendars) {
            enabled = data.calendars
            defaultCalendar = data.defaultCalendar
            attendees = data.defaultAttendees
        }

        var cleanDraft: String { draft.trimmingCharacters(in: .whitespaces).lowercased() }

        /// A finished address still in the box counts: Save adds it.
        func isDirty(against data: Calendars) -> Bool {
            enabled != data.calendars || defaultCalendar != data.defaultCalendar
                || attendees != data.defaultAttendees || HouseholdArea.isEmail(cleanDraft)
        }

        /// Ticks or unticks a calendar; when the default goes, the first one left takes its place.
        mutating func toggle(_ id: String) {
            if let i = enabled.firstIndex(of: id) {
                enabled.remove(at: i)
            } else {
                enabled.append(id)
            }
            if !enabled.contains(defaultCalendar), let first = enabled.first {
                defaultCalendar = first
            }
        }

        /// Adds the typed address. False when nothing changed (empty, or not an address).
        @discardableResult
        mutating func commitDraft() -> Bool {
            let email = cleanDraft
            guard !email.isEmpty else { return false }
            guard HouseholdArea.isEmail(email) else {
                draftBad = true
                return false
            }
            if !attendees.contains(email) { attendees.append(email) }
            draft = ""
            return true
        }

        /// What Save sends; nil when no calendar is ticked ("Keep at least one calendar.").
        var patch: HouseholdPatch? {
            guard let first = enabled.first else { return nil }
            var list = attendees
            let email = cleanDraft
            if HouseholdArea.isEmail(email), !list.contains(email) { list.append(email) }
            return HouseholdPatch(
                calendars: enabled, defaultCalendar: defaultCalendar.isEmpty ? first : defaultCalendar,
                defaultAttendees: list
            )
        }
    }

    /// The calendars the screen lists: everything the credential sees, or the household's own.
    static func listed(_ data: Calendars) -> [CalendarInfo] {
        data.available.isEmpty ? data.enabledList : data.available
    }

    static func name(of id: String, in data: Calendars) -> String {
        data.available.first { $0.id == id }?.name ?? id
    }

    /// Where new events may go: a ticked calendar luach can write to.
    static func defaultChoices(_ data: Calendars, enabled: [String]) -> [CalendarInfo] {
        listed(data).filter { enabled.contains($0.id) && $0.writable }
    }

    // MARK: Booking

    /// The weekly hours: `["HH:MM", "HH:MM"]` windows per day.
    enum Hours {
        static let defaultWindow = ["09:00", "17:00"]
        static let lastMinute = "23:59"

        /// Today at that time, for a time picker.
        static func date(_ hhmm: String, on day: Date = .now) -> Date {
            let parts = hhmm.split(separator: ":").compactMap { Int($0) }
            var c = Calendar.current.dateComponents([.year, .month, .day], from: day)
            c.hour = parts.first ?? 9
            c.minute = parts.count > 1 ? parts[1] : 0
            return Calendar.current.date(from: c) ?? day
        }

        static func hhmm(_ date: Date) -> String {
            let c = Calendar.current.dateComponents([.hour, .minute], from: date)
            return String(format: "%02d:%02d", c.hour ?? 0, c.minute ?? 0)
        }

        /// A day switched on keeps its first window (9 to 5 when it had none); off has none.
        static func toggled(_ windows: [[String]], on: Bool) -> [[String]] {
            on ? [windows.first ?? defaultWindow] : []
        }

        /// One more window, starting where the last ends and two hours long (to 23:59 at most);
        /// nil when the last one already runs to the end of the day.
        static func adding(to windows: [[String]]) -> [[String]]? {
            let from = windows.last?[householdSafe: 1] ?? defaultWindow[1]
            let start = date(from)
            let end = min(start.addingTimeInterval(2 * 3600), date(lastMinute))
            guard end > start else { return nil }
            return windows + [[hhmm(start), hhmm(end)]]
        }

        static func removing(_ windows: [[String]], at i: Int) -> [[String]] {
            var next = windows
            if next.indices.contains(i) { next.remove(at: i) }
            return next
        }

        /// The start (`end` 0) or end (1) of window `i`, with 9 to 5 for a missing one.
        static func time(_ windows: [[String]]?, _ i: Int, _ end: Int) -> String {
            windows?[householdSafe: i]?[householdSafe: end] ?? defaultWindow[end == 0 ? 0 : 1]
        }

        /// Window `i` with its start or end moved; nil when there is no such window.
        static func setting(_ windows: [[String]]?, _ i: Int, _ end: Int, to date: Date) -> [[String]]? {
            guard var windows, windows.indices.contains(i), windows[i].indices.contains(end) else { return nil }
            windows[i][end] = hhmm(date)
            return windows
        }
    }

    /// A menu's values, with a saved value it does not offer kept in order rather than lost.
    static func choices(_ options: [Int], keeping value: Int) -> [Int] {
        options.contains(value) ? options : (options + [value]).sorted()
    }

    /// The calendars a booking may land on: the household's, writable.
    static func bookingCalendars(_ household: Calendars?) -> [CalendarInfo] {
        (household?.enabledList ?? []).filter(\.writable)
    }

    /// The first choice of "Meetings land on", naming the household's default.
    static func defaultCalendarLabel(_ household: Calendars?, _ calendars: [CalendarInfo]) -> String {
        guard let id = household?.defaultCalendar, !id.isEmpty else { return String(localized: "The household default") }
        let name = calendars.first { $0.id == id }?.name ?? id
        return String(localized: "The household default (\(name))")
    }

    /// When a booking is, in the member's zone: "Tue, 3 Nov, 10:00"; the raw value if unreadable.
    static func when(_ row: BookingRow, in zone: TimeZone?) -> String {
        guard let date = EventTime.parse(row.start) else { return row.start }
        var style = Date.FormatStyle.dateTime.weekday(.abbreviated).day().month(.abbreviated).hour().minute()
        if let zone { style.timeZone = zone }
        return date.formatted(style)
    }

    // MARK: Reminders

    /// A saved value the menu does not offer (set by asking luach), to show as its own row.
    static func offMenu(_ value: Int?, known: [Int]) -> Int? {
        guard let value, !known.contains(value) else { return nil }
        return value
    }

    // MARK: Busy calendars

    /// "Read 5 minutes ago", "just now", or "not read yet".
    static func readAgo(_ iso: String?) -> String {
        relative(iso) ?? String(localized: "not read yet")
    }
}

extension Array {
    subscript(householdSafe i: Int) -> Element? { indices.contains(i) ? self[i] : nil }
}
