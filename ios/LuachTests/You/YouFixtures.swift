import Foundation
import Testing
@testable import Luach

/// The You screens' answers as dev gives them (captured 2026-10-27, addresses made example.com).
@MainActor
enum YouFixtures {
    static let me: [String: Any] = [
        "id": 1, "username": "robin", "email": "robin@example.com", "display_name": "Robin",
        "timezone": "America/New_York", "language": "auto", "is_owner": true, "model": "",
        "last_seen": "2026-10-27T15:21:43.619628+00:00",
        "emails": ["robin@example.com", "robin@work.example.com"],
        "notify_emails": [], "notify_pending": [],
    ]

    static func me(_ changes: [String: Any]) -> [String: Any] {
        me.merging(changes) { _, new in new }
    }

    static let answering: [String: Any] = ["status": "ok", "since": NSNull(), "reason": ""]

    /// `GET /api/models` as the menu kept in the database gives it: where each model runs, and
    /// whether it is answering.
    static let models: [String: Any] = [
        "models": ["qwen3.6-35b", "cloud-deepseek-v4-flash", "openrouter/google/gemini-3.8-flash"],
        "default": "qwen3.6-35b",
        "configured": true,
        "catalogue": [
            ["id": "qwen3.6-35b", "name": "Home server · Qwen 3.6", "about": "Runs on the household's own machine. Nothing leaves the house.",
             "local": true, "provider": "", "health": answering],
            ["id": "cloud-deepseek-v4-flash", "name": "DeepSeek V4 Flash", "about": "A fast cloud model. What you ask is sent to the provider.",
             "local": false, "provider": "DeepSeek", "health": answering],
            ["id": "openrouter/google/gemini-3.8-flash", "name": "Gemini 3.8 Flash", "about": "Google's cloud model. What you ask is sent to Google.",
             "local": false, "provider": "Google, through OpenRouter", "health": answering],
        ],
        "chosen": "",
    ]

    /// The same menu from a luach older than the model menu: no `local`, `provider` or `health`.
    static let olderModels: [String: Any] = [
        "models": ["qwen3.6-35b", "cloud-deepseek-v4-flash"],
        "default": "qwen3.6-35b",
        "catalogue": [
            ["id": "qwen3.6-35b", "name": "Home server · Qwen 3.6", "about": "Runs on the household's own machine."],
            ["id": "cloud-deepseek-v4-flash", "name": "DeepSeek V4 Flash", "about": "A fast cloud model."],
        ],
        "chosen": "",
    ]

    /// A menu with a model that stopped answering, and one at home that is not the default.
    static let modelsOneDown: [String: Any] = [
        "models": ["cloud-deepseek-v4-flash", "shed-llama", "openrouter/google/gemini-3.8-flash"],
        "default": "cloud-deepseek-v4-flash",
        "configured": true,
        "catalogue": [
            ["id": "cloud-deepseek-v4-flash", "name": "DeepSeek V4 Flash", "about": "", "local": false,
             "provider": "DeepSeek", "health": answering],
            ["id": "shed-llama", "name": "Shed Llama", "about": "The old machine in the shed.", "local": true,
             "provider": "", "health": answering],
            ["id": "openrouter/google/gemini-3.8-flash", "name": "Gemini 3.8 Flash", "about": "", "local": false,
             "provider": "Google, through OpenRouter",
             "health": ["status": "not_answering", "since": "2026-10-28T08:00:00+00:00", "reason": "its provider refused it — 404"]],
        ],
        "chosen": "",
    ]

    static let emails: [String: Any] = [
        "primary": "robin@example.com",
        "emails": [
            ["email": "robin@example.com", "added_at": "2026-09-15T21:05:57.720975+00:00", "verified": true],
            ["email": "robin@work.example.com", "added_at": "2026-09-22T03:38:49.637740+00:00", "verified": true],
        ],
    ]

    static let memory: [String: Any] = [
        "facts": [["key": "chores", "topic": "chores", "fact": "Lily feeds the fish every day",
                   "saved_at": "2026-09-24T01:57:03.358608+00:00"]],
    ]

    static let passkeys: [String: Any] = [
        "passkeys": [
            ["id": "pk1", "name": "iPhone", "created_at": "2026-10-01T14:07:00+00:00", "last_used": "2026-10-20T09:00:00+00:00"],
            ["id": "pk2", "name": "", "created_at": "2026-10-02T14:07:00+00:00", "last_used": NSNull()],
        ],
    ]

