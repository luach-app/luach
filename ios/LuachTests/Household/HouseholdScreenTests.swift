import Foundation
import SwiftUI
import Testing
import UIKit
@testable import Luach

/// The Household screens drawn in a window over a stub luach, in states dev cannot show:
/// bookings to cancel, a calendar that went away, Zoom without credentials, values no menu
/// offers, feeds that failed, and a server that does not answer. Each screen must load what
/// it needs and draw without tripping over any of them; the UI tests do the tapping.
@MainActor
@Suite(.serialized, .timeLimit(.minutes(2)))
struct HouseholdScreenTests {
    typealias H = HouseholdArea
    typealias F = HouseholdFixtures
    let server = StubServer()

    /// Views only build their accessibility tree for a client that asks; this turns the
    /// runtime on in the test process (what VoiceOver or XCUITest would do), so the labels
    /// a screen drew can be read back.
    /// Automation mode (the KIF approach, as AgendaScreenTests does) is what makes the tree
    /// exist whatever ran before on the simulator; app accessibility is switched on too.
    private static let accessibilityOn: Bool = {
        guard let lib = dlopen("/usr/lib/libAccessibility.dylib", RTLD_NOW) else { return false }
        var on = false
        if let sym = dlsym(lib, "_AXSSetAutomationEnabled") {
            typealias SetAutomation = @convention(c) (Int32) -> Void
            unsafeBitCast(sym, to: SetAutomation.self)(1)
            on = true
        }
        if let sym = dlsym(lib, "_AXSApplicationAccessibilitySetEnabled") {
            typealias SetEnabled = @convention(c) (Bool) -> Void
            unsafeBitCast(sym, to: SetEnabled.self)(true)
            on = true
        }
        return on
    }()

    private func session() async -> AppSession {
        #expect(Self.accessibilityOn, "libAccessibility could not be switched on: labels cannot be read")
        server.on("GET", "/api/auth/me", json: F.member)
        let s = AppSession(api: server.api)
        await s.restore()
        return s
    }

