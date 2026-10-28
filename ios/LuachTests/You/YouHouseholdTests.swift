import Foundation
import Testing
import UIKit
@testable import Luach

/// Members: inviting, revoking and removing (none of which may run on dev).
@MainActor
struct YouMembersTests {
    let server = StubServer()

    private func loaded(invites: [[String: Any]] = []) async -> (YouMembersModel, AppSession) {
        let session = await YouFixtures.session(server)
        var reply = YouFixtures.members
        reply["invites"] = invites
        server.on("GET", "/api/members", json: reply)
        let m = YouMembersModel()
        await m.load(session)
        return (m, session)
    }

    @Test func theHouseholdAndItsInvitations() async {
        let (m, _) = await loaded(invites: YouFixtures.invites)
        #expect(m.data?.members.map(\.username) == ["robin", "smoke"] && m.data?.invites.count == 2 && m.error == nil)
    }

    @Test func anInvitationLineSaysWhenItEnds() throws {
        let invites = try YouFixtures.decode([YouKit.Invite].self, YouFixtures.invites)
        #expect(YouMembersModel.inviteLine(invites[1]).hasPrefix("Expired · sent "))
        let fresh = YouKit.Invite(email: "a@example.com", createdAt: Date.now.addingTimeInterval(-86_400).ISO8601Format(),
                                  expiresAt: Date.now.addingTimeInterval(6 * 86_400 + 60).ISO8601Format(), expired: false)
        let line = YouMembersModel.inviteLine(fresh)
        #expect(line.hasPrefix("Expires in ") && line.contains(" · sent "))
    }

    @Test func invitingSendsTheAddressAndListsAgain() async throws {
        let (m, session) = await loaded()
        #expect(!m.canInvite)
        m.email = "  new@example.com "
        #expect(m.canInvite)
        server.on("POST", "/api/members/invite", json: ["sent": true])
        await m.invite(session)
        let sent = try #require(server.requests("POST", "/api/members/invite").first)
        #expect(sent.json as? [String: String] == ["email": "new@example.com"])
        #expect(m.result?.sent == true && m.result?.link == nil && m.email.isEmpty && !m.inviting)
        #expect(server.requests("GET", "/api/members").count == 2, "the list again")
    }

    @Test func withoutMailTheLinkIsGivenToShare() async {
        let (m, session) = await loaded()
        m.email = "new@example.com"
        server.on("POST", "/api/members/invite", json: ["sent": false, "link": "https://luach.example.com/invite/abc"])
        await m.invite(session)
        #expect(m.result?.sent == false && m.result?.link == "https://luach.example.com/invite/abc" && !m.copied)
        m.copy("https://luach.example.com/invite/abc")
        #expect(m.copied && UIPasteboard.general.string == "https://luach.example.com/invite/abc")
        // A new invitation starts over.
        m.email = "other@example.com"
        server.fail("POST", "/api/members/invite", status: 400, "That address is already a member.")
        await m.invite(session)
        #expect(m.result == nil && !m.copied && m.inviteError == "That address is already a member." && m.email == "other@example.com")
    }

    @Test func aBlankAddressInvitesNoOne() async {
        let (m, session) = await loaded()
        m.email = "   "
        await m.invite(session)
        #expect(server.requests("POST", "/api/members/invite").isEmpty)
    }

    @Test func removingAMemberAsksThenDeletesThem() async throws {
        let (m, session) = await loaded()
        let smoke = try #require(m.data?.members.last)
        m.ask(smoke)
        #expect(m.confirmRemove?.id == 2 && m.actError == nil)
        server.on("DELETE", "/api/members/2", json: ["ok": true])
        await m.remove(2, session)
        #expect(server.requests("DELETE", "/api/members/2").count == 1 && m.confirmRemove == nil)
        #expect(server.requests("GET", "/api/members").count == 2 && !m.busy)
    }

    @Test func theOwnerCannotBeRemoved() async {
        let (m, session) = await loaded()
        server.fail("DELETE", "/api/members/1", status: 400, "The owner cannot be removed.")
        await m.remove(1, session)
        #expect(m.actError == "The owner cannot be removed.")
        m.ask(m.data!.members[0])
        #expect(m.actError == nil, "asking again clears it")
    }

    @Test func revokingAnInvitation() async {
        let (m, session) = await loaded(invites: YouFixtures.invites)
        server.on("DELETE", "/api/members/invite/new@example.com", json: ["ok": true, "revoked": 1])
        await m.revoke("new@example.com", session)
        #expect(server.requests("DELETE", "/api/members/invite/new@example.com").count == 1 && m.actError == nil)
        server.fail("DELETE", "/api/members/invite/gone@example.com", status: 404, "No invitation is waiting for that address.")
        await m.revoke("gone@example.com", session)
        #expect(m.actError == "No invitation is waiting for that address.")
    }

