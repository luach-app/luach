import SwiftUI
import Testing
import UIKit
@testable import Luach

/// A Board screen shown for real in a window of the test host and answered by a StubServer:
/// what dev cannot show — a board that does not load, a save refused, a screen that may not
/// edit, a child's task list — without touching dev.
@MainActor
final class BoardHost {
    let window: UIWindow

    /// SwiftUI builds its accessibility tree only for an assistive client; turn automation on
    /// (as KIF does), or what the screen shows depends on whether a UI test ran before.
    private static let automation: Void = {
        guard let lib = dlopen("/usr/lib/libAccessibility.dylib", RTLD_NOW),
              let set = dlsym(lib, "_AXSSetAutomationEnabled") else { return }
        typealias Set = @convention(c) (Int32) -> Void
        unsafeBitCast(set, to: Set.self)(1)
    }()

    init(_ view: some View, session: AppSession, stack: Bool = false) {
        _ = Self.automation
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        window = scene.map { UIWindow(windowScene: $0) } ?? UIWindow()
        // Tall, so the list lays out every section at once.
        window.frame = CGRect(x: 0, y: 0, width: 402, height: 3000)
        let root = stack ? AnyView(NavigationStack { view }) : AnyView(view)
        window.rootViewController = UIHostingController(rootView: root.environment(session))
        window.isHidden = false
    }

    func close() {
        window.isHidden = true
        window.rootViewController = nil
    }

    func settle(_ time: Duration = .milliseconds(400)) async {
        try? await Task.sleep(for: time)
        window.layoutIfNeeded()
        try? await Task.sleep(for: .milliseconds(50))
    }

    /// Waits until the screen shows `text` (or `seconds` pass) and says whether it did.
    func waitFor(_ text: String, seconds: Double = 5) async -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while Date() < end {
            if shows(text) { return true }
            await settle(.milliseconds(150))
        }
        if shows(text) { return true }
        let scene = window.windowScene.map { "\($0.activationState.rawValue)" } ?? "none"
        Issue.record("never showed “\(text)”; scene state \(scene); on screen: \(labels.prefix(30))")
        return false
    }

    var elements: [NSObject] {
        var found: [NSObject] = []
        func walk(_ node: NSObject, depth: Int) {
            guard depth < 60 else { return }
            if node.isAccessibilityElement { found.append(node) }
            let children: [Any]
            if let list = node.accessibilityElements, !list.isEmpty {
                children = list
            } else if let view = node as? UIView {
                children = view.subviews
            } else {
                let n = node.accessibilityElementCount()
                children = n == NSNotFound || n <= 0 ? [] : (0..<n).compactMap { node.accessibilityElement(at: $0) }
            }
            for child in children { if let child = child as? NSObject { walk(child, depth: depth + 1) } }
        }
        if let root = window.rootViewController?.view { walk(root, depth: 0) }
        return found
    }

    var labels: [String] { elements.compactMap(\.accessibilityLabel) }

    func shows(_ text: String) -> Bool { labels.contains { $0 == text || $0.contains(text) } }

    func value(of label: String) -> String? { elements.first { $0.accessibilityLabel == label }?.accessibilityValue }

    /// Presses the element labelled so, a button first (a row's words can carry the same label).
    @discardableResult
    func press(_ label: String) async -> Bool {
        let all = elements.filter { $0.accessibilityLabel == label }
        guard let target = all.first(where: { $0.accessibilityTraits.contains(.button) }) ?? all.first else { return false }
        let pressed = target.accessibilityActivate()
        await settle(.milliseconds(300))
        return pressed
    }
}

@MainActor
@Suite(.serialized, .timeLimit(.minutes(2)))
struct BoardScreenTests {
    let server = StubServer()

    private var session: AppSession { AppSession(api: server.api) }

