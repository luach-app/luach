import Foundation
import XCTest

/// The UI tests' line to dev's API, with the run's session: to read what the screen should
/// show, and as a safety net that removes whatever an `ios-test…` test made should it stop
/// before removing it by tapping. Blocking (with a timeout), so tests and tearDown stay
/// synchronous: an async XCTest that fails under `continueAfterFailure = false` hangs.
enum YouDevCleanup {
    private final class Box: @unchecked Sendable { var data: Data? }

    private static func send(_ method: String, _ path: String) -> Data? {
        guard let server = LuachApp.server, let session = LuachApp.session, !session.isEmpty,
              let url = URL(string: server + path) else { return nil }
        var req = URLRequest(url: url, timeoutInterval: 20)
        req.httpMethod = method
        req.setValue("luach_session=\(session)", forHTTPHeaderField: "Cookie")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        let box = Box()
        let done = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: req) { data, _, _ in
            box.data = data
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + 25)
        return box.data
    }

    private static func json(_ path: String) -> [String: Any] {
        guard let data = send("GET", path) else { return [:] }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
    }

    /// The signed-in member as dev has them (`timezone`, `language`, …).
    static func me() -> [String: Any] { json("/api/auth/me") }

    /// The family as dev has it: key, name and kind of each person.
    static func people() -> [(key: String, name: String, kind: String)] {
        let list = json("/api/family")["people"] as? [[String: Any]] ?? []
        return list.map { (($0["key"] as? String) ?? "", ($0["name"] as? String) ?? "", ($0["kind"] as? String) ?? "") }
    }

    /// Whether a name or fact is the test's own: the marker, and the test's random token
    /// (compared loosely: the keyboard may have autocorrected what was typed).
    static func isOurs(_ text: String, token: String) -> Bool {
        let t = text.lowercased()
        return t.hasPrefix("ios-test") && t.contains(token.lowercased())
    }

    /// The person the test made, as dev named them.
    static func person(token: String) -> (key: String, name: String, kind: String)? {
        people().first { isOurs($0.name, token: token) }
    }

    /// Removes the people the test made.
    static func removePeople(token: String) {
        for p in people() where isOurs(p.name, token: token) {
            _ = send("DELETE", "/api/family/\(p.key)")
        }
    }

    /// Forgets the facts the test kept.
    static func forgetFacts(token: String) {
        let facts = json("/api/memory")["facts"] as? [[String: Any]] ?? []
        for f in facts where isOurs((f["fact"] as? String) ?? "", token: token) {
            if let key = (f["key"] as? String)?.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) {
                _ = send("DELETE", "/api/memory/\(key)")
            }
        }
    }
}
