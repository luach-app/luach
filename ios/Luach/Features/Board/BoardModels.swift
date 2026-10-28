import SwiftUI

// Shapes of the house board and the task list (docs/API.md, "House board" and
// "Tasks"). Decoded with .convertFromSnakeCase like everything else.

/// Someone on the board: a column, with their colour.
struct BoardPerson: Decodable, Hashable, Identifiable {
    let key: String
    let name: String
    let hex: String
    /// `adult` or `kid`.
    let kind: String?

    var id: String { key }
}

struct BoardEvent: Decodable, Hashable, Identifiable {
    let id: String
    let title: String
    /// An instant with its offset, or `YYYY-MM-DD` for an all-day event.
    let start: String
    let end: String
    let allDay: Bool
    let location: String?
    var leader: String?
    /// Everyone it is for; older servers send only `leader`.
    var leaders: [String]?
    /// Someone else's invitation, or a calendar luach only reads: it stays where it is.
    let readOnly: Bool?
    let organizer: String?
    /// One day of a series: moving it to another day is the editor's job.
    let recurring: Bool?
    let calendarId: String?

    var people: [String] {
        if let leaders, !leaders.isEmpty { return leaders }
        if let leader, !leader.isEmpty { return [leader] }
        return []
    }

    var isAllDay: Bool { allDay || start.count <= 10 }
}

/// A to-do (no `days`) or a chore (some weekdays). `Task` is Swift's, so this is `TaskItem`.
struct TaskItem: Decodable, Hashable, Identifiable {
    let id: Int
    var title: String
    /// A family key; "" for whoever gets to it.
    var person: String
    var due: String
    /// MO…SU for a chore; [] for a to-do.
    var days: [String]
    var notes: String?
    var done: Bool
    var overdue: Bool
    var chore: Bool
}

struct BoardDay: Decodable {
    /// Whether this viewer may add, change and remove (a member always may).
    let canEdit: Bool?
    /// Today in the household's zone; `day` is the page being looked at.
    let today: String?
    let viewer: String?
    let timezone: String
    let now: String?
    let day: String
    var people: [BoardPerson]
    var events: [BoardEvent]
    let tomorrow: [BoardEvent]
    var tasks: [TaskItem]

    var zone: TimeZone { TimeZone(identifier: timezone) ?? .current }
    var todayISO: String { today ?? day }
}

struct TaskDay: Decodable {
    let day: String?
    let tasks: [TaskItem]
    let mayAssign: Bool
}

struct FamilyList: Decodable {
    let people: [BoardPerson]
}

/// What the task sheet sends; nil fields are left out of the JSON.
struct TaskInput: Encodable {
    var title: String?
    var person: String?
    var due: String?
    var days: [String]?
    var notes: String?
}

/// A change to an event made by giving it to someone or moving it to another day.
struct EventPatch: Encodable {
    var leaders: [String]?
    var start: String?
    var end: String?
}

/// One column on the board: a person's things, or the family's shared ones (key "").
struct BoardColumn: Identifiable {
    let key: String
    let name: String
    let hex: String
    var events: [BoardEvent]
    var tasks: [TaskItem]

    var id: String { key.isEmpty ? "\u{0}family" : key }
}

extension BoardDay {
    /// One column per person, then the family's shared things. An event for two
    /// people is in both columns. An empty family column is kept only where the
    /// viewer can add: its + is the only way to add something for everyone.
    func columns(withFamily: Bool) -> [BoardColumn] {
        let known = Set(people.map(\.key))
        var cols = people.map { p in
            BoardColumn(
                key: p.key, name: p.name, hex: p.hex,
                events: events.filter { $0.people.contains(p.key) },
                tasks: tasks.filter { $0.person == p.key }
            )
        }
        let shared = BoardColumn(
            key: "", name: String(localized: "Family"), hex: "",
            events: events.filter { !$0.people.contains(where: known.contains) },
            tasks: tasks.filter { $0.person.isEmpty || !known.contains($0.person) }
        )
        if withFamily || !shared.events.isEmpty || !shared.tasks.isEmpty { cols.append(shared) }
        return cols
    }
}

// MARK: - Calls

extension API {
    /// The member's board for `day` (today when nil): today up to 30 days ahead.
    func boardDay(_ day: String?) async throws -> BoardDay {
        try await get("/api/board/today", query: day.map { ["day": $0] } ?? [:])
    }

    /// Ticked for the day on the page (nil: today).
    func boardTick(_ id: Int, done: Bool, day: String?) async throws {
        struct Body: Encodable { let done: Bool; let day: String? }
        let _: Ignored = try await post("/api/board/tasks/\(id)/done", Body(done: done, day: day))
    }

    func boardMoveEvent(_ event: BoardEvent, _ change: EventPatch) async throws {
        let query = (event.calendarId ?? "").isEmpty ? [:] : ["calendar": event.calendarId!]
        // The id as it is: `request` percent-encodes the path, so encoding it here too sent `%2520`.
        let _: Ignored = try await patch("/api/board/events/\(event.id)", change, query: query)
    }

    func tasksDay(_ day: String?) async throws -> TaskDay {
        try await get("/api/tasks", query: day.map { ["day": $0] } ?? [:])
    }

    func tasksAll() async throws -> TaskDay {
        try await get("/api/tasks/all")
    }

    func tick(_ id: Int, done: Bool, day: String) async throws {
        struct Body: Encodable { let day: String; let done: Bool }
        let _: Ignored = try await post("/api/tasks/\(id)/done", Body(day: day, done: done))
    }

    func family() async throws -> [BoardPerson] {
        let list: FamilyList = try await get("/api/family")
        return list.people
    }
}

