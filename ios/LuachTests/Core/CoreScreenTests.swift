import AuthenticationServices
import AVFoundation
import Foundation
import SwiftUI
import Testing
import UIKit
@testable import Luach

/// A microphone that is not there: records for as long as the test says.
final class FakeRecording: AudioRecording {
    let currentTime: TimeInterval
    let ok: Bool
    private(set) var stopped = false

    init(seconds: TimeInterval, ok: Bool = true) {
        currentTime = seconds
        self.ok = ok
    }

    func record() -> Bool { ok }
    func stop() { stopped = true }
}

/// A recorder whose "recording" is the bytes the test wrote to its file.
@MainActor
func fakeRecorder(granted: Bool = true, seconds: TimeInterval = 2, ok: Bool = true, bytes: Data = Data([1, 2, 3, 4])) -> Recorder {
    let file = FileManager.default.temporaryDirectory.appending(path: "luach-test-\(UUID().uuidString).m4a")
    try? bytes.write(to: file)
    return Recorder(file: file, permission: { granted }, make: { _, _ in FakeRecording(seconds: seconds, ok: ok) })
}

@MainActor
struct RecorderTests {
    @Test func aNoteIsTheFileItRecorded() async throws {
        let bytes = Data((0..<64).map { UInt8($0) })
        let r = fakeRecorder(bytes: bytes)
        try await r.start()
        #expect(r.recording)
        #expect(r.stop() == bytes)
        #expect(!r.recording)
    }

    @Test func aMomentIsNotWorthSending() async throws {
        let r = fakeRecorder(seconds: 0.1)
        try await r.start()
        #expect(r.stop() == nil)
    }

    @Test func thePhonesOwnRecorderIsAnAVAudioRecorder() throws {
        let url = FileManager.default.temporaryDirectory.appending(path: "luach-system-\(UUID().uuidString).m4a")
        let r = try Recorder.system(url, [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 16_000, AVNumberOfChannelsKey: 1])
        #expect(r is AVAudioRecorder)
        #expect(r.currentTime == 0)
        r.stop()
        #expect(Recorder().file.lastPathComponent == "luach-voice.m4a")
    }

    /// The recorder as the app makes it, permission and all. Only where the microphone is already
    /// allowed (test.sh grants it on its simulator), so the question never waits on a prompt.
    @Test(.enabled(if: AVAudioApplication.shared.recordPermission == .granted))
    func theDefaultRecorderAsksAndRecordsOrSaysWhy() async {
        let r = Recorder(file: FileManager.default.temporaryDirectory.appending(path: "luach-real-\(UUID().uuidString).m4a"))
        do {
            try await r.start()
            #expect(r.recording)
            _ = r.stop()
            #expect(!r.recording)
        } catch {
            // A simulator with no input to record from: refused, and not left recording.
            #expect(!r.recording)
        }
    }

    @Test func aRefusedMicrophoneSaysWhere() async {
        await #expect(throws: Recorder.Denied.self) { try await fakeRecorder(granted: false).start() }
    }

    @Test func aRecorderThatWillNotStartIsAnError() async {
        await #expect(throws: CocoaError.self) { try await fakeRecorder(ok: false).start() }
        let broken = Recorder(permission: { true }, make: { _, _ in throw URLError(.cannotCreateFile) })
        await #expect(throws: URLError.self) { try await broken.start() }
        #expect(!broken.recording)
    }
}

@MainActor
@Suite(.serialized, .timeLimit(.minutes(2)))
struct CoreScreenTests {
    let server = StubServer()
    private var session: AppSession { AppSession(api: server.api) }

    init() {
        Conversation.forget()
        for key in ["ask", "showThreads"] { UserDefaults.standard.removeObject(forKey: key) }
    }

    private func pendingRow(_ id: String, _ summary: String, subject: String? = nil) -> [String: Any] {
        var row: [String: Any] = ["id": id, "tool": "create_event", "summary": summary, "status": "pending",
                                  "reason": ["ambiguous", "possible-duplicate"], "principal": "robin", "door": "web"]
        if let subject { row["source"] = ["kind": "email", "subject": subject, "from": "x@example.com"] }
        return row
    }

