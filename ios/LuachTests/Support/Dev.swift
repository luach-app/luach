import Foundation
import Testing
@testable import Luach

/// The integration tests run against a real luach, normally dev, only when the run says
/// which one and hands over a session (ios/scripts/test.sh mints one and logs it out after):
///
///     LUACH_TEST_SERVER=https://test.luach.example.com LUACH_TEST_SESSION=<token>
///
/// (xcodebuild passes them through as TEST_RUNNER_LUACH_TEST_…; test.sh takes the server from
/// the LUACH_DEV_SERVER setting). Without them those tests are skipped, so the unit tests alone
/// run anywhere.
///
/// What they may do on that server: read anything; create only items whose title starts with
/// `ios-test`, with no one invited, and delete them before the test ends; never decide a hold
/// they did not cause, never send mail, never change a setting without putting it back.
enum Dev {
    static let marker = "ios-test"

    static var server: URL? {
        ProcessInfo.processInfo.environment["LUACH_TEST_SERVER"].flatMap(URL.init(string:))
    }

    static var session: String? {
        ProcessInfo.processInfo.environment["LUACH_TEST_SESSION"].flatMap { $0.isEmpty ? nil : $0 }
    }

    /// The family's own luach, when the run names it: LUACH_PROD_HOST (test.sh passes the host
    /// of the LUACH_PROD_SERVER setting), or the server of a prod run. Nothing in `.dev` may run
    /// against it: those tests write.
    static var production: String? {
        let env = ProcessInfo.processInfo.environment
        if let host = env["LUACH_PROD_HOST"], !host.isEmpty { return host.lowercased() }
        return Prod.server?.host()?.lowercased()
    }

    static var isProduction: Bool {
        guard let production, let host = server?.host()?.lowercased() else { return false }
        return host == production
    }

    /// A test server that is not prod, and a session for it.
    static var available: Bool { server != nil && session != nil && !isProduction }

    /// An API signed in to the test server with the run's session.
    @MainActor static func api() throws -> API {
        guard let server, let session, let host = server.host(), !isProduction else {
            throw CancellationError()
        }
        let cookie = HTTPCookie(properties: [
            .name: "luach_session", .value: session, .domain: host, .path: "/", .secure: "TRUE",
        ])!
        HTTPCookieStorage.shared.setCookie(cookie)
        return API(server: server)
    }

    /// A title no real item has: the marker, what it is, and a few random letters.
    static func title(_ what: String) -> String {
        "\(marker) \(what) \(UUID().uuidString.prefix(6).lowercased())"
    }
}

extension Trait where Self == ConditionTrait {
    /// Only when the run points at a real luach (see `Dev`).
    static var dev: Self {
        .enabled(if: Dev.available, "set LUACH_TEST_SERVER and LUACH_TEST_SESSION (ios/scripts/test.sh does); never prod")
    }

    /// Only in a read-only run against prod (ios/scripts/test-prod.sh).
    static var prod: Self {
        .enabled(if: Prod.available, "a read-only run against prod: ios/scripts/test-prod.sh")
    }
}

/// The read-only check against the family's luach (ios/scripts/test-prod.sh, which takes the
/// server from the LUACH_PROD_SERVER setting). It has variables of its own, so in a prod run every
/// `Dev` test and helper sees no server and does nothing:
///
///     LUACH_PROD_SERVER=https://luach.example.com LUACH_PROD_SESSION=<token>
///
/// The session belongs to a member made for this (`ios-test`), signed in and out by the run on
/// the Mac. A `.prod` test only reads: no turn with the agent, no tick, no save, nothing decided.
enum Prod {
    static var server: URL? {
        ProcessInfo.processInfo.environment["LUACH_PROD_SERVER"].flatMap(URL.init(string:))
    }

    static var session: String? {
        ProcessInfo.processInfo.environment["LUACH_PROD_SESSION"].flatMap { $0.isEmpty ? nil : $0 }
    }

    static var available: Bool { server?.host() != nil && session != nil }

    /// An API that can only read: every call goes through `get`.
    @MainActor static func api() throws -> API {
        guard available, let server, let session, let host = server.host() else { throw CancellationError() }
        let cookie = HTTPCookie(properties: [
            .name: "luach_session", .value: session, .domain: host, .path: "/", .secure: "TRUE",
        ])!
        HTTPCookieStorage.shared.setCookie(cookie)
        return API(server: server)
    }
}
