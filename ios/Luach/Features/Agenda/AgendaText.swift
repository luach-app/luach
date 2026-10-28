import SwiftUI

/// Repeats, as a person says them, and as Google needs them (web `lib/recurrence.ts`).
enum AgendaRepeat: String, CaseIterable, Identifiable {
    case none, daily, weekly, biweekly, monthly, yearly
    /// A rule luach's menu cannot say: left exactly as it was.
    case custom

    var id: String { rawValue }

    static let offered: [AgendaRepeat] = [.none, .daily, .weekly, .biweekly, .monthly, .yearly]

    var label: String {
        switch self {
        case .none: String(localized: "Does not repeat")
        case .daily: String(localized: "Every day")
        case .weekly: String(localized: "Every week")
        case .biweekly: String(localized: "Every two weeks")
        case .monthly: String(localized: "Every month")
        case .yearly: String(localized: "Every year")
        case .custom: String(localized: "Custom")
        }
    }

    private static let days = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]

    private static func body(_ rules: [String]) -> String {
        guard let rule = rules.first(where: { $0.uppercased().contains("FREQ=") }) else { return "" }
        let upper = rule.uppercased()
        return upper.hasPrefix("RRULE:") ? String(upper.dropFirst(6)) : upper
    }

    private static func value(_ rule: String, _ key: String) -> String? {
        rule.split(separator: ";").first { $0.hasPrefix("\(key)=") }.map { String($0.dropFirst(key.count + 1)) }
    }

    /// Which of the offered repeats an event already is.
    static func of(_ rules: [String]) -> AgendaRepeat {
        let rule = body(rules)
        if rule.isEmpty { return .none }
        let has = { (k: String) in rule.contains(k) }
        let interval = value(rule, "INTERVAL")
        let plain = !has("COUNT=") && !has("UNTIL=") && !has("BYMONTHDAY=") && !has("BYSETPOS=")
        if !plain { return .custom }
        if has("FREQ=DAILY") && interval == nil { return .daily }
        if has("FREQ=WEEKLY") && (interval == nil || interval == "1") { return .weekly }
        if has("FREQ=WEEKLY") && interval == "2" { return .biweekly }
        if has("FREQ=MONTHLY") && interval == nil { return .monthly }
        if has("FREQ=YEARLY") && interval == nil { return .yearly }
        return .custom
    }

    /// What the editor sends for a choice: the menu's own word, which the server makes into a
    /// rule on the event's own day in the member's zone (it owns the RRULE, for the web too).
    /// "" is no repeat; a kept rule is never sent, so "" for it too.
    var word: String {
        switch self {
        case .none, .custom: ""
        default: rawValue
        }
    }

    /// "Every week on Tuesday" rather than "RRULE:FREQ=WEEKLY;BYDAY=TU".
    static func describe(_ rules: [String], locale: Locale) -> String {
        let rule = body(rules)
        if rule.isEmpty { return "" }
        var cal = Calendar(identifier: .gregorian)
        cal.locale = locale
        let weekdays = (value(rule, "BYDAY") ?? "")
            .split(separator: ",")
            .map { d -> String in
                guard let i = days.firstIndex(of: String(d.suffix(2))) else { return String(d) }
                return cal.standaloneWeekdaySymbols[i]
            }
            .joined(separator: ", ")
        let unit: String
        if rule.contains("FREQ=DAILY") { unit = "day" }
        else if rule.contains("FREQ=WEEKLY") { unit = "week" }
        else if rule.contains("FREQ=MONTHLY") { unit = "month" }
        else if rule.contains("FREQ=YEARLY") { unit = "year" }
        else { return rule }
        let every = value(rule, "INTERVAL")
        var out: String
        if let every, every != "1" {
            switch unit {
            case "day": out = String(localized: "Every \(every) days")
            case "week": out = String(localized: "Every \(every) weeks")
            case "month": out = String(localized: "Every \(every) months")
            default: out = String(localized: "Every \(every) years")
            }
        } else {
            switch unit {
            case "day": out = String(localized: "Every day")
            case "week": out = String(localized: "Every week")
            case "month": out = String(localized: "Every month")
            default: out = String(localized: "Every year")
            }
        }
        if !weekdays.isEmpty { out = String(localized: "\(out) on \(weekdays)") }
        if let times = value(rule, "COUNT") {
            out = String(localized: "\(out), \(times) times")
        } else if let until = value(rule, "UNTIL"), until.count >= 8 {
            let d = Array(until)
            out = String(localized: "\(out), until \(String(d[0..<4]))-\(String(d[4..<6]))-\(String(d[6..<8]))")
        }
        return out
    }
}

