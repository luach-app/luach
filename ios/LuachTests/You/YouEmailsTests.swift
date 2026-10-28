import Foundation
import Testing
@testable import Luach

/// The addresses you sign in with: every change answers with the whole listing. None of
/// these may run on dev (they mail confirmation links or change who signs in), so all are here.
@MainActor
struct YouEmailsTests {
    let server = StubServer()

    private func loaded(_ listing: [String: Any]? = nil) async -> (YouEmailsModel, AppSession) {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/auth/emails", json: listing ?? YouFixtures.emails)
        let m = YouEmailsModel()
        await m.load(session)
        return (m, session)
    }

    private func listing(adding row: [String: Any]) -> [String: Any] {
        var l = YouFixtures.emails
        l["emails"] = (l["emails"] as! [[String: Any]]) + [row]
        return l
    }

    @Test func thePrimaryComesFirstThenTheOthers() async {
        let (m, _) = await loaded([
            "primary": "robin@example.com",
            "emails": [
                ["email": "new@example.com", "added_at": "2026-10-27T10:00:00+00:00", "verified": false],
                ["email": "robin@example.com", "verified": true],
                ["email": "old@example.com"],
            ],
        ])
        #expect(m.rows == [
            .init(email: "robin@example.com", verified: true),
            .init(email: "new@example.com", verified: false),
            .init(email: "old@example.com", verified: true),
        ])
        #expect(m.rows[1].id == "new@example.com" && m.loadError == nil)
    }

    @Test func nothingToAddUntilTheListingIsThereAndSomethingIsTyped() async {
        let fresh = YouEmailsModel()
        fresh.draft = "a@example.com"
        #expect(!fresh.canAdd && fresh.rows.isEmpty)
        let (m, _) = await loaded()
        #expect(!m.canAdd)
        m.draft = "   "
        #expect(!m.canAdd)
        m.draft = "a@example.com"
        #expect(m.canAdd)
    }

    @Test func addingPostsTheAddressAndTakesTheNewListing() async throws {
        let (m, session) = await loaded()
        server.on("POST", "/api/auth/emails", json: listing(adding: ["email": "new@example.com", "verified": false]))
        server.on("GET", "/api/auth/me", json: YouFixtures.me(["display_name": "Robin again"]))
        m.draft = "  new@example.com\n"
        await m.add(session)
        let sent = try #require(server.requests("POST", "/api/auth/emails").first)
        #expect(sent.json as? [String: String] == ["email": "new@example.com"])
        #expect(m.rows.last == .init(email: "new@example.com", verified: false))
        #expect(m.draft.isEmpty && m.error == nil && !m.busy)
        #expect(session.member?.displayName == "Robin again", "the app hears of the change")
    }

    @Test func aBlankAddressIsNotSent() async {
        let (m, session) = await loaded()
        m.draft = "  \n "
        await m.add(session)
        #expect(server.requests("POST", "/api/auth/emails").isEmpty)
    }

    @Test func anAddressThatIsSomeoneElsesSaysSo() async {
        let (m, session) = await loaded()
        server.fail("POST", "/api/auth/emails", status: 400, "That address belongs to someone else.")
        m.draft = "smoke@example.com"
        await m.add(session)
        #expect(m.error == "That address belongs to someone else." && m.draft == "smoke@example.com" && m.rows.count == 2)
    }

    @Test func removingAsksFirstThenDeletesThatAddress() async throws {
        let (m, session) = await loaded()
        server.fail("POST", "/api/auth/emails", status: 400, "earlier")
        m.draft = "x@example.com"
        await m.add(session)
        m.askRemove("robin@work.example.com")
        #expect(m.confirmRemove == "robin@work.example.com" && m.error == nil, "asking clears the last error")
        server.on("DELETE", "/api/auth/emails/robin@work.example.com", json: [
            "ok": true, "primary": "robin@example.com", "emails": [["email": "robin@example.com", "verified": true]],
        ])
        await m.remove("robin@work.example.com", session)
        #expect(server.requests("DELETE", "/api/auth/emails/robin@work.example.com").count == 1)
        #expect(m.rows.map(\.email) == ["robin@example.com"] && m.confirmRemove == nil)
    }

    @Test func thePrimaryCannotBeRemoved() async {
        let (m, session) = await loaded()
        server.fail("DELETE", "/api/auth/emails/robin@example.com", status: 400, "Make another address primary first.")
        m.askRemove("robin@example.com")
        await m.remove("robin@example.com", session)
        #expect(m.error == "Make another address primary first." && m.confirmRemove == nil && m.rows.count == 2)
    }

    @Test func makingAnAddressPrimary() async throws {
        let (m, session) = await loaded()
        var swapped = YouFixtures.emails
        swapped["primary"] = "robin@work.example.com"
        server.on("POST", "/api/auth/emails/primary", json: swapped)
        await m.makePrimary("robin@work.example.com", session)
        let sent = try #require(server.requests("POST", "/api/auth/emails/primary").first)
        #expect(sent.json as? [String: String] == ["email": "robin@work.example.com"])
        #expect(m.rows.map(\.email) == ["robin@work.example.com", "robin@example.com"])

        server.fail("POST", "/api/auth/emails/primary", status: 400, "Confirm that address first.")
        await m.makePrimary("new@example.com", session)
        #expect(m.error == "Confirm that address first.")
    }

    @Test func resendingTheConfirmation() async throws {
        let (m, session) = await loaded()
        server.on("POST", "/api/auth/emails/resend", json: ["sent": true, "email": "new@example.com"])
        await m.resend("new@example.com", session)
        #expect(server.requests("POST", "/api/auth/emails/resend").first?.json as? [String: String] == ["email": "new@example.com"])
        #expect(m.sentTo == "new@example.com" && m.error == nil && !m.busy)

        server.fail("POST", "/api/auth/emails/resend", status: 400, "Nothing is waiting for that address.")
        await m.resend("other@example.com", session)
        #expect(m.error == "Nothing is waiting for that address." && m.sentTo == "new@example.com")
    }

    @Test func aListingThatWillNotLoadSaysWhy() async {
        let session = await YouFixtures.session(server)
        server.fail("GET", "/api/auth/emails", status: 503, "luach is resting")
        let m = YouEmailsModel()
        await m.load(session)
        #expect(m.loadError == "luach is resting" && m.listing == nil && m.rows.isEmpty)
    }
}

