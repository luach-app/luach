import Foundation
import Testing
import UIKit
@testable import Luach

/// The address a person types for their household's luach, before any request is made.
struct ServerAddressTests {
    private func url(_ text: String) throws -> String {
        try ServerAddress.url(from: text).absoluteString
    }

    @Test func aBareNameIsHTTPS() throws {
        #expect(try url("luach.example.com") == "https://luach.example.com")
        #expect(try url("  luach.example.com/ \n") == "https://luach.example.com")
        #expect(try url("luach.example.com:8443") == "https://luach.example.com:8443")
    }

    @Test func aFullAddressIsKeptWithoutItsQuery() throws {
        #expect(try url("https://luach.example.com") == "https://luach.example.com")
        #expect(try url("HTTPS://home.example.org/luach/") == "https://home.example.org/luach")
        #expect(try url("https://luach.example.com/?x=1#top") == "https://luach.example.com")
    }

    @Test func plainHTTPIsRefusedEvenAtHome() throws {
        // A private address names a different machine on every network: a phone that kept
        // "http://192.168.1.20" would hand its session to whatever answers it in a café.
        for plain in ["http://luach.example.com", "http://192.168.1.20", "http://10.0.0.5:8000", "http://172.20.1.1",
                      "http://100.101.102.103", "http://169.254.3.4", "http://nas.local:8000", "http://[fd12:3456::1]",
                      "http://[fe80::1]", "http://8.8.8.8"] {
            #expect(throws: ServerAddress.Problem.notSecure, "\(plain)") { try url(plain) }
        }
        #expect(try url("https://192.168.1.20") == "https://192.168.1.20", "https at home is fine")
        #expect(try url("https://nas.local:8443") == "https://nas.local:8443")
    }

    @Test func onlyADebugBuildReachesThisDeviceOverHTTP() throws {
        // The demo household for the screenshots runs on the Mac, reached from the simulator.
        #expect(ServerAddress.allowsLoopback, "the tests run a debug build")
        #expect(try url("http://localhost:8000") == "http://localhost:8000")
        #expect(try url("http://127.0.0.1:8765") == "http://127.0.0.1:8765")
        #expect(try url("http://[::1]:8000") == "http://[::1]:8000")
        // What a release build decides, whatever this build is.
        for loopback in ["http://localhost:8000", "http://127.0.0.1:8765", "http://[::1]"] {
            #expect(!ServerAddress.isAllowed(URL(string: loopback)!, loopback: false), "\(loopback)")
        }
        #expect(ServerAddress.isAllowed(URL(string: "https://luach.example.com")!, loopback: false))
        #expect(!ServerAddress.isAllowed(URL(string: "http://192.168.1.20")!, loopback: true))
        #expect(!ServerAddress.isAllowed(URL(string: "ftp://luach.example.com")!))
        #expect(ServerAddress.isLoopback("127.1.2.3") && ServerAddress.isLoopback("[::1]") && ServerAddress.isLoopback("LOCALHOST"))
        #expect(!ServerAddress.isLoopback("128.0.0.1") && !ServerAddress.isLoopback("localhost.example.com"))
    }

    @Test func whatIsNotAnAddress() {
        for text in ["", "   ", "luach example com", "ftp://luach.example.com", "https://", "mailto:robin@example.com",
                     "https://robin@luach.example.com"] {
            #expect(throws: ServerAddress.Problem.notAnAddress, "\(text)") { try url(text) }
        }
    }

    @Test func shownAsAPersonWouldSayIt() throws {
        #expect(ServerAddress.display(try ServerAddress.url(from: "luach.example.com")) == "luach.example.com")
        #expect(ServerAddress.display(try ServerAddress.url(from: "luach.example.com:8443/home")) == "luach.example.com:8443/home")
        #expect(ServerAddress.display(try ServerAddress.url(from: "http://127.0.0.1:8000")) == "http://127.0.0.1:8000")
    }

