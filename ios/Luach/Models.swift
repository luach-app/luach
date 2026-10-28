import Foundation

// Shapes from docs/API.md. Decoded with .convertFromSnakeCase, so `display_name`
// arrives as `displayName`. Only the fields the app shows are declared; the rest
// of each payload is ignored rather than mirrored.

struct Member: Codable, Equatable {
    let id: Int
    let username: String
    let displayName: String?
    let email: String?
    let timezone: String?
    /// `auto`, `en`, `es` or `he`.
    let language: String?
    let isOwner: Bool?

    var name: String {
        if let displayName, !displayName.isEmpty { return displayName }
        return username
    }
}

enum EventTime {
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
    /// An all-day date is a day on the phone's own calendar, not an instant in UTC.
    private static let day: DateFormatter = {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    static func parse(_ s: String) -> Date? {
        if s.count == 10 { return day.date(from: s) }
        return instant.date(from: s) ?? instantFractional.date(from: s)
    }

    static func dayString(_ date: Date) -> String {
        day.string(from: date)
    }
}

struct PendingAction: Decodable, Identifiable {
    struct Source: Decodable {
        let kind: String?
        /// The Gmail message's id, for "Open in Gmail".
        let id: String?
        let subject: String?
        let from: String?
        /// When the mail came, as the server words it.
        let when: String?

        /// The message in Gmail (the web app's link: by id under #all, whatever its label).
        var gmailLink: URL? {
            guard kind == "email", let id, !id.isEmpty,
                  let safe = id.addingPercentEncoding(withAllowedCharacters: .alphanumerics) else { return nil }
            return URL(string: "https://mail.google.com/mail/u/0/#all/\(safe)")
        }
    }

    let id: String
    let tool: String
    let summary: String
    let reason: [String]
    let principal: String
    let door: String
    let status: String
    let createdAt: String?
    /// Where a proposal came from when no one asked for it (the email scan); absent otherwise.
    let source: Source?
    /// Why an approved call did not go through (status "failed"): the tool's own error.
    let failure: String?

    private struct Result: Decodable { let error: String? }

    enum CodingKeys: String, CodingKey {
        case id, tool, summary, reason, principal, door, status, createdAt, source, result
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        tool = try c.decode(String.self, forKey: .tool)
        summary = try c.decode(String.self, forKey: .summary)
        reason = (try? c.decode([String].self, forKey: .reason)) ?? []
        principal = (try? c.decode(String.self, forKey: .principal)) ?? ""
        door = (try? c.decode(String.self, forKey: .door)) ?? ""
        status = try c.decode(String.self, forKey: .status)
        createdAt = try? c.decode(String.self, forKey: .createdAt)
        // "" when there is none, an object when there is.
        source = try? c.decode(Source.self, forKey: .source)
        failure = (try? c.decode(Result.self, forKey: .result))?.error
    }

    /// Approved, but the call it ran was refused, so nothing changed.
    var failed: Bool { status == "failed" }
}

struct PendingList: Decodable {
    let pending: [PendingAction]
}

// MARK: - The agent stream

/// Any JSON: a tool's arguments, or a field whose type varies.
enum JSONValue: Decodable, Hashable {
    case string(String), number(Double), bool(Bool), array([JSONValue]), object([String: JSONValue]), null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    var string: String? {
        if case .string(let s) = self { return s }
        return nil
    }

    var isTruthy: Bool {
        switch self {
        case .bool(let b): b
        case .string(let s): !s.isEmpty
        case .number(let n): n != 0
        case .null: false
        default: true
        }
    }

    subscript(key: String) -> JSONValue? {
        if case .object(let o) = self { return o[key] }
        return nil
    }
}

/// One `data:` line of `POST /api/agent/stream`. Every frame shares this one
/// shape; `type` says which fields are set.
struct StreamFrame: Decodable {
    let type: String
    let text: String?
    let threadId: String?
    /// The model (`model`, `done`) or the guide it followed (`skill`).
    let name: String?
    let model: String?
    let tool: String?
    let args: JSONValue?
    /// On a `tool_result` that failed: the tool's own words, written for the model.
    let error: JSONValue?
    let id: String?
    let summary: String?
    /// On a `held` frame: the gate's tags, as PendingRow.describe words them.
    let reason: JSONValue?
    let reasonText: String?
    let reply: String?
    let message: String?
    let kind: String?
    let data: WidgetData?
}

/// The data of an `agenda`, `availability` or `event` widget.
struct WidgetData: Decodable, Hashable {
    let title: String?
    let events: [CompactEvent]?
    let truncated: Bool?
    let event: CompactEvent?
    let free: Bool?
    let clashes: [CompactEvent]?
}

struct CompactEvent: Decodable, Hashable, Identifiable {
    let id: String
    let title: String
    /// A human line in the member's zone: "Fri 11 Sep 2026, 12:30–13:30".
    let when: String
    let location: String?
}

struct ThreadDetail: Decodable {
    struct Turn: Decodable {
        let role: String
        let content: String
        /// For an answer: its tool steps `{tool, args}`, then `{widget}` cards, then
        /// `{held: [...], created}`.
        let events: [JSONValue]?
    }
    let id: String
    let turns: [Turn]
}

struct ThreadSummary: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let door: String?
    let turns: Int
    let createdAt: String?
    let updatedAt: String
}

struct ThreadPage: Decodable {
    let threads: [ThreadSummary]
    let more: Bool
    let retentionDays: Int?
}
