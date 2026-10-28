import Foundation
import Observation

/// One thread with luach, as the Ask view shows it. The thread id is kept, so
/// opening the app again carries on where it was left; "New" starts another, and
/// the conversation list opens any earlier one.
@Observable
final class Conversation {
    enum Kind {
        case user(String)
        /// What luach did on the way to its answer, step by step.
        case trace([Step])
        case assistant(String)
        case widget(kind: String, data: WidgetData)
        /// `restored`: from a reloaded thread, so it may have been decided since.
        /// `labels`: the gate's tags ("ambiguous", "outside-the-house"), shown in words.
        case held(id: String, summary: String, reason: String, labels: [String], restored: Bool)
        /// Under a finished answer: the model that gave it, and the words to copy.
        case footer(model: String?, text: String, stopped: Bool)
        case error(String)
    }

    struct Item: Identifiable {
        let id = UUID()
        var kind: Kind
    }

    struct Step: Hashable {
        var label: String
        var done = false
        var failed: String?
    }

    enum Decision {
        case approved, denied
        /// Approved, but the call was refused when it ran: nothing changed.
        case failed

        /// What a decided row's status means on a held card.
        init(status: String) {
            switch status {
            case "denied": self = .denied
            case "failed": self = .failed
            default: self = .approved
            }
        }
    }

    private(set) var items: [Item] = []
    private(set) var streaming = false
    /// What luach is doing right now ("Reading the calendar"), while a tool runs.
    private(set) var activity: String?
    var decisions: [String: Decision] = [:]

    private(set) var threadID: String? {
        didSet { UserDefaults.standard.set(threadID, forKey: Self.threadKey) }
    }
    private var turn: Task<Void, Never>?
    /// The bubbles the words streaming now went into, each with what it held before them:
    /// a `retract` frame takes exactly those words back.
    private var words: [(id: UUID, before: String)] = []
    private static let threadKey = "thread"

    init() {
        threadID = UserDefaults.standard.string(forKey: Self.threadKey).flatMap { $0.isEmpty ? nil : $0 }
    }

    static func forget() {
        UserDefaults.standard.removeObject(forKey: threadKey)
    }

    /// Brings back the saved thread after a relaunch.
    func restore(api: API) async {
        guard let threadID, items.isEmpty else { return }
        await open(threadID, api: api)
    }

    /// Shows an earlier conversation, its steps and cards as they were.
    func open(_ id: String, api: API) async {
        stop()
        do {
            let thread = try await api.thread(id)
            decisions = [:]
            items = thread.turns.flatMap(Self.items(for:))
            threadID = id
        } catch let error as APIError where error.status == 404 || error.status == 403 {
            // Swept after the retention period, or not ours: start fresh.
            if threadID == id { reset() }
        } catch {}
    }

    private static func items(for turn: ThreadDetail.Turn) -> [Item] {
        if turn.role == "user" { return [Item(kind: .user(turn.content))] }
        guard turn.role == "assistant" else { return [] }
        var out: [Item] = []
        let events = turn.events ?? []
        let steps = events.compactMap { e -> Step? in
            guard let tool = e["tool"]?.string, tool != "just_talking" else { return nil }
            return Step(label: StepLabel.text(tool: tool, args: e["args"]), done: true)
        }
        if !steps.isEmpty { out.append(Item(kind: .trace(steps))) }
        for e in events {
            if let w = e["widget"], let kind = w["kind"]?.string,
               let data = try? JSONDecoder.snake.decode(WidgetData.self, from: JSONEncoder().encode(w["data"] ?? .null)) {
                out.append(Item(kind: .widget(kind: kind, data: data)))
            }
            if case .array(let held)? = e["held"] {
                for h in held {
                    guard let id = h["id"]?.string else { continue }
                    out.append(Item(kind: .held(
                        id: id, summary: h["summary"]?.string ?? "", reason: "",
                        labels: Self.labels(h["reason"]), restored: true)))
                }
            }
        }
        if !turn.content.isEmpty {
            out.append(Item(kind: .assistant(turn.content)))
            out.append(Item(kind: .footer(model: nil, text: turn.content, stopped: turn.content.hasSuffix("(stopped)"))))
        }
        return out
    }

    func reset() {
        stop()
        items = []
        decisions = [:]
        threadID = nil
    }

    func stop() {
        turn?.cancel()
        turn = nil
    }

