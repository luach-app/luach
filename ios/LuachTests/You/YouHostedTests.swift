import Foundation
import SwiftUI
import Testing
@testable import Luach

/// The You screens laid out for real against a stub luach, in the states dev cannot show:
/// errors, invitations, boards, passkeys, unconfirmed addresses, a broken chain.
/// Serialized: the `-youPush` / `-youPerson` cases set the shared UserDefaults.
@MainActor
@Suite(.serialized, .timeLimit(.minutes(3)))
struct YouHostedTests {
    let server = StubServer()

    init() {
        URLProtocol.registerClass(StubProtocol.self)  // the audit trail is read with URLSession.shared
    }

    private func show(_ view: some View, me: [String: Any]? = nil) async -> (YouHost, AppSession) {
        let session = await YouFixtures.session(server, me: me)
        let host = YouHost(view, session: session)
        await host.settle()
        return (host, session)
    }

    /// A debug launch argument, for one hosted screen.
    private func with(_ key: String, _ value: String, _ body: () async -> Void) async {
        UserDefaults.standard.set(value, forKey: key)
        await body()
        UserDefaults.standard.removeObject(forKey: key)
    }

    // MARK: You

    @Test func profileThroughItsStates() async throws {
        server.on("GET", "/api/models", json: YouFixtures.models)
        let m = YouProfileModel()
        let (host, session) = await show(ProfileView(model: m))
        #expect(m.me != nil && m.models.count == 3)
        m.model = "cloud-deepseek-v4-flash"
        m.displayName = "Robin Harper"
        await host.settle()
        server.fail("PATCH", "/api/auth/me", status: 400, "That is not a time zone.")
        await m.save(session)
        await host.settle()
        #expect(m.error != nil)
        server.on("PATCH", "/api/auth/me", json: YouFixtures.me(["display_name": "Robin Harper", "model": "cloud-deepseek-v4-flash"]))
        await m.save(session)
        await host.settle()
        #expect(m.showsSaved, "the answer resetting the pick does not hide Saved.")
        host.close()
    }

    @Test func profileShowsAModelNotAnsweringAndAsksBeforeTheCloud() async throws {
        server.on("GET", "/api/models", json: YouFixtures.modelsOneDown)
        let gemini = "openrouter/google/gemini-3.8-flash"
        YouAIConsent.withdraw("shed-llama")
        let m = YouProfileModel()
        let (host, _) = await show(ProfileView(model: m))
        #expect(await host.waitFor("Not answering since"), "\(host.labels)")
        #expect(host.shows("its provider refused it — 404"))
        // Not answering: pressing it picks nothing.
        let down = try #require(host.elements.first { ($0.accessibilityLabel ?? "").hasPrefix("Gemini 3.8 Flash") })
        down.accessibilityActivate()
        await host.settle()
        #expect(m.model.isEmpty && host.dialog == nil)
        // At home: picked at once, no question.
        #expect(host.elements.contains { ($0.accessibilityLabel ?? "").hasPrefix("Shed Llama") })
        if let shed = host.elements.first(where: { ($0.accessibilityLabel ?? "").hasPrefix("Shed Llama") }) {
            shed.accessibilityActivate()
            await host.settle()
        }
        #expect(m.model == "shed-llama" && host.dialog == nil)
        #expect(!YouAIConsent.given(gemini))
        host.close()
    }

    @Test func profileAsksBeforeAModelOutsideTheHouse() async throws {
        server.on("GET", "/api/models", json: YouFixtures.models)
        let flash = "cloud-deepseek-v4-flash"
        YouAIConsent.withdraw(flash)
        defer { YouAIConsent.withdraw(flash) }
        let m = YouProfileModel()
        let (host, _) = await show(ProfileView(model: m))
        let row = try #require(host.elements.first { ($0.accessibilityLabel ?? "").hasPrefix("DeepSeek V4 Flash") })
        row.accessibilityActivate()
        #expect(await host.waitFor("Send your questions to DeepSeek V4 Flash?"), "\(host.labels)")
        #expect(host.dialog?.message?.contains("at DeepSeek") == true)
        #expect(await host.choose("Keep the household's model"))
        #expect(m.model.isEmpty && !YouAIConsent.given(flash))
        // The list is drawn again once the alert has gone: ask for its row afresh.
        await host.settle()
        let again = try #require(host.elements.first { ($0.accessibilityLabel ?? "").hasPrefix("DeepSeek V4 Flash") })
        again.accessibilityActivate()
        #expect(await host.waitFor("Send your questions to DeepSeek V4 Flash?"), "\(host.labels)")
        #expect(await host.choose("Use DeepSeek V4 Flash"))
        #expect(m.model == flash && YouAIConsent.given(flash))
        host.close()
    }