    /// Shows the screen in a tall window (so every row of the form is drawn), until `done`;
    /// returns every label and value it put on screen, as VoiceOver would read them.
    @discardableResult
    private func show(_ view: some View, until done: @escaping () -> Bool) async throws -> Set<String> {
        let s = await session()
        // The test host's scene connects shortly after launch.
        var scene: UIWindowScene?
        for _ in 0..<100 {
            scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
            if scene != nil { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        let frame = CGRect(x: 0, y: 0, width: 402, height: 5000)
        let window = scene.map(UIWindow.init(windowScene:)) ?? UIWindow(frame: frame)
        window.frame = frame
        window.rootViewController = UIHostingController(rootView: NavigationStack { view }.environment(s))
        window.isHidden = false
        defer { window.isHidden = true; window.rootViewController = nil }
        let deadline = Date.now.addingTimeInterval(10)
        while !done() && Date.now < deadline {
            try await Task.sleep(for: .milliseconds(50))
        }
        #expect(done(), "the screen never loaded what it needed")
        // Let the loaded state draw.
        window.layoutIfNeeded()
        try await Task.sleep(for: .milliseconds(300))
        window.layoutIfNeeded()
        return Self.labels(window)
    }

    private static func labels(_ root: NSObject) -> Set<String> {
        var out = Set<String>()
        func walk(_ o: NSObject, _ depth: Int) {
            guard depth < 60 else { return }
            if let l = o.accessibilityLabel, !l.isEmpty { out.insert(l) }
            if let v = o.accessibilityValue, !v.isEmpty { out.insert(v) }
            if let els = o.accessibilityElements as? [NSObject] {
                els.forEach { walk($0, depth + 1) }
            } else {
                let n = o.accessibilityElementCount()
                if n != NSNotFound { for i in 0..<n { (o.accessibilityElement(at: i) as? NSObject).map { walk($0, depth + 1) } } }
            }
            (o as? UIView)?.subviews.forEach { walk($0, depth + 1) }
        }
        walk(root, 0)
        return out
    }

    /// Whether some label on screen contains `text`.
    private func shows(_ labels: Set<String>, _ text: String) -> Bool {
        labels.contains { $0.contains(text) }
    }

    private func asked(_ method: String, _ path: String) -> () -> Bool {
        { !server.requests(method, path).isEmpty }
    }

    // MARK: Booking

    @Test func bookingDrawsBookingsAnOddCalendarAndZoomWithoutCredentials() async throws {
        server.on("GET", "/api/booking", json: F.booking([
            "enabled": false, "slot_minutes": 25, "max_per_day": 7, "calendar_id": "gone@example.com",
            "conferencing": "zoom", "zoom_ready": false, "location": "the office", "note": "Bring the forms",
        ]))
        server.on("GET", "/api/booking/upcoming", json: F.upcoming)
        server.on("GET", "/api/household/calendars", json: F.calendars)
        let seen = try await show(BookingView(), until: asked("GET", "/api/household/calendars"))
        #expect(server.requests("GET", "/api/booking").count == 1)
        #expect(shows(seen, "Dana Levi") && shows(seen, "sam@example.com"), "the bookings: \(seen.sorted())")
        #expect(shows(seen, "not live yet"))
        #expect(shows(seen, "Where, if Zoom cannot be reached"))
        #expect(server.requests("GET", "/api/booking/upcoming").count == 1)
    }

    @Test func bookingDrawsWithZoomReadyAndOneCalendar() async throws {
        server.on("GET", "/api/booking", json: F.booking(["zoom_ready": true, "calendar_id": "family@group.calendar.google.com"]))
        server.on("GET", "/api/booking/upcoming", json: ["bookings": []])
        server.on("GET", "/api/household/calendars", json: F.devCalendars)
        try await show(BookingView(), until: asked("GET", "/api/household/calendars"))
    }

    @Test func bookingSaysWhyItCouldNotLoad() async throws {
        server.fail("GET", "/api/booking", status: 500, "the database is not answering")
        let seen = try await show(BookingView(), until: asked("GET", "/api/booking"))
        #expect(shows(seen, "the database is not answering"), "\(seen.sorted())")
        #expect(server.requests("GET", "/api/booking/upcoming").isEmpty, "nothing more is asked once the page fails")
    }

    @Test func bookingStillDrawsWhenItsExtrasFail() async throws {
        server.on("GET", "/api/booking", json: F.booking())
        server.fail("GET", "/api/booking/upcoming", status: 502, "the calendar could not be reached")
        server.fail("GET", "/api/household/calendars", status: 403, "only the owner")
        try await show(BookingView(), until: asked("GET", "/api/household/calendars"))
    }

    // MARK: Household

    @Test func householdDrawsEveryCalendarItsDefaultAndInvitees() async throws {
        server.on("GET", "/api/household/calendars", json: F.calendars)
        let seen = try await show(HouseholdView(), until: asked("GET", "/api/household/calendars"))
        #expect(shows(seen, "Use Holidays") && shows(seen, "Use luach (local)"), "\(seen.sorted())")
        #expect(shows(seen, "grandma@example.com"))
    }

    @Test func householdNamesADefaultItCannotOffer() async throws {
        server.on("GET", "/api/household/calendars", json: F.devCalendars)
        try await show(HouseholdView(), until: asked("GET", "/api/household/calendars"))
    }

    @Test func householdWithNoDefaultSaysNone() async throws {
        var json = F.devCalendars
        json["default_calendar"] = ""
        json["available"] = []
        server.on("GET", "/api/household/calendars", json: json)
        try await show(HouseholdView(), until: asked("GET", "/api/household/calendars"))
    }

    @Test func householdSaysWhyItCouldNotLoad() async throws {
        server.fail("GET", "/api/household/calendars", status: 502, "the calendar could not be reached")
        let seen = try await show(HouseholdView(), until: asked("GET", "/api/household/calendars"))
        #expect(shows(seen, "the calendar could not be reached") && shows(seen, "Try again"), "\(seen.sorted())")
    }

    // MARK: Busy calendars

    @Test func busyDrawsAGoodFeedAndOneThatFailed() async throws {
        server.on("GET", "/api/busy", json: ["sources": [
            F.source(),
            F.source(id: 3, name: "Old job", error: "403 Forbidden", blocks: nil, fetched: NSNull()),
        ]])
        let seen = try await show(BusyCalendarsView(), until: asked("GET", "/api/busy"))
        #expect(shows(seen, "Old job") && shows(seen, "403 Forbidden") && shows(seen, "could not read"), "\(seen.sorted())")
        #expect(shows(seen, "4 busy") && shows(seen, "not read yet"))
    }

    @Test func busyWithNoFeedsSaysSo() async throws {
        server.on("GET", "/api/busy", json: ["sources": []])
        let seen = try await show(BusyCalendarsView(), until: asked("GET", "/api/busy"))
        #expect(shows(seen, "No work calendar yet."), "\(seen.sorted())")
    }

    @Test func busySaysWhyItCouldNotLoad() async throws {
        server.fail("GET", "/api/busy", status: 500, "the database is not answering")
        try await show(BusyCalendarsView(), until: asked("GET", "/api/busy"))
    }

    // MARK: Reminders

    @Test func remindersKeepValuesTheMenusDoNotOffer() async throws {
        server.on("GET", "/api/reminders", json: [
            "lead_minutes": 45, "evening_hour": 23, "weekly_day": -1, "weekly_hour": 7, "by_email": true,
        ])
        let seen = try await show(RemindersView(), until: asked("GET", "/api/reminders"))
        #expect(shows(seen, "45 minutes before") && shows(seen, "23:00"), "\(seen.sorted())")
    }

    @Test func remindersSayWhyTheyCouldNotLoad() async throws {
        server.fail("GET", "/api/reminders", status: 500, "the database is not answering")
        try await show(RemindersView(), until: asked("GET", "/api/reminders"))
    }
}

/// A screen held in a window so a test can press its buttons and type into its fields, the
/// way VoiceOver does (`accessibilityActivate`), and read back what it shows.
@MainActor
final class HouseholdHost {
    let window: UIWindow

    init(_ view: some View, session: AppSession) async {
        HouseholdHost.switchOnAccessibility()
        var scene: UIWindowScene?
        for _ in 0..<100 {
            scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
            if scene != nil { break }
            try? await Task.sleep(for: .milliseconds(50))
        }
        let frame = CGRect(x: 0, y: 0, width: 402, height: 3000)
        window = scene.map(UIWindow.init(windowScene:)) ?? UIWindow(frame: frame)
        window.frame = frame
        window.rootViewController = UIHostingController(rootView: NavigationStack { view }.environment(session))
        window.isHidden = false
    }

    private static func switchOnAccessibility() {
        guard let lib = dlopen("/usr/lib/libAccessibility.dylib", RTLD_NOW) else { return }
        if let sym = dlsym(lib, "_AXSSetAutomationEnabled") {
            typealias SetAutomation = @convention(c) (Int32) -> Void
            unsafeBitCast(sym, to: SetAutomation.self)(1)
        }
    }

    func close() {
        window.endEditing(true)
        window.isHidden = true
        window.rootViewController = nil
    }

    func settle(_ time: Duration = .milliseconds(250)) async {
        try? await Task.sleep(for: time)
        window.layoutIfNeeded()
        try? await Task.sleep(for: .milliseconds(50))
    }

    var elements: [NSObject] {
        var found: [NSObject] = []
        func walk(_ node: NSObject, _ depth: Int) {
            guard depth < 60, !node.accessibilityElementsHidden else { return }
            // A row the form took away can linger as a hidden cell kept for reuse.
            if let view = node as? UIView, view.isHidden || view.alpha < 0.01 { return }
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
            for child in children { if let child = child as? NSObject { walk(child, depth + 1) } }
        }
        walk(window, 0)
        return found
    }

    func shows(_ text: String) -> Bool {
        elements.contains { ($0.accessibilityLabel ?? "").contains(text) || ($0.accessibilityValue ?? "").contains(text) }
    }

    func waitFor(_ text: String, seconds: Double = 5) async -> Bool {
        let end = Date.now.addingTimeInterval(seconds)
        while Date.now < end {
            if shows(text) { return true }
            await settle(.milliseconds(100))
        }
        return shows(text)
    }

    func waitGone(_ text: String, seconds: Double = 5) async -> Bool {
        let end = Date.now.addingTimeInterval(seconds)
        while Date.now < end {
            if !shows(text) { return true }
            await settle(.milliseconds(100))
        }
        return !shows(text)
    }

    /// Whether the element named `label` is there and can be used (not dimmed).
    func enabled(_ label: String) -> Bool? {
        guard let e = elements.last(where: { $0.accessibilityLabel == label }) else { return nil }
        return !e.accessibilityTraits.contains(.notEnabled)
    }

    @discardableResult
    func press(_ label: String) async -> Bool {
        guard let target = elements.last(where: { $0.accessibilityLabel == label }) else { return false }
        let pressed = target.accessibilityActivate()
        await settle()
        return pressed
    }

    /// The text fields on screen, in the order they are laid out.
    var textFields: [UITextField] {
        var out: [UITextField] = []
        func walk(_ v: UIView) {
            if let f = v as? UITextField { out.append(f) }
            v.subviews.forEach(walk)
        }
        walk(window)
        return out
    }

    /// Types into the field whose placeholder is `placeholder`, as the keyboard would.
    @discardableResult
    func type(_ text: String, into placeholder: String) async -> Bool {
        guard let field = textFields.first(where: { $0.placeholder == placeholder }) else { return false }
        field.becomeFirstResponder()
        field.insertText(text)
        await settle()
        return true
    }

    func text(of placeholder: String) -> String? {
        textFields.first { $0.placeholder == placeholder }?.text
    }
}

/// Household's Save, pressed on a stub luach: the one write the dev tests may never make.
@MainActor
@Suite(.serialized, .timeLimit(.minutes(2)))
struct HouseholdSaveTests {
    typealias F = HouseholdFixtures
    let server = StubServer()

    private func host() async -> HouseholdHost {
        server.on("GET", "/api/auth/me", json: F.member)
        let s = AppSession(api: server.api)
        await s.restore()
        return await HouseholdHost(HouseholdView(), session: s)
    }

    /// The household as saved: what the GET answers before and after the PATCH.
    private func serve(before: [String: Any], after: [String: Any]? = nil) {
        let path = "/api/household/calendars"
        server.on("GET", path) { [weak server] _ in
            let saved = !(server?.requests("PATCH", "/api/household").isEmpty ?? true)
            return .init(body: F.data(saved ? (after ?? before) : before))
        }
    }

    @Test func savingSendsTheTicksAndATypedAddressThenSaysSaved() async throws {
        var after = F.calendars
        after["calendars"] = (F.calendars["calendars"] as! [String]) + ["local"]
        after["default_attendees"] = ["grandma@example.com", "uncle@example.com"]
        serve(before: F.calendars, after: after)
        server.on("PATCH", "/api/household") { req in
            // Slow enough for the screen to show it is working.
            Thread.sleep(forTimeInterval: 0.6)
            return .init(body: req.body)
        }
        let h = await host()
        defer { h.close() }
        #expect(await h.waitFor("Use luach (local)"))
        #expect(h.enabled("Save") == false, "nothing to save yet")

        #expect(await h.press("Use luach (local)"))
        #expect(await h.type("Uncle@Example.com", into: "name@example.com"))
        #expect(h.enabled("Save") == true)
        #expect(await h.press("Save"))

        let deadline = Date.now.addingTimeInterval(5)
        while server.requests("PATCH", "/api/household").isEmpty && Date.now < deadline { await h.settle(.milliseconds(50)) }
        let sent = try #require(server.requests("PATCH", "/api/household").first)
        #expect(sent.json["calendars"] as? [String] == after["calendars"] as? [String])
        #expect(sent.json["default_calendar"] as? String == "family@group.calendar.google.com")
        #expect(sent.json["default_attendees"] as? [String] == ["grandma@example.com", "uncle@example.com"],
                "the address still in the box is saved with the rest")

        #expect(await h.waitFor("Saved."))
        #expect(server.requests("GET", "/api/household/calendars").count >= 2, "read again after saving")
        #expect(h.text(of: "name@example.com")?.isEmpty ?? true, "the typed address is cleared")
        #expect(h.shows("uncle@example.com"))
        #expect(h.enabled("Save") == false)

        // A change after saving takes "Saved." away.
        #expect(await h.press("Use luach (local)"))
        #expect(h.enabled("Save") == true, "unticked again: a change")
        #expect(await h.waitGone("Saved."))
    }

    @Test func untickingEveryCalendarIsRefusedBeforeAnythingIsSent() async throws {
        let one: [String: Any] = [
            "available": [["id": "local", "name": "luach (local)", "color": "#f4b942", "primary": true,
                           "writable": true, "enabled": true, "default": true]],
            "calendars": ["local"], "default_calendar": "local", "default_attendees": [],
        ]
        serve(before: one)
        let h = await host()
        defer { h.close() }
        #expect(await h.waitFor("Use luach (local)"))
        #expect(await h.press("Use luach (local)"))
        #expect(await h.press("Save"))
        #expect(await h.waitFor("Keep at least one calendar."))
        #expect(server.requests("PATCH", "/api/household").isEmpty)
    }

    @Test func theServersRefusalIsShownAndTheEditsKept() async throws {
        serve(before: F.calendars)
        server.fail("PATCH", "/api/household", status: 400, "a calendar the credential cannot see: local")
        let h = await host()
        defer { h.close() }
        #expect(await h.waitFor("Use luach (local)"))
        #expect(await h.press("Use luach (local)"))
        #expect(await h.press("Save"))
        #expect(await h.waitFor("a calendar the credential cannot see: local"))
        #expect(server.requests("GET", "/api/household/calendars").count == 1, "nothing re-read after a refusal")
        #expect(h.enabled("Save") == true, "the change is still there to try again")
    }

    @Test func aBadAddressIsSaidSoAndAGoodOneAdded() async throws {
        serve(before: F.calendars)
        let h = await host()
        defer { h.close() }
        #expect(await h.waitFor("Use luach (local)"))
        #expect(await h.type("not an address", into: "name@example.com"))
        #expect(await h.press("Add"))
        #expect(await h.waitFor("That is not an email address."))
        #expect(h.enabled("Save") == false)
        h.textFields.first { $0.placeholder == "name@example.com" }?.text = ""
        #expect(await h.type("cousin@example.com", into: "name@example.com"))
        #expect(await h.press("Add"))
        #expect(await h.waitFor("cousin@example.com"))
        #expect(server.requests("PATCH", "/api/household").isEmpty, "Add alone saves nothing")
    }

    @Test func aFailedLoadCanBeTriedAgain() async throws {
        server.fail("GET", "/api/household/calendars", status: 502, "the calendar could not be reached")
        let h = await host()
        defer { h.close() }
        #expect(await h.waitFor("the calendar could not be reached"))
        serve(before: F.calendars)
        #expect(await h.press("Try again"))
        #expect(await h.waitFor("Use luach (local)"))
        #expect(server.requests("GET", "/api/household/calendars").count == 2)
    }
}
