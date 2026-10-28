import Foundation
import Testing
@testable import Luach

@MainActor
@Suite(.serialized, .timeLimit(.minutes(1))) // a Conversation keeps its thread in UserDefaults
struct ConversationTests {
    let server = StubServer()

    init() {
        Conversation.forget()
    }

    /// Sends one turn and waits for the stream to end.
    private func turn(_ text: String, _ conversation: Conversation, onHeld: @escaping () -> Void = {}) async {
        conversation.send(text, api: server.api, onHeld: onHeld)
        while conversation.streaming { try? await Task.sleep(for: .milliseconds(10)) }
    }

    @Test func aHeldCardSaysWhenAnApprovalDidNotGoThrough() {
        #expect(Conversation.Decision(status: "approved") == .approved)
        #expect(Conversation.Decision(status: "denied") == .denied)
        #expect(Conversation.Decision(status: "failed") == .failed)
    }

    @Test func aTurnBecomesWordsCardsAndAFooter() async throws {
        server.stream([
            ["type": "session", "thread_id": "th-1"],
            ["type": "model", "name": "qwen3.6-35b"],
            ["type": "tool_start", "tool": "list_events", "args": ["start_date": "2026-09-01"]],
            ["type": "tool_result", "tool": "list_events", "result": ["events": []]],
            ["type": "widget", "kind": "agenda", "data": [
                "title": "Tue 01 – Wed 30 Sep 2026", "truncated": false,
                "events": [["id": "e1", "title": "Tennis", "when": "Sat 19 Sep 2026, 16:00–17:00"]]]],
            ["type": "token", "text": "You have "],
            ["type": "token", "text": "**Tennis**."],
            ["type": "done", "reply": "You have **Tennis**.", "thread_id": "th-1", "model": "qwen3.6-35b"],
        ])
        let c = Conversation()
        await turn("What's on in September?", c)

        let kinds = c.items.map(\.kind)
        #expect(kinds.count == 5)
        guard case .user(let asked) = kinds[0], case .trace(let steps) = kinds[1],
              case .widget(let kind, let data) = kinds[2], case .assistant(let words) = kinds[3],
              case .footer(let model, let copied, let stopped) = kinds[4] else {
            Issue.record("unexpected items: \(kinds)"); return
        }
        #expect(asked == "What's on in September?")
        #expect(steps == [Conversation.Step(label: "Reading the calendar", done: true)])
        #expect(kind == "agenda" && data.events?.first?.title == "Tennis")
        #expect(words == "You have **Tennis**.")
        #expect(model == "qwen3.6-35b" && copied == words && !stopped)
        #expect(c.threadID == "th-1" && UserDefaults.standard.string(forKey: "thread") == "th-1")

        let sent = try #require(server.requests("POST", "/api/agent/stream").first)
        #expect(sent.json["text"] as? String == "What's on in September?")
        #expect(sent.headers["Accept"] == "text/event-stream")
    }

    @Test func theNextTurnCarriesTheThread() async {
        server.stream([["type": "session", "thread_id": "th-9"], ["type": "done", "reply": "ok", "thread_id": "th-9"]])
        let c = Conversation()
        await turn("one", c)
        await turn("two", c)
        let threads = server.requests("POST", "/api/agent/stream").map { $0.json["thread_id"] as? String }
        #expect(threads == [nil, "th-9"])
    }

    @Test func aHoldBecomesACardAndTellsTheApp() async {
        server.stream([
            ["type": "tool_start", "tool": "create_event", "args": ["title": "Dentist", "start": "2026-10-27T15:00"]],
            ["type": "held", "id": "h-1", "tool": "create_event", "summary": "Add “Dentist”",
             "reason": ["ambiguous"], "reason_text": "The time was a guess."],
            ["type": "tool_result", "tool": "create_event", "result": ["status": "held_for_approval"]],
            ["type": "done", "reply": "I need a yes for that.", "held": [["id": "h-1"]]],
        ])
        let c = Conversation()
        var told = 0
        await turn("dentist tomorrow at 3", c) { told += 1 }
        #expect(told == 1)
        let held = c.items.compactMap { item -> (String, String, String, Bool)? in
            if case .held(let id, let s, let r, let labels, let restored) = item.kind {
                #expect(labels == ["ambiguous"])
                return (id, s, r, restored)
            }
            return nil
        }
        #expect(held.count == 1 && held[0].0 == "h-1" && held[0].2 == "The time was a guess." && !held[0].3)
        guard case .trace(let steps) = c.items[1].kind else { Issue.record("no trace"); return }
        #expect(steps.first?.label.hasPrefix("Adding “Dentist” · ") == true)
    }

    @Test func aReplyWithoutTokensStillShows() async {
        server.stream([["type": "done", "reply": "Done.", "model": "m"]])
        let c = Conversation()
        await turn("hi", c)
        guard case .assistant(let words) = c.items[1].kind else { Issue.record("no answer"); return }
        #expect(words == "Done.")
    }