    @Test func everyProblemSaysWhatToDo() {
        typealias P = ServerAddress.Problem
        #expect(P.notAnAddress.localizedDescription.contains("luach.example.com"))
        #expect(P.notSecure.localizedDescription.contains("https://") && P.notSecure.localizedDescription.contains("reverse proxy"))
        #expect(P.notALuach("x.example.com").localizedDescription.contains("x.example.com answered, but it is not a luach"))
        #expect(P.unreachable("x.example.com", "it is down").localizedDescription == "Could not reach x.example.com: it is down")
        #expect(P.noAccounts("x.example.com").localizedDescription.contains("No one has an account on x.example.com"))
        #expect(ServerAddress.about.host() == "github.com")
    }
}

extension SessionTests {
    /// Checking an address against a luach (`GET /api/auth/status`) before anyone signs in.
    @MainActor
    struct Connecting {
        let luach = StubServer()

        /// A session that knows no luach yet, whose calls the stubs answer.
        private func fresh() -> AppSession {
            AppSession(api: API(server: URL(string: "https://luach.invalid")!, protocolClasses: [StubProtocol.self]), hasServer: false)
        }

        @Test func aLuachIsCheckedAndUsed() async throws {
            luach.on("GET", "/api/auth/status", json: ["users_exist": true, "authenticated": false, "sso": ["enabled": false]])
            let session = fresh()
            #expect(!session.hasServer)
            let url = try await session.connect(to: luach.host)
            #expect(url == luach.url && session.server == luach.url && session.hasServer)
            #expect(luach.requests("GET", "/api/auth/status").count == 1)
        }

        @Test func aServerThatIsNotALuach() async {
            luach.on("GET", "/api/auth/status", raw: "<html><body>Welcome to nginx!</body></html>", contentType: "text/html")
            let session = fresh()
            await #expect(throws: ServerAddress.Problem.notALuach(luach.host)) { try await session.connect(to: luach.host) }
            #expect(!session.hasServer)
        }

        @Test func aPageThatIsNotThereIsNotALuach() async {
            // A web server with no such page: a refusal, but not in luach's words.
            luach.on("GET", "/api/auth/status", status: 404, raw: "Not Found", contentType: "text/plain")
            await #expect(throws: ServerAddress.Problem.notALuach(luach.host)) { try await fresh().connect(to: luach.host) }
        }

        @Test func aLuachThatCannotAnswerSaysWhy() async {
            luach.fail("GET", "/api/auth/status", status: 503, "luach is starting")
            await #expect(throws: ServerAddress.Problem.unreachable(luach.host, "luach is starting")) {
                try await fresh().connect(to: luach.host)
            }
        }