    static let audit: [String: Any] = [
        "entries": [
            ["seq": 212, "ts": "2026-10-20T08:41:02.118430+00:00", "event_type": "task.added",
             "payload": ["id": 42, "title": "smoke check", "person": "ruby", "by": "smoke", "door": "web"],
             "hash": "ec7eeb3e6612b1a105761919b3d6da6e7486b6c7c4ea3fe469babdbbbf1c2f8a"],
            ["seq": 214, "ts": "2026-10-20T08:41:03.902215+00:00", "event_type": "turn.end",
             "payload": ["thread": "1e6285ae67dd8267ab6500d218824c0a", "tools": 1, "held": 0],
             "hash": "417c3f68dc0123a614e603b0f999b338fc13f149d8690d3f8b9607b2ce002f42"],
            ["seq": 213, "ts": "2026-10-20T08:41:02.130871+00:00", "event_type": "task.added",
             "payload": ["id": 43, "title": "smoke check", "person": "lily", "by": "smoke", "door": "web"],
             "hash": "2b514680b8320f437928d7989ace992eac8ef380b1e246219c16afa695ac3087"],
        ],
        "total": 217, "chain_verified": true,
        "head": "15a5b993a5f1a9f8b9b517cae8ac812553b955bf8968e1bf112ddea408002a51",
    ]

    static let members: [String: Any] = [
        "members": [
            me,
            ["id": 2, "username": "smoke", "email": "smoke@example.com", "display_name": "Smoke test",
             "timezone": "America/New_York", "language": "auto", "is_owner": false, "model": "",
             "last_seen": "2026-10-06T16:56:47.312513+00:00", "emails": ["smoke@example.com"],
             "notify_emails": [], "notify_pending": []],
        ],
        "invites": [],
    ]

    static let invites: [[String: Any]] = [
        ["email": "new@example.com", "created_at": "2026-10-25T10:00:00+00:00", "expires_at": "2026-11-01T10:00:00+00:00", "expired": false],
        ["email": "old@example.com", "created_at": "2026-09-01T10:00:00+00:00", "expires_at": "2026-09-08T10:00:00+00:00", "expired": true],
    ]

    static let colors: [[String: Any]] = [
        ["id": "1", "name": "Lavender", "hex": "#7986cb"], ["id": "2", "name": "Sage", "hex": "#33b679"],
        ["id": "3", "name": "Grape", "hex": "#8e24aa"], ["id": "4", "name": "Flamingo", "hex": "#e67c73"],
        ["id": "5", "name": "Banana", "hex": "#f6bf26"], ["id": "6", "name": "Tangerine", "hex": "#f4511e"],
        ["id": "7", "name": "Peacock", "hex": "#039be5"], ["id": "8", "name": "Graphite", "hex": "#616161"],
        ["id": "9", "name": "Blueberry", "hex": "#3f51b5"], ["id": "10", "name": "Basil", "hex": "#0b8043"],
        ["id": "11", "name": "Tomato", "hex": "#d50000"],
    ]

    static let ruby: [String: Any] = [
        "key": "ruby", "name": "Ruby", "color": "2", "kind": "kid", "email": "", "user_id": NSNull(),
        "position": 2, "hex": "#33b679",
    ]

    static let family: [String: Any] = [
        "people": [
            ["key": "robin", "name": "Robin", "color": "7", "kind": "adult", "email": "robin@example.com",
             "user_id": 1, "position": 0, "hex": "#039be5"],
            ruby,
            ["key": "lily", "name": "Lily", "color": "3", "kind": "kid", "email": "", "user_id": NSNull(),
             "position": 3, "hex": "#8e24aa"],
        ],
        "colors": colors,
    ]

    static let boards: [String: Any] = [
        "boards": [
            ["id": 3, "name": "Kitchen", "created_at": "2026-10-01T10:00:00+00:00",
             "last_seen": "2026-10-27T10:00:00+00:00", "can_edit": true, "language": "auto"],
            ["id": 4, "name": "Hall", "created_at": "2026-10-02T10:00:00+00:00",
             "last_seen": NSNull(), "can_edit": false, "language": "he"],
        ],
    ]

    /// A session signed in to `server` as the fixture member (so `setMember` takes).
    static func session(_ server: StubServer, me: [String: Any]? = nil) async -> AppSession {
        server.on("GET", "/api/auth/me", json: me ?? Self.me)
        let session = AppSession(api: server.api)
        await session.restore()
        return session
    }

    static func decode<T: Decodable>(_ type: T.Type, _ json: Any) throws -> T {
        try JSONDecoder.you.decode(T.self, from: JSONSerialization.data(withJSONObject: json))
    }
}

extension JSONDecoder {
    /// The API's own decoding: snake_case keys.
    static var you: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }
}

extension StubServer.Request {
    /// The body's keys, to check a PATCH sends only what changed.
    var keys: Set<String> { Set(json.keys) }
}
