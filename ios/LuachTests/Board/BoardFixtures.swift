import Foundation
@testable import Luach

/// Answers as dev gives them (captured with curl on 2026-10-27, addresses replaced).
enum BoardFixtures {
    static let people: [[String: Any]] = [
        ["key": "robin", "name": "Robin", "hex": "#039be5", "kind": "adult"],
        ["key": "smoke-test", "name": "Smoke test", "hex": "#f4511e", "kind": "adult"],
        ["key": "ruby", "name": "Ruby", "hex": "#33b679", "kind": "kid"],
        ["key": "lily", "name": "Lily", "hex": "#8e24aa", "kind": "kid"],
    ]

    static let timedEvent: [String: Any] = [
        "id": "c6956f0a832e", "title": "Swim", "start": "2026-10-27T15:00:00-04:00",
        "end": "2026-10-27T16:00:00-04:00", "all_day": false, "location": "",
        "leaders": ["ruby", "lily"], "leader": "ruby", "read_only": false, "organizer": "",
        "recurring": false, "calendar_id": "fake",
    ]

    static let allDayEvent: [String: Any] = [
        "id": "d3cfd3f1ce66", "title": "Book fair", "start": "2026-10-28", "end": "2026-10-29",
        "all_day": true, "location": "", "leaders": [], "leader": "", "read_only": false,
        "organizer": "", "recurring": false, "calendar_id": "fake",
    ]

    static let todo: [String: Any] = [
        "id": 132, "title": "Library books", "person": "ruby", "due": "2026-10-26", "days": [],
        "notes": "the blue bag", "done": false, "overdue": true, "chore": false,
    ]

    static let chore: [String: Any] = [
        "id": 133, "title": "Feed the cat", "person": "", "due": "",
        "days": ["MO", "TU", "WE", "TH", "FR", "SA", "SU"], "notes": "", "done": false,
        "overdue": false, "chore": true,
    ]

    static func board(
        day: String = "2026-10-27", today: String = "2026-10-27",
        events: [[String: Any]]? = nil, tomorrow: [[String: Any]]? = nil, tasks: [[String: Any]]? = nil,
        people: [[String: Any]]? = nil, canEdit: Bool = true
    ) -> [String: Any] {
        [
            "board": "", "viewer": "Robin", "can_edit": canEdit, "language": "auto",
            "timezone": "America/New_York", "now": "2026-10-27T11:25:03.951184-04:00",
            "today": today, "day": day, "people": people ?? Self.people,
            "events": events ?? [timedEvent], "tomorrow": tomorrow ?? [allDayEvent],
            "tasks": tasks ?? [todo, chore],
        ]
    }

    static let family: [String: Any] = [
        "people": [
            ["key": "robin", "name": "Robin", "color": "7", "kind": "adult", "email": "robin@example.com",
             "user_id": 1, "position": 0, "hex": "#039be5"],
            ["key": "ruby", "name": "Ruby", "color": "2", "kind": "kid", "email": "",
             "user_id": NSNull(), "position": 2, "hex": "#33b679"],
        ],
        "colors": [["id": "1", "name": "Lavender", "hex": "#7986cb"]],
    ]

    static func decode<T: Decodable>(_ type: T.Type, _ json: Any) throws -> T {
        try JSONDecoder.snake.decode(T.self, from: JSONSerialization.data(withJSONObject: json))
    }

    static func day(_ json: [String: Any] = board()) throws -> BoardDay {
        try decode(BoardDay.self, json)
    }

    static func task(_ json: [String: Any] = todo) throws -> TaskItem {
        try decode(TaskItem.self, json)
    }

    static func event(_ json: [String: Any] = timedEvent) throws -> BoardEvent {
        try decode(BoardEvent.self, json)
    }
}
