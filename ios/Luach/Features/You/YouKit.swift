import SwiftUI

/// Shapes and helpers the You screens share (Profile, emails, memory, security,
/// members). Namespaced so they never meet another area's types of the same name.
enum YouKit {
    // MARK: Shapes

    /// `GET`/`PATCH /api/auth/me` with the fields core `Member` leaves out.
    struct Me: Decodable {
        let member: Member
        /// The member's model pick; "" is the household's default.
        let model: String
        let emails: [String]
        let notifyEmails: [String]
        let notifyPending: [String]

        private enum Keys: String, CodingKey { case model, emails, notifyEmails, notifyPending }

        init(from decoder: Decoder) throws {
            member = try Member(from: decoder)
            let c = try decoder.container(keyedBy: Keys.self)
            model = (try? c.decodeIfPresent(String.self, forKey: .model)) ?? ""
            emails = (try? c.decodeIfPresent([String].self, forKey: .emails)) ?? []
            notifyEmails = (try? c.decodeIfPresent([String].self, forKey: .notifyEmails)) ?? []
            notifyPending = (try? c.decodeIfPresent([String].self, forKey: .notifyPending)) ?? []
        }
    }

    /// `GET /api/models`. Every field past the id, name and about is newer than the first
    /// servers the app met, so each is optional: an older luach still decodes, and asks.
    struct ModelMenu: Decodable {
        /// Whether a model is answering: `ok`, or `not_answering` since a time, with the reason.
        struct Health: Decodable, Equatable {
            let status: String
            let since: String?
            let reason: String

            static let ok = Health(status: "ok", since: nil, reason: "")

            init(status: String, since: String?, reason: String) {
                self.status = status
                self.since = since
                self.reason = reason
            }

            private enum Keys: String, CodingKey { case status, since, reason }

            init(from decoder: Decoder) throws {
                let c = try decoder.container(keyedBy: Keys.self)
                status = (try? c.decodeIfPresent(String.self, forKey: .status)) ?? "ok"
                since = try? c.decodeIfPresent(String.self, forKey: .since)
                reason = (try? c.decodeIfPresent(String.self, forKey: .reason)) ?? ""
            }

            /// Only a model the server says is not answering is not: anything else is taken as ok.
            var answering: Bool { status != "not_answering" }
        }

        struct Choice: Decodable, Identifiable {
            let id: String
            let name: String
            let about: String
            /// Runs on the household's own machine: nothing leaves the house. Unknown is false,
            /// so a member is asked before their questions go anywhere.
            let local: Bool
            /// Who answers it ("" at home, or unknown).
            let provider: String
            let health: Health

            init(id: String, name: String, about: String, local: Bool = false, provider: String = "",
                 health: Health = .ok) {
                self.id = id
                self.name = name
                self.about = about
                self.local = local
                self.provider = provider
                self.health = health
            }

            private enum Keys: String, CodingKey { case id, name, about, local, provider, health }

            init(from decoder: Decoder) throws {
                let c = try decoder.container(keyedBy: Keys.self)
                id = try c.decode(String.self, forKey: .id)
                let named = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
                name = named.isEmpty ? id : named
                about = (try? c.decodeIfPresent(String.self, forKey: .about)) ?? ""
                local = (try? c.decodeIfPresent(Bool.self, forKey: .local)) ?? false
                provider = (try? c.decodeIfPresent(String.self, forKey: .provider)) ?? ""
                health = (try? c.decodeIfPresent(Health.self, forKey: .health)) ?? .ok
            }

            var answering: Bool { health.answering }
        }
        let catalogue: [Choice]?
        let `default`: String?
        /// Whether the household has a model server set up (newer servers only).
        let configured: Bool?
    }

    /// `/api/auth/emails`: every call answers with the whole listing.
    struct EmailListing: Decodable {
        struct Row: Decodable {
            let email: String
            let addedAt: String?
            let verified: Bool?
        }
        let primary: String
        let emails: [Row]
    }

    struct MemoryFact: Decodable, Identifiable {
        let key: String
        let topic: String?
        let fact: String
        let savedAt: String?
        var id: String { key }
    }

    struct MemoryListing: Decodable {
        let facts: [MemoryFact]
    }

    struct Passkey: Decodable, Identifiable {
        let id: String
        let name: String?
        let createdAt: String?
        let lastUsed: String?
    }

    struct PasskeyListing: Decodable {
        let passkeys: [Passkey]
    }

    /// A member as `/api/members` lists them.
    struct Housemate: Decodable, Identifiable {
        let id: Int
        let username: String
        let email: String?
        let emails: [String]?
        let displayName: String?
        let isOwner: Bool?
        let lastSeen: String?

        var name: String { (displayName ?? "").isEmpty ? username : displayName! }
        /// Every address, primary first; older servers only send `email`.
        var allEmails: [String] { (emails ?? []).isEmpty ? [email].compactMap { $0 } : emails! }
    }

