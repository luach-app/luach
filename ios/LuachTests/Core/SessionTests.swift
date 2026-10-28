import Foundation
import Testing
@testable import Luach

@MainActor
@Suite(.serialized) // the session keeps its server in UserDefaults and its cookie in the shared jar
struct SessionTests {
    let server = StubServer()

    private let me: [String: Any] = ["id": 1, "username": "robin", "display_name": "Robin", "is_owner": true]

    @Test func aStoredSessionOpensTheApp() async {
        server.on("GET", "/api/auth/me", json: me)
        let session = AppSession(api: server.api)
        #expect(session.phase == .starting)
        await session.restore()
        #expect(session.member?.name == "Robin")
    }

    @Test func noSessionMeansSignIn() async {
        server.fail("GET", "/api/auth/me", status: 401, "sign in first")
        let session = AppSession(api: server.api)
        await session.restore()
        #expect(session.phase == .signedOut && session.member == nil)
    }

    @Test func anUnreachableServerIsNotSignedOut() async {
        // No route answers like a server that is down: the app says so and offers to retry.
        let session = AppSession(api: API(server: URL(string: "https://nothing.invalid")!, protocolClasses: [StubProtocol.self]))
        await session.restore()
        guard case .unreachable(let why) = session.phase else { Issue.record("phase \(session.phase)"); return }
        #expect(!why.isEmpty)
    }

    @Test func theLaunchCheckGivesUpWithinSeconds() async {
        // A minute on a blank screen was URLSession's default; the check now says so sooner.
        server.on("GET", "/api/auth/me", json: me)
        let session = AppSession(api: server.api)
        await session.restore()
        let asked = server.requests("GET", "/api/auth/me")
        #expect(asked.count == 1 && (10...15).contains(asked[0].timeout), "\(asked.map(\.timeout))")
        #expect((10...15).contains(AppSession.launchTimeout))
    }

    @Test func outOfReachIsNotADeadEnd_anotherAddress() async {
        let before = UserDefaults.standard.string(forKey: "server")
        defer { UserDefaults.standard.set(before, forKey: "server") }
        let gone = URL(string: "https://nothing.invalid")!
        let session = AppSession(api: API(server: gone, protocolClasses: [StubProtocol.self]))
        await session.restore()
        guard case .unreachable = session.phase else { Issue.record("phase \(session.phase)"); return }
        await session.useAnotherAddress()
        #expect(session.phase == .signedOut && !session.hasServer, "the sign-in screen asks for an address")
        #expect(session.previousServer == gone)
    }

    @Test func outOfReachIsNotADeadEnd_signOut() async {
        let session = AppSession(api: server.api)
        server.fail("GET", "/api/auth/me", status: 503, "luach is starting")
        await session.restore()
        #expect(session.phase == .unreachable("luach is starting"))
        UserDefaults.standard.set("th-1", forKey: "thread")
        let cookie = HTTPCookie(properties: [.name: "luach_session", .value: "x", .domain: server.host, .path: "/"])!
        HTTPCookieStorage.shared.setCookie(cookie)
        await session.signOutHere()
        #expect(session.phase == .signedOut && session.hasServer, "signed out of the same luach")
        #expect(HTTPCookieStorage.shared.cookies(for: server.url)?.isEmpty ?? true, "the cookie is gone")
        #expect(UserDefaults.standard.string(forKey: "thread") == nil, "the open conversation is forgotten")
        #expect(server.requests("POST", "/api/auth/logout").isEmpty, "nothing is sent to a luach that is not there")
    }

    @Test func aServerErrorIsUnreachableToo() async {
        server.fail("GET", "/api/auth/me", status: 503, "luach is starting")
        let session = AppSession(api: server.api)
        await session.restore()
        #expect(session.phase == .unreachable("luach is starting"))
    }

    @Test func anUpdateKeepsTheLuachAnEarlierBuildWasSignedInTo() {
        let before = UserDefaults.standard.string(forKey: "server")
        defer { UserDefaults.standard.set(before, forKey: "server") }
        UserDefaults.standard.removeObject(forKey: "server")
        func cookie(_ name: String, _ domain: String, secure: Bool) -> HTTPCookie {
            var p: [HTTPCookiePropertyKey: Any] = [.name: name, .value: "x", .domain: domain, .path: "/"]
            if secure { p[.secure] = "TRUE" }
            return HTTPCookie(properties: p)!
        }
        #expect(AppSession.signedInBefore([]) == nil)
        #expect(AppSession.signedInBefore([cookie("other", "luach.example.com", secure: true)]) == nil)
        #expect(AppSession.signedInBefore([cookie("luach_session", "luach.example.com", secure: false)]) == nil,
                "a session sent in the clear is not taken as the household's luach")
        #expect(UserDefaults.standard.string(forKey: "server") == nil)

