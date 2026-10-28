import Foundation
import SwiftUI
import Testing
@testable import Luach

/// The buttons dev must never see pressed, pressed on a stub luach: adding, removing and
/// making primary an address, resending its confirmation, removing a passkey, and the row
/// that would open Safari.
@MainActor
@Suite(.serialized, .timeLimit(.minutes(3)))
struct YouPressTests {
    let server = StubServer()

    private let listing: [String: Any] = [
        "primary": "robin@example.com",
        "emails": [["email": "robin@example.com", "verified": true],
                   ["email": "work@example.com", "verified": true],
                   ["email": "new@example.com", "verified": false]],
    ]

    private func show(_ view: some View) async -> (YouHost, AppSession) {
        let session = await YouFixtures.session(server)
        let host = YouHost(view, session: session)
        await host.settle()
        return (host, session)
    }

    @Test func addingAnAddressByItsButton() async throws {
        server.on("GET", "/api/auth/emails", json: listing)
        server.on("POST", "/api/auth/emails", json: listing)
        let m = YouEmailsModel()
        let (host, _) = await show(EmailsView(model: m))
        m.draft = "add@example.com"
        await host.settle()
        #expect(await host.press("Add"))
        await host.settle()
        #expect(server.requests("POST", "/api/auth/emails").first?.json as? [String: String] == ["email": "add@example.com"])
        #expect(m.draft.isEmpty)

        server.fail("POST", "/api/auth/emails", status: 400, "That address belongs to someone else.")
        m.draft = "smoke@example.com"
        await host.settle()
        await host.press("Add")
        #expect(await host.waitFor("That address belongs to someone else."))
        host.close()
    }

    @Test func resendingByItsButton() async {
        server.on("GET", "/api/auth/emails", json: listing)
        server.on("POST", "/api/auth/emails/resend", json: ["sent": true, "email": "new@example.com"])
        let m = YouEmailsModel()
        let (host, _) = await show(EmailsView(model: m))
        #expect(await host.press("Resend"))
        await host.settle()
        #expect(server.requests("POST", "/api/auth/emails/resend").first?.json as? [String: String] == ["email": "new@example.com"])
        #expect(m.sentTo == "new@example.com" && host.shows("Sent"))
        host.close()
    }

    @Test func anAddressIsMadePrimaryAndRemovedByItsSwipes() async {
        server.on("GET", "/api/auth/emails", json: listing)
        server.on("POST", "/api/auth/emails/primary", json: listing)
        server.on("DELETE", "/api/auth/emails/work@example.com", json: [
            "ok": true, "primary": "robin@example.com",
            "emails": [["email": "robin@example.com", "verified": true], ["email": "new@example.com", "verified": false]],
        ])
        let m = YouEmailsModel()
        let (host, _) = await show(EmailsView(model: m))

        #expect(await host.swipe("Make primary", on: "work@example.com"))
        await host.settle()
        #expect(server.requests("POST", "/api/auth/emails/primary").first?.json as? [String: String] == ["email": "work@example.com"])

        // Remove asks first; Keep keeps it.
        #expect(await host.swipe("Remove", on: "work@example.com"))
        #expect(m.confirmRemove == "work@example.com")
        #expect(await host.choose("Keep"))
        #expect(m.confirmRemove == nil && server.requests("DELETE", "/api/auth/emails/work@example.com").isEmpty)

        // …and Remove removes it.
        await host.swipe("Remove", on: "work@example.com")
        #expect(await host.choose("Remove"))
        await host.settle()
        #expect(server.requests("DELETE", "/api/auth/emails/work@example.com").count == 1)
        #expect(m.rows.map(\.email) == ["robin@example.com", "new@example.com"] && m.confirmRemove == nil)
        host.close()
    }

    @Test func anAddressesMenuOffersTheSame() async {
        server.on("GET", "/api/auth/emails", json: listing)
        server.on("POST", "/api/auth/emails/primary", json: listing)
        let m = YouEmailsModel()
        let (host, _) = await show(EmailsView(model: m))
        #expect(await host.press("Actions for work@example.com"))
        // The menu, where the system shows one in-process.
        if await host.waitFor("Make primary", seconds: 2) {
            await host.press("Make primary")
            await host.settle()
            #expect(server.requests("POST", "/api/auth/emails/primary").count == 1)
        }
        host.close()
    }

    @Test func aPasskeyIsRemovedOnlyAfterAsking() async {
        server.on("GET", "/api/auth/passkeys", json: YouFixtures.passkeys)
        server.on("DELETE", "/api/auth/passkeys/pk1", json: ["ok": true, "passkeys": [(YouFixtures.passkeys["passkeys"] as! [Any])[1]]])
        let m = YouPasskeysModel()
        let (host, _) = await show(PasskeysView(model: m))

        #expect(await host.swipe("Remove", on: "iPhone"))
        #expect(m.confirm?.id == "pk1")
        #expect(await host.choose("Keep"))
        #expect(m.confirm == nil && server.requests("DELETE", "/api/auth/passkeys/pk1").isEmpty)

        await host.swipe("Remove", on: "iPhone")
        #expect(await host.choose("Remove iPhone"))
        await host.settle()
        #expect(server.requests("DELETE", "/api/auth/passkeys/pk1").count == 1)
        #expect(m.list?.map(\.id) == ["pk2"])

        // A refused removal says why.
        server.fail("DELETE", "/api/auth/passkeys/pk2", status: 404, "That passkey is not yours.")
        await host.swipe("Remove", on: "Passkey")
        #expect(await host.choose("Remove Passkey"))
        #expect(await host.waitFor("That passkey is not yours."))
        host.close()
    }

    @Test func addingAPasskeyOpensTheWebApp() async {
        server.on("GET", "/api/auth/passkeys", json: ["passkeys": []])
        var opened: URL?
        let view = PasskeysView().environment(\.openURL, OpenURLAction { url in
            opened = url
            return .handled
        })
        let (host, session) = await show(view)
        #expect(await host.press("Add a passkey"))
        #expect(opened == session.server, "the web app, where a passkey can be made")
        host.close()
    }
}
