import Foundation

/// Days and times as the member sees them, the way the web agenda does: a day is a
/// `YYYY-MM-DD` string in the member's own zone (the zone the write API reads wall
/// clocks in, which may not be the phone's), and words are in the member's language.
final class AgendaClock {
    let tz: TimeZone
    let locale: Locale
    let calendar: Calendar

    private static var last: AgendaClock?

    /// The clock for a member, reused while their zone and language stay the same.
    static func of(_ member: Member?) -> AgendaClock {
        let tz = member?.timezone.flatMap(TimeZone.init(identifier:)) ?? .current
        let locale: Locale
        switch member?.language {
        case let lang? where ["en", "es", "he"].contains(lang): locale = Locale(identifier: lang)
        default: locale = .current
        }
        if let last, last.tz == tz, last.locale == locale { return last }
        let clock = AgendaClock(tz: tz, locale: locale)
        last = clock
        return clock
    }

    init(tz: TimeZone, locale: Locale) {
        self.tz = tz
        self.locale = locale
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = tz
        cal.locale = locale
        cal.firstWeekday = Self.sundayFirst(locale) ? 1 : 2
        calendar = cal
    }

    /// Weeks start on Sunday where the family's language counts them so (Hebrew, as the web
    /// board does), and on Monday otherwise.
    static func sundayFirst(_ locale: Locale) -> Bool {
        locale.language.languageCode?.identifier == "he"
    }

    var sundayFirst: Bool { Self.sundayFirst(locale) }

    // MARK: Pure day arithmetic (no zone)