    @Test func notTheOwnerSaysSo() async {
        let session = await YouFixtures.session(server)
        server.fail("GET", "/api/members", status: 403, "Only the owner manages members.")
        let m = YouMembersModel()
        await m.load(session)
        #expect(m.error == "Only the owner manages members." && m.data == nil)
    }
}

/// The family: adding someone, and one person's changes.
@MainActor
struct YouFamilyTests {
    let server = StubServer()

    @Test func addingAChildPostsTheNameAndKind() async throws {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/family", json: YouFixtures.family)
        let m = YouFamilyModel()
        await m.load(session)
        #expect(m.family?.people.count == 3 && !m.canAdd)
        m.name = "  Noa "
        m.kid = true
        #expect(m.canAdd)
        server.on("POST", "/api/family", json: ["key": "noa", "name": "Noa", "color": "5", "kind": "kid", "email": "",
                                                "user_id": NSNull(), "position": 4, "hex": "#f6bf26"])
        let made = await m.add(session)
        let sent = try #require(server.requests("POST", "/api/family").first)
        #expect(sent.json as? [String: String] == ["name": "Noa", "kind": "kid"])
        #expect(made?.key == "noa" && m.name.isEmpty && !m.kid && !m.adding)
        #expect(server.requests("GET", "/api/family").count == 2)
    }

    @Test func aGrownUpIsAnAdult() async {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/family", json: YouFixtures.family)
        server.on("POST", "/api/family", json: YouFixtures.ruby)
        let m = YouFamilyModel()
        m.name = "Dana"
        await m.add(session)
        #expect(server.requests("POST", "/api/family").first?.json["kind"] as? String == "adult")
    }

    @Test func aRefusedAdditionKeepsTheName() async {
        let session = await YouFixtures.session(server)
        server.fail("POST", "/api/family", status: 403, "Only the owner changes the family.")
        let m = YouFamilyModel()
        m.name = "Noa"
        #expect(await m.add(session) == nil)
        #expect(m.addError == "Only the owner changes the family." && m.name == "Noa")
    }

    @Test func aFamilyThatWillNotLoadSaysWhy() async {
        let session = await YouFixtures.session(server)
        server.fail("GET", "/api/family", status: 500, "luach is resting")
        let m = YouFamilyModel()
        await m.load(session)
        #expect(m.loadError == "luach is resting" && m.family == nil)
    }

    private func ruby() throws -> (YouPersonModel, () -> Int) {
        var calls = 0
        let person = try YouFixtures.decode(YouKit.Person.self, YouFixtures.ruby)
        let m = YouPersonModel(person: person) { calls += 1 }
        return (m, { calls })
    }

    @Test func aColourIsSavedOnItsOwn() async throws {
        let session = await YouFixtures.session(server)
        let (m, calls) = try ruby()
        var changed = YouFixtures.ruby
        changed["color"] = "5"
        changed["hex"] = "#f6bf26"
        server.on("PATCH", "/api/family/ruby", json: changed)
        await m.save(.init(color: "5"), session)
        let sent = try #require(server.requests("PATCH", "/api/family/ruby").first)
        #expect(sent.json as? [String: String] == ["color": "5"], "only the colour")
        #expect(m.person.color == "5" && calls() == 1 && !m.busy && m.error == nil)
    }

    @Test func anAddressIsSavedTrimmed() async throws {
        let session = await YouFixtures.session(server)
        let (m, _) = try ruby()
        #expect(!m.emailChanged)
        m.email = " ruby@example.com "
        #expect(m.emailChanged)
        var changed = YouFixtures.ruby
        changed["email"] = "ruby@example.com"
        server.on("PATCH", "/api/family/ruby", json: changed)
        await m.saveEmail(session)
        #expect(server.requests("PATCH", "/api/family/ruby").first?.json as? [String: String] == ["email": "ruby@example.com"])
        #expect(m.email == "ruby@example.com" && !m.emailChanged)
    }

    @Test func childOrNot() async throws {
        let session = await YouFixtures.session(server)
        let (m, _) = try ruby()
        var grown = YouFixtures.ruby
        grown["kind"] = "adult"
        server.on("PATCH", "/api/family/ruby", json: grown)
        await m.save(.init(kind: "adult"), session)
        #expect(server.requests("PATCH", "/api/family/ruby").first?.json as? [String: String] == ["kind": "adult"])
        #expect(!m.person.isKid)
    }

