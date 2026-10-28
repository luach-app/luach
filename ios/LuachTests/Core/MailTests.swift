import Foundation
import Testing
@testable import Luach

@MainActor
struct MailTests {
    let server = StubServer()

    private func status(connected: Bool, via: String = "own", scan: [String: Any]? = nil) -> [String: Any] {
        var st: [String: Any] = ["connected": connected, "address": connected ? "me@example.com" : "",
                                 "via": connected ? via : "", "can_connect": true]
        if let scan { st["scan"] = scan }
        return st
    }

    @Test func theStatusDecodesWithAndWithoutTheScan() async throws {
        server.on("GET", "/api/mail", json: status(connected: true, scan: [
            "available": true, "enabled": true, "since": "2026-10-01T12:00:00", "minutes": 10,
            "read": 120, "proposed": 6, "last_read": "2026-10-26T09:00:00+00:00"]))
        let st = try await server.api.mailStatus()
        #expect(st.connected && st.via == "own" && st.scan?.read == 120 && st.scan?.lastRead != nil)

        server.on("GET", "/api/mail", json: status(connected: false))
        #expect(try await server.api.mailStatus().scan == nil)
    }

    @Test func theConsentURLComesFromTheAppRoute() async throws {
        server.on("POST", "/api/mail/connect/app", json: ["url": "https://accounts.google.com/o/oauth2/v2/auth?state=app1.x"])
        let url = try await server.api.mailConsentURL()
        #expect(url.host() == "accounts.google.com")
        #expect(server.requests("POST", "/api/mail/connect/app").count == 1)
    }

    @Test func aLuachWithoutConnectingSaysSo() async {
        server.fail("POST", "/api/mail/connect/app", status: 409, "connecting email is not set up on this luach")
        await #expect {
            _ = try await server.api.mailConsentURL()
        } throws: { $0.localizedDescription == "connecting email is not set up on this luach" }
    }

    @Test func theAppClaimsItsConnectWithTheNonce() async throws {
        server.on("POST", "/api/mail/connect/app/finish", json: status(connected: true))
        let st = try await server.api.finishMailConnect(nonce: "n0nce")
        #expect(st.connected && st.via == "own")
        #expect(server.requests("POST", "/api/mail/connect/app/finish").first?.json["nonce"] as? String == "n0nce")

        server.fail("POST", "/api/mail/connect/app/finish", status: 409, "that email connection could not be completed; connect again")
        await #expect {
            _ = try await server.api.finishMailConnect(nonce: "used")
        } throws: { $0.localizedDescription == "that email connection could not be completed; connect again" }
    }

    @Test func theWayBackFromGoogleIsRead() {
        #expect(MailReturn(URL(string: "luach://mail?mail=confirm&nonce=abc")!) == .confirm("abc"))
        #expect(MailReturn(URL(string: "luach://mail?mail=confirm")!) == .failed)
        #expect(MailReturn(URL(string: "luach://mail?mail=connected")!) == .connected)
        #expect(MailReturn(URL(string: "luach://mail?mail=failed&reason=not-yours")!) == .notYours)
        #expect(MailReturn(URL(string: "luach://mail?mail=failed")!) == .failed)
        #expect(MailReturn(URL(string: "luach://mail")!) == .failed)
    }

    @Test func theScanIsSwitchedAndTheMailboxForgotten() async throws {
        server.on("PATCH", "/api/mail/scan", json: status(connected: true, scan: [
            "available": true, "enabled": true, "since": "", "minutes": 10]))
        let on = try await server.api.setMailScan(true)
        #expect(on.scan?.enabled == true)
        #expect(server.requests("PATCH", "/api/mail/scan").first?.json["enabled"] as? Bool == true)

        server.on("DELETE", "/api/mail", json: status(connected: false))
        #expect(try await server.api.disconnectMail().connected == false)
    }

    @Test func theScanLineSaysWhatItDid() throws {
        let scan = MailStatus.Scan(available: true, enabled: true, since: "2026-10-01T12:00:00", minutes: 10,
                                   read: 120, proposed: 6, lastRead: "2026-10-26T09:00:00+00:00")
        let line = ScanLine.text(scan)
        #expect(line.hasPrefix("Reading your email every 10 minutes · last "))
        #expect(line.hasSuffix("120 read · 6 found"))
        let quiet = MailStatus.Scan(available: true, enabled: true, since: "", minutes: 5, read: nil, proposed: nil, lastRead: nil)
        #expect(ScanLine.text(quiet) == "Reading your email every 5 minutes")
    }

    @Test func luachsTimesWithAndWithoutAZone() throws {
        let naive = try #require(ScanLine.date("2026-10-01T12:00:00"))
        let utc = try #require(ScanLine.date("2026-10-01T12:00:00Z"))
        let offset = try #require(ScanLine.date("2026-10-01T08:00:00-04:00"))
        #expect(naive == utc && utc == offset)
        #expect(ScanLine.date("") == nil)
    }
}