    /// The words of a turn, bubble by bubble, and the words its footer copies.
    private func said(_ c: Conversation) -> (bubbles: [String], copied: String?) {
        var bubbles: [String] = []
        var copied: String?
        for item in c.items {
            if case .assistant(let s) = item.kind { bubbles.append(s) }
            if case .footer(_, let text, _) = item.kind { copied = text }
        }
        return (bubbles, copied)
    }

    /// The chat repeated its answer two to six times: a model answered, called a tool,
    /// and answered again, and every word streamed stayed on the screen.
    @Test func anAnswerSaidAgainAfterAToolShowsOnce() async {
        server.stream([
            ["type": "token", "text": "Hi there!"],
            ["type": "retract"],
            ["type": "token", "text": "Hi "],
            ["type": "token", "text": "there!"],
            ["type": "retract"],
            ["type": "token", "text": "Hi there!"],
            ["type": "done", "reply": "Hi there!", "model": "m"],
        ])
        let c = Conversation()
        await turn("hello", c)
        let (bubbles, copied) = said(c)
        #expect(bubbles == ["Hi there!"] && copied == "Hi there!")
    }

    @Test func wordsTakenBackBeforeACardLeaveTheCard() async {
        server.stream([
            ["type": "token", "text": "Let me look."],
            ["type": "tool_start", "tool": "list_events", "args": ["start_date": "2026-10-29"]],
            ["type": "tool_result", "tool": "list_events", "result": ["events": []]],
            ["type": "widget", "kind": "agenda", "data": ["title": "Thu 29 Oct", "truncated": false, "events": []]],
            ["type": "retract"],
            ["type": "token", "text": "Nothing on tomorrow."],
            ["type": "done", "reply": "Nothing on tomorrow."],
        ])
        let c = Conversation()
        await turn("tomorrow?", c)
        let kinds = c.items.map(\.kind)
        guard kinds.count == 5, case .trace = kinds[1], case .widget = kinds[2],
              case .assistant(let words) = kinds[3], case .footer = kinds[4] else {
            Issue.record("unexpected items: \(kinds)"); return
        }
        #expect(words == "Nothing on tomorrow.")
    }

    /// luach rewrites an answer that is not true (a write held for approval, a turn that
    /// called nothing); the rewrite is what the person must see, as the web shows it.
    @Test func theServersReplyHasTheLastWord() async {
        server.stream([
            ["type": "token", "text": "Added: "],
            ["type": "token", "text": "Tennis, Sat 16:00."],
            ["type": "done", "reply": "Waiting for your approval — nothing is on the calendar yet: Add “Tennis”"],
        ])
        let c = Conversation()
        await turn("tennis saturday at 4", c)
        let (bubbles, copied) = said(c)
        let rewrite = "Waiting for your approval — nothing is on the calendar yet: Add “Tennis”"
        #expect(bubbles == [rewrite] && copied == rewrite)
    }

    @Test func aFailedToolSaysWhyInWords() async {
        server.stream([
            ["type": "tool_start", "tool": "search_the_web", "args": ["query": "the lakers"]],
            ["type": "tool_result", "tool": "search_the_web", "error": "the search engine timed out; say so and offer to try again"],
            ["type": "done", "reply": "I could not search just now."],
        ])
        let c = Conversation()
        await turn("when do the lakers play", c)
        guard case .trace(let steps) = c.items[1].kind else { Issue.record("no trace"); return }
        #expect(steps.first?.label == "Searching the web for “the lakers”")
        #expect(steps.first?.failed == "couldn't: the search engine timed out")
    }

    @Test func justTalkingIsNotAStep() async {
        server.stream([
            ["type": "tool_start", "tool": "just_talking"],
            ["type": "tool_result", "tool": "just_talking"],
            ["type": "token", "text": "Hello!"],
            ["type": "done", "reply": "Hello!"],
        ])
        let c = Conversation()
        await turn("hi", c)
        #expect(!c.items.contains { if case .trace = $0.kind { true } else { false } })
    }

    @Test func stoppingSaysSoUnderWhatCame() async throws {
        // The first words, then a long quiet: the person taps Stop while it waits.
        server.on("POST", "/api/agent/stream") { _ in
            Thread.sleep(forTimeInterval: 2)
            let frame = #"data: {"type":"token","text":"Planning a week"}"#
            return StubServer.Reply(body: Data((frame + "\n\n").utf8), contentType: "text/event-stream")
        }
        let c = Conversation()
        c.send("a long paragraph", api: server.api) {}
        try await Task.sleep(for: .milliseconds(300))
        c.stop()
        while c.streaming { try await Task.sleep(for: .milliseconds(10)) }
        guard case .footer(_, _, let stopped) = c.items.last?.kind else {
            Issue.record("no footer: \(c.items.map(\.kind))"); return
        }
        #expect(stopped)
    }

    @Test func anErrorFrameIsShown() async {
        server.stream([["type": "error", "message": "The model is not answering."]])
        let c = Conversation()
        await turn("hi", c)
        guard case .error(let m) = c.items.last?.kind else { Issue.record("no error"); return }
        #expect(m == "The model is not answering.")
    }