        let url = AppSession.signedInBefore([cookie("luach_session", ".luach.example.com", secure: true)])
        #expect(url?.absoluteString == "https://luach.example.com")
        #expect(UserDefaults.standard.string(forKey: "server") == "https://luach.example.com", "and it is remembered")
    }

    @Test func signingInAndOut() async throws {
        let before = UserDefaults.standard.string(forKey: "server")
        defer { UserDefaults.standard.set(before, forKey: "server") }
        server.on("POST", "/api/auth/login", json: me)
        server.on("POST", "/api/auth/logout", json: ["ok": true])
        let session = AppSession(api: server.api)
        try await session.login(username: "robin", password: "pw")
        #expect(session.member?.username == "robin")

        UserDefaults.standard.set("th-1", forKey: "thread")
        let cookie = HTTPCookie(properties: [.name: "luach_session", .value: "x", .domain: server.host, .path: "/"])!
        HTTPCookieStorage.shared.setCookie(cookie)
        await session.logout()
        #expect(session.phase == .signedOut)
        #expect(HTTPCookieStorage.shared.cookies(for: server.url)?.isEmpty ?? true, "the cookie is gone")
        #expect(UserDefaults.standard.string(forKey: "thread") == nil, "the open conversation is forgotten")
        #expect(server.requests("POST", "/api/auth/logout").count == 1)
    }

    @Test func aRefusedSignInStaysOnTheForm() async {
        server.fail("POST", "/api/auth/login", status: 429, "Too many tries; wait a minute.")
        let session = AppSession(api: server.api)
        await #expect { try await session.login(username: "a", password: "b") } throws: {
            $0.localizedDescription == "Too many tries; wait a minute."
        }
        #expect(session.phase == .starting)
    }

    @Test func aLostSessionMidwaySignsOut() async throws {
        server.on("GET", "/api/auth/me", json: me)
        server.fail("GET", "/api/control/pending", status: 401, "sign in first")
        let session = AppSession(api: server.api)
        await session.restore()
        await session.pending.refresh()
        #expect(session.phase == .signedOut)
    }

    @Test func aChangedMemberReplacesTheOldOne() async throws {
        server.on("GET", "/api/auth/me", json: me)
        let session = AppSession(api: server.api)
        await session.restore()
        let renamed = try JSONDecoder.snake.decode(Member.self, from: Data(#"{"id":1,"username":"robin","display_name":"Robin Harper"}"#.utf8))
        session.setMember(renamed)
        #expect(session.member?.name == "Robin Harper")
    }

    @Test func signedOutAMemberChangeIsIgnored() throws {
        let session = AppSession(api: server.api)
        session.setMember(try JSONDecoder.snake.decode(Member.self, from: Data(#"{"id":1,"username":"x"}"#.utf8)))
        #expect(session.member == nil)
    }

    @Test func theServerIsRememberedOnceASignInThereSucceeds() async throws {
        let before = UserDefaults.standard.string(forKey: "server")
        defer { UserDefaults.standard.set(before, forKey: "server") }
        UserDefaults.standard.set("https://luach.example.com", forKey: "server")
        let session = AppSession(api: API(server: URL(string: "https://luach.example.com")!, protocolClasses: [StubProtocol.self]))
        server.on("GET", "/api/auth/status", json: ["users_exist": true, "authenticated": false])
        server.fail("POST", "/api/auth/login", status: 401, "That username and password do not match.")
        try await session.connect(to: server.host)
        #expect(session.server == server.url)
        await #expect(throws: APIError.self) { try await session.login(username: "robin", password: "no") }
        #expect(UserDefaults.standard.string(forKey: "server") == "https://luach.example.com", "a refused sign-in keeps the old one")
        server.on("POST", "/api/auth/login", json: me)
        try await session.login(username: "robin", password: "pw")
        #expect(UserDefaults.standard.string(forKey: "server") == server.url.absoluteString)
    }

    @Test func aSavedServerIsWhereTheAppStarts() {
        let before = UserDefaults.standard.string(forKey: "server")
        defer { UserDefaults.standard.set(before, forKey: "server") }
        UserDefaults.standard.set("https://luach.example.com", forKey: "server")
        let session = AppSession()
        #expect(session.hasServer)
        #expect(session.server.host() == "luach.example.com")
    }

    @Test func aLaunchCookieSignsInToTheKnownServer() {
        // `-sessionCookie <token>` at launch (simulator checks, UI tests): a cookie for that luach.
        UserDefaults.standard.set("tok-\(server.host)", forKey: "sessionCookie")
        defer { UserDefaults.standard.removeObject(forKey: "sessionCookie") }
        _ = AppSession(api: server.api)
        let cookie = HTTPCookieStorage.shared.cookies(for: server.url)?.first { $0.name == "luach_session" }
        #expect(cookie?.value == "tok-\(server.host)")
        cookie.map(HTTPCookieStorage.shared.deleteCookie)
    }

    @Test func noServerAtAllMeansSignInWithoutAsking() async {
        let before = UserDefaults.standard.string(forKey: "server")
        defer { UserDefaults.standard.set(before, forKey: "server") }
        UserDefaults.standard.removeObject(forKey: "server")
        let session = AppSession()
        #expect(!session.hasServer)
        await session.restore()
        #expect(session.phase == .signedOut)
    }
}

@MainActor
struct PendingStoreTests {
    let server = StubServer()

    @Test func onlyWhatIsStillWaiting() async {
        server.on("GET", "/api/control/pending", json: ["pending": [
            ["id": "a", "tool": "t", "summary": "s", "status": "pending"],
            ["id": "b", "tool": "t", "summary": "s", "status": "approved"],
        ]])
        let store = PendingStore(api: server.api)
        await store.refresh()
        #expect(store.items.map(\.id) == ["a"] && store.error == nil)
    }

    @Test func aFailedReadKeepsWhatWasThereAndSaysWhy() async {
        server.on("GET", "/api/control/pending", json: ["pending": [["id": "a", "tool": "t", "summary": "s", "status": "pending"]]])
        let store = PendingStore(api: server.api)
        await store.refresh()
        server.fail("GET", "/api/control/pending", status: 500, "the database is away")
        await store.refresh()
        #expect(store.items.count == 1 && store.error == "the database is away")
    }

    @Test func anApprovalThatDidNotGoThroughSaysSo() async throws {
        // The server marks it "failed" when the call it ran was refused; it leaves the list
        // like any decided hold, so the store keeps why until the next decision.
        server.on("POST", "/api/control/pending/a/approve", json: [
            "id": "a", "tool": "t", "summary": "s", "status": "failed", "result": ["error": "no such event"],
        ])
        server.on("POST", "/api/control/pending/b/approve", json: [
            "id": "b", "tool": "t", "summary": "s", "status": "approved", "result": ["created": ["id": "e1"]],
        ])
        server.on("GET", "/api/control/pending", json: ["pending": []])
        let store = PendingStore(api: server.api)
        let row = try await store.decide("a", approve: true)
        #expect(row.failed && row.failure == "no such event")
        #expect(store.failure?.hasSuffix(": no such event") == true)
        let next = try await store.decide("b", approve: true)
        #expect(!next.failed && next.failure == nil && store.failure == nil)
    }

    @Test func decidingRefreshesTheList() async throws {
        server.on("POST", "/api/control/pending/a/deny", json: ["id": "a", "tool": "t", "summary": "s", "status": "denied"])
        server.on("GET", "/api/control/pending", json: ["pending": []])
        let store = PendingStore(api: server.api)
        let row = try await store.decide("a", approve: false)
        #expect(row.status == "denied")
        try await Task.sleep(for: .milliseconds(200))
        #expect(server.requests("GET", "/api/control/pending").count >= 1)
    }
}

/// What the app shows while it checks its luach at launch, and when that luach does not answer.
@MainActor
struct OutOfReachScreenTests {
    let server = StubServer()

    @Test func whileItChecksItSaysWhere() async {
        let session = AppSession(api: server.api)
        let host = ScreenHost(RootView(), session: session, stack: false)
        defer { host.close() }
        #expect(await host.waitFor("Reaching \(server.host)…"))
    }

    private func outOfReach() async -> (AppSession, ScreenHost) {
        server.fail("GET", "/api/auth/me", status: 503, "luach is starting")
        let session = AppSession(api: server.api)
        await session.restore()
        let host = ScreenHost(RootView(), session: session, stack: false)
        return (session, host)
    }

    @Test func outOfReachOffersAnotherAddress() async {
        let (session, host) = await outOfReach()
        defer { host.close() }
        #expect(await host.waitFor("luach is out of reach"))
        #expect(host.shows("luach is starting") && host.shows("Try again") && host.shows("Sign out"))
        #expect(await host.press("Use another address"))
        #expect(await host.waitFor("Your luach's address"))
        #expect(host.field("luach.example.com")?.text == server.host, "starting from the one that did not answer")
        #expect(!session.hasServer)
    }

    @Test func outOfReachOffersSigningOut() async {
        let (session, host) = await outOfReach()
        defer { host.close() }
        #expect(await host.waitFor("luach is out of reach"))
        #expect(await host.press("Sign out"))
        #expect(await host.waitFor("Username or email"))
        #expect(host.shows(server.host), "signed out of the same luach")
        #expect(session.phase == .signedOut)
    }

    @Test func tryingAgainChecksAgain() async {
        let (session, host) = await outOfReach()
        defer { host.close() }
        #expect(await host.waitFor("luach is out of reach"))
        server.on("GET", "/api/auth/me", json: ["id": 1, "username": "robin", "display_name": "Robin", "is_owner": true])
        await host.press("Try again")
        for _ in 0..<50 where session.member == nil { try? await Task.sleep(for: .milliseconds(100)) }
        #expect(session.member?.name == "Robin")
        #expect(server.requests("GET", "/api/auth/me").count >= 2, "asked again")
    }
}
