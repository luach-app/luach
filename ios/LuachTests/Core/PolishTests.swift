import Foundation
import SwiftUI
import Testing
import UIKit
import UserNotifications
@testable import Luach

/// Sign-in's household line and "Forgot your password?", https only, the caches that must not
/// cross households, approvals' who/door/when, deleting an account, unsaved edits, and the ink
/// on the accent.
@MainActor
@Suite(.serialized, .timeLimit(.minutes(3))) // UserDefaults, the cookie jar and AgendaData.shared are shared
struct PolishTests {
    let luach = StubServer()
    private let me: [String: Any] = ["id": 1, "username": "robin", "display_name": "Robin", "is_owner": true,
                                     "timezone": "America/New_York", "language": "en"]

    init() {
        AgendaData.shared.forget()
        Conversation.forget()
    }

    private func fresh() -> AppSession {
        AppSession(api: API(server: URL(string: "https://luach.invalid")!, protocolClasses: [StubProtocol.self]),
                   hasServer: false, reminders: LocalReminders(center: FakeNoticeCenter()))
    }

    private func signedIn(_ center: FakeNoticeCenter? = nil, owner: Bool = true) async -> AppSession {
        let center = center ?? FakeNoticeCenter()
        var who = me
        who["is_owner"] = owner
        luach.on("GET", "/api/auth/me", json: who)
        let s = AppSession(api: luach.api, reminders: LocalReminders(center: center))
        await s.restore()
        return s
    }

    private func withSavedServer(_ body: () async throws -> Void) async rethrows {
        let before = UserDefaults.standard.string(forKey: "server")
        defer { UserDefaults.standard.set(before, forKey: "server") }
        try await body()
    }

    // MARK: The sign-in screen