    private func tasksAnswer(mayAssign: Bool, tasks: [[String: Any]] = [BoardFixtures.todo, BoardFixtures.chore]) {
        server.on("GET", "/api/tasks", json: ["day": "2026-10-27", "tasks": tasks, "may_assign": mayAssign])
        server.on("GET", "/api/tasks/all", json: ["tasks": tasks, "may_assign": mayAssign])
        server.on("GET", "/api/family", json: ["people": BoardFixtures.people, "colors": []])
    }

    /// Launch arguments land in UserDefaults; the test host is the app, so put them back.
    private func with(_ defaults: [String: String], _ body: () async throws -> Void) async rethrows {
        for (k, v) in defaults { UserDefaults.standard.set(v, forKey: k) }
        defer { for k in defaults.keys { UserDefaults.standard.removeObject(forKey: k) } }
        try await body()
    }

    // MARK: The board

    @Test func aBoardThatDidNotLoadSaysSoAndTriesAgain() async throws {
        server.fail("GET", "/api/board/today", status: 503, "luach is restarting")
        tasksAnswer(mayAssign: true)
        let host = BoardHost(BoardView(), session: session)
        defer { host.close() }
        #expect(await host.waitFor("The board did not load"))
        #expect(host.shows("luach is restarting"))

        server.on("GET", "/api/board/today", json: BoardFixtures.board())
        #expect(await host.press("Try again"))
        #expect(await host.waitFor("Library books"))
        #expect(host.shows("Open Swim") && host.shows("Add for Ruby") && host.shows("Add for the family"))
        #expect(host.value(of: "Library books") == "Not done")
        // Under "Open …", VoiceOver hears what the row's smaller lines say.
        #expect(host.value(of: "Open Library books") == "late — was due \(ISODay.short("2026-10-26")), the blue bag")
        #expect(host.value(of: "Open Feed the cat") == Weekday.describe(Weekday.codes))
        #expect(host.shows("Book fair"), "tomorrow's events, underneath")
    }

    @Test func aTickIsShownAtOnceAndSentForThePage() async throws {
        server.on("GET", "/api/board/today", json: BoardFixtures.board())
        server.on("POST", "/api/board/tasks/132/done", json: BoardFixtures.todo)
        tasksAnswer(mayAssign: true)
        let host = BoardHost(BoardView(), session: session)
        defer { host.close() }
        #expect(await host.waitFor("Library books"))
        #expect(await host.press("Library books"))
        #expect(host.value(of: "Library books") == "Done")
        await host.settle()
        let sent = try #require(server.requests("POST", "/api/board/tasks/132/done").first)
        #expect(sent.json["done"] as? Bool == true && sent.json["day"] == nil)
    }

    @Test func aRefusedTickSaysWhyAndAnUnreachableBoardKeepsTheLastDay() async throws {
        server.on("GET", "/api/board/today", json: BoardFixtures.board())
        server.fail("POST", "/api/board/tasks/132/done", status: 403, "that screen may not change things")
        tasksAnswer(mayAssign: true)
        let host = BoardHost(BoardView(), session: session)
        defer { host.close() }
        #expect(await host.waitFor("Library books"))

        // From now on the board is out of reach: the last day stays, marked offline.
        server.fail("GET", "/api/board/today", status: 502, "bad gateway")
        #expect(await host.press("Library books"))
        #expect(await host.waitFor("did not save: that screen may not change things"))
        #expect(await host.waitFor("offline — showing the last known day"))
        #expect(host.shows("Library books"))
    }