/// An event's notes as a person should read them (web `lib/notes.tsx`). Google keeps an
/// invitation's description as HTML; it is shown as text, each link's address kept
/// beside its words, and the links are tappable.
enum AgendaNotes {
    static func isHTML(_ text: String) -> Bool {
        text.firstMatch(of: /(?i)<\/?(a|b|strong|i|em|u|br|p|div|span|ul|ol|li|h[1-6])\b[^>]*>/) != nil
    }

    /// Notes for editing (and reading), as text.
    static func asText(_ text: String) -> String {
        guard isHTML(text) else { return text }
        var s = text
        s = replace(s, #"<(script|style)\b[^>]*>.*?</\1>"#) { _ in "" }
        s = replace(s, #"<a\b[^>]*?href\s*=\s*["']([^"']*)["'][^>]*>(.*?)</a>"#) { g in
            // Decoded once, with the rest below: decoding here too turned an escaped
            // `&lt;name@example.com&gt;` into a tag the strip below then removed.
            let href = g[1], words = strip(g[2])
            guard href.range(of: #"^(https?:|mailto:)"#, options: [.regularExpression, .caseInsensitive]) != nil,
                  !words.contains(href) else { return words }
            return "\(words) (\(href))"
        }
        s = replace(s, #"<br\s*/?>"#) { _ in "\n" }
        s = replace(s, #"<li\b[^>]*>"#) { _ in "\n• " }
        s = replace(s, #"</(p|div|ul|ol|h[1-6])>"#) { _ in "\n" }
        s = decode(strip(s))
        s = replace(s, #"[ \t]+\n"#) { _ in "\n" }
        s = replace(s, #"\n{3,}"#) { _ in "\n\n" }
        return s.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// The text with every web address and email made a link.
    static func attributed(_ text: String) -> AttributedString {
        let plain = asText(text)
        let ns = NSMutableAttributedString(string: plain)
        if let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) {
            for match in detector.matches(in: plain, range: NSRange(location: 0, length: (plain as NSString).length)) {
                if let url = match.url { ns.addAttribute(.link, value: url, range: match.range) }
            }
        }
        return (try? AttributedString(ns, including: \.foundation)) ?? AttributedString(plain)
    }

    private static func strip(_ s: String) -> String {
        s.replacingOccurrences(of: #"<[^>]+>"#, with: "", options: .regularExpression)
    }

    private static func decode(_ s: String) -> String {
        var out = s
        for (entity, char) in [("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", "\""), ("&#39;", "'"), ("&apos;", "'")] {
            out = out.replacingOccurrences(of: entity, with: char)
        }
        out = replace(out, #"&#(\d+);"#) { g in
            Int(g[1]).flatMap(UnicodeScalar.init).map { String(Character($0)) } ?? g[0]
        }
        return out.replacingOccurrences(of: "&amp;", with: "&")
    }

    private static func replace(_ s: String, _ pattern: String, _ with: ([String]) -> String) -> String {
        guard let re = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive, .dotMatchesLineSeparators]) else { return s }
        let ns = s as NSString
        var out = ""
        var at = 0
        for m in re.matches(in: s, range: NSRange(location: 0, length: ns.length)) {
            out += ns.substring(with: NSRange(location: at, length: m.range.location - at))
            let groups = (0..<m.numberOfRanges).map { i -> String in
                let r = m.range(at: i)
                return r.location == NSNotFound ? "" : ns.substring(with: r)
            }
            out += with(groups)
            at = m.range.location + m.range.length
        }
        return out + ns.substring(from: at)
    }
}

enum AgendaWords {
    /// "Noa", "Noa and Sam", "Noa, Sam and Ari".
    static func names(_ names: [String]) -> String {
        guard let last = names.last else { return "" }
        return names.count > 1 ? String(localized: "\(names.dropLast().joined(separator: ", ")) and \(last)") : last
    }

    static let emailPattern = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

    /// Under "Delete this event?": its title, or for one occurrence of a repeating event, the
    /// choice its buttons offer.
    static func deleting(_ event: AgendaEvent) -> String {
        event.isOccurrence
            ? String(localized: "\(event.displayTitle) repeats. Delete only this one, or every one?")
            : event.displayTitle
    }
}

enum AgendaPalette {
    /// `#039be5` as a colour; nil when it is not one.
    static func color(_ hex: String) -> Color? {
        var s = hex.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#") { s.removeFirst() }
        guard s.count == 6, let v = UInt32(s, radix: 16) else { return nil }
        return Color(red: Double((v >> 16) & 0xFF) / 255, green: Double((v >> 8) & 0xFF) / 255, blue: Double(v & 0xFF) / 255)
    }
}
