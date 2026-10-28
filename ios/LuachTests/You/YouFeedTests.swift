import Foundation
import SwiftUI
import Testing
@testable import Luach

/// Settings › Calendar feed against a stub luach: off until turned on, the link shown once,
/// Add to Calendar opening its webcal:// form, reset and turn off asked first. Dev may not have
/// the routes yet, so nothing here needs it.
@MainActor
@Suite(.serialized, .timeLimit(.minutes(3)))
struct YouFeedTests {
    let server = StubServer()

    static let token = "k3Wq0pZ8mJ1xV7bN2cR5tY9uI4oP6aS8dF0gH2jK4lQ"
    static let off: [String: Any] = ["enabled": false, "scope": "household", "created_at": NSNull(), "last_read": NSNull()]
    static func on(_ scope: String = "household", read: Any = NSNull()) -> [String: Any] {
        ["enabled": true, "scope": scope, "created_at": "2026-10-20T12:00:00+00:00", "last_read": read]
    }
    static func link(_ scope: String = "household") -> [String: Any] {
        on(scope).merging([
            "url": "https://luach.test/feed/\(token).ics",
            "webcal": "webcal://luach.test/feed/\(token).ics",
        ]) { $1 }
    }

    private func loaded(_ status: [String: Any]) async -> (YouFeedModel, AppSession) {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/feed", json: status)
        let m = YouFeedModel()
        await m.load(session)
        return (m, session)
    }

    // MARK: The model

    @Test func offUntilTurnedOnAndNoLinkFromTheStatus() async {
        let (m, _) = await loaded(Self.off)
        #expect(m.status?.enabled == false && m.link == nil && m.scope == .household && m.error == nil)
        let (on, _) = await loaded(Self.on("mine", read: "2026-10-20T11:00:00+00:00"))
        #expect(on.status?.enabled == true && on.scope == .mine && on.link == nil)
        #expect(on.lastRead != String(localized: "not yet"))
    }

    @Test func turningOnSendsTheChoiceAndKeepsTheLinkOnlyInMemory() async throws {
        let (m, session) = await loaded(Self.off)
        await m.choose(.mine, session)
        #expect(server.requests("PATCH", "/api/feed").isEmpty, "off, a choice is only what Turn on sends")
        server.on("POST", "/api/feed", json: Self.link("mine"))
        await m.turnOn(session)
        let sent = try #require(server.requests("POST", "/api/feed").first)
        #expect(sent.json as? [String: String] == ["scope": "mine"])
        #expect(m.link?.webcal == "webcal://luach.test/feed/\(Self.token).ics")
        #expect(m.status?.enabled == true && m.scope == .mine && !m.busy)
        // Shown once: the next load has no link to show, and the screen does not keep one.
        server.on("GET", "/api/feed", json: Self.on("mine"))
        let again = YouFeedModel()
        await again.load(session)
        #expect(again.link == nil)
    }

    @Test func copyingPutsTheLinkOnThePasteboard() async {
        let (m, session) = await loaded(Self.off)
        var pasted: [String] = []
        m.pasteboard = { pasted.append($0) }
        m.copy()
        #expect(pasted.isEmpty && !m.copied, "nothing to copy before there is a link")
        server.on("POST", "/api/feed", json: Self.link())
        await m.turnOn(session)
        m.copy()
        #expect(pasted == ["https://luach.test/feed/\(Self.token).ics"] && m.copied)
    }

    @Test func aNewLinkAndOffBothForgetTheOldOne() async {
        let (m, session) = await loaded(Self.on())
        var reset = Self.link()
        reset["url"] = "https://luach.test/feed/new.ics"
        server.on("POST", "/api/feed/reset", json: reset)
        await m.reset(session)
        #expect(m.link?.url == "https://luach.test/feed/new.ics")
        server.on("DELETE", "/api/feed", json: Self.off)
        await m.turnOff(session)
        #expect(m.link == nil && m.status?.enabled == false && !m.copied)
    }

