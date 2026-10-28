import Foundation
import SwiftUI
import Testing
@testable import Luach

/// The shapes the You screens read, and the words and times they share.
@MainActor
struct YouKitTests {
    // MARK: Shapes

    @Test func meDecodesTheMemberAndTheFieldsItLeavesOut() throws {
        let me = try YouFixtures.decode(YouKit.Me.self, YouFixtures.me(["model": "cloud-deepseek-v4-flash",
                                                                         "notify_emails": ["work@example.com"],
                                                                         "notify_pending": ["new@example.com"]]))
        #expect(me.member.id == 1 && me.member.name == "Robin" && me.member.isOwner == true)
        #expect(me.member.timezone == "America/New_York" && me.member.language == "auto")
        #expect(me.model == "cloud-deepseek-v4-flash")
        #expect(me.emails == ["robin@example.com", "robin@work.example.com"])
        #expect(me.notifyEmails == ["work@example.com"] && me.notifyPending == ["new@example.com"])
    }

    @Test func anOlderMeWithoutTheExtrasStillDecodes() throws {
        let me = try YouFixtures.decode(YouKit.Me.self, ["id": 2, "username": "ana", "model": NSNull(), "emails": "not a list"])
        #expect(me.member.name == "ana" && me.model.isEmpty && me.emails.isEmpty)
        #expect(me.notifyEmails.isEmpty && me.notifyPending.isEmpty)
    }

    @Test func theModelMenuDecodesWithAndWithoutACatalogue() throws {
        let menu = try YouFixtures.decode(YouKit.ModelMenu.self, YouFixtures.models)
        #expect(menu.default == "qwen3.6-35b")
        #expect(menu.catalogue?.map(\.id) == ["qwen3.6-35b", "cloud-deepseek-v4-flash", "openrouter/google/gemini-3.8-flash"])
        #expect(menu.catalogue?[1].about.hasPrefix("A fast cloud model") == true)
        let bare = try YouFixtures.decode(YouKit.ModelMenu.self, ["models": ["x"]])
        #expect(bare.catalogue == nil && bare.default == nil && bare.configured == nil)
    }

    @Test func theModelMenuSaysWhereEachRunsAndWhetherItAnswers() throws {
        let menu = try YouFixtures.decode(YouKit.ModelMenu.self, YouFixtures.modelsOneDown)
        #expect(menu.configured == true)
        let models = try #require(menu.catalogue)
        #expect(!models[0].local && models[0].provider == "DeepSeek" && models[0].answering && models[0].health == .ok)
        #expect(models[1].local && models[1].provider.isEmpty)
        let down = models[2]
        #expect(!down.answering && down.health.status == "not_answering")
        #expect(down.health.since == "2026-10-28T08:00:00+00:00" && down.health.reason == "its provider refused it — 404")
    }

    @Test func anOlderMenuIsTakenAsOutsideTheHouseAndAnswering() throws {
        // Nothing said of where a model runs: it is not taken to be at home, so the member is asked.
        let menu = try YouFixtures.decode(YouKit.ModelMenu.self, YouFixtures.olderModels)
        let models = try #require(menu.catalogue)
        #expect(models.allSatisfy { !$0.local && $0.provider.isEmpty && $0.answering })
        let odd = try YouFixtures.decode(YouKit.ModelMenu.Choice.self, ["id": "x", "name": "", "local": "yes", "health": ["since": 3]])
        #expect(odd.name == "x" && odd.about.isEmpty && !odd.local && odd.health.status == "ok" && odd.health.since == nil)
        #expect(odd.health.reason.isEmpty && odd.answering)
    }

    @Test func theEmailListingDecodes() throws {
        let l = try YouFixtures.decode(YouKit.EmailListing.self, YouFixtures.emails)
        #expect(l.primary == "robin@example.com" && l.emails.count == 2)
        #expect(l.emails[1].addedAt == "2026-09-22T03:38:49.637740+00:00" && l.emails[1].verified == true)
        let older = try YouFixtures.decode(YouKit.EmailListing.self, ["primary": "a@example.com", "emails": [["email": "a@example.com"]]])
        #expect(older.emails[0].verified == nil && older.emails[0].addedAt == nil)
    }

    @Test func memoryAndPasskeysDecode() throws {
        let m = try YouFixtures.decode(YouKit.MemoryListing.self, YouFixtures.memory)
        #expect(m.facts.map(\.id) == ["chores"] && m.facts[0].topic == "chores" && m.facts[0].savedAt != nil)
        let p = try YouFixtures.decode(YouKit.PasskeyListing.self, YouFixtures.passkeys)
        #expect(p.passkeys.map(\.id) == ["pk1", "pk2"] && p.passkeys[1].lastUsed == nil && p.passkeys[0].createdAt != nil)
    }

    @Test func membersDecodeWithEveryAddressPrimaryFirst() throws {
        var json = YouFixtures.members
        json["invites"] = YouFixtures.invites
        let r = try YouFixtures.decode(YouKit.MembersReply.self, json)
        #expect(r.members.map(\.name) == ["Robin", "Smoke test"])
        #expect(r.members[0].allEmails == ["robin@example.com", "robin@work.example.com"])
        #expect(r.members[1].isOwner == false && r.members[1].lastSeen != nil)
        #expect(r.invites.map(\.email) == ["new@example.com", "old@example.com"] && r.invites[1].expired)
        #expect(r.invites[0].id == "new@example.com-2026-10-25T10:00:00+00:00")

        let older = try YouFixtures.decode(YouKit.Housemate.self, ["id": 3, "username": "ana", "email": "ana@example.com", "display_name": ""])
        #expect(older.name == "ana" && older.allEmails == ["ana@example.com"])
        let none = try YouFixtures.decode(YouKit.Housemate.self, ["id": 4, "username": "kid"])
        #expect(none.allEmails.isEmpty)
    }