        @Test func nothingThere() async {
            let session = fresh()
            await #expect {
                try await session.connect(to: "nothing.invalid")
            } throws: { error in
                guard case .unreachable(let host, let why) = error as? ServerAddress.Problem else { return false }
                return host == "nothing.invalid" && !why.isEmpty
            }
        }

        @Test func aLuachWithNoAccountsYet() async {
            luach.on("GET", "/api/auth/status", json: ["users_exist": false, "authenticated": false])
            let session = fresh()
            await #expect(throws: ServerAddress.Problem.noAccounts(luach.host)) { try await session.connect(to: luach.host) }
            #expect(!session.hasServer)
        }

        @Test func plainHTTPToTheInternetIsNeverSent() async {
            let session = fresh()
            await #expect(throws: ServerAddress.Problem.notSecure) { try await session.connect(to: "http://\(luach.host)") }
            #expect(luach.requests.isEmpty)
        }
    }

    /// The sign-in screen, hosted, answered by stubs.
    @MainActor
    struct SignInScreen {
        let luach = StubServer()
        private let me: [String: Any] = ["id": 1, "username": "robin", "display_name": "Robin", "is_owner": true]

        init() {
            luach.on("GET", "/api/auth/status", json: ["users_exist": true, "authenticated": false])
        }

        private func fresh() -> AppSession {
            AppSession(api: API(server: URL(string: "https://luach.invalid")!, protocolClasses: [StubProtocol.self]), hasServer: false)
        }

        @Test func withNoLuachItAsksForTheAddressFirst() async {
            let host = ScreenHost(LoginView(), session: fresh(), stack: false)
            defer { host.close() }
            #expect(await host.waitFor("Your luach's address"))
            #expect(host.shows("luach runs on your household's own server"))
            #expect(host.shows("What's luach?"))
            #expect(host.field("luach.example.com") != nil)
            #expect(host.field("Username or email") == nil, "no password before the address is checked")
            #expect(luach.requests.isEmpty)
        }

        @Test func anAddressWithoutASchemeIsCheckedThenSignedIn() async throws {
            let before = UserDefaults.standard.string(forKey: "server")
            defer { UserDefaults.standard.set(before, forKey: "server") }
            UserDefaults.standard.removeObject(forKey: "server")
            luach.on("POST", "/api/auth/login", json: me)
            let session = fresh()
            let host = ScreenHost(LoginView(), session: session, stack: false)
            defer { host.close() }
            #expect(await host.waitFor("Your luach's address"))
            #expect(await host.type(" \(luach.host)/", into: "luach.example.com"))
            await host.press("Continue")
            #expect(await host.waitFor("Username or email"))
            #expect(host.shows(luach.host) && host.shows("Change"))
            #expect(session.server == luach.url)
            #expect(luach.requests("GET", "/api/auth/status").count == 1)
            #expect(UserDefaults.standard.string(forKey: "server") == nil, "not remembered before a sign-in succeeds")

            #expect(await host.type("robin", into: "Username or email"))
            #expect(await host.type("pw", into: "Password"))
            await host.press("Sign in")
            for _ in 0..<50 where session.member == nil { try await Task.sleep(for: .milliseconds(100)) }
            #expect(session.member?.username == "robin")
            #expect(luach.requests("POST", "/api/auth/login").first?.json["username"] as? String == "robin")
            #expect(UserDefaults.standard.string(forKey: "server") == luach.url.absoluteString)
        }

        @Test func aServerThatIsNotALuachStaysOnTheAddress() async {
            luach.on("GET", "/api/auth/status", raw: "<html>Welcome to nginx!</html>", contentType: "text/html")
            let session = fresh()
            let host = ScreenHost(LoginView(), session: session, stack: false)
            defer { host.close() }
            #expect(await host.waitFor("Your luach's address"))
            #expect(await host.type(luach.host, into: "luach.example.com"))
            await host.press("Continue")
            #expect(await host.waitFor("answered, but it is not a luach"))
            #expect(host.field("Username or email") == nil)
            #expect(!session.hasServer)
        }

        @Test func aBadPasswordIsSaidInTheServersWords() async {
            luach.fail("POST", "/api/auth/login", status: 401, "That username and password do not match.")
            let host = ScreenHost(LoginView(), session: AppSession(api: luach.api), stack: false)
            defer { host.close() }
            #expect(await host.waitFor("Username or email"))
            await host.type("robin", into: "Username or email")
            await host.type("nope", into: "Password")
            await host.press("Sign in")
            #expect(await host.waitFor("That username and password do not match."))
        }

        @Test func changeAsksAgainAndChecksTheNewOne() async throws {
            let other = StubServer()
            other.on("GET", "/api/auth/status", json: ["users_exist": true, "authenticated": false])
            let session = AppSession(api: luach.api)
            let host = ScreenHost(LoginView(), session: session, stack: false)
            defer { host.close() }
            #expect(await host.waitFor(luach.host))
            #expect(host.field("luach.example.com") == nil, "a known luach goes straight to the sign-in")
            await host.press("Change")
            #expect(await host.waitFor("Your luach's address"))
            #expect(host.field("luach.example.com")?.text == luach.host, "the address so far, to correct")
            #expect(await host.type(other.host, into: "luach.example.com"))
            await host.press("Continue")
            #expect(await host.waitFor(other.host))
            #expect(host.field("Username or email") != nil)
            #expect(session.server == other.url)
            // The known luach was asked only for its name; the new one is checked before use.
            #expect(luach.requests("GET", "/api/auth/status").count == 1 && other.requests("GET", "/api/auth/status").count == 1)
        }
    }
}