/// Where a task is added, changed and removed: the board's routes from the board
/// (as the web board does) and the task routes from the task list. Same checks.
enum TaskRoutes {
    case board, tasks

    var base: String { self == .board ? "/api/board/tasks" : "/api/tasks" }

    func add(_ api: API, _ input: TaskInput) async throws -> TaskItem {
        try await api.post(base, input)
    }

    func update(_ api: API, _ id: Int, _ input: TaskInput) async throws -> TaskItem {
        try await api.patch("\(base)/\(id)", input)
    }

    func remove(_ api: API, _ id: Int) async throws {
        let _: API.Ignored = try await api.delete("\(base)/\(id)")
    }
}

// MARK: - Days as the server writes them (YYYY-MM-DD)

enum ISODay {
    private static let utc = TimeZone(identifier: "UTC")!
    private static let calendar: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = utc
        return c
    }()
    private static let formatter: DateFormatter = {
        let f = DateFormatter()
        f.calendar = calendar
        f.timeZone = utc
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    /// Noon UTC on that day: formatted in UTC it is that day everywhere.
    static func date(_ iso: String) -> Date? {
        formatter.date(from: String(iso.prefix(10))).map { $0.addingTimeInterval(12 * 3600) }
    }

    static func add(_ iso: String, _ days: Int) -> String {
        guard let d = date(iso), let moved = calendar.date(byAdding: .day, value: days, to: d) else { return iso }
        return formatter.string(from: moved)
    }

    static func between(_ from: String, _ to: String) -> Int {
        guard let a = date(from), let b = date(to) else { return 0 }
        return calendar.dateComponents([.day], from: a, to: b).day ?? 0
    }

    /// Today in a zone.
    static func today(in zone: TimeZone) -> String {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = zone
        let parts = c.dateComponents([.year, .month, .day], from: .now)
        return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }

    private static func style(_ base: Date.FormatStyle) -> Date.FormatStyle {
        var s = base
        s.timeZone = utc
        return s
    }

    /// "Thursday, October 29".
    static func long(_ iso: String) -> String {
        guard let d = date(iso) else { return iso }
        return d.formatted(style(.dateTime.weekday(.wide).month(.wide).day()))
    }

    /// "Oct 29".
    static func short(_ iso: String) -> String {
        guard let d = date(iso) else { return iso }
        return d.formatted(style(.dateTime.month(.abbreviated).day()))
    }

    /// Today, Tomorrow, or "Thu 29".
    static func chip(_ iso: String, today: String) -> String {
        if iso == today { return String(localized: "Today") }
        if iso == add(today, 1) { return String(localized: "Tomorrow") }
        guard let d = date(iso) else { return iso }
        return d.formatted(style(.dateTime.weekday(.abbreviated).day()))
    }

    /// A day the phone's date picker can show (local midnight), and back.
    static func local(_ iso: String) -> Date? { EventTime.parse(String(iso.prefix(10))) }
    static func fromLocal(_ date: Date) -> String { EventTime.dayString(date) }
}

// MARK: - Chores' weekdays

enum Weekday {
    /// Monday first, as the web board lays out the week in English.
    static let codes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

    /// Foundation's symbols start on Sunday.
    private static func index(_ code: String) -> Int? {
        guard let i = codes.firstIndex(of: code) else { return nil }
        return (i + 1) % 7
    }

    static func initial(_ code: String) -> String {
        index(code).map { Calendar.current.veryShortStandaloneWeekdaySymbols[$0] } ?? code
    }

    static func name(_ code: String) -> String {
        index(code).map { Calendar.current.standaloneWeekdaySymbols[$0] } ?? code
    }

    static func short(_ code: String) -> String {
        index(code).map { Calendar.current.shortStandaloneWeekdaySymbols[$0] } ?? code
    }

    /// The days a chore falls on: "every day", "weekdays", "weekends", or "Mon, Thu".
    static func describe(_ days: [String]) -> String {
        if days.count == 7 { return String(localized: "every day") }
        if days == ["MO", "TU", "WE", "TH", "FR"] { return String(localized: "weekdays") }
        if days == ["SA", "SU"] { return String(localized: "weekends") }
        return days.map { short($0) }.joined(separator: ", ")
    }

    /// In the week's order, whatever order they were picked in.
    static func sorted(_ days: [String]) -> [String] {
        codes.filter(days.contains)
    }
}

// MARK: - A person's colour

extension Color {
    /// `#rgb` or `#rrggbb`; nil for anything else.
    init?(luachHex hex: String) {
        guard let rgb = Self.rgb(hex) else { return nil }
        self.init(red: rgb.0, green: rgb.1, blue: rgb.2)
    }

    /// Black or white, whichever reads better on a person's colour (WCAG luminance).
    static func ink(on hex: String) -> Color {
        guard let (r, g, b) = rgb(hex) else { return .white }
        func lin(_ c: Double) -> Double { c <= 0.03928 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4) }
        let l = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
        return (l + 0.05) / 0.05 > 1.05 / (l + 0.05) ? .black : .white
    }

    private static func rgb(_ hex: String) -> (Double, Double, Double)? {
        var s = hex.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#") { s.removeFirst() }
        if s.count == 3 { s = s.map { "\($0)\($0)" }.joined() }
        guard s.count == 6, let v = UInt32(s, radix: 16) else { return nil }
        return (Double((v >> 16) & 0xFF) / 255, Double((v >> 8) & 0xFF) / 255, Double(v & 0xFF) / 255)
    }
}

/// A person's colour, or the app's accent for the family / anyone.
func personColor(_ hex: String) -> Color { Color(luachHex: hex) ?? .accentColor }