    @Test func profileThatWillNotLoad() async {
        let session = AppSession(api: server.api)
        server.fail("GET", "/api/auth/me", status: 500, "luach is resting")
        let m = YouProfileModel()
        let host = YouHost(ProfileView(model: m), session: session)
        await host.settle()
        #expect(m.loadError == "luach is resting")
        host.close()
    }

    @Test func profileOpensTheZoneList() async {
        server.on("GET", "/api/models", json: YouFixtures.models)
        await with("youPush", "timezone") {
            let (host, _) = await show(ProfileView())
            await host.settle(.milliseconds(600))
            host.close()
        }
    }

    @Test func theZoneListTicksTheSelection() async {
        var zone = "America/New_York"
        let binding = Binding(get: { zone }, set: { zone = $0 })
        let (host, _) = await show(YouTimeZonePicker(selection: binding))
        let (unknown, _) = await show(YouTimeZonePicker(selection: .constant("Mars/Olympus")))
        host.close()
        unknown.close()
    }

    @Test func emailsWithAnUnconfirmedAddress() async throws {
        server.on("GET", "/api/auth/emails", json: [
            "primary": "robin@example.com",
            "emails": [["email": "robin@example.com", "verified": true],
                       ["email": "work@example.com", "verified": true],
                       ["email": "new@example.com", "verified": false]],
        ])
        let m = YouEmailsModel()
        let (host, session) = await show(EmailsView(model: m))
        #expect(m.rows.count == 3)
        server.on("POST", "/api/auth/emails/resend", json: ["sent": true, "email": "new@example.com"])
        await m.resend("new@example.com", session)
        await host.settle()
        #expect(m.sentTo == "new@example.com")
        server.fail("POST", "/api/auth/emails", status: 400, "That address belongs to someone else.")
        m.draft = "smoke@example.com"
        await m.add(session)
        await host.settle()
        #expect(m.error != nil)
        m.askRemove("work@example.com")
        await host.settle()
        m.confirmRemove = nil
        await host.settle()
        host.close()
    }

    @Test func emailsThatWillNotLoad() async {
        server.fail("GET", "/api/auth/emails", status: 500, "luach is resting")
        let m = YouEmailsModel()
        let (host, _) = await show(EmailsView(model: m))
        #expect(m.loadError == "luach is resting")
        host.close()
    }

    @Test func alsoNotifyThroughItsStates() async {
        let m = YouNotifyModel()
        let (host, session) = await show(NotifyEmailsView(model: m),
                                         me: YouFixtures.me(["notify_emails": ["work@example.com"], "notify_pending": ["new@example.com"]]))
        #expect(m.list.count == 2)
        m.draft = "not an address"
        await host.settle()  // typed first, as a person does, then return
        m.commit()
        await host.settle()
        #expect(m.bad)
        server.on("POST", "/api/auth/emails/resend", json: ["sent": true])
        await m.resend("new@example.com", session)
        m.draft = ""
        server.fail("PATCH", "/api/auth/me", status: 400, "No.")
        await m.save(session)
        await host.settle()
        server.on("PATCH", "/api/auth/me", json: YouFixtures.me(["notify_emails": ["work@example.com"], "notify_pending": []]))
        await m.save(session)
        await host.settle()
        #expect(m.showsSaved)
        host.close()
    }

    @Test func alsoNotifyThatWillNotLoad() async {
        server.fail("GET", "/api/auth/me", status: 500, "luach is resting")
        let m = YouNotifyModel()
        let host = YouHost(NotifyEmailsView(model: m), session: AppSession(api: server.api))
        await host.settle()
        #expect(m.loadError == "luach is resting")
        host.close()
    }

    @Test func memoryWithFactsAndAnError() async {
        server.on("GET", "/api/family", json: YouFixtures.family)
        server.on("GET", "/api/memory", json: ["facts": [
            ["key": "chores", "topic": "chores", "fact": "Lily feeds the fish every day"],
            ["key": "fridays", "topic": "", "fact": "We keep Friday nights clear"],
        ]])
        let m = YouMemoryModel()
        let (host, session) = await show(MemoryView(model: m))
        #expect(m.facts?.count == 2 && m.example == "Ruby")
        m.draft = "Something"
        server.fail("POST", "/api/memory", status: 400, "That is too long to remember.")
        await m.add(session)
        await host.settle()
        #expect(m.error != nil)
        host.close()
    }