/// Also notify: the list is edited here and replaced on Save.
@MainActor
struct YouNotifyTests {
    let server = StubServer()

    private func loaded(notify: [String] = ["work@example.com"], pending: [String] = ["new@example.com"]) async -> (YouNotifyModel, AppSession) {
        let session = await YouFixtures.session(server, me: YouFixtures.me(["notify_emails": notify, "notify_pending": pending]))
        let m = YouNotifyModel()
        await m.load(session)
        return (m, session)
    }

    @Test func theListIsTheConfirmedThenTheWaiting() async {
        let (m, _) = await loaded()
        #expect(m.list == ["work@example.com", "new@example.com"] && m.saved == m.list)
        #expect(m.pending == ["new@example.com"] && !m.dirty && !m.showsSaved)
    }

    @Test func returnMakesARowOfAnAddressOnly() async {
        let (m, _) = await loaded(notify: [], pending: [])
        m.draft = "  Office@Example.com; "
        m.commit()
        #expect(m.list == ["office@example.com"] && m.draft.isEmpty && !m.bad && m.dirty)
        m.draft = "office@example.com"
        m.commit()
        #expect(m.list == ["office@example.com"], "an address is listed once")
        m.draft = "not an address"
        m.commit()
        #expect(m.bad && m.draft == "not an address" && m.list.count == 1)
        m.draft = "   "
        m.commit()
        #expect(m.list.count == 1)
    }

    @Test func anAddressStillBeingTypedCountsOnSave() async {
        let (m, _) = await loaded(notify: [], pending: [])
        m.draft = "Typed@Example.com"
        #expect(m.draftEmail == "typed@example.com" && m.dirty)
        #expect(m.patch.notifyEmails == ["typed@example.com"])
        m.draft = "typed@"
        #expect(m.draftEmail.isEmpty && !m.dirty && m.patch.notifyEmails.isEmpty)
        m.draft = "work@example.com"
        m.commit()
        m.draft = "work@example.com"
        #expect(m.draftEmail.isEmpty, "already listed")
    }

    @Test func deletingARowIsAnEdit() async {
        let (m, _) = await loaded()
        m.delete(at: IndexSet(integer: 0))
        #expect(m.list == ["new@example.com"] && m.dirty)
    }

    @Test func savingReplacesTheWholeList() async throws {
        let (m, session) = await loaded()
        m.delete(at: IndexSet(integer: 0))
        m.draft = "Home@Example.com"
        server.on("PATCH", "/api/auth/me", json: YouFixtures.me(["notify_emails": [], "notify_pending": ["new@example.com", "home@example.com"]]))
        await m.save(session)
        let sent = try #require(server.requests("PATCH", "/api/auth/me").first)
        #expect(sent.keys == ["notify_emails"])
        #expect(sent.json["notify_emails"] as? [String] == ["new@example.com", "home@example.com"])
        #expect(m.list == ["new@example.com", "home@example.com"] && m.pending == m.list)
        #expect(m.draft.isEmpty && m.showsSaved && !m.busy && session.member?.id == 1)
        m.draft = "more@example.com"
        #expect(!m.showsSaved, "a new address typed is unsaved")
    }

    @Test func aRefusedSaveKeepsTheEdit() async {
        let (m, session) = await loaded()
        m.draft = "x@example.com"
        m.commit()
        server.fail("PATCH", "/api/auth/me", status: 400, "That address signs in to this household.")
        await m.save(session)
        #expect(m.error == "That address signs in to this household." && m.list.contains("x@example.com") && !m.showsSaved)
    }

    @Test func resendingAWaitingConfirmation() async {
        let (m, session) = await loaded()
        server.on("POST", "/api/auth/emails/resend", json: ["sent": true, "email": "new@example.com"])
        await m.resend("new@example.com", session)
        #expect(server.requests("POST", "/api/auth/emails/resend").first?.json as? [String: String] == ["email": "new@example.com"])
        #expect(m.sentTo == "new@example.com")
        server.fail("POST", "/api/auth/emails/resend", status: 429, "Wait a minute before sending another.")
        await m.resend("new@example.com", session)
        #expect(m.error == "Wait a minute before sending another.")
    }

    @Test func aMemberThatWillNotLoadSaysWhy() async {
        server.fail("GET", "/api/auth/me", status: 502, "luach is out of reach")
        let m = YouNotifyModel()
        await m.load(AppSession(api: server.api))
        #expect(m.loadError == "luach is out of reach" && m.me == nil && m.list.isEmpty)
    }
}