    struct Invite: Decodable, Identifiable {
        let email: String
        let createdAt: String
        let expiresAt: String
        let expired: Bool
        var id: String { "\(email)-\(createdAt)" }
    }

    struct MembersReply: Decodable {
        let members: [Housemate]
        let invites: [Invite]
    }

    /// Someone events and tasks are for; not an account.
    struct Person: Decodable, Identifiable, Hashable {
        let key: String
        let name: String
        let color: String
        let hex: String
        let kind: String
        let email: String
        let userId: Int?
        let position: Int?
        var id: String { key }
        var isKid: Bool { kind == "kid" }
    }

    struct FamilyColor: Decodable, Identifiable, Hashable {
        let id: String
        let name: String
        let hex: String
    }

    struct Family: Decodable {
        let people: [Person]
        let colors: [FamilyColor]

        /// The web's `exampleName`: a child's name, else anyone's, else "someone".
        var exampleName: String {
            (people.first { $0.isKid } ?? people.first)?.name ?? String(localized: "someone")
        }
    }

    struct HouseBoard: Decodable, Identifiable {
        let id: Int
        let name: String
        let createdAt: String?
        let lastSeen: String?
        let canEdit: Bool?
        let language: String?
    }

    struct BoardList: Decodable {
        let boards: [HouseBoard]
    }

    // MARK: Words and choices

    /// The languages luach answers in, as the web lists them (each in its own words).
    static let languages: [(value: String, label: String)] = [
        ("auto", String(localized: "Automatic")),
        ("en", "English"),
        ("es", "Español"),
        ("he", "עברית"),
    ]

    private static let emailPattern = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

    /// The web's EmailChips cleaning: trimmed, lower case, a trailing `,` or `;` dropped.
    static func cleanEmail(_ text: String) -> String {
        var s = text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if s.hasSuffix(",") || s.hasSuffix(";") { s.removeLast() }
        return s
    }

    static func isEmail(_ text: String) -> Bool {
        text.wholeMatch(of: emailPattern) != nil
    }

    // MARK: Times

    private static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    /// luach's stored times: UTC with an offset, sometimes with microseconds; a time
    /// without an offset is UTC (as the web reads it).
    static func date(_ text: String?) -> Date? {
        guard var s = text, !s.isEmpty else { return nil }
        if !(s.hasSuffix("Z") || s.wholeMatch(of: /.*[+-]\d{2}:\d{2}/) != nil) { s += "Z" }
        return isoFractional.date(from: s) ?? iso.date(from: s)
    }

    /// "3 days ago", "in 6 days"; "never" for no time at all.
    static func relative(_ text: String?) -> String {
        guard let text, !text.isEmpty else { return String(localized: "never") }
        guard let d = date(text) else { return text }
        let f = RelativeDateTimeFormatter()
        f.dateTimeStyle = .named
        return f.localizedString(for: d, relativeTo: .now)
    }

    /// "26 Oct, 10:07" in the member's own zone, like the web's formatTimestamp.
    static func timestamp(_ text: String?, zone: String?) -> String {
        guard let text, let d = date(text) else { return text ?? "" }
        var style = Date.FormatStyle.dateTime.day().month(.abbreviated).hour().minute()
        if let zone, let tz = TimeZone(identifier: zone) { style.timeZone = tz }
        return d.formatted(style)
    }
}

extension Color {
    /// `#rrggbb`, the family's Google Calendar colours.
    init(youHex hex: String) {
        let digits = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        let v = UInt32(digits, radix: 16) ?? 0x888888
        self.init(
            red: Double((v >> 16) & 0xFF) / 255,
            green: Double((v >> 8) & 0xFF) / 255,
            blue: Double(v & 0xFF) / 255
        )
    }
}

/// A small capsule label: "primary", "owner", "unconfirmed".
struct YouBadge: View {
    let text: LocalizedStringKey
    var tint: Color = .secondary

    init(_ text: LocalizedStringKey, tint: Color = .secondary) {
        self.text = text
        self.tint = tint
    }

    var body: some View {
        Text(text)
            .font(.caption.weight(.medium))
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .foregroundStyle(tint)
            .background(tint.opacity(0.15), in: Capsule())
    }
}

/// The server's sentence after something did not work, in red, as the other screens show it.
struct YouError: View {
    let message: String?

    var body: some View {
        if let message, !message.isEmpty {
            Text(message).foregroundStyle(.red)
        }
    }
}

/// "Saved." and the like, after something went through.
struct YouDone: View {
    let text: LocalizedStringKey

    init(_ text: LocalizedStringKey) { self.text = text }

    var body: some View {
        Label(text, systemImage: "checkmark.circle.fill").foregroundStyle(.green)
    }
}

#if DEBUG
/// Debug launch arguments for inner states, e.g. `-youPush family`.
enum YouDebug {
    static func value(_ key: String) -> String? { UserDefaults.standard.string(forKey: key) }
}
#endif