/// Connecting a Gmail the way the app does, against dev's Gmail stand-in. The browser
/// sheet's part is played here: Google's consent is the one page dev cannot fake for a
/// browser, so the test goes straight back to luach's callback with the stand-in's code,
/// from a session with no luach cookie at all, as the sheet has none.
@MainActor
@Suite(.dev, .serialized, .timeLimit(.minutes(2)))
struct DevMailTests {
    /// Only when dev offers connecting and nobody's own mailbox is connected for this member
    /// (the test must leave dev as it found it).
    static func free() async -> Bool {
        guard let st = try? await Dev.api().mailStatus() else { return false }
        return st.canConnect && st.via != "own"
    }

    /// GETs without following the redirect, with no cookies: what the browser sheet would see.
    private func redirect(_ url: URL) async throws -> (Int, String?) {
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        let (_, response) = try await URLSession(configuration: config).data(from: url, delegate: NoRedirect())
        let http = try #require(response as? HTTPURLResponse)
        return (http.statusCode, http.value(forHTTPHeaderField: "Location"))
    }

    /// The stand-in signs in as whoever the code names after "~"; luach connects a mailbox only
    /// when it is one of the member's own addresses.
    private func callback(state: String, code: String = "fixture-code") throws -> URL {
        var c = URLComponents(url: try #require(Dev.server).appending(path: "/api/mail/callback"), resolvingAgainstBaseURL: false)!
        c.queryItems = [URLQueryItem(name: "code", value: code), URLQueryItem(name: "state", value: state)]
        return c.url!
    }

    @Test(.enabled { await DevMailTests.free() })
    func connectingFromThePhoneEndToEnd() async throws {
        let api = try Dev.api()
        let consent = try await api.mailConsentURL()
        let state = try #require(URLComponents(url: consent, resolvingAgainstBaseURL: false)?
            .queryItems?.first { $0.name == "state" }?.value)
        #expect(state.hasPrefix("app1."), "the member travels in a sealed state")

        let email = try #require(try await api.me().email)
        let (status, location) = try await redirect(try callback(state: state, code: "fixture-code~\(email)"))
        #expect(status == 302)
        let back = try #require(location.flatMap(URL.init(string:)))
        let after: MailStatus
        switch MailReturn(back) {
        case .confirm(let nonce):
            // Nothing is stored until this session claims it.
            #expect(try await api.mailStatus().via != "own")
            after = try await api.finishMailConnect(nonce: nonce)
            #expect(after.address == email.lowercased())
            await #expect(throws: APIError.self) { _ = try await api.finishMailConnect(nonce: nonce) }
        case .connected:
            after = try await api.mailStatus()  // a luach from before the nonce
        default:
            Issue.record("the way back was \(back)")
            return
        }
        #expect(after.connected && after.via == "own")

        let gone = try await api.disconnectMail()
        #expect(gone.via != "own")
    }

    @Test(.enabled { await DevMailTests.free() })
    func someoneElsesGmailIsNotConnected() async throws {
        let api = try Dev.api()
        let consent = try await api.mailConsentURL()
        let state = try #require(URLComponents(url: consent, resolvingAgainstBaseURL: false)?
            .queryItems?.first { $0.name == "state" }?.value)
        let (status, location) = try await redirect(try callback(state: state, code: "fixture-code~stranger@fixture.test"))
        #expect(status == 302)
        switch MailReturn(try #require(location.flatMap(URL.init(string:)))) {
        case .notYours:
            #expect(try await api.mailStatus().via != "own")
        case .connected:
            _ = try await api.disconnectMail()  // a luach from before the address check
        default:
            Issue.record("the way back was \(location ?? "")")
        }
    }

    @Test func aForgedStateConnectsNothing() async throws {
        let api = try Dev.api()
        let before = try await api.mailStatus()
        let (status, location) = try await redirect(try callback(state: "app1.forged"))
        #expect(status == 302 && location == "luach://mail?mail=failed")
        let after = try await api.mailStatus()
        #expect(after.connected == before.connected && after.via == before.via)
    }
}

/// Stops at the first redirect, so a test reads where luach sends the browser.
nonisolated final class NoRedirect: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