    private func mail(connected: Bool, via: String = "own", canConnect: Bool = true, scan: [String: Any]? = nil) -> [String: Any] {
        var st: [String: Any] = ["connected": connected, "address": connected ? "me@example.com" : "",
                                 "via": connected ? via : "", "can_connect": canConnect]
        if let scan { st["scan"] = scan }
        return st
    }

    private let scanOn: [String: Any] = ["available": true, "enabled": true, "since": "2026-10-01T12:00:00",
                                         "minutes": 10, "read": 120, "proposed": 6, "last_read": "2026-10-26T09:00:00+00:00"]

    // MARK: Approvals

    @Test func approvalsShowTheScanTheSourceAndARefusal() async throws {
        let s = session
        server.on("GET", "/api/control/pending", json: ["pending": [pendingRow("h1", "Add Dentist", subject: "Your appointment")]])
        server.on("GET", "/api/mail", json: mail(connected: true, scan: scanOn))
        server.fail("POST", "/api/control/pending/h1/deny", status: 500, "the database is away")
        let host = ScreenHost(PendingView(), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Add Dentist"))
        #expect(await host.waitFor("Reading your email every 10 minutes"))
        #expect(host.shows("Your appointment"))
        #expect(host.shows("the time was a guess · looks like one already there"))
        await host.press("Deny")
        #expect(await host.waitFor("the database is away"))
    }

    @Test func approvalsSayWhyTheyCannotLoad() async throws {
        let s = session
        server.fail("GET", "/api/control/pending", status: 500, "the database is away")
        server.fail("GET", "/api/mail", status: 500, "no")
        let host = ScreenHost(PendingView(), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("the database is away"))
    }

    @Test func nothingWaitingSaysSo() async throws {
        let s = session
        server.on("GET", "/api/control/pending", json: ["pending": []])
        server.on("GET", "/api/mail", json: mail(connected: false))
        let host = ScreenHost(PendingView(), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Nothing waiting"))
    }

    @Test func eachLabelInWords() {
        #expect(PendingRow.describe("past") == "it is in the past")
        #expect(PendingRow.describe("mutation-existing") == "changes something luach did not make")
        #expect(PendingRow.describe("bulk") == "more than one event at once")
        #expect(PendingRow.describe("from-your-email") == "from your email")
        #expect(PendingRow.describe("outside-the-house") == "sends an invitation outside the household")
    }

    @Test func outsideTheHouseIsSaidInEachLanguage() throws {
        // Localizable.xcstrings carries it like every other label: the app's Spanish and Hebrew.
        for (lang, words) in [("es", "envía una invitación fuera de casa"), ("he", "שולח הזמנה מחוץ לבית")] {
            let path = try #require(Bundle(for: AppSession.self).path(forResource: lang, ofType: "lproj"))
            let bundle = try #require(Bundle(path: path))
            #expect(bundle.localizedString(
                forKey: "sends an invitation outside the household", value: nil, table: nil) == words)
        }
    }

    // MARK: Conversations

    private func threads(_ rows: [[String: Any]], more: Bool = false) -> [String: Any] {
        ["threads": rows, "more": more, "retention_days": 60]
    }

    private func thread(_ id: String, _ title: String, updated: String = "2026-10-26T10:00:00+00:00", door: String = "web") -> [String: Any] {
        ["id": id, "title": title, "door": door, "turns": 2, "created_at": updated, "updated_at": updated]
    }