    @Test func aScreenThatMayNotEditOnlyShows() async throws {
        var stranger = BoardFixtures.todo
        stranger["person"] = "someone-gone"
        let eight = (1...8).map { i -> [String: Any] in
            var e = BoardFixtures.allDayEvent
            e["id"] = "t\(i)"
            e["title"] = "Next \(i)"
            e["leaders"] = i == 1 ? ["ruby"] : []
            return e
        }
        server.on("GET", "/api/board/today", json: BoardFixtures.board(events: [], tomorrow: eight, tasks: [stranger], people: [], canEdit: false))
        tasksAnswer(mayAssign: true)
        let host = BoardHost(BoardView(), session: session)
        defer { host.close() }
        #expect(await host.waitFor("No one is on the board yet"))
        #expect(host.shows("Settings › Household › Family"), "where the family is set up in the app")
        #expect(!host.shows("Settings › Members"), "Members is who signs in, not who is on the board")
        #expect(!host.shows("Add for"), "no + where nothing may be added")
        // Someone no longer in the family: their task is the family's.
        #expect(host.shows(String(localized: "Family")) && host.shows("Library books"))
        #expect(host.shows("+2 more"))
        #expect(host.shows("Next 1") && !host.shows("Next 7"))
    }

    @Test func aLaterPageGoesBackToToday() async throws {
        server.on("GET", "/api/board/today") { req in
            let day = req.query["day"] ?? "2026-10-27"
            let body = try! JSONSerialization.data(withJSONObject: BoardFixtures.board(day: day, events: [], tomorrow: [BoardFixtures.allDayEvent], tasks: []))
            return StubServer.Reply(body: body)
        }
        tasksAnswer(mayAssign: true)
        try await with(["boardDay": "2"]) {
            let host = BoardHost(BoardView(), session: session)
            defer { host.close() }
            #expect(await host.waitFor("Back to today"))
            #expect(host.shows("The day after"))
            #expect(host.shows("A free day."))
            #expect(await host.press("Next day"))
            #expect(await host.press("Previous day"))
            #expect(await host.press("Back to today"))
            #expect(await host.waitFor("Tomorrow"))
            let asked = server.requests("GET", "/api/board/today").compactMap { $0.query["day"] }
            #expect(asked.contains(ISODay.add(ISODay.today(in: .current), 2)))
        }
    }

    @Test func theUndoBarTakesAChangeBack() async throws {
        server.on("GET", "/api/board/today", json: BoardFixtures.board())
        tasksAnswer(mayAssign: true)
        try await with(["boardToast": "YES"]) {
            let host = BoardHost(BoardView(), session: session)
            defer { host.close() }
            #expect(await host.waitFor("ios-test is now Ruby’s."))
            #expect(await host.press("Undo"))
            #expect(await host.waitFor("is back where it was."))
        }
    }

    @Test func aTaskSheetOpensAtLaunchForANewTaskOrAnOldOne() async throws {
        server.on("GET", "/api/board/today", json: BoardFixtures.board())
        tasksAnswer(mayAssign: true)
        try await with(["boardTask": "132"]) {
            let host = BoardHost(BoardView(), session: session)
            defer { host.close() }
            #expect(await host.waitFor("Library books"))
            for _ in 0..<20 where host.window.rootViewController?.presentedViewController == nil { await host.settle(.milliseconds(250)) }
            #expect(host.window.rootViewController?.presentedViewController != nil, "the task's sheet is up")
        }
    }

    // MARK: The task list

    @Test func aChildTicksButIsToldWhoHandsOutTheTasks() async throws {
        tasksAnswer(mayAssign: false)
        server.on("POST", "/api/tasks/132/done", json: BoardFixtures.todo)
        let host = BoardHost(TasksView(), session: session, stack: true)
        defer { host.close() }
        #expect(await host.waitFor("A grown-up hands out the tasks"))
        #expect(!host.shows("New task") && !host.shows("Open Library books"), "nothing to open or add")
        #expect(host.shows("0/1"), "each column counts what is done")
        #expect(await host.press("Library books"))
        await host.settle()
        let sent = try #require(server.requests("POST", "/api/tasks/132/done").first)
        #expect(sent.json["day"] as? String == "2026-10-27" && sent.json["done"] as? Bool == true)
        #expect(host.shows("1/1"))
    }