    @Test func aRefusedChangeKeepsThePerson() async throws {
        let session = await YouFixtures.session(server)
        let (m, calls) = try ruby()
        server.fail("PATCH", "/api/family/ruby", status: 400, "That address belongs to a member.")
        m.email = "robin@example.com"
        await m.saveEmail(session)
        #expect(m.error == "That address belongs to a member." && m.person.email.isEmpty && calls() == 0)
        #expect(m.email == "robin@example.com")
    }

    @Test func removingAsksThenDeletes() async throws {
        let session = await YouFixtures.session(server)
        let (m, calls) = try ruby()
        server.fail("DELETE", "/api/family/ruby", status: 403, "Only the owner changes the family.")
        #expect(await m.remove(session) == false)
        #expect(m.error == "Only the owner changes the family.")
        m.askRemove()
        #expect(m.confirmRemove && m.error == nil)
        server.on("DELETE", "/api/family/ruby", json: ["ok": true])
        #expect(await m.remove(session))
        #expect(calls() == 1 && !m.busy)
    }
}

/// House boards: pairing, settings and removing (dev has none, and pairing needs a screen).
@MainActor
struct YouBoardsTests {
    let server = StubServer()

    private func loaded() async -> (YouBoardsModel, AppSession) {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/boards", json: YouFixtures.boards)
        let m = YouBoardsModel()
        await m.load(session)
        return (m, session)
    }

    @Test func theBoardsLoad() async {
        let (m, _) = await loaded()
        #expect(m.boards?.map(\.name) == ["Kitchen", "Hall"] && m.loadError == nil && m.name == "Kitchen")
    }

    @Test func boardsThatWillNotLoadAreSaidOutLoud() async {
        let session = await YouFixtures.session(server)
        server.fail("GET", "/api/boards", status: 500, "luach is resting")
        let m = YouBoardsModel()
        await m.load(session)
        #expect(m.loadError == "luach is resting" && m.boards == nil)
        server.fail("GET", "/api/boards", status: 500, "")
        await m.load(session)
        #expect(m.loadError == "Could not load the boards.", "never an empty line")
    }

    @Test func eachSettingIsPatchedOnItsOwn() async throws {
        let (m, session) = await loaded()
        server.on("PATCH", "/api/boards/3", json: YouFixtures.boards)
        await m.change(3, .init(canEdit: false), session)
        #expect(server.requests("PATCH", "/api/boards/3").last?.json as? [String: Bool] == ["can_edit": false])
        #expect(m.saved == 3 && !m.busy)
        await m.change(3, .init(language: "he"), session)
        #expect(server.requests("PATCH", "/api/boards/3").last?.json as? [String: String] == ["language": "he"])

        server.fail("PATCH", "/api/boards/4", status: 400, "language must be auto, en, es or he")
        await m.change(4, .init(language: "fr"), session)
        #expect(m.actError == "language must be auto, en, es or he" && m.saved == nil)
    }

    @Test func pairingSendsTheCodeAndName() async throws {
        let (m, session) = await loaded()
        #expect(!m.canPair)
        m.code = "k7p3qx"
        m.upperCode()
        #expect(m.code == "K7P3QX" && m.canPair)
        m.name = " Hall "
        server.on("POST", "/api/boards", json: ["id": 5, "name": "Hall"])
        await m.pair(session)
        let sent = try #require(server.requests("POST", "/api/boards").first)
        #expect(sent.json as? [String: String] == ["code": "K7P3QX", "name": "Hall"])
        #expect(m.code.isEmpty && !m.pairing && server.requests("GET", "/api/boards").count == 2)
    }

    @Test func aWrongCodeKeepsIt() async {
        let (m, session) = await loaded()
        m.code = "ZZZZZZ"
        server.fail("POST", "/api/boards", status: 404, "No screen is showing that code.")
        await m.pair(session)
        #expect(m.pairError == "No screen is showing that code." && m.code == "ZZZZZZ")
    }

    @Test func removingAsksThenDeletes() async throws {
        let (m, session) = await loaded()
        let hall = try #require(m.boards?.last)
        m.ask(hall)
        #expect(m.confirmRemove?.id == 4)
        server.on("DELETE", "/api/boards/4", json: ["ok": true])
        await m.remove(4, session)
        #expect(server.requests("DELETE", "/api/boards/4").count == 1 && m.confirmRemove == nil && m.actError == nil)
        server.fail("DELETE", "/api/boards/9", status: 404, "No such board.")
        await m.remove(9, session)
        #expect(m.actError == "No such board.")
    }
}