    @Test func noConversationsYet() async {
        let s = session
        server.on("GET", "/api/threads", json: threads([]))
        let host = ScreenHost(ThreadsView(current: nil, onOpen: { _ in }, onDeleted: { _ in }), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Nothing yet"))
    }

    @Test func conversationsThatCannotLoadSaySo() async {
        let s = session
        server.fail("GET", "/api/threads", status: 500, "the list is away")
        let host = ScreenHost(ThreadsView(current: nil, onOpen: { _ in }, onDeleted: { _ in }), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("the list is away"))
    }

    @Test func olderConversationsComeOnRequestAndOtherDoorsSaySo() async {
        let s = session
        let first = try! JSONSerialization.data(withJSONObject: threads([thread("t1", "Dentist next week")], more: true))
        let older = try! JSONSerialization.data(withJSONObject: threads(
            [thread("t0", "The Lakers", updated: "2026-10-01T10:00:00+00:00", door: "service")]))
        server.on("GET", "/api/threads") { req in
            StubServer.Reply(body: req.query["before"] == nil ? first : older)
        }
        var opened: String?
        let host = ScreenHost(ThreadsView(current: "t1", onOpen: { opened = $0 }, onDeleted: { _ in }), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Dentist next week"))
        #expect(host.shows("Conversations are kept for 60 days"))
        await host.press("Show older")
        #expect(await host.waitFor("The Lakers"))
        #expect(host.shows("service"))
        #expect(server.requests("GET", "/api/threads").last?.query["before"] == "2026-10-26T10:00:00+00:00")
        if let row = host.elements.first(where: { $0.accessibilityLabel?.hasPrefix("The Lakers") == true }) {
            row.accessibilityActivate()
        }
        await host.settle()
        #expect(opened == "t0")
    }

    @Test func renamingAndDeletingAndTheirRefusals() async throws {
        let s = session
        server.on("GET", "/api/threads", json: threads([thread("t1", "Dentist next week")]))
        server.fail("DELETE", "/api/threads/t1", status: 500, "could not delete")
        var deleted: [String] = []
        let host = ScreenHost(ThreadsView(current: "t1", onOpen: { _ in }, onDeleted: { deleted.append($0) }), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Dentist next week"))
        #expect(await host.action("Delete", on: "Dentist next week"))
        #expect(await host.waitFor("could not delete"))
        #expect(deleted.isEmpty)

        server.on("DELETE", "/api/threads/t1", json: ["ok": true])
        #expect(await host.action("Delete", on: "Dentist next week"))
        await host.settle()
        #expect(deleted == ["t1"])
    }

    // MARK: Your Gmail

    @Test func gmailNotSetUpSaysSo() async {
        let s = session
        server.on("GET", "/api/mail", json: mail(connected: false, canConnect: false))
        let host = ScreenHost(MailboxView(), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Connecting email is not set up on this luach yet."))
    }

    @Test func gmailThatCannotLoadSaysWhy() async {
        let s = session
        server.fail("GET", "/api/mail", status: 503, "mail is resting")
        let host = ScreenHost(MailboxView(), session: s)
        defer { host.close() }
        #expect(await host.waitFor("mail is resting"))
    }

    @Test func connectingOwnGmailOverTheHouseholds() async {
        let s = session
        final class Flag: @unchecked Sendable { var on = false }
        let connected = Flag()
        let own = try! JSONSerialization.data(withJSONObject: mail(connected: true))
        let household = try! JSONSerialization.data(withJSONObject: mail(connected: true, via: "household"))
        server.on("GET", "/api/mail") { _ in StubServer.Reply(body: connected.on ? own : household) }
        server.on("POST", "/api/mail/connect/app", json: ["url": "https://accounts.google.com/o/oauth2/v2/auth?state=app1.x"])
        var asked: URL?
        let view = MailboxView(signIn: { url in
            asked = url
            connected.on = true
            return URL(string: "luach://mail?mail=connected")!
        })
        let host = ScreenHost(view, session: s)
        defer { host.close() }
        #expect(await host.waitFor("The household mailbox, the one you forward things to."))
        #expect(host.shows("This is the household's shared connection"))
        await host.press("Connect my own Gmail")
        #expect(await host.waitFor("Your email is connected."))
        #expect(asked?.host() == "accounts.google.com")
        #expect(await host.waitFor("Disconnect"))
    }

    @Test func theConnectIsClaimedWithTheNonceFromTheWayBack() async {
        let s = session
        final class Flag: @unchecked Sendable { var on = false }
        let connected = Flag()
        let own = try! JSONSerialization.data(withJSONObject: mail(connected: true))
        let off = try! JSONSerialization.data(withJSONObject: mail(connected: false))
        server.on("GET", "/api/mail") { _ in StubServer.Reply(body: connected.on ? own : off) }
        server.on("POST", "/api/mail/connect/app", json: ["url": "https://accounts.google.com/o/oauth2/v2/auth?state=app1.x"])
        server.on("POST", "/api/mail/connect/app/finish") { _ in
            connected.on = true
            return StubServer.Reply(body: own)
        }
        let host = ScreenHost(MailboxView(signIn: { _ in URL(string: "luach://mail?mail=confirm&nonce=n0nce")! }), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Connect my Gmail"))
        await host.press("Connect my Gmail")
        #expect(await host.waitFor("Your email is connected."))
        #expect(server.requests("POST", "/api/mail/connect/app/finish").first?.json["nonce"] as? String == "n0nce")
        #expect(await host.waitFor("Disconnect"))
    }

    @Test func someoneElsesGmailIsSaidPlainly() async {
        let s = session
        server.on("GET", "/api/mail", json: mail(connected: false))
        server.on("POST", "/api/mail/connect/app", json: ["url": "https://accounts.google.com/o/oauth2/v2/auth"])
        let host = ScreenHost(MailboxView(signIn: { _ in URL(string: "luach://mail?mail=failed&reason=not-yours")! }), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Connect my Gmail"))
        await host.press("Connect my Gmail")
        #expect(await host.waitFor("That Gmail is not one of your addresses here"))
        #expect(server.requests("POST", "/api/mail/connect/app/finish").isEmpty)
    }

    @Test func aConnectThatFailsOrIsCancelled() async {
        let s = session
        server.on("GET", "/api/mail", json: mail(connected: false))
        server.on("POST", "/api/mail/connect/app", json: ["url": "https://accounts.google.com/o/oauth2/v2/auth"])
        var answer: Result<URL, Error> = .success(URL(string: "luach://mail?mail=failed")!)
        let host = ScreenHost(MailboxView(signIn: { _ in try answer.get() }), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Connect my Gmail"))
        await host.press("Connect my Gmail")
        #expect(await host.waitFor("Connecting your email did not work"))

        answer = .failure(URLError(.notConnectedToInternet))
        await host.press("Connect my Gmail")
        #expect(await host.waitFor(URLError(.notConnectedToInternet).localizedDescription))

        server.fail("POST", "/api/mail/connect/app", status: 409, "connecting email is not set up on this luach")
        await host.press("Connect my Gmail")
        #expect(await host.waitFor("connecting email is not set up on this luach"))
    }

    @Test func closingGooglesSheetSaysNothing() async {
        let s = session
        server.on("GET", "/api/mail", json: mail(connected: false))
        server.on("POST", "/api/mail/connect/app", json: ["url": "https://accounts.google.com/o/oauth2/v2/auth"])
        var asked = 0
        let host = ScreenHost(MailboxView(signIn: { _ in
            asked += 1
            throw ASWebAuthenticationSessionError(.canceledLogin)
        }), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Connect my Gmail"))
        #expect(await host.press("Connect my Gmail"))
        await host.settle(.milliseconds(500))
        #expect(asked == 1)
        #expect(!host.shows("did not work") && !host.shows("is connected"))
        #expect(await host.waitFor("Connect my Gmail"), "the button is back for another try")
    }

    @Test func theScanAndDisconnectingAndTheirRefusals() async {
        let s = session
        server.on("GET", "/api/mail", json: mail(connected: true, scan: scanOn))
        server.fail("PATCH", "/api/mail/scan", status: 409, "the scan is off on this luach")
        server.fail("DELETE", "/api/mail", status: 500, "Google did not answer")
        let host = ScreenHost(MailboxView(), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Connected as"))
        #expect(await host.waitFor("120 read · 6 found"))
        #expect(host.shows("Reading mail from"))
        await host.press("Look through new mail for things to add")
        #expect(await host.waitFor("the scan is off on this luach"))
        await host.press("Disconnect")
        #expect(await host.waitFor("Google did not answer"))
    }

    // MARK: Ask

    private func askBasics(mic: Bool = true) {
        server.on("GET", "/api/transcribe/status", json: ["available": mic])
        server.on("GET", "/api/control/pending", json: ["pending": []])
    }

    /// A conversation with one turn already in it, from the frames given.
    private func conversation(_ frames: [[String: Any]], api: API) async -> Conversation {
        server.stream(frames)
        let c = Conversation()
        c.send("what's on", api: api) {}
        while c.streaming { try? await Task.sleep(for: .milliseconds(10)) }
        return c
    }

    @Test func everyKindOfCardAndStep() async {
        let s = session
        askBasics()
        let c = await conversation([
            ["type": "skill", "name": "plan-a-trip"],
            ["type": "tool_start", "tool": "get_event", "args": [:]],
            ["type": "tool_result", "tool": "get_event", "error": "no such event; ask which one"],
            ["type": "widget", "kind": "availability", "data": ["free": false, "clashes": [
                ["id": "e1", "title": "Tennis", "when": "Sat 19 Sep, 16:00–17:00", "location": "The courts"]]]],
            ["type": "widget", "kind": "event", "data": ["event": ["id": "e2", "title": "Dentist", "when": "Tue 27 Oct, 15:00"]]],
            ["type": "widget", "kind": "agenda", "data": ["title": "Next week", "events": [], "truncated": true]],
            ["type": "error", "message": "The model stopped answering."],
        ], api: s.api)
        let host = ScreenHost(AskView(conversation: c, recorder: fakeRecorder()), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Something's on"))
        #expect(host.shows("The courts"))
        #expect(host.shows("Dentist"))
        #expect(host.shows("Nothing on the calendar."))
        #expect(host.shows("And more."))
        #expect(host.shows("The model stopped answering."))
        await host.press("2 steps")
        #expect(await host.waitFor("Following the guide: plan a trip"))
        #expect(host.shows("couldn't: no such event"))
    }

    private func heldTurn(_ s: AppSession) async -> Conversation {
        askBasics()
        return await conversation([
            ["type": "held", "id": "h1", "tool": "create_event", "summary": "Add “Dentist”", "reason_text": "The time was a guess."],
            ["type": "done", "reply": "I need a yes."],
        ], api: s.api)
    }

    @Test func aHoldApprovedInTheChat() async {
        let s = session
        let c = await heldTurn(s)
        server.on("POST", "/api/control/pending/h1/approve", json: ["id": "h1", "tool": "t", "summary": "s", "status": "approved"])
        let host = ScreenHost(AskView(conversation: c, recorder: fakeRecorder()), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("The time was a guess."))
        await host.press("Approve")
        #expect(await host.waitFor("Approved"))
    }

    @Test func aHoldSomeoneElseDecidedFirst() async {
        let s = session
        let c = await heldTurn(s)
        server.fail("POST", "/api/control/pending/h1/approve", status: 409, "already decided")
        let host = ScreenHost(AskView(conversation: c, recorder: fakeRecorder()), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Waiting for a yes"))
        await host.press("Approve")
        #expect(await host.waitFor("Already decided elsewhere."))
        server.fail("POST", "/api/control/pending/h1/approve", status: 500, "the gate is away")
        await host.press("Approve")
        #expect(await host.waitFor("the gate is away"))
    }

    @Test func aHoldFromAnEarlierVisitThatIsNoLongerWaiting() async {
        let s = session
        askBasics()
        server.on("GET", "/api/threads/th-1", json: ["id": "th-1", "turns": [
            ["role": "user", "content": "dentist", "events": []],
            ["role": "assistant", "content": "Held.", "events": [["held": [["id": "old", "summary": "Add “Dentist”"]], "created": []]]],
        ]])
        let c = Conversation()
        await c.open("th-1", api: s.api)
        let host = ScreenHost(AskView(conversation: c, recorder: fakeRecorder()), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Decided"))
    }

    @Test func speakingPutsWhatWasHeardInTheField() async {
        let s = session
        askBasics()
        server.on("POST", "/api/transcribe", json: ["text": "dentist on tuesday"])
        let host = ScreenHost(AskView(conversation: Conversation(), recorder: fakeRecorder()), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Speak"))
        await host.press("Speak")
        #expect(await host.waitFor("Stop listening"))
        await host.press("Stop listening")
        #expect(await host.waitFor("dentist on tuesday"))
        #expect(server.requests("POST", "/api/transcribe").first?.headers["Content-Type"] == "audio/mp4")
    }

    @Test func whatGoesWrongWithTheMicIsSaid() async {
        let s = session
        askBasics()
        let host = ScreenHost(AskView(conversation: Conversation(), recorder: fakeRecorder(granted: false)), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Speak"))
        await host.press("Speak")
        #expect(await host.waitFor("luach cannot hear you"))

        let s2 = AppSession(api: server.api)
        server.fail("POST", "/api/transcribe", status: 503, "no transcriber on this luach")
        let host2 = ScreenHost(AskView(conversation: Conversation(), recorder: fakeRecorder()), session: s2, stack: false)
        defer { host2.close() }
        #expect(await host2.waitFor("Speak"))
        await host2.press("Speak")
        #expect(await host2.waitFor("Stop listening"))
        await host2.press("Stop listening")
        #expect(await host2.waitFor("no transcriber on this luach"))
    }

    @Test func anAskArgumentSendsAtLaunchAndTheListOpensAThread() async {
        let s = session
        askBasics()
        server.stream([["type": "session", "thread_id": "t9"], ["type": "token", "text": "Ready."], ["type": "done", "reply": "Ready."]])
        server.on("GET", "/api/threads", json: threads([thread("t5", "Last week's plan")]))
        server.on("GET", "/api/threads/t5", json: ["id": "t5", "turns": [["role": "user", "content": "Last week's plan", "events": []]]])
        UserDefaults.standard.set("Say ready", forKey: "ask")
        UserDefaults.standard.set(true, forKey: "showThreads")
        defer { for key in ["ask", "showThreads"] { UserDefaults.standard.removeObject(forKey: key) } }
        let host = ScreenHost(AskView(conversation: Conversation(), recorder: fakeRecorder()), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Last week's plan"))
        #expect(server.requests("POST", "/api/agent/stream").first?.json["text"] as? String == "Say ready")
        if let row = host.elements.last(where: { $0.accessibilityLabel?.hasPrefix("Last week's plan") == true }) {
            row.accessibilityActivate()
        }
        #expect(await host.waitFor("Last week's plan"))
        await host.settle(.milliseconds(500))
        #expect(server.requests("GET", "/api/threads/t5").count >= 1)
    }
}

@MainActor
struct MoreStepLabelTests {
    private func label(_ tool: String, _ args: [String: Any] = [:]) -> String {
        let data = try! JSONSerialization.data(withJSONObject: args)
        return StepLabel.text(tool: tool, args: try! JSONDecoder().decode(JSONValue.self, from: data))
    }

    @Test func theRestOfTheTools() {
        #expect(label("get_event") == "Opening an event")
        #expect(label("read_email") == "Reading an email")
        #expect(label("read_web_page") == "Reading a page")
        #expect(label("search_the_web") == "Searching the web")
        #expect(label("search_email") == "Searching your email")
        #expect(label("list_tasks") == "Checking the tasks")
        #expect(label("list_tasks", ["for_whom": "Lily"]) == "Checking the tasks for Lily")
        #expect(label("change_task") == "Changing a task")
        #expect(label("remove_task") == "Removing a task")
        #expect(label("add_task") == "Adding a task")
        #expect(label("update_event") == "Changing an event")
        #expect(label("remember") == "Recalling what it knows")
        #expect(label("forget") == "Forgetting something")
        #expect(Conversation.describe(tool: "add_task") == "Seeing to the to-dos")
        #expect(Conversation.describe(tool: "search_email") == "Reading your email")
        #expect(Conversation.describe(tool: "check_availability") == "Checking who is free")
        #expect(Conversation.describe(tool: "create_event") == "Adding it to the calendar")
        #expect(Conversation.describe(tool: "update_event") == "Changing the event")
        #expect(Conversation.describe(tool: "delete_event") == "Removing the event")
        #expect(Conversation.describe(tool: "remember") == "Checking what it knows about you")
    }

    @Test func aFrameOfAKindNotKnownIsPassedOver() async {
        let server = StubServer()
        server.stream([["type": "thinking", "text": "hm"], ["type": "brand-new", "x": 1], ["type": "done", "reply": "ok"]])
        Conversation.forget()
        let c = Conversation()
        c.send("hi", api: server.api) {}
        while c.streaming { try? await Task.sleep(for: .milliseconds(10)) }
        #expect(c.items.count == 3)
        Conversation.forget()
    }
}