    func send(_ text: String, api: API, onHeld: @escaping () -> Void) {
        guard !streaming else { return }
        items.append(Item(kind: .user(text)))
        streaming = true
        words = []
        turn = Task {
            var answer = ""
            var model: String?
            var traceAt: Int?
            defer {
                streaming = false
                activity = nil
                // A turn may have changed the calendar: the agenda, and the reminders worked
                // out from it, follow.
                AgendaData.shared.invalidate()
            }
            @MainActor func step(_ change: (inout [Step]) -> Void) {
                if traceAt == nil {
                    items.append(Item(kind: .trace([])))
                    traceAt = items.count - 1
                }
                guard let i = traceAt, case .trace(var steps) = items[i].kind else { return }
                change(&steps)
                items[i].kind = .trace(steps)
            }
            do {
                for try await frame in api.ask(text, threadID: threadID) {
                    switch frame.type {
                    case "session":
                        if let id = frame.threadId { threadID = id }
                    case "model":
                        model = frame.name
                    case "token":
                        if let t = frame.text {
                            appendText(t)
                            answer += t
                            activity = nil
                        }
                    case "retract":
                        // A model answered, called a tool, and is answering again: what it
                        // said first goes, or the same answer stood on the screen twice or more.
                        takeBackWords()
                        answer = ""
                    case "skill":
                        if let name = frame.name {
                            step { $0.append(Step(label: StepLabel.skill(name), done: true)) }
                        }
                    case "tool_start":
                        guard let tool = frame.tool, tool != "just_talking" else { break }
                        activity = Self.describe(tool: tool)
                        step { $0.append(Step(label: StepLabel.text(tool: tool, args: frame.args))) }
                    case "tool_result":
                        activity = nil
                        guard frame.tool != "just_talking" else { break }
                        step { steps in
                            guard let i = steps.lastIndex(where: { !$0.done }) else { return }
                            steps[i].done = true
                            if let e = frame.error, e.isTruthy {
                                steps[i].failed = StepLabel.humane(e.string ?? "")
                            }
                        }
                    case "widget":
                        if let kind = frame.kind, let data = frame.data {
                            items.append(Item(kind: .widget(kind: kind, data: data)))
                        }
                    case "held":
                        if let id = frame.id {
                            items.append(Item(kind: .held(
                                id: id, summary: frame.summary ?? "", reason: frame.reasonText ?? "",
                                labels: Self.labels(frame.reason), restored: false)))
                            onHeld()
                        }
                    case "done":
                        if let id = frame.threadId { threadID = id }
                        // The server's reply has the last word, as on the web: luach rewrites an
                        // answer that is not true (a write held for approval, a turn that called
                        // nothing), and the rewrite is what the person must read.
                        if let reply = frame.reply, !reply.isEmpty,
                           reply != answer.trimmingCharacters(in: .whitespacesAndNewlines) {
                            takeBackWords()
                            appendText(reply)
                            answer = reply
                        }
                        items.append(Item(kind: .footer(model: frame.model ?? model, text: answer, stopped: false)))
                    case "error":
                        items.append(Item(kind: .error(frame.message ?? String(localized: "Something went wrong."))))
                    default:
                        break
                    }
                }
                // A stopped stream ends without an error: the loop just runs out.
                if Task.isCancelled { stopped(answer, model) }
            } catch is CancellationError {
                stopped(answer, model)
            } catch let error as URLError where error.code == .cancelled {
                stopped(answer, model)
            } catch {
                items.append(Item(kind: .error(error.localizedDescription)))
            }
        }
    }

    /// The web's Stop: luach keeps what the turn already did, its reply ending "(stopped)".
    private func stopped(_ answer: String, _ model: String?) {
        items.append(Item(kind: .footer(model: model, text: answer, stopped: true)))
    }

    /// Text after a card goes in a new bubble below it, so the reply reads in order.
    private func appendText(_ t: String) {
        if case .assistant(let s) = items.last?.kind {
            let id = items[items.count - 1].id
            if !words.contains(where: { $0.id == id }) { words.append((id, s)) }
            items[items.count - 1].kind = .assistant(s + t)
        } else {
            // Only the leading space goes: a token's trailing one is the gap before the next word.
            let item = Item(kind: .assistant(String(t.drop { $0 == " " || $0 == "\t" })))
            words.append((item.id, ""))
            items.append(item)
        }
    }

    /// Takes the words streamed since the last retract back off the screen: a bubble they
    /// made goes, a bubble they added to keeps what it had.
    private func takeBackWords() {
        for (id, before) in words.reversed() {
            guard let i = items.firstIndex(where: { $0.id == id }) else { continue }
            if before.isEmpty { items.remove(at: i) } else { items[i].kind = .assistant(before) }
        }
        words = []
    }

    /// A hold's tags, from a frame or a saved turn: a list of strings, or nothing.
    static func labels(_ value: JSONValue?) -> [String] {
        guard case .array(let items)? = value else { return [] }
        return items.compactMap(\.string)
    }