    @Test func theFamilyDecodesAndNamesAnExample() throws {
        let f = try YouFixtures.decode(YouKit.Family.self, YouFixtures.family)
        #expect(f.people.map(\.id) == ["robin", "ruby", "lily"] && f.colors.count == 11)
        #expect(f.people[0].userId == 1 && !f.people[0].isKid && f.people[1].isKid && f.people[1].userId == nil)
        #expect(f.people[2].position == 3 && f.colors[6].hex == "#039be5")
        #expect(f.exampleName == "Ruby", "a child's name first")
        let grownUps = YouKit.Family(people: [f.people[0]], colors: [])
        #expect(grownUps.exampleName == "Robin")
        #expect(YouKit.Family(people: [], colors: []).exampleName == "someone")
    }

    @Test func boardsDecode() throws {
        let b = try YouFixtures.decode(YouKit.BoardList.self, YouFixtures.boards)
        #expect(b.boards.map(\.id) == [3, 4] && b.boards[1].lastSeen == nil)
        #expect(b.boards[0].canEdit == true && b.boards[1].canEdit == false && b.boards[1].language == "he")
    }

    // MARK: Words

    @Test func theLanguagesAreTheWebs() {
        #expect(YouKit.languages.map(\.value) == ["auto", "en", "es", "he"])
        #expect(YouKit.languages.map(\.label) == ["Automatic", "English", "Español", "עברית"])
    }

    @Test(arguments: [
        ("  Work@Example.com ", "work@example.com"),
        ("a@example.com,", "a@example.com"),
        ("a@example.com;", "a@example.com"),
        ("\nA@B.CO\t", "a@b.co"),
        ("", ""),
    ])
    func addressesAreCleanedAsTheWebDoes(typed: String, clean: String) {
        #expect(YouKit.cleanEmail(typed) == clean)
    }

    @Test(arguments: [
        ("a@example.com", true), ("first.last+tag@sub.example.co.uk", true),
        ("a@example", false), ("not an email", false), ("@example.com", false),
        ("a@@example.com", false), ("a b@example.com", false), ("", false),
    ])
    func whatCountsAsAnAddress(text: String, valid: Bool) {
        #expect(YouKit.isEmail(text) == valid)
    }

    // MARK: Times

    @Test func luachsTimesReadWithAndWithoutAnOffset() throws {
        let micro = try #require(YouKit.date("2026-10-27T15:21:43.619628+00:00"))
        let z = try #require(YouKit.date("2026-10-27T15:21:43Z"))
        let naive = try #require(YouKit.date("2026-10-27T15:21:43"))
        let offset = try #require(YouKit.date("2026-10-27T11:21:43-04:00"))
        #expect(abs(micro.timeIntervalSince(z) - 0.619628) < 0.001)
        #expect(z == naive && naive == offset)
        #expect(YouKit.date(nil) == nil && YouKit.date("") == nil && YouKit.date("yesterday") == nil)
    }

    @Test func agoAndInSayWhen() {
        #expect(YouKit.relative(nil) == "never" && YouKit.relative("") == "never")
        #expect(YouKit.relative("whenever") == "whenever", "what cannot be read is shown as it came")
        let past = Date.now.addingTimeInterval(-3 * 86_400).ISO8601Format()
        let future = Date.now.addingTimeInterval(6 * 86_400 + 60).ISO8601Format()
        #expect(YouKit.relative(past).contains("ago"))
        #expect(YouKit.relative(future).hasPrefix("in "))
    }

    @Test func timestampsAreInTheMembersZone() {
        let ny = YouKit.timestamp("2026-10-26T14:07:00+00:00", zone: "America/New_York")
        let tlv = YouKit.timestamp("2026-10-26T14:07:00+00:00", zone: "Asia/Jerusalem")
        #expect(ny.contains("10:07") && ny.contains("Oct") && ny.contains("26"))
        #expect(tlv.contains("16:07") || tlv.contains("4:07"))
        #expect(!YouKit.timestamp("2026-10-26T14:07:00Z", zone: "Not/AZone").isEmpty)
        #expect(!YouKit.timestamp("2026-10-26T14:07:00Z", zone: nil).isEmpty)
        #expect(YouKit.timestamp(nil, zone: "UTC") == "")
        #expect(YouKit.timestamp("soon", zone: "UTC") == "soon")
    }

    @Test func familyColoursComeFromTheirHex() {
        let env = EnvironmentValues()
        #expect(Color(youHex: "#039be5").resolve(in: env).description == "#039BE5FF")
        #expect(Color(youHex: "f4511e").resolve(in: env).description == "#F4511EFF")
        #expect(Color(youHex: "not a colour").resolve(in: env).description == "#888888FF")
    }

    @Test func debugValuesAreLaunchArguments() {
        UserDefaults.standard.set("family", forKey: "ios-test-youPush")
        defer { UserDefaults.standard.removeObject(forKey: "ios-test-youPush") }
        #expect(YouDebug.value("ios-test-youPush") == "family")
        #expect(YouDebug.value("ios-test-nothing") == nil)
    }
}