    @Test func aChangeOfScopeOnTheSameLinkAndBackWhenRefused() async {
        let (m, session) = await loaded(Self.on())
        server.on("PATCH", "/api/feed", json: Self.on("mine"))
        await m.choose(.mine, session)
        #expect(m.scope == .mine && server.requests("PATCH", "/api/feed").count == 1)
        server.fail("PATCH", "/api/feed", status: 404, "your calendar feed is off")
        await m.choose(.household, session)
        #expect(m.scope == .mine && m.error == "your calendar feed is off")
    }

    @Test func refusalsSayWhy() async {
        let (m, session) = await loaded(Self.off)
        server.fail("POST", "/api/feed", status: 409, "your calendar feed is already on; reset it for a new link")
        await m.turnOn(session)
        #expect(m.error == "your calendar feed is already on; reset it for a new link" && m.link == nil)
        let session2 = await YouFixtures.session(server)
        server.fail("GET", "/api/feed", status: 500, "the server is having a moment")
        let broken = YouFeedModel()
        await broken.load(session2)
        #expect(broken.status == nil && broken.error == "the server is having a moment")
    }

    // MARK: The screen

    @Test func theScreenOffSaysWhatItHoldsAndTurnsOn() async {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/feed", json: Self.off)
        server.on("POST", "/api/feed", json: Self.link())
        let host = YouHost(CalendarFeedView(), session: session)
        defer { host.close() }
        #expect(await host.waitFor("Turn on"), "\(host.labels)")
        #expect(host.shows("Never who is invited, nothing waiting for approval"))
        #expect(host.shows("Anyone with the link can read the calendar"))
        #expect(!host.labels.contains("Reset link"), "no Reset button while it is off (the footer names it)")
        #expect(await host.press("Turn on"))
        #expect(await host.waitFor("Add to Calendar"), "\(host.labels)")
        #expect(host.shows("https://luach.test/feed/\(Self.token).ics"))
        #expect(host.labels.contains("Copy link") && host.labels.contains("Reset link") && host.labels.contains("Turn off"))
        #expect(host.shows("this is the one time it is shown"))
    }

    @Test func addToCalendarOpensTheWebcalLink() async {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/feed", json: Self.off)
        server.on("POST", "/api/feed", json: Self.link())
        var opened: [URL] = []
        let view = CalendarFeedView().environment(\.openURL, OpenURLAction { url in
            opened.append(url)
            return .handled
        })
        let host = YouHost(view, session: session)
        defer { host.close() }
        #expect(await host.press("Turn on"))
        #expect(await host.press("Add to Calendar"))
        #expect(opened == [URL(string: "webcal://luach.test/feed/\(Self.token).ics")!])
    }

    @Test func onItShowsNoLinkAndAsksBeforeResettingOrTurningOff() async throws {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/feed", json: Self.on())
        server.on("POST", "/api/feed/reset", json: Self.link())
        server.on("DELETE", "/api/feed", json: Self.off)
        let host = YouHost(CalendarFeedView(), session: session)
        defer { host.close() }
        #expect(await host.waitFor("Last read by a calendar"), "\(host.labels)")
        #expect(!host.shows("luach.test/feed"))
        #expect(await host.press("Reset link"))
        #expect(host.dialog != nil && server.requests("POST", "/api/feed/reset").isEmpty)
        #expect(await host.choose("Keep it"))
        #expect(server.requests("POST", "/api/feed/reset").isEmpty)
        #expect(await host.press("Reset link"))
        #expect(await host.choose("Reset link"))
        #expect(await host.waitFor("Add to Calendar"))
        #expect(server.requests("POST", "/api/feed/reset").count == 1)
        #expect(await host.press("Turn off"))
        #expect(await host.choose("Turn off"))
        #expect(await host.waitFor("Turn on"))
        #expect(server.requests("DELETE", "/api/feed").count == 1)
    }

    @Test func itIsSaidInSpanishAndHebrew() throws {
        for (lang, words) in [("es", "Calendario suscrito"), ("he", "הזנת יומן")] {
            let path = try #require(Bundle(for: AppSession.self).path(forResource: lang, ofType: "lproj"))
            let bundle = try #require(Bundle(path: path))
            #expect(bundle.localizedString(forKey: "Calendar feed", value: nil, table: nil) == words)
            #expect(bundle.localizedString(forKey: "Add to Calendar", value: nil, table: nil) != "Add to Calendar")
        }
    }
}