    static func describe(tool: String?) -> String {
        switch tool ?? "" {
        case "list_events", "find_events", "get_event": String(localized: "Reading the calendar")
        case "check_availability": String(localized: "Checking who is free")
        case "create_event": String(localized: "Adding it to the calendar")
        case "update_event": String(localized: "Changing the event")
        case "delete_event": String(localized: "Removing the event")
        case "list_tasks", "add_task", "change_task", "complete_task", "remove_task":
            String(localized: "Seeing to the to-dos")
        case "search_email", "read_email": String(localized: "Reading your email")
        case "remember", "recall", "forget": String(localized: "Checking what it knows about you")
        case "search_the_web", "read_web_page": String(localized: "Looking it up")
        default: String(localized: "Working on it")
        }
    }
}

extension JSONDecoder {
    static let snake: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()
}

extension JSONValue: Encodable {
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }
}

/// A step of the trace in words (web lib/labels.ts, stepLabel).
enum StepLabel {
    static func skill(_ name: String) -> String {
        String(localized: "Following the guide: \(name.replacingOccurrences(of: "-", with: " "))")
    }

    static func text(tool: String, args: JSONValue?) -> String {
        func s(_ key: String) -> String? {
            guard let v = args?[key]?.string?.trimmingCharacters(in: .whitespaces), !v.isEmpty else { return nil }
            return v
        }
        func q(_ v: String, _ n: Int = 40) -> String { "“\(clip(v, n))”" }
        switch tool {
        case "list_events":
            return String(localized: "Reading the calendar")
        case "find_events":
            return s("query").map { String(localized: "Looking for \(q($0))") } ?? String(localized: "Looking through the calendar")
        case "check_availability":
            return s("start").flatMap { when($0) }.map { String(localized: "Checking \($0)") } ?? String(localized: "Checking for a free slot")
        case "get_event":
            return String(localized: "Opening an event")
        case "create_event":
            let what = s("title").map { String(localized: "Adding \(q($0))") } ?? String(localized: "Adding an event")
            return s("start").flatMap { when($0) }.map { "\(what) · \($0)" } ?? what
        case "update_event":
            return s("title").map { String(localized: "Changing \(q($0))") } ?? String(localized: "Changing an event")
        case "delete_event":
            return String(localized: "Removing an event")
        case "search_email":
            return s("query").map { String(localized: "Searching your email for \(q($0))") } ?? String(localized: "Searching your email")
        case "read_email":
            return String(localized: "Reading an email")
        case "search_the_web":
            return s("query").map { String(localized: "Searching the web for \(q($0))") } ?? String(localized: "Searching the web")
        case "read_web_page":
            return String(localized: "Reading a page")
        case "add_task":
            let what = s("title").map { String(localized: "Adding the task \(q($0))") } ?? String(localized: "Adding a task")
            return s("for_whom").map { "\(what) " + String(localized: "for \(clip($0, 24))") } ?? what
        case "list_tasks":
            return s("for_whom").map { String(localized: "Checking the tasks for \(clip($0, 24))") } ?? String(localized: "Checking the tasks")
        case "complete_task":
            return args?["undo"]?.isTruthy == true ? String(localized: "Unticking a task") : String(localized: "Ticking a task off")
        case "change_task":
            return String(localized: "Changing a task")
        case "remove_task":
            return String(localized: "Removing a task")
        case "remember":
            // With no fact, `remember` is recall: it reads, it does not write.
            if let fact = s("fact") { return String(localized: "Remembering: \(clip(fact, 48))") }
            return s("topic").map { String(localized: "Recalling what it knows about \(q($0, 32))") } ?? String(localized: "Recalling what it knows")
        case "forget":
            return s("what").map { String(localized: "Forgetting \(q($0))") } ?? String(localized: "Forgetting something")
        default:
            let words = tool.replacingOccurrences(of: "_", with: " ")
            return words.prefix(1).uppercased() + words.dropFirst()
        }
    }

    /// The first clause of a tool's error: the rest is written for the model.
    static func humane(_ e: String) -> String {
        let cut = e.firstIndex { ";.?!".contains($0) } ?? e.endIndex
        return String(localized: "couldn't: \(clip(String(e[..<cut]), 60))")
    }

    /// "2026-10-27T15:00" (the model writes wall time) as "Tue 27 Oct, 15:00".
    private static func when(_ s: String) -> String? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        // Any offset after the wall time is ignored: the time as written is the one meant.
        for (format, length, timed) in [("yyyy-MM-dd'T'HH:mm", 16, true), ("yyyy-MM-dd", 10, false)]
        where s.count >= length {
            f.dateFormat = format
            guard let d = f.date(from: String(s.prefix(length))) else { continue }
            return timed
                ? d.formatted(.dateTime.weekday().day().month().hour().minute())
                : d.formatted(.dateTime.weekday().day().month())
        }
        return nil
    }

    private static func clip(_ s: String, _ n: Int) -> String {
        s.count > n ? String(s.prefix(n - 1)) + "…" : s
    }
}