    @Test func aRefusedTickInTheListIsPutBack() async throws {
        tasksAnswer(mayAssign: true)
        server.fail("POST", "/api/tasks/132/done", status: 500, "the database is busy")
        let host = BoardHost(TasksView(), session: session, stack: true)
        defer { host.close() }
        #expect(await host.waitFor("Open Library books"))
        #expect(host.shows("New task"))
        #expect(await host.press("Library books"))
        #expect(await host.waitFor("the database is busy"))
        #expect(host.value(of: "Library books") == "Not done")
    }

    @Test func aListThatDidNotLoadSaysWhy() async throws {
        server.fail("GET", "/api/tasks", status: 500, "the tasks are not there")
        server.fail("GET", "/api/family", status: 500, "the family is not there")
        let host = BoardHost(TasksView(), session: session, stack: true)
        defer { host.close() }
        #expect(await host.waitFor("not there"))
    }

    @Test func everythingOpenAndADayPaged() async throws {
        tasksAnswer(mayAssign: true, tasks: [])
        try await with(["tasksMode": "all"]) {
            let host = BoardHost(TasksView(), session: session, stack: true)
            defer { host.close() }
            #expect(await host.waitFor("Nothing open."))
            #expect(server.requests("GET", "/api/tasks/all").count >= 1)
        }
        try await with(["tasksDay": "1"]) {
            let host = BoardHost(TasksView(), session: session, stack: true)
            defer { host.close() }
            #expect(await host.waitFor("Nothing today."))
            await host.settle(.milliseconds(1500))
            #expect(server.requests("GET", "/api/tasks").contains { $0.query["day"] == "2026-10-28" })
            #expect(await host.press("Previous day"))
            #expect(await host.waitFor("Today"))
        }
    }

    // MARK: The task sheet

    @Test func aTaskSomeoneMayNotChangeOnlyShows() async throws {
        let task = try BoardFixtures.task()
        let host = BoardHost(TaskEditor(sheet: .open(task), people: try BoardFixtures.day().people, canEdit: false, routes: .tasks), session: session)
        defer { host.close() }
        #expect(await host.waitFor("Close"))
        #expect(!host.shows("Save") && !host.shows("Remove"))
    }

    @Test func aSaveTheServerRefusesSaysWhy() async throws {
        server.fail("PATCH", "/api/board/tasks/133", status: 403, "a child's account cannot change tasks")
        let chore = try BoardFixtures.task(BoardFixtures.chore)
        var changed = false
        let host = BoardHost(TaskEditor(sheet: .open(chore), people: try BoardFixtures.day().people, canEdit: true, routes: .board, onChanged: { changed = true }), session: session)
        defer { host.close() }
        #expect(await host.waitFor(Weekday.name("SU")))
        #expect(host.shows("Remove"))
        #expect(await host.press(Weekday.name("SU")), "a day unpicked")
        #expect(await host.press("Save"))
        #expect(await host.waitFor("a child's account cannot change tasks"))
        #expect(!changed)
        let sent = try #require(server.requests("PATCH", "/api/board/tasks/133").first)
        #expect(sent.json["days"] as? [String] == ["MO", "TU", "WE", "TH", "FR", "SA"] && sent.json["due"] as? String == "")
    }

    @Test func aSavedTaskTellsTheBoard() async throws {
        server.on("PATCH", "/api/tasks/132", json: BoardFixtures.todo)
        var changed = false
        let host = BoardHost(TaskEditor(sheet: .open(try BoardFixtures.task()), people: try BoardFixtures.day().people, canEdit: true, routes: .tasks, onChanged: { changed = true }), session: session)
        defer { host.close() }
        #expect(await host.waitFor("Save"))
        #expect(host.shows("Due"), "a dated to-do shows its day")
        #expect(await host.press("Lily"))
        #expect(await host.press("Save"))
        await host.settle()
        #expect(changed)
        let sent = try #require(server.requests("PATCH", "/api/tasks/132").first)
        #expect(sent.json["person"] as? String == "lily" && sent.json["due"] as? String == "2026-10-26" && sent.json["title"] as? String == "Library books")
    }
}