    private static let utc: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "UTC")!
        return c
    }()
    private static let dayFormat = posix("yyyy-MM-dd", TimeZone(identifier: "UTC")!)

    private static func posix(_ format: String, _ tz: TimeZone) -> DateFormatter {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = tz
        f.dateFormat = format
        return f
    }

    static func isDay(_ s: String) -> Bool {
        s.count == 10 && s.wholeMatch(of: /\d{4}-\d{2}-\d{2}/) != nil
    }

    /// Noon UTC of that calendar day: safe to name its weekday and month in UTC.
    static func noon(_ day: String) -> Date {
        (dayFormat.date(from: day) ?? .distantPast).addingTimeInterval(12 * 3600)
    }

    static func addDays(_ day: String, _ n: Int) -> String {
        dayFormat.string(from: utc.date(byAdding: .day, value: n, to: noon(day)) ?? noon(day))
    }

    static func ym(_ day: String) -> String { String(day.prefix(7)) }

    static func addMonths(_ ym: String, _ n: Int) -> String {
        let first = noon("\(ym)-01")
        return String(dayFormat.string(from: utc.date(byAdding: .month, value: n, to: first) ?? first).prefix(7))
    }

    /// The day's place in the week: 0 = Monday … 6 = Sunday, or 0 = Sunday … 6 = Saturday.
    static func weekdayMon(_ day: String, sundayFirst: Bool = false) -> Int {
        (utc.component(.weekday, from: noon(day)) + (sundayFirst ? 6 : 5)) % 7
    }

    /// The grid of whole weeks (Mon–Sun, or Sun–Sat) that covers `ym`, four to six rows.
    static func monthGrid(_ ym: String, sundayFirst: Bool = false) -> (first: String, last: String, weeks: [[String]]) {
        let first1 = "\(ym)-01"
        let lastOfMonth = addDays("\(addMonths(ym, 1))-01", -1)
        let first = addDays(first1, -weekdayMon(first1, sundayFirst: sundayFirst))
        let last = addDays(lastOfMonth, 6 - weekdayMon(lastOfMonth, sundayFirst: sundayFirst))
        var weeks: [[String]] = []
        var d = first
        while d <= last {
            weeks.append((0..<7).map { addDays(d, $0) })
            d = addDays(d, 7)
        }
        return (first, last, weeks)
    }

    // MARK: In the member's zone

    private lazy var zonedDay = Self.posix("yyyy-MM-dd", tz)
    private lazy var zonedInput = Self.posix("yyyy-MM-dd'T'HH:mm", tz)

    func day(of date: Date) -> String { zonedDay.string(from: date) }
    func today() -> String { day(of: .now) }
    /// Midnight of that day in the member's zone.
    func date(ofDay day: String) -> Date { zonedDay.date(from: day) ?? .now }
    /// `YYYY-MM-DDTHH:MM` in the member's zone: the shape the write API takes.
    func input(_ date: Date) -> String { zonedInput.string(from: date) }
    func date(fromInput s: String) -> Date? { zonedInput.date(from: s) }

    /// The top of the next hour, on `day` (YYYY-MM-DD) when given.
    func nextHour(on day: String? = nil) -> Date {
        let soon = Date.now.addingTimeInterval(3600)
        let top = calendar.dateInterval(of: .hour, for: soon)?.start ?? soon
        guard let day else { return top }
        return date(fromInput: "\(day)T\(input(top).suffix(5))") ?? top
    }

    private static let instant: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    private static let instantFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    /// An ISO instant with its offset (`2026-09-16T15:00:00-04:00`, fractions allowed).
    func instant(_ s: String) -> Date? {
        if let d = Self.instant.date(from: s) ?? Self.instantFractional.date(from: s) { return d }
        // Microseconds, which ISO8601DateFormatter will not read: drop them.
        let trimmed = s.replacing(/\.\d+/, with: "")
        return Self.instant.date(from: trimmed)
    }

    // MARK: Words

    private var formatters: [String: DateFormatter] = [:]

    private func formatter(_ template: String, zoned: Bool) -> DateFormatter {
        let key = "\(zoned)|\(template)"
        if let f = formatters[key] { return f }
        let f = DateFormatter()
        f.calendar = calendar
        f.locale = locale
        f.timeZone = zoned ? tz : TimeZone(identifier: "UTC")
        f.setLocalizedDateFormatFromTemplate(template)
        formatters[key] = f
        return f
    }

    func dayName(_ day: String, long: Bool = false) -> String {
        formatter(long ? "EEEE" : "EEE", zoned: false).string(from: Self.noon(day))
    }
    func dayNumber(_ day: String) -> String { String(Int(day.suffix(2)) ?? 0) }
    /// "Monday, October 26".
    func dateLong(_ day: String) -> String { formatter("EEEEdMMMM", zoned: false).string(from: Self.noon(day)) }
    func dateShort(_ day: String) -> String { formatter("EEEdMMM", zoned: false).string(from: Self.noon(day)) }
    func time(_ date: Date) -> String { formatter("jmm", zoned: true).string(from: date) }
    func dateTime(_ date: Date) -> String { formatter("EEEdMMMjmm", zoned: true).string(from: date) }
    func monthYear(_ ym: String) -> String { formatter("MMMMy", zoned: false).string(from: Self.noon("\(ym)-01")) }
    func monthShort(_ month: Int) -> String {
        formatter("MMM", zoned: false).string(from: Self.noon(String(format: "2024-%02d-01", month)))
    }

    /// The week's days as one letter each in the member's language, from the day it starts on.
    func weekdayLetters() -> [String] {
        let symbols = calendar.veryShortStandaloneWeekdaySymbols // Sun first
        return sundayFirst ? symbols : Array(symbols[1...]) + [symbols[0]]
    }

    // MARK: Events

    /// The day (YYYY-MM-DD, member's zone) an event starts.
    func startDay(_ ev: AgendaEvent) -> String {
        if ev.isAllDay { return String(ev.start.prefix(10)) }
        return instant(ev.start).map(day(of:)) ?? String(ev.start.prefix(10))
    }

    /// Every day the event touches, clipped to `from`…`to` inclusive.
    func days(_ ev: AgendaEvent, from: String, to: String) -> [String] {
        let first = startDay(ev)
        guard !first.isEmpty else { return [] }
        var last = first
        if ev.isAllDay {
            if Self.isDay(ev.end) { last = Self.addDays(ev.end, -1) }
        } else if let end = instant(ev.end) {
            last = day(of: end)
        }
        if last < first { last = first }
        var out: [String] = []
        var d = max(first, from)
        while d <= last && d <= to {
            out.append(d)
            d = Self.addDays(d, 1)
        }
        return out
    }

    /// Each day's events, all-day first, then by start.
    func byDay(_ events: [AgendaEvent], from: String, to: String) -> [String: [AgendaEvent]] {
        var map: [String: [AgendaEvent]] = [:]
        for ev in sorted(events) {
            for d in days(ev, from: from, to: to) { map[d, default: []].append(ev) }
        }
        return map
    }

    func sorted(_ events: [AgendaEvent]) -> [AgendaEvent] {
        events.sorted { a, b in
            let da = startDay(a), db = startDay(b)
            if da != db { return da < db }
            if a.isAllDay != b.isAllDay { return a.isAllDay }
            return (instant(a.start) ?? .distantPast) < (instant(b.start) ?? .distantPast)
        }
    }

    /// "3:00 – 3:45 PM", "All day", "Tue, Sep 16 – Thu, Sep 18", or both dates when it spans days.
    func range(_ ev: AgendaEvent) -> String {
        if ev.start.isEmpty { return "" }
        if ev.isAllDay {
            let endInc = Self.isDay(ev.end) ? Self.addDays(ev.end, -1) : ev.start
            if endInc != ev.start { return "\(dateShort(ev.start)) – \(dateShort(endInc))" }
            return String(localized: "All day")
        }
        guard let start = instant(ev.start) else { return ev.start }
        guard let end = instant(ev.end) else { return time(start) }
        if day(of: start) != day(of: end) { return "\(dateTime(start)) – \(dateTime(end))" }
        return "\(time(start)) – \(time(end))"
    }
}