    @Test func aRefusedTurnShowsTheServersSentence() async {
        server.fail("POST", "/api/agent/stream", status: 403, "That conversation is someone else's.")
        let c = Conversation()
        await turn("hi", c)
        guard case .error(let m) = c.items.last?.kind else { Issue.record("no error"); return }
        #expect(m == "That conversation is someone else's.")
    }

    @Test func anEarlierThreadComesBackWithItsStepsAndCards() async {
        server.on("GET", "/api/threads/th-2", json: [
            "id": "th-2",
            "turns": [
                ["role": "user", "content": "September?", "events": []],
                ["role": "assistant", "content": "Two things.", "events": [
                    ["tool": "list_events", "args": [:]],
                    ["tool": "just_talking", "args": [:]],
                    ["widget": ["kind": "agenda", "data": ["title": "Sep", "events": [["id": "e", "title": "Tennis", "when": "Sat"]]]]],
                    ["held": [["id": "h-9", "tool": "create_event", "summary": "Add Tennis", "reason": ["outside-the-house"]]], "created": []],
                ]],
            ],
        ])
        let c = Conversation()
        await c.open("th-2", api: server.api)
        let kinds = c.items.map(\.kind)
        #expect(kinds.count == 6)
        if case .trace(let steps) = kinds[1] { #expect(steps.count == 1) } else { Issue.record("no trace") }
        if case .widget(_, let data) = kinds[2] { #expect(data.events?.first?.title == "Tennis") } else { Issue.record("no card") }
        if case .held(let id, _, _, let labels, let restored) = kinds[3] {
            #expect(id == "h-9" && restored && labels == ["outside-the-house"])
        } else { Issue.record("no hold") }
        #expect(c.threadID == "th-2")
    }

    @Test func aSweptThreadStartsFresh() async {
        UserDefaults.standard.set("gone", forKey: "thread")
        server.fail("GET", "/api/threads/gone", status: 404, "no such conversation")
        let c = Conversation()
        await c.restore(api: server.api)
        #expect(c.threadID == nil && c.items.isEmpty)
    }

    @Test func newForgetsTheThread() async {
        server.stream([["type": "session", "thread_id": "th-3"], ["type": "done", "reply": "ok"]])
        let c = Conversation()
        await turn("hi", c)
        c.reset()
        #expect(c.items.isEmpty && c.threadID == nil && UserDefaults.standard.string(forKey: "thread") == nil)
    }
}

@MainActor
struct StepLabelTests {
    private func label(_ tool: String, _ args: [String: Any] = [:]) -> String {
        let data = try! JSONSerialization.data(withJSONObject: args)
        return StepLabel.text(tool: tool, args: try! JSONDecoder().decode(JSONValue.self, from: data))
    }

    @Test func eachToolInWords() {
        #expect(label("list_events") == "Reading the calendar")
        #expect(label("find_events", ["query": "dentist"]) == "Looking for “dentist”")
        #expect(label("find_events") == "Looking through the calendar")
        #expect(label("check_availability") == "Checking for a free slot")
        #expect(label("create_event", ["title": "Dentist"]) == "Adding “Dentist”")
        #expect(label("update_event", ["title": "Dentist"]) == "Changing “Dentist”")
        #expect(label("delete_event") == "Removing an event")
        #expect(label("search_email", ["query": "flight"]) == "Searching your email for “flight”")
        #expect(label("add_task", ["title": "Milk", "for_whom": "Ruby"]) == "Adding the task “Milk” for Ruby")
        #expect(label("complete_task", ["undo": true]) == "Unticking a task")
        #expect(label("complete_task") == "Ticking a task off")
        #expect(label("remember", ["fact": "mornings only"]) == "Remembering: mornings only")
        #expect(label("remember", ["topic": "school"]) == "Recalling what it knows about “school”")
        #expect(label("forget", ["what": "mornings"]) == "Forgetting “mornings”")
        #expect(label("brand_new_tool") == "Brand new tool")
        #expect(StepLabel.skill("book-a-trip") == "Following the guide: book a trip")
    }

    @Test func longWordsAreClipped() {
        let long = String(repeating: "a", count: 80)
        #expect(label("find_events", ["query": long]) == "Looking for “\(String(repeating: "a", count: 39))…”")
    }

    @Test func aTimeIsWrittenForPeople() {
        let s = label("create_event", ["title": "Dentist", "start": "2026-10-27T15:00:00-04:00"])
        #expect(s.hasPrefix("Adding “Dentist” · ") && s.contains("27") && s.contains("Oct"))
        #expect(label("check_availability", ["start": "2026-10-27"]).contains("27"))
        #expect(label("create_event", ["start": "soon"]) == "Adding an event")
    }

    @Test func onlyTheFirstClauseOfAnError() {
        #expect(StepLabel.humane("not found; call find_events first") == "couldn't: not found")
        #expect(StepLabel.humane("no") == "couldn't: no")
    }

    @Test func toolsInAWord() {
        #expect(Conversation.describe(tool: "list_events") == "Reading the calendar")
        #expect(Conversation.describe(tool: "read_web_page") == "Looking it up")
        #expect(Conversation.describe(tool: nil) == "Working on it")
    }
}
