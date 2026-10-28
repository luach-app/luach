import SwiftUI
import Testing
import UIKit
@testable import Luach

/// An Agenda screen shown for real in a window of the test host, answered by a StubServer:
/// what dev cannot show — an invitation luach may not change, a calendar luach only reads,
/// several calendars, a server that refuses — without touching dev.
@MainActor
final class AgendaHost {
    let window: UIWindow

    /// SwiftUI builds its accessibility tree only for an assistive client. A UI test run turns
    /// automation on for the simulator and leaves it on until the next run ends, so without
    /// this the screen tests passed or found nothing depending on what ran before.
    private static let automation: Void = {
        guard let lib = dlopen("/usr/lib/libAccessibility.dylib", RTLD_NOW),
              let set = dlsym(lib, "_AXSSetAutomationEnabled") else { return }
        typealias Set = @convention(c) (Int32) -> Void
        unsafeBitCast(set, to: Set.self)(1)
    }()

    init(_ view: some View, session: AppSession) {
        _ = Self.automation
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        window = scene.map { UIWindow(windowScene: $0) } ?? UIWindow()
        // Tall, so a list lays out every section at once.
        window.frame = CGRect(x: 0, y: 0, width: 402, height: 3000)
        window.rootViewController = UIHostingController(rootView: NavigationStack { view }.environment(session))
        window.isHidden = false
    }

    func close() {
        window.rootViewController?.dismiss(animated: false)
        window.isHidden = true
        window.rootViewController = nil
    }

    func settle(_ time: Duration = .milliseconds(300)) async {
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
        return shows(text)
    }

    /// Every accessibility element on screen, in what is presented over it too.
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
        var controller = window.rootViewController
        while let c = controller {
            walk(c.view, depth: 0)
            controller = c.presentedViewController
        }
        return found
    }

    var labels: [String] { elements.compactMap(\.accessibilityLabel) }

    /// On screen as a label or as a value (a picker's choice).
    func shows(_ text: String) -> Bool {
        (labels + elements.compactMap(\.accessibilityValue)).contains { $0 == text || $0.contains(text) }
    }

    @discardableResult
    func press(_ label: String) async -> Bool {
        guard let target = elements.last(where: { $0.accessibilityLabel == label }) else { return false }
        let pressed = target.accessibilityActivate()
        await settle()
        return pressed
    }
}

@MainActor
@Suite(.serialized, .timeLimit(.minutes(2)))
struct AgendaScreenTests {
    let server = StubServer()
    typealias F = AgendaFixtures

    private var session: AppSession { AppSession(api: server.api) }

    /// The shared store, loaded from the stub: a household with several calendars, the family.
    private func basics(_ api: API) async {
        server.on("GET", "/api/household/calendars", json: F.household)
        server.on("GET", "/api/family", json: F.family)
        server.on("GET", "/api/auth/me", json: F.me)
        AgendaData.shared.bind(nil)
        await AgendaData.shared.loadBasics(api, force: true)
    }

    /// The editor's DEBUG launch arguments, set for one test and taken away after.
    private func withDefaults(_ values: [String: Any], _ body: () async throws -> Void) async rethrows {
        let d = UserDefaults.standard
        for (k, v) in values { d.set(v, forKey: k) }
        defer { for k in values.keys { d.removeObject(forKey: k) } }
        try await body()
    }

    // MARK: Reading an event

