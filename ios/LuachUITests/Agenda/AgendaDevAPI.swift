import Foundation
import XCTest

/// The UI tests' own line to the test server, beside the app: to know the member's today, to
/// find what a test made, and to remove it whatever happened. Only `ios-test…` events, with no
/// one invited, are ever written.
nonisolated enum AgendaDevAPI {
    static var server: String? { ProcessInfo.processInfo.environment["LUACH_TEST_SERVER"] }
    static var session: String? { ProcessInfo.processInfo.environment["LUACH_TEST_SESSION"] }

    struct Event {
        let json: [String: Any]
        var id: String { json["id"] as? String ?? "" }
        var title: String { json["title"] as? String ?? "" }
        var series: String { (json["recurring_event_id"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? id }
        var calendar: String { json["calendar_id"] as? String ?? "" }
        var allDay: Bool { json["all_day"] as? Bool ?? false }
        var recurrence: [String] { json["recurrence"] as? [String] ?? [] }
        var attendees: [String] { json["attendees"] as? [String] ?? [] }
        var leaders: [String] { json["leaders"] as? [String] ?? [] }
        var location: String { json["location"] as? String ?? "" }
    }

    static func call(_ method: String, _ path: String, query: [String: String] = [:],
                     body: [String: Any]? = nil) async throws -> (Int, [String: Any]) {
        guard let server, let session, !session.isEmpty,
              var url = URL(string: server)?.appending(path: path) else {
            throw XCTSkip("no test server")
        }
        if !query.isEmpty { url.append(queryItems: query.map { URLQueryItem(name: $0.key, value: $0.value) }) }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("luach_session=\(session)", forHTTPHeaderField: "Cookie")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await URLSession.shared.data(for: req)
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        return ((response as? HTTPURLResponse)?.statusCode ?? 0, json)
    }

    /// The member's zone, as the agenda reads days.
    static func zone() async throws -> TimeZone {
        let (_, me) = try await call("GET", "/api/auth/me")
        return (me["timezone"] as? String).flatMap(TimeZone.init(identifier:)) ?? .current
    }

    /// `YYYY-MM-DD` of today plus `n` days in the member's zone.
    static func day(_ n: Int, in tz: TimeZone) -> String {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = tz
        let date = cal.date(byAdding: .day, value: n, to: .now)!
        let c = cal.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year!, c.month!, c.day!)
    }

    static func events(from: String, to: String) async throws -> [Event] {
        let (_, page) = try await call("GET", "/api/calendar/events", query: ["start": from, "end": to])
        return (page["events"] as? [[String: Any]] ?? []).map(Event.init)
    }

    /// The events whose title starts with `title`, around `day`.
    static func find(_ title: String, around day: String) async throws -> [Event] {
        try await events(from: shift(day, -7), to: shift(day, 45)).filter { $0.title.hasPrefix(title) }
    }

    static func event(_ id: String) async throws -> (Int, Event) {
        let (status, json) = try await call("GET", "/api/calendar/events/\(id)")
        return (status, Event(json: json))
    }

    /// A timed event at `hour`, inviting nobody.
    static func create(_ title: String, on day: String, hour: Int = 10) async throws -> Event {
        precondition(title.hasPrefix("ios-test"))
        let (status, json) = try await call("POST", "/api/calendar/events", body: [
            "title": title, "start": String(format: "%@T%02d:00", day, hour),
            "end": String(format: "%@T%02d:30", day, hour), "attendees": [String](),
        ])
        XCTAssertEqual(status, 200, "could not make \(title): \(json)")
        return Event(json: json)
    }

    /// Deletes every event (the whole series of a repeating one) whose title starts with `title`.
    static func sweep(_ title: String, around day: String) async {
        precondition(title.hasPrefix("ios-test"))
        for _ in 0..<3 {
            guard let left = try? await find(title, around: day), !left.isEmpty else { return }
            for id in Set(left.map(\.series)) {
                _ = try? await call("DELETE", "/api/calendar/events/\(id)")
            }
        }
    }

    static func shift(_ day: String, _ n: Int) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd"
        let d = f.date(from: day)!.addingTimeInterval(Double(n) * 86400 + 43200)
        return f.string(from: d)
    }

    /// "Thursday, October 29", as the agenda writes a day.
    static func long(_ day: String) -> String {
        words(day, "EEEEMMMMd")
    }

    /// "October 2026".
    static func monthYear(_ day: String) -> String {
        words(day, "MMMMyyyy")
    }

    static func weekday(_ day: String) -> String {
        words(day, "EEEE")
    }

    private static func words(_ day: String, _ template: String) -> String {
        let read = DateFormatter()
        read.locale = Locale(identifier: "en_US_POSIX")
        read.timeZone = TimeZone(identifier: "UTC")
        read.dateFormat = "yyyy-MM-dd"
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US")
        f.timeZone = TimeZone(identifier: "UTC")
        f.setLocalizedDateFormatFromTemplate(template)
        return f.string(from: read.date(from: day)!.addingTimeInterval(43200))
    }
}