    @Test func theStatusSaysTheHouseholdAndTheMail() async throws {
        luach.on("GET", "/api/auth/status", json: [
            "users_exist": true, "household": "  Rivera ",
            "mail": ["enabled": false, "limitation": "This luach does not send email.", "offline_reset": "run this"],
        ])
        let session = fresh()
        try await session.connect(to: luach.host)
        #expect(session.status == API.ServerStatus(
            usersExist: true, household: "Rivera",
            mail: .init(enabled: false, limitation: "This luach does not send email.", offlineReset: "run this")))
    }

    @Test func anOlderLuachSaysNeither() async throws {
        luach.on("GET", "/api/auth/status", json: ["users_exist": true, "mail": "odd"])
        let session = fresh()
        try await session.connect(to: luach.host)
        #expect(session.status?.household == "" && session.status?.mail == .init())
        #expect(LoginView.householdLine(nil) == "The household calendar")
        #expect(LoginView.householdLine(" ") == "The household calendar")
        #expect(LoginView.householdLine("Rivera") == "The Rivera household calendar")
    }

    @Test func theHouseholdIsNamedOnceTheAddressIsChecked() async {
        luach.on("GET", "/api/auth/status", json: ["users_exist": true, "household": "Rivera"])
        let session = fresh()
        let host = ScreenHost(LoginView(), session: session, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Your luach's address"))
        #expect(host.shows("The household calendar") && !host.shows("Rivera"), "not before the address is checked")
        await host.type(luach.host, into: "luach.example.com")
        await host.press("Continue")
        #expect(await host.waitFor("The Rivera household calendar"))
    }

    @Test func aRememberedLuachIsAskedItsName() async {
        luach.on("GET", "/api/auth/status", json: ["users_exist": true, "household": "Rivera"])
        let session = AppSession(api: luach.api, reminders: LocalReminders(center: FakeNoticeCenter()))
        let host = ScreenHost(LoginView(), session: session, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("The Rivera household calendar"))
        #expect(host.shows("Forgot your password?"))
    }

    @Test func forgotSendsTheLinkAndSaysSoEitherWay() async throws {
        luach.on("GET", "/api/auth/status", json: [
            "users_exist": true, "mail": ["enabled": true, "limitation": "LUACH_APP_URL is not set."],
        ])
        luach.on("POST", "/api/auth/forgot", json: ["ok": true])
        let session = AppSession(api: luach.api, reminders: LocalReminders(center: FakeNoticeCenter()))
        let host = ScreenHost(LoginView(), session: session, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Forgot your password?"))
        for _ in 0..<20 where session.status == nil { await host.settle(.milliseconds(100)) }
        await host.press("Forgot your password?")
        #expect(await host.waitFor("We will email you a reset link"))
        #expect(host.shows("LUACH_APP_URL is not set."), "what mail cannot do here, as the web says it")
        #expect(await host.type(" robin@example.com ", into: "Email"))
        await host.press("Send the link")
        #expect(await host.waitFor("a reset link is on its way"))
        #expect(host.shows("then sign in here with it"))
        let sent = try #require(luach.requests("POST", "/api/auth/forgot").first)
        #expect(sent.json["email"] as? String == "robin@example.com")
    }

    @Test func forgotSaysWhyItCouldNotSend() async {
        luach.on("GET", "/api/auth/status", json: ["users_exist": true])
        luach.fail("POST", "/api/auth/forgot", status: 429, "too many attempts; try again later")
        let host = ScreenHost(ForgotPasswordView(mail: nil), session: AppSession(api: luach.api), stack: true)
        defer { host.close() }
        #expect(await host.waitFor("Send the link"))
        await host.type("robin@example.com", into: "Email")
        await host.press("Send the link")
        #expect(await host.waitFor("too many attempts; try again later"))
    }

    @Test func withoutMailItSaysWhatTheOwnerRuns() async {
        let mail = API.ServerStatus.Mail(enabled: false, limitation: "x", offlineReset: "docker compose exec luach python -m luach.passwd <username>")
        let host = ScreenHost(ForgotPasswordView(mail: mail), session: AppSession(api: luach.api), stack: true)
        defer { host.close() }
        #expect(await host.waitFor("This luach does not send email, so a reset link cannot reach you."))
        #expect(host.shows("python -m luach.passwd"))
        #expect(host.field("Email") == nil, "no form promising a link that will not come")
        let unsaid = ScreenHost(ForgotPasswordView(mail: .init(enabled: false)), session: AppSession(api: luach.api), stack: true)
        defer { unsaid.close() }
        #expect(await unsaid.waitFor("python -m luach.passwd <username>"), "an older luach's command, when it names none")
    }

    // MARK: https only

    @Test func nothingIsSentToAPlainHTTPLuach() async {
        let api = API(server: URL(string: "http://\(luach.host)")!, protocolClasses: [StubProtocol.self])
        await #expect(throws: ServerAddress.Problem.notSecure) { try await api.me() }
        await #expect(throws: ServerAddress.Problem.notSecure) { _ = try await api.status(of: URL(string: "http://\(luach.host)")!) }
        await #expect(throws: ServerAddress.Problem.notSecure) { try await api.forgot(email: "a@example.com") }
        #expect(luach.requests.isEmpty)
    }

    @Test func aRedirectToPlainHTTPIsNotFollowed() async {
        let guardian = API.RedirectGuard()
        let task = URLSession.shared.dataTask(with: URL(string: "https://luach.example.com")!)
        let response = HTTPURLResponse(url: URL(string: "https://luach.example.com")!, statusCode: 302, httpVersion: nil, headerFields: nil)!
        var followed: [URL?] = []
        for target in ["http://luach.example.com/api/auth/me", "https://other.example.com/api/auth/me"] {
            guardian.urlSession(.shared, task: task, willPerformHTTPRedirection: response,
                                newRequest: URLRequest(url: URL(string: target)!)) { followed.append($0?.url) }
        }
        #expect(followed == [nil, URL(string: "https://other.example.com/api/auth/me")])
    }

    @Test func aPlainHTTPAddressAnOlderBuildSavedIsForgotten() {
        let defaults = UserDefaults(suiteName: "polish-\(UUID())")!
        let jar = HTTPCookieStorage.shared
        let home = URL(string: "http://192.168.1.20:8000")!
        defaults.set(home.absoluteString, forKey: "server")
        jar.setCookie(HTTPCookie(properties: [.name: "luach_session", .value: "x", .domain: "192.168.1.20", .path: "/"])!)
        #expect(AppSession.savedServer(defaults, cookies: jar) == nil, "asked for again, over https")
        #expect(defaults.string(forKey: "server") == nil)
        #expect(jar.cookies(for: home)?.isEmpty ?? true, "its session goes with it")
        defaults.set("https://luach.example.com", forKey: "server")
        #expect(AppSession.savedServer(defaults, cookies: jar) == URL(string: "https://luach.example.com"))
    }

    // MARK: Nothing of one household shows for the next

    @Test func theAgendaIsKeptPerLuachAndMember() async {
        luach.on("GET", "/api/household/calendars", json: AgendaFixtures.household)
        luach.on("GET", "/api/family", json: AgendaFixtures.family)
        luach.on("GET", "/api/auth/me", json: me)
        let data = AgendaData()
        let robin = Member(id: 1, username: "robin", displayName: nil, email: nil, timezone: nil, language: nil, isOwner: true)
        data.bind(robin, server: URL(string: "https://one.example.com"))
        await data.loadBasics(luach.api)
        #expect(data.basicsLoaded && !data.people.isEmpty)
        data.bind(robin, server: URL(string: "https://one.example.com"))
        #expect(data.basicsLoaded, "the same member of the same luach keeps it")
        data.bind(robin, server: URL(string: "https://two.example.com"))
        #expect(!data.basicsLoaded && data.people.isEmpty && data.household == nil, "member 1 of another luach is someone else")
        await data.loadBasics(luach.api)
        data.forget()
        #expect(!data.basicsLoaded && data.people.isEmpty)
    }

    @Test func whatArrivesAfterASignOutIsDropped() async {
        luach.on("GET", "/api/household/calendars") { _ in
            Thread.sleep(forTimeInterval: 0.4)
            return .init(body: try! JSONSerialization.data(withJSONObject: AgendaFixtures.household))
        }
        luach.on("GET", "/api/calendar/events") { _ in
            Thread.sleep(forTimeInterval: 0.4)
            return .init(body: Data(#"{"events":[]}"#.utf8))
        }
        let data = AgendaData()
        let robin = Member(id: 1, username: "robin", displayName: nil, email: nil, timezone: nil, language: nil, isOwner: true)
        data.bind(robin, server: luach.url)
        let clock = AgendaClock(tz: .gmt, locale: Locale(identifier: "en"))
        async let basics: Void = data.loadBasics(luach.api)
        async let month: Void = data.loadMonth("2026-11", clock: clock, api: luach.api)
        async let upcoming: Void = data.loadUpcoming(from: "2026-11-01", days: 14, clock: clock, api: luach.api)
        try? await Task.sleep(for: .milliseconds(100))
        data.forget()
        _ = await (basics, month, upcoming)
        #expect(data.household == nil && data.months.isEmpty && data.upcoming == nil)
    }

    @Test func signingOutForgetsEverythingThisPhoneKept() async throws {
        let center = FakeNoticeCenter()
        let s = await signedIn(center)
        luach.on("GET", "/api/control/pending", json: ["pending": [["id": "h1", "tool": "x", "summary": "Add", "status": "pending"]]])
        luach.on("POST", "/api/auth/logout", json: ["ok": true])
        await s.pending.refresh()
        try await center.add(UNNotificationRequest(identifier: "luach.event.x", content: .init(), trigger: nil))
        UserDefaults.standard.set("th-1", forKey: "thread")
        luach.on("GET", "/api/household/calendars", json: AgendaFixtures.household)
        AgendaData.shared.bind(s.member, server: s.server)
        await AgendaData.shared.loadBasics(s.api)
        #expect(AgendaData.shared.basicsLoaded)
        await s.logout()
        #expect(s.phase == .signedOut)
        #expect(s.pending.items.isEmpty && center.pending.isEmpty && center.badges.last == 0)
        #expect(UserDefaults.standard.string(forKey: "thread") == nil)
        #expect(!AgendaData.shared.basicsLoaded)
    }

    @Test func aListAskedForBeforeASignOutIsNotShownAfter() async {
        let s = await signedIn()
        luach.on("GET", "/api/control/pending") { _ in
            Thread.sleep(forTimeInterval: 0.4)
            return .init(body: Data(#"{"pending":[{"id":"h1","tool":"x","summary":"Add","status":"pending"}]}"#.utf8))
        }
        async let asked: Void = s.pending.refresh()
        try? await Task.sleep(for: .milliseconds(100))
        s.pending.clear()
        await asked
        #expect(s.pending.items.isEmpty)
    }

    @Test func signingInToAnotherLuachForgetsTheLastOnes() async throws {
        try await withSavedServer {
            UserDefaults.standard.set("https://elsewhere.example.com", forKey: "server")
            UserDefaults.standard.set("th-9", forKey: "thread")
            luach.on("POST", "/api/auth/login", json: me)
            let s = AppSession(api: luach.api, reminders: LocalReminders(center: FakeNoticeCenter()))
            try await s.login(username: "robin", password: "pw")
            #expect(UserDefaults.standard.string(forKey: "thread") == nil, "that conversation was on another luach")
            #expect(UserDefaults.standard.string(forKey: "server") == luach.url.absoluteString)
            UserDefaults.standard.set("th-10", forKey: "thread")
            try await s.login(username: "robin", password: "pw")
            #expect(UserDefaults.standard.string(forKey: "thread") == "th-10", "the same luach keeps it")
        }
    }

    @Test func backgroundRefreshCountsAndSchedules() async throws {
        let center = FakeNoticeCenter()
        luach.on("GET", "/api/auth/me", json: me)
        luach.on("GET", "/api/control/pending", json: ["pending": [
            ["id": "h1", "tool": "x", "summary": "Add", "status": "pending"],
            ["id": "h2", "tool": "x", "summary": "Move", "status": "pending"],
        ]])
        luach.on("GET", "/api/reminders", json: ["lead_minutes": 0, "evening_hour": -1, "weekly_day": -1, "weekly_hour": 18, "by_email": false])
        let s = AppSession(api: luach.api, reminders: LocalReminders(center: center))
        #expect(s.member == nil, "woken in the background before the launch check ran")
        await BackgroundRefresh.run(s)
        #expect(s.member?.username == "robin")
        #expect(s.pending.items.count == 2 && center.badges.last == 2)
        #expect(luach.requests("GET", "/api/reminders").count == 1)
        BackgroundRefresh.schedule(after: 3600)
    }

    @Test func backgroundRefreshSignedOutDoesNothing() async {
        luach.fail("GET", "/api/auth/me", status: 401, "sign in first")
        let s = AppSession(api: luach.api, reminders: LocalReminders(center: FakeNoticeCenter()))
        await s.backgroundRefresh()
        #expect(s.member == nil && luach.requests("GET", "/api/control/pending").isEmpty)
    }

    // MARK: Approvals

    private func hold(door: String = "web", source: [String: Any]? = nil) throws -> PendingAction {
        var row: [String: Any] = ["id": "h1", "tool": "create_event", "summary": "Add Dentist", "status": "pending",
                                  "principal": "ana", "door": door, "created_at": "2026-10-28T18:05:00+00:00"]
        if let source { row["source"] = source }
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return try d.decode(PendingAction.self, from: JSONSerialization.data(withJSONObject: row))
    }

    @Test func whoAskedThroughWhichDoorAndWhen() throws {
        let clock = AgendaClock(tz: TimeZone(identifier: "America/New_York")!, locale: Locale(identifier: "en"))
        let line = PendingRow.meta(try hold(), clock: clock)
        #expect(line.hasPrefix("Asked by ana · in a chat · "), "\(line)")
        #expect(line.contains("2:05") || line.contains("14:05"), "in the member's zone: \(line)")
        #expect(PendingRow.door("email") == "by email")
        #expect(PendingRow.door("email-scan") == "from the email scan")
        #expect(PendingRow.door("whatsapp") == "via whatsapp")
        #expect(PendingRow.door("") == nil)
        let bare = try hold(door: "")
        #expect(PendingRow.meta(bare, clock: clock).hasPrefix("Asked by ana · Wed"), "no door, no words for one")
    }

    @Test func theGmailLinkOnlyForMail() throws {
        let mail = try hold(door: "email-scan", source: ["kind": "email", "id": "18c2f0a9b1", "subject": "Your appointment",
                                                          "from": "clinic@example.com", "when": "Tue 27 Oct"])
        #expect(mail.source?.gmailLink == URL(string: "https://mail.google.com/mail/u/0/#all/18c2f0a9b1"))
        let odd = try hold(source: ["kind": "email", "id": "a/b?c"])
        #expect(odd.source?.gmailLink?.absoluteString == "https://mail.google.com/mail/u/0/#all/a%2Fb%3Fc")
        #expect(try hold(source: ["kind": "email"]).source?.gmailLink == nil)
        #expect(try hold(source: ["kind": "other", "id": "x"]).source?.gmailLink == nil)
    }

    @Test func approvalsShowTheMailAndPollWhileOnScreen() async throws {
        PendingView.pollInterval = .milliseconds(300)
        defer { PendingView.pollInterval = .seconds(30) }
        let s = await signedIn()
        luach.on("GET", "/api/control/pending", json: ["pending": [[
            "id": "h1", "tool": "create_event", "summary": "Add Dentist", "status": "pending", "principal": "robin",
            "door": "email-scan", "created_at": "2026-10-28T18:05:00+00:00",
            "source": ["kind": "email", "id": "18c2", "subject": "Your appointment", "from": "clinic@example.com", "when": "Tue 27 Oct"],
        ]]])
        luach.on("GET", "/api/mail", json: ["connected": false])
        let host = ScreenHost(PendingView(), session: s, stack: false)
        #expect(await host.waitFor("Add Dentist"))
        #expect(host.shows("Asked by robin · from the email scan"))
        #expect(host.shows("From your email · Tue 27 Oct") && host.shows("clinic@example.com"))
        #expect(host.shows("Open in Gmail"))
        let first = luach.requests("GET", "/api/control/pending").count
        try await Task.sleep(for: .milliseconds(1000))
        #expect(luach.requests("GET", "/api/control/pending").count >= first + 2, "asked again while it is on screen")
        host.close()
        try await Task.sleep(for: .milliseconds(400))
        let after = luach.requests("GET", "/api/control/pending").count
        try await Task.sleep(for: .milliseconds(800))
        #expect(luach.requests("GET", "/api/control/pending").count == after, "and not once it is gone")
    }

    @Test func anApprovalChangesTheCalendar() async throws {
        let s = await signedIn()
        luach.on("GET", "/api/control/pending", json: ["pending": []])
        luach.on("POST", "/api/control/pending/h1/approve", json: ["id": "h1", "tool": "x", "summary": "Add", "status": "approved"])
        let before = AgendaData.shared.version
        _ = try await s.pending.decide("h1", approve: true)
        #expect(AgendaData.shared.version == before + 1, "the agenda and the reminders follow")
    }

    // MARK: Deleting an account

    @Test func deletingAnAccountAsksThePasswordThenSignsOut() async throws {
        let center = FakeNoticeCenter()
        let s = await signedIn(center, owner: false)
        luach.on("DELETE", "/api/auth/me", json: ["ok": true])
        try await center.add(UNNotificationRequest(identifier: "luach.event.x", content: .init(), trigger: nil))
        let host = ScreenHost(DeleteAccountView(), session: s)
        defer { host.close() }
        #expect(await host.waitFor("is deleted for good"))
        #expect(host.shows(luach.host))
        #expect(!host.shows("You own this household"))
        #expect(host.enabledButton("Delete my account") == false, "not before the password is typed")
        await host.type("my password", into: "Password")
        await host.press("Delete my account")
        #expect(await host.waitFor("This cannot be undone."))
        #expect(luach.requests("DELETE", "/api/auth/me").isEmpty, "nothing until it is confirmed")
        #expect(await host.choose("Delete my account"))
        for _ in 0..<30 where s.phase != .signedOut { await host.settle(.milliseconds(100)) }
        #expect(s.phase == .signedOut)
        let sent = try #require(luach.requests("DELETE", "/api/auth/me").first)
        #expect(sent.json["password"] as? String == "my password")
        #expect(center.pending.isEmpty, "its reminders do not outlive it")
    }

    @Test func theOwnerHearsTheServersReason() async {
        let s = await signedIn()
        luach.fail("DELETE", "/api/auth/me", status: 409, "you own this household, so your account cannot go while others belong to it")
        let host = ScreenHost(DeleteAccountView(), session: s)
        defer { host.close() }
        #expect(await host.waitFor("You own this household"))
        await host.type("pw", into: "Password")
        await host.press("Delete my account")
        #expect(await host.waitFor("This cannot be undone."))
        #expect(await host.choose("Delete my account"))
        #expect(await host.waitFor("your account cannot go while others belong to it"))
        #expect(s.member != nil, "still signed in")
    }

    @Test func aWrongPasswordDoesNotSignOut() async {
        let s = await signedIn(owner: false)
        luach.fail("DELETE", "/api/auth/me", status: 401, "the password is wrong")
        try? await s.api.deleteAccount(password: "nope")
        #expect(s.member != nil, "a 401 under /api/auth/ is the password, not the session")
    }

    // MARK: Unsaved edits

    @Test func aNewEventWithATitleAsksBeforeCancel() async {
        let s = await signedIn()
        let host = ScreenHost(EventEditor(mode: .create(day: .now)), session: s)
        defer { host.close() }
        #expect(await host.waitFor("New event"))
        await host.press("Cancel")
        #expect(!host.shows("Discard changes?"), "nothing typed: Cancel just closes")
        await host.type("Dentist", into: "Title")
        await host.press("Cancel")
        #expect(await host.waitFor("Discard changes?"))
        #expect(host.shows("What you changed here has not been saved."))
        #expect(await host.choose("Keep editing"))
        #expect(await host.waitGone("Discard changes?"))
        #expect(host.field("Title")?.text == "Dentist")
    }

    @Test func aTaskBeingWrittenAsksBeforeCancel() async throws {
        let s = await signedIn()
        let people = try BoardFixtures.day().people
        let host = ScreenHost(TaskEditor(sheet: .new(person: ""), people: people, canEdit: true, routes: .tasks), session: s, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Add task"))
        await host.press("Cancel")
        #expect(!host.shows("Discard changes?"))
        #expect(await host.press("Lily"), "a person chosen is an edit")
        await host.press("Cancel")
        #expect(await host.waitFor("Discard changes?"))
    }

    @Test func aSettingsFormAsksBeforeBack() async {
        let s = await signedIn()
        let host = ScreenHost(PasswordView(), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Update password"))
        #expect(!host.shows("Back"), "nothing typed: the usual back")
        await host.type("old one", into: "Current password")
        #expect(await host.waitFor("Back"))
        await host.press("Back")
        #expect(await host.waitFor("Discard changes?"))
        #expect(await host.choose("Discard changes"))
        #expect(await host.waitGone("Discard changes?"))
    }

    // MARK: Reminders on this iPhone

    private func serveReminders(lead: Int) {
        luach.on("GET", "/api/reminders", json: ["lead_minutes": lead, "evening_hour": -1, "weekly_day": -1, "weekly_hour": 18, "by_email": false])
        luach.on("GET", "/api/calendar/events", json: ["events": [
            ["id": "far", "title": "Far", "start": "2099-01-01T10:00:00+00:00", "end": "2099-01-01T11:00:00+00:00"],
        ]])
    }

    @Test func remindersOnButNotYetAllowedOfferToAllow() async {
        let center = FakeNoticeCenter(status: .notDetermined)
        let s = await signedIn(center)
        serveReminders(lead: 30)
        let host = ScreenHost(RemindersView(), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Not shown on this iPhone yet."))
        #expect(host.shows("worked out from the calendar each time luach opens"))
        #expect(!host.shows("Sent to each device"), "the old promise is gone")
        #expect(center.asked == 0, "opening the screen asks nothing")
        await host.press("Allow notifications")
        #expect(await host.waitFor("coming up on this iPhone"))
        #expect(center.asked == 1 && center.pending.count == 1)
    }

    @Test func savingWithAReminderOnIsWhenIOSIsAsked() async throws {
        let center = FakeNoticeCenter(status: .notDetermined)
        let s = await signedIn(center)
        serveReminders(lead: 30)
        luach.on("PATCH", "/api/reminders", json: ["lead_minutes": 30, "evening_hour": -1, "weekly_day": -1, "weekly_hour": 18, "by_email": true])
        let host = ScreenHost(RemindersView(), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Email them to me as well"))
        await host.press("Email them to me as well")
        #expect(await host.waitFor("Back"), "an unsaved change guards Back")
        await host.press("Save")
        #expect(await host.waitFor("Saved."))
        #expect(center.asked == 1, "a reminder is on: iOS is asked now")
        #expect(center.pending.count == 1, "and the phone's own follow")
        let sent = try #require(luach.requests("PATCH", "/api/reminders").first)
        #expect(sent.json["by_email"] as? Bool == true)
    }

    @Test func theTabsKeepTheRemindersAndTheBadgeUpToDate() async throws {
        let center = FakeNoticeCenter()
        let s = await signedIn(center)
        serveReminders(lead: 30)
        luach.on("GET", "/api/control/pending", json: ["pending": [["id": "h1", "tool": "x", "summary": "Add", "status": "pending"]]])
        UserDefaults.standard.removeObject(forKey: "screen")
        // A window of the test host is no scene of SwiftUI's: it is told it is in front.
        let host = ScreenHost(MainTabs().environment(\.scenePhase, .active), session: s, stack: false)
        defer { host.close() }
        for _ in 0..<50 where center.pending.isEmpty { await host.settle(.milliseconds(100)) }
        #expect(center.pending.count == 1, "worked out when the app comes forward")
        for _ in 0..<30 where center.badges.last != 1 { await host.settle(.milliseconds(100)) }
        #expect(center.badges.last == 1, "the Approvals count on the icon")
        let asked = luach.requests("GET", "/api/reminders").count
        AgendaData.shared.invalidate()
        for _ in 0..<50 where luach.requests("GET", "/api/reminders").count == asked { await host.settle(.milliseconds(100)) }
        #expect(luach.requests("GET", "/api/reminders").count > asked, "a change to the calendar is followed")
    }

    @Test func remindersOffOfferNothingToAllow() async {
        let s = await signedIn(FakeNoticeCenter(status: .notDetermined))
        serveReminders(lead: 0)
        let host = ScreenHost(RemindersView(), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Not shown on this iPhone yet."))
        #expect(!host.shows("Allow notifications"), "asked when a reminder is turned on, not before")
    }

    @Test func notificationsTurnedOffInIOSSaySo() async {
        let s = await signedIn(FakeNoticeCenter(status: .denied))
        serveReminders(lead: 30)
        let host = ScreenHost(RemindersView(), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Notifications are off for luach on this iPhone."))
        #expect(host.shows("Open iOS Settings"))
    }

    @Test func allowedWithNothingComingSaysItIsOn() async {
        let s = await signedIn(FakeNoticeCenter())
        serveReminders(lead: 0)
        let host = ScreenHost(RemindersView(), session: s)
        defer { host.close() }
        #expect(await host.waitFor("Notifications are on for luach on this iPhone."))
    }

    // MARK: Ink on the accent

    @Test func inkOnTheAccentReadsInEveryAppearance() throws {
        let accent = try #require(UIColor(named: "AccentColor"))
        let ink = try #require(UIColor(named: "AccentOn"))
        for style in [UIUserInterfaceStyle.light, .dark] {
            for contrast in [UIAccessibilityContrast.normal, .high] {
                let traits = UITraitCollection { $0.userInterfaceStyle = style; $0.accessibilityContrast = contrast }
                let ratio = Self.contrast(accent.resolvedColor(with: traits), ink.resolvedColor(with: traits))
                #expect(ratio >= 7, "\(style.rawValue)/\(contrast.rawValue): \(ratio)")
                let white = Self.contrast(accent.resolvedColor(with: traits), .white)
                #expect(white < 3, "white was the problem: \(white)")
            }
        }
    }

    static func contrast(_ a: UIColor, _ b: UIColor) -> Double {
        func luminance(_ c: UIColor) -> Double {
            var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, al: CGFloat = 0
            c.getRed(&r, green: &g, blue: &b, alpha: &al)
            func lin(_ v: CGFloat) -> Double { let v = Double(v); return v <= 0.03928 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4) }
            return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
        }
        let (x, y) = (luminance(a), luminance(b))
        return (max(x, y) + 0.05) / (min(x, y) + 0.05)
    }
}

extension ScreenHost {
    /// The dialog up over the screen, if any (a confirmationDialog is an alert controller).
    var dialog: UIAlertController? {
        var controller = window.rootViewController
        while let c = controller {
            if let alert = c as? UIAlertController { return alert }
            controller = c.presentedViewController
        }
        return nil
    }

    /// Chooses `title` in the dialog up. An action sheet's buttons do not activate in-process,
    /// so the action's own handler is run, as a tap does (YouHost does the same).
    @discardableResult
    func choose(_ title: String) async -> Bool {
        let end = Date().addingTimeInterval(3)
        while dialog == nil && Date() < end { await settle(.milliseconds(150)) }
        guard let alert = dialog, let action = alert.actions.first(where: { $0.title == title }),
              let block = action.value(forKey: "handler") else { return false }
        typealias Handler = @convention(block) (UIAlertAction) -> Void
        let handler = unsafeBitCast(block as AnyObject, to: Handler.self)
        alert.dismiss(animated: false)
        handler(action)
        await settle()
        return true
    }

    /// Whether the button labelled `label` can be pressed; nil when there is none.
    func enabledButton(_ label: String) -> Bool? {
        guard let e = elements.last(where: { $0.accessibilityLabel == label }) else { return nil }
        return !e.accessibilityTraits.contains(.notEnabled)
    }
}