    @Test func anInvitationSaysWhoseItIsAndCannotBeChanged() async throws {
        let s = session
        await basics(s.api)
        let ev = try F.event(F.invitation)
        let host = AgendaHost(AgendaEventDetail(event: ev, clock: F.newYork, onEdit: {}, onChanged: {}), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Board meeting"))
        #expect(host.shows("An invitation from boss@example.com. Only they can change it"))
        #expect(host.shows("ana@example.com, sam@example.com"))
        #expect(host.shows("Open in Google Calendar"))
        #expect(host.shows("Family"), "its calendar, among several")
        #expect(!host.labels.contains("Delete") && !host.labels.contains("Edit"))
    }

    @Test func busyTimeFromAFeedSaysLuachOnlyReadsIt() async throws {
        let s = session
        await basics(s.api)
        var json = F.invitation
        json["organizer"] = ""
        json["attendees"] = []
        let host = AgendaHost(AgendaEventDetail(event: try F.event(json), clock: F.newYork, onEdit: {}, onChanged: {}), session: s)
        defer { host.close() }
        #expect(await host.waitFor("From a calendar luach only reads."))
    }

    @Test func anEventShowsItsPeopleRepeatNotesAndInviteTrouble() async throws {
        let s = session
        await basics(s.api)
        var json = F.timed
        json["invite_error"] = "Saved, but the invitations could not be sent."
        var edits = 0
        let host = AgendaHost(AgendaEventDetail(event: try F.event(json), clock: F.newYork, onEdit: { edits += 1 }, onChanged: {}),
                              session: s)
        defer { host.close() }
        #expect(await host.waitFor("Dentist"))
        #expect(host.shows("For Ruby and Lily"))
        #expect(host.shows("Every week on Tuesday"))
        #expect(host.shows("See the page (https://example.com/x)"))
        #expect(host.shows("Saved, but the invitations could not be sent."))
        #expect(host.shows("Clinic") && host.shows("luach (local)"))
        await host.press("Edit")
        #expect(edits == 1)
    }

    @Test func deletingTheSeriesItselfAsksPlainly() async throws {
        // The dialog's own buttons cannot be pressed from here (the UI tests press them on dev).
        let s = session
        let host = AgendaHost(AgendaEventDetail(event: try F.event(F.timed), clock: F.newYork, onEdit: {}, onChanged: {}),
                              session: s)
        defer { host.close() }
        #expect(await host.waitFor("Dentist"))
        await host.press("Delete")
        #expect(await host.waitFor("Delete for real"))
        #expect(!host.shows("All events"))
    }

    @Test func deletingAnOccurrenceAsksThisEventOrAllEvents() async throws {
        let s = session
        let host = AgendaHost(AgendaEventDetail(event: try F.event(F.occurrence), clock: F.newYork, onEdit: {}, onChanged: {}),
                              session: s)
        defer { host.close() }
        #expect(await host.waitFor("Every week on Tuesday"), "an occurrence says how its series repeats")
        await host.press("Delete")
        #expect(await host.waitFor("All events"))
        #expect(host.shows("This event") && !host.shows("Delete for real"))
        #expect(host.shows("Dentist repeats. Delete only this one, or every one?"))
    }

    // MARK: An occurrence in the editor

    private var occurrencePath: String { "/api/calendar/events/4fd5aabcaffd_20261110T150000" }

    @Test func savingAnOccurrenceAsksThisEventOrAllEvents() async throws {
        let s = session
        await basics(s.api)
        let ev = try F.event(F.occurrence)
        let host = AgendaHost(EventEditor(mode: .edit(id: ev.id, calendar: ev.calendarId), initial: ev, day: nil, onSaved: {}),
                              session: s)
        defer { host.close() }
        #expect(await host.waitFor("Edit event"))
        #expect(host.shows("Every week"), "it opens on its series' repeat, not \"Does not repeat\"")
        await host.press("Save")
        #expect(await host.waitFor("Save this change for this event only, or for every one?"))
        #expect(host.shows("This event") && host.shows("All events"))
        #expect(server.requests("PATCH", occurrencePath).isEmpty, "nothing is saved until it is answered")
    }

    @Test(arguments: ["this", "series"])
    func anOccurrenceIsSavedForTheEventsChosen(scope: String) async throws {
        let s = session
        await basics(s.api)
        server.on("PATCH", occurrencePath, json: F.occurrence)
        server.on("GET", "/api/control/pending", json: ["pending": []])
        let ev = try F.event(F.occurrence)
        var saved = 0
        try await withDefaults(["editorTitle": "Dentist, early", "editorAutoSave": true, "editorScope": scope]) {
            let host = AgendaHost(EventEditor(mode: .edit(id: ev.id, calendar: ev.calendarId), initial: ev, day: nil,
                                              onSaved: { saved += 1 }), session: s)
            defer { host.close() }
            for _ in 0..<20 where saved == 0 { await host.settle(.milliseconds(150)) }
        }
        #expect(saved == 1)
        let sent = try #require(server.requests("PATCH", occurrencePath).first)
        #expect(sent.query == ["calendar": "fake", "scope": scope])
        #expect(sent.json["title"] as? String == "Dentist, early")
        #expect(sent.json["recurrence"] == nil, "the repeat it showed is not sent back")
    }

    @Test func aNewRepeatChosenOnAnOccurrenceIsTheSeriesWithoutAsking() async throws {
        let s = session
        await basics(s.api)
        server.on("PATCH", occurrencePath, json: F.occurrence)
        server.on("GET", "/api/control/pending", json: ["pending": []])
        let ev = try F.event(F.occurrence)
        var saved = 0
        try await withDefaults(["editorRepeat": "biweekly", "editorAutoSave": true]) {
            let host = AgendaHost(EventEditor(mode: .edit(id: ev.id, calendar: ev.calendarId), initial: ev, day: nil,
                                              onSaved: { saved += 1 }), session: s)
            defer { host.close() }
            for _ in 0..<20 where saved == 0 { await host.settle(.milliseconds(150)) }
        }
        #expect(saved == 1)
        let sent = try #require(server.requests("PATCH", occurrencePath).first)
        #expect(sent.query == ["calendar": "fake", "scope": "series"])
        #expect(sent.json["recurrence"] as? String == "biweekly")
    }

    @Test func anOccurrenceDeletedFromTheEditorSaysWhich() async throws {
        let s = session
        server.on("DELETE", occurrencePath, json: ["ok": true, "guest_told": false])
        server.on("GET", "/api/control/pending", json: ["pending": []])
        let ev = try F.event(F.occurrence)
        var saved = 0
        try await withDefaults(["editorAutoDelete": true, "editorScope": "this"]) {
            let host = AgendaHost(EventEditor(mode: .edit(id: ev.id, calendar: nil), initial: ev, day: nil,
                                              onSaved: { saved += 1 }), session: s)
            defer { host.close() }
            for _ in 0..<20 where saved == 0 { await host.settle(.milliseconds(150)) }
        }
        #expect(saved == 1)
        #expect(server.requests("DELETE", occurrencePath).first?.query == ["calendar": "fake", "scope": "this"])
    }

    // MARK: The editor

    @Test func anEventThatWillNotOpenSaysSo() async {
        let s = session
        server.fail("GET", "/api/calendar/events/gone", status: 404, "no such event")
        let host = AgendaHost(EventEditor(mode: .edit(id: "gone", calendar: "fake")), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Could not open this event"))
        #expect(host.shows("no such event"))
        #expect(server.requests("GET", "/api/calendar/events/gone").first?.query == ["calendar": "fake"])
    }

    @Test func anInvitationOpensReadOnlyInTheEditor() async {
        let s = session
        server.on("GET", "/api/calendar/events/inv1", json: F.invitation)
        let host = AgendaHost(EventEditor(mode: .edit(id: "inv1", calendar: nil)), session: s)
        defer { host.close() }
        #expect(await host.waitFor("An invitation from boss@example.com"))
        #expect(!host.shows("Save"))
    }

    @Test func aNewEventFromTheBoardIsSeededAndSaved() async throws {
        let s = session
        await basics(s.api)
        server.on("POST", "/api/calendar/events", json: F.timed)
        server.on("GET", "/api/control/pending", json: ["pending": []])
        var saved = 0
        let day = DateComponents(calendar: .current, year: 2030, month: 1, day: 15, hour: 9).date!
        try await withDefaults(["editorTitle": "ios-test stub", "editorRepeat": "monthly", "editorAutoSave": true]) {
            let host = AgendaHost(EventEditor(mode: .create(day: day, leader: "ruby,lily"), onSaved: { saved += 1 }), session: s)
            defer { host.close() }
            #expect(await host.waitFor("New event"))
            for _ in 0..<20 where saved == 0 { await host.settle(.milliseconds(150)) }
            #expect(saved == 1)
            let sent = try #require(server.requests("POST", "/api/calendar/events").first)
            #expect(sent.json["title"] as? String == "ios-test stub")
            #expect((sent.json["start"] as? String)?.hasPrefix("2030-01-15T") == true)
            #expect(sent.json["recurrence"] as? String == "monthly", "the menu's word, for the server to anchor")
            #expect(sent.json["calendar_id"] as? String == "fake")
            #expect(sent.json["attendees"] as? [String] == ["grandma@example.com", "work@example.com"])
            #expect(sent.json["leader"] as? String == "ruby,lily")
        }
    }

    @Test func aNewEventShowsTheCalendarsAndTheUsualInvitees() async throws {
        let s = session
        await basics(s.api)
        let host = AgendaHost(EventEditor(mode: .create(day: .now), initial: nil, day: "2030-01-15", onSaved: {}), session: s)
        defer { host.close() }
        #expect(await host.waitFor("grandma@example.com"))
        #expect(host.shows("work@example.com"))
        #expect(host.shows("Calendar"), "two writable calendars: a choice")
        #expect(host.shows("Prefilled with the household"))
        #expect(host.shows("Everyone") && host.shows("Ruby"))
        // Nothing typed: it asks for a title.
        await host.press("Add")
        #expect(await host.waitFor("Give it a title."))
        #expect(server.requests("POST", "/api/calendar/events").isEmpty)
    }

    @Test func aSaveTheServerRefusesSaysWhy() async throws {
        let s = session
        await basics(s.api)
        server.fail("PATCH", "/api/calendar/events/b4fb50149034", status: 400, "ana@example is not an email address")
        let ev = try F.event(F.allDay)
        try await withDefaults(["editorAutoSave": true, "editorAllDay": true]) {
            let host = AgendaHost(EventEditor(mode: .edit(id: ev.id, calendar: ev.calendarId), initial: ev, day: nil, onSaved: {}),
                                  session: s)
            defer { host.close() }
            #expect(await host.waitFor("ana@example is not an email address"))
            let sent = try #require(server.requests("PATCH", "/api/calendar/events/b4fb50149034").first)
            #expect(sent.query == ["calendar": "fake"])
            #expect(sent.json["start"] as? String == "2026-11-05" && sent.json["end"] as? String == "2026-11-07")
            #expect(host.shows("Everyone here gets a Google Calendar invitation."))
        }
    }

    @Test func aKeptRuleIsShownAndTheEventDeletedFromTheEditor() async throws {
        let s = session
        await basics(s.api)
        server.on("DELETE", "/api/calendar/events/c1", json: ["ok": true, "guest_told": false])
        server.on("GET", "/api/control/pending", json: ["pending": []])
        let ev = try F.event(["id": "c1", "title": "Course", "start": "2026-11-03T09:00:00-05:00",
                              "end": "2026-11-03T10:00:00-05:00", "calendar_id": "fake",
                              "recurrence": ["RRULE:FREQ=DAILY;COUNT=3"]])
        var saved = 0
        let host = AgendaHost(EventEditor(mode: .edit(id: "c1", calendar: nil), initial: ev, day: nil, onSaved: { saved += 1 }),
                              session: s)
        defer { host.close() }
        #expect(await host.waitFor("Edit event"))
        #expect(host.shows("Every day, 3 times (kept)"))
        #expect(host.shows("Changing this changes every occurrence, past and future."))
        await host.press("Delete event")
        #expect(await host.waitFor("Delete for real"))
        host.close()
        // Deleted, as the editor's own Delete does it.
        try await withDefaults(["editorAutoDelete": true]) {
            let again = AgendaHost(EventEditor(mode: .edit(id: "c1", calendar: nil), initial: ev, day: nil, onSaved: { saved += 1 }),
                                   session: s)
            defer { again.close() }
            for _ in 0..<20 where saved == 0 { await again.settle(.milliseconds(150)) }
        }
        #expect(saved == 1)
        #expect(server.requests("DELETE", "/api/calendar/events/c1").first?.query == ["calendar": "fake"])
    }

    @Test func aDeleteFromTheEditorTheServerRefusesSaysWhy() async throws {
        let s = session
        server.fail("DELETE", "/api/calendar/events/b4fb50149034", status: 404, "no such event")
        let ev = try F.event(F.allDay)
        try await withDefaults(["editorAutoDelete": true]) {
            let host = AgendaHost(EventEditor(mode: .edit(id: ev.id, calendar: nil), initial: ev, day: nil, onSaved: {}), session: s)
            defer { host.close() }
            #expect(await host.waitFor("no such event"))
        }
    }

    // MARK: Month and Upcoming

    @Test func aMonthThatWillNotLoadSaysSoAndTriesAgain() async throws {
        let s = session
        server.fail("GET", "/api/calendar/events", status: 503, "The calendar did not answer.")
        var selected = "2031-05-14"
        let binding = Binding(get: { selected }, set: { selected = $0 })
        let actions = AgendaActions(open: { _ in }, edit: { _ in }, delete: { _ in }, create: { _ in })
        let host = AgendaHost(AgendaMonth(clock: F.newYork, selected: binding, actions: actions, notice: "Could not delete that."),
                              session: s)
        defer { host.close() }
        #expect(await host.waitFor("The calendar did not answer."))
        #expect(host.shows("Could not delete that."))
        let before = server.requests("GET", "/api/calendar/events").count
        server.on("GET", "/api/calendar/events", json: ["events": [F.allDay]])
        await host.press("Try again")
        for _ in 0..<20 where server.requests("GET", "/api/calendar/events").count == before { await host.settle(.milliseconds(150)) }
        #expect(server.requests("GET", "/api/calendar/events").count > before)
        #expect(await host.waitFor("Nothing on Wednesday."))
    }

    @Test func upcomingThatWillNotLoadSaysSo() async throws {
        let s = session
        server.fail("GET", "/api/calendar/events", status: 503, "The calendar is down.")
        var selected = "2031-05-14"
        let binding = Binding(get: { selected }, set: { selected = $0 })
        var created: [String] = []
        let actions = AgendaActions(open: { _ in }, edit: { _ in }, delete: { _ in }, create: { created.append($0) })
        let host = AgendaHost(AgendaUpcoming(clock: F.newYork, selected: binding, actions: actions, notice: "Could not delete that."),
                              session: s)
        defer { host.close() }
        #expect(await host.waitFor("The calendar is down."))
        #expect(host.shows("Could not delete that."))
        // Back up: a day picked in the month shows today here, with nothing on it.
        server.on("GET", "/api/calendar/events", json: ["events": []])
        await AgendaData.shared.loadUpcoming(from: F.newYork.today(), days: 14, clock: F.newYork, api: s.api)
        #expect(await host.waitFor("Nothing on today."))
        #expect(host.shows("A quiet week ahead."))
        await host.press("Add something")
        #expect(created == [F.newYork.today()])
    }
}