    @Test func memoryEmptyAndOff() async {
        server.on("GET", "/api/memory", json: ["facts": []])
        let empty = YouMemoryModel()
        let (host, _) = await show(MemoryView(model: empty))
        #expect(empty.facts?.isEmpty == true)
        host.close()
        server.fail("GET", "/api/memory", status: 503, "Memory is not set up on this luach.")
        let off = YouMemoryModel()
        let (offHost, _) = await show(MemoryView(model: off))
        #expect(off.off != nil)
        offHost.close()
    }

    // MARK: Security

    @Test func passkeysListedAndOneToRemove() async throws {
        server.on("GET", "/api/auth/passkeys", json: YouFixtures.passkeys)
        let m = YouPasskeysModel()
        let (host, session) = await show(PasskeysView(model: m))
        #expect(m.list?.count == 2)
        server.fail("DELETE", "/api/auth/passkeys/pk1", status: 404, "That passkey is not yours.")
        await m.remove("pk1", session)
        await host.settle()
        #expect(m.error != nil)
        m.ask(try #require(m.list?.first))
        await host.settle()
        m.confirm = nil
        await host.settle()
        host.close()
    }

    @Test func passkeysNoneAndUnreadable() async {
        server.on("GET", "/api/auth/passkeys", json: ["passkeys": []])
        let none = YouPasskeysModel()
        let (host, _) = await show(PasskeysView(model: none))
        #expect(none.list?.isEmpty == true)
        host.close()
        server.fail("GET", "/api/auth/passkeys", status: 500, "luach is resting")
        let bad = YouPasskeysModel()
        let (badHost, _) = await show(PasskeysView(model: bad))
        #expect(bad.loadError != nil)
        badHost.close()
    }

    @Test func passwordMismatchThenChanged() async {
        let m = YouPasswordModel()
        let (host, session) = await show(PasswordView(model: m))
        m.current = "old password"
        m.next = "correct horse"
        m.confirm = "correct house"
        await m.submit(session)
        await host.settle()
        #expect(m.error != nil)
        server.on("POST", "/api/auth/password", json: ["ok": true])
        m.confirm = "correct horse"
        await m.submit(session)
        await host.settle()
        #expect(m.done)
        host.close()
    }

    @Test func auditVerifiedWithOlderEntries() async throws {
        server.on("GET", "/api/control/audit", json: YouFixtures.audit)
        let m = YouAuditModel()
        let (host, _) = await show(AuditView(model: m))
        #expect(m.trail?.entries.count == 3 && m.hasOlder)
        host.close()
        let entry = try #require(m.trail?.entries.first)
        let (detail, _) = await show(YouAuditEntryDetail(entry: entry, zone: "America/New_York"))
        detail.close()
        let bare = YouAuditTrail.Entry(seq: 1, ts: "", eventType: "boot", hash: "", fields: [("note", "")])
        let empty = YouAuditTrail.Entry(seq: 2, ts: "", eventType: "boot", hash: "", fields: [])
        let (bareHost, _) = await show(YouAuditEntryDetail(entry: bare, zone: nil))
        let (emptyHost, _) = await show(YouAuditEntryDetail(entry: empty, zone: nil))
        bareHost.close()
        emptyHost.close()
    }

    @Test func auditBrokenAndUnreadable() async {
        var broken = YouFixtures.audit
        broken["chain_verified"] = false
        broken["entries"] = [["seq": 9, "ts": "2026-10-27T15:19:07Z", "event_type": "boot", "payload": [:], "hash": "x"]]
        server.on("GET", "/api/control/audit", json: broken)
        let m = YouAuditModel()
        let (host, _) = await show(AuditView(model: m))
        #expect(m.trail?.verified == false)
        host.close()
        server.fail("GET", "/api/control/audit", status: 403, "Only the owner reads the audit trail.")
        let denied = YouAuditModel()
        let (deniedHost, _) = await show(AuditView(model: denied))
        #expect(denied.error != nil)
        deniedHost.close()
    }

    // MARK: Household

    private func membersRoutes(invites: [[String: Any]]? = nil) {
        var reply = YouFixtures.members
        reply["invites"] = invites ?? YouFixtures.invites
        server.on("GET", "/api/members", json: reply)
        server.on("GET", "/api/family", json: YouFixtures.family)
        server.on("GET", "/api/boards", json: YouFixtures.boards)
    }

    @Test func membersWithInvitationsAndALink() async throws {
        membersRoutes()
        let m = YouMembersModel()
        let (host, session) = await show(MembersView(model: m))
        #expect(m.data?.invites.count == 2)
        m.email = "new@example.com"
        server.on("POST", "/api/members/invite", json: ["sent": false, "link": "https://luach.example.com/invite/abc"])
        await m.invite(session)
        m.copy("https://luach.example.com/invite/abc")
        await host.settle()
        #expect(m.copied)
        m.email = "other@example.com"
        server.on("POST", "/api/members/invite", json: ["sent": true])
        await m.invite(session)
        await host.settle()
        server.fail("DELETE", "/api/members/1", status: 400, "The owner cannot be removed.")
        await m.remove(1, session)
        server.fail("POST", "/api/members/invite", status: 400, "That address is already a member.")
        m.email = "robin@example.com"
        await m.invite(session)
        await host.settle()
        #expect(m.actError != nil && m.inviteError != nil)
        m.ask(try #require(m.data?.members.last))
        await host.settle()
        m.confirmRemove = nil
        await host.settle()
        host.close()
    }

    @Test func membersNotForEveryone() async {
        server.fail("GET", "/api/members", status: 403, "Only the owner manages members.")
        let m = YouMembersModel()
        let (host, _) = await show(MembersView(model: m))
        #expect(m.error != nil)
        host.close()
    }

    @Test func membersOpenTheFamilyAndTheBoards() async {
        membersRoutes(invites: [])
        for screen in ["family", "boards"] {
            await with("youPush", screen) {
                let (host, _) = await show(MembersView())
                await host.settle(.milliseconds(600))
                host.close()
            }
        }
    }

    @Test func familyWithAChildAndSomeoneWhoSignsIn() async {
        server.on("GET", "/api/family", json: YouFixtures.family)
        let m = YouFamilyModel()
        let (host, session) = await show(YouFamilyView(model: m))
        #expect(m.family?.people.count == 3)
        m.name = "Noa"
        server.fail("POST", "/api/family", status: 403, "Only the owner changes the family.")
        await m.add(session)
        await host.settle()
        #expect(m.addError != nil)
        host.close()
        server.fail("GET", "/api/family", status: 500, "luach is resting")
        let bad = YouFamilyModel()
        let (badHost, _) = await show(YouFamilyView(model: bad))
        #expect(bad.loadError != nil)
        badHost.close()
    }

    @Test func familyOpensAPerson() async {
        server.on("GET", "/api/family", json: YouFixtures.family)
        await with("youPerson", "ruby") {
            let (host, _) = await show(YouFamilyView())
            await host.settle(.milliseconds(600))
            host.close()
        }
    }

    @Test func aPersonsEditorAndItsError() async throws {
        let person = try YouFixtures.decode(YouKit.Person.self, YouFixtures.ruby)
        let colors = try YouFixtures.decode([YouKit.FamilyColor].self, YouFixtures.colors)
        server.fail("PATCH", "/api/family/ruby", status: 400, "That address belongs to a member.")
        server.on("DELETE", "/api/family/ruby", json: ["ok": true])
        let m = YouPersonModel(person: person)
        let (host, session) = await show(YouPersonEditor(model: m, colors: colors))
        m.email = "robin@example.com"
        await host.settle()
        await m.saveEmail(session)
        await host.settle()
        #expect(m.error == "That address belongs to a member.")
        m.askRemove()
        await host.settle()
        m.confirmRemove = false
        await host.settle()
        host.close()
    }

    @Test func boardsWithTheirSettings() async throws {
        server.on("GET", "/api/boards", json: YouFixtures.boards)
        let m = YouBoardsModel()
        let (host, session) = await show(YouHouseBoardsView(model: m))
        #expect(m.boards?.count == 2)
        server.on("PATCH", "/api/boards/3", json: YouFixtures.boards)
        await m.change(3, .init(canEdit: false), session)
        await host.settle()
        #expect(m.saved == 3)
        m.code = "ZZZZZZ"
        server.fail("POST", "/api/boards", status: 404, "No screen is showing that code.")
        await m.pair(session)
        server.fail("DELETE", "/api/boards/4", status: 404, "No such board.")
        await m.remove(4, session)
        await host.settle()
        #expect(m.pairError != nil && m.actError != nil)
        m.ask(try #require(m.boards?.last))
        await host.settle()
        m.confirmRemove = nil
        await host.settle()
        host.close()
        server.fail("GET", "/api/boards", status: 500, "luach is resting")
        let bad = YouBoardsModel()
        let (badHost, _) = await show(YouHouseBoardsView(model: bad))
        #expect(bad.loadError != nil)
        badHost.close()
    }
}
