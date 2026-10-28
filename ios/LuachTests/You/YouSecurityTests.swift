import Foundation
import Testing
@testable import Luach

/// Passkeys: listing and removing (removing never runs on dev).
@MainActor
struct YouPasskeysTests {
    let server = StubServer()

    private func loaded() async -> (YouPasskeysModel, AppSession) {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/auth/passkeys", json: YouFixtures.passkeys)
        let m = YouPasskeysModel()
        await m.load(session)
        return (m, session)
    }

    @Test func theListAndHowEachIsNamed() async throws {
        let (m, _) = await loaded()
        let list = try #require(m.list)
        #expect(list.map(\.id) == ["pk1", "pk2"] && m.loadError == nil)
        #expect(YouPasskeysModel.name(list[0]) == "iPhone")
        #expect(YouPasskeysModel.name(list[1]) == "Passkey", "a passkey made without a name")
        let used = YouPasskeysModel.detail(list[0], zone: "America/New_York")
        #expect(used.hasPrefix("Added Oct 1") || used.hasPrefix("Added 1 Oct"))
        #expect(used.contains("10:07") && used.contains(" · used "))
        #expect(YouPasskeysModel.detail(list[1], zone: nil).hasSuffix(" · never used"))
    }

    @Test func removingAsksThenDeletesThatOne() async throws {
        let (m, session) = await loaded()
        let key = try #require(m.list?.first)
        server.fail("DELETE", "/api/auth/passkeys/nope", status: 404, "That passkey is not yours.")
        await m.remove("nope", session)
        #expect(m.error == "That passkey is not yours." && m.list?.count == 2)
        m.ask(key)
        #expect(m.confirm?.id == "pk1" && m.error == nil)
        server.on("DELETE", "/api/auth/passkeys/pk1", json: ["ok": true, "passkeys": [(YouFixtures.passkeys["passkeys"] as! [Any])[1]]])
        await m.remove("pk1", session)
        #expect(server.requests("DELETE", "/api/auth/passkeys/pk1").count == 1)
        #expect(m.list?.map(\.id) == ["pk2"] && m.confirm == nil && !m.busy)
    }

    @Test func aListThatWillNotLoadSaysWhy() async {
        let session = await YouFixtures.session(server)
        server.fail("GET", "/api/auth/passkeys", status: 500, "luach is resting")
        let m = YouPasskeysModel()
        await m.load(session)
        #expect(m.loadError == "luach is resting" && m.list == nil)
    }
}

/// The password form: its own checks, and the one call (never made on dev).
@MainActor
struct YouPasswordTests {
    let server = StubServer()

    @Test func theButtonWaitsForAllThreeFields() {
        let m = YouPasswordModel()
        #expect(!m.filled)
        m.current = "old"
        m.next = "new"
        #expect(!m.filled)
        m.confirm = "new"
        #expect(m.filled)
    }

    @Test func twoDifferentNewPasswordsAreNotSent() async {
        let m = YouPasswordModel()
        m.current = "old password"
        m.next = "correct horse"
        m.confirm = "correct house"
        await m.submit(AppSession(api: server.api))
        #expect(m.error == "The two new passwords do not match." && !m.done && server.requests.isEmpty)
    }

    @Test func aShortNewPasswordIsNotSent() async {
        let m = YouPasswordModel()
        m.current = "old password"
        m.next = "short"
        m.confirm = "short"
        await m.submit(AppSession(api: server.api))
        #expect(m.error == "The new password must be at least 8 characters." && server.requests.isEmpty)
        m.next = "12345678"
        m.confirm = "12345678"
        #expect(m.problem == nil, "eight is enough")
    }

    @Test func aGoodChangeIsPostedAndTheFormCleared() async throws {
        let m = YouPasswordModel()
        server.on("POST", "/api/auth/password", json: ["ok": true])
        m.current = "old password"
        m.next = "correct horse"
        m.confirm = "correct horse"
        await m.submit(AppSession(api: server.api))
        let sent = try #require(server.requests("POST", "/api/auth/password").first)
        #expect(sent.json as? [String: String] == ["current": "old password", "new": "correct horse"])
        #expect(m.done && m.error == nil && !m.busy && m.current.isEmpty && m.next.isEmpty && m.confirm.isEmpty)
        m.edited()
        #expect(m.done, "the cleared form is not an edit")
        m.current = "a"
        m.edited()
        #expect(!m.done, "typing again takes the line away")
    }

    @Test func aWrongCurrentPasswordIsTheServersSentence() async {
        let m = YouPasswordModel()
        server.fail("POST", "/api/auth/password", status: 400, "Your current password is not right.")
        m.current = "guess"
        m.next = "correct horse"
        m.confirm = "correct horse"
        await m.submit(AppSession(api: server.api))
        #expect(m.error == "Your current password is not right." && !m.done && m.current == "guess")
    }
}

/// The audit trail: read raw so payload keys stay as luach wrote them.
@MainActor
@Suite(.serialized)
struct YouAuditTests {
    let server = StubServer()

    init() {
        // The trail is fetched with URLSession.shared (see YouAuditTrail.fetch); the stub
        // answers only its own hosts, so registering it globally changes nothing else.
        URLProtocol.registerClass(StubProtocol.self)
    }

    private func data(_ json: Any) throws -> Data { try JSONSerialization.data(withJSONObject: json) }

    @Test func newestFirstWithTheChainState() throws {
        let t = try YouAuditTrail.parse(data(YouFixtures.audit))
        #expect(t.entries.map(\.seq) == [214, 213, 212] && t.entries[0].id == 214)
        #expect(t.total == 217 && t.verified && t.head.hasPrefix("15a5b993"))
        #expect(t.entries[0].eventType == "turn.end" && t.entries[0].ts == "2026-10-20T08:41:03.902215+00:00")
        #expect(t.entries[0].hash.hasPrefix("417c3f68"))
        #expect(t.entries[0].fields.map(\.key) == ["held", "thread", "tools"], "keys sorted")
        #expect(t.entries[0].compact == "held=0  thread=1e6285ae67dd8267ab6500d218824c0a  tools=1")
        #expect(t.entries[1].compact == "by=smoke  door=web  id=43  person=lily", "the first four")
    }

    @Test func payloadValuesAreShownAsTheWebShowsThem() throws {
        let t = try YouAuditTrail.parse(data([
            "entries": [["seq": 1, "event_type": "event.created", "payload": [
                "by_who": "robin", "ok": true, "none": NSNull(), "empty": "", "list": [1, "a/b"],
                "nested": ["z": 1, "a": ["k": "v"]], "long": String(repeating: "x", count: 60),
            ]]],
        ]))
        let e = try #require(t.entries.first)
        let fields = Dictionary(uniqueKeysWithValues: e.fields.map { ($0.key, $0.value) })
        #expect(fields["by_who"] == "robin", "keys are not camel-cased")
        #expect(fields["ok"] == "true" && fields["none"] == "" && fields["empty"] == "")
        #expect(fields["list"] == #"[1,"a/b"]"#)
        #expect(fields["nested"] == #"{"a":{"k":"v"},"z":1}"#)
        #expect(e.compact == "by_who=robin  list=[1,\"a/b\"]  long=\(String(repeating: "x", count: 48))…  nested={\"a\":{\"k\":\"v\"},\"z\":1}")
        #expect(t.total == 1 && !t.verified && t.head.isEmpty && e.ts.isEmpty && e.hash.isEmpty)
    }

    @Test func emptyAndOddAnswers() throws {
        let t = try YouAuditTrail.parse(data(["entries": [["payload": "not a dict"]], "chain_verified": false]))
        #expect(t.entries.count == 1 && t.entries[0].seq == 0 && t.entries[0].fields.isEmpty && t.entries[0].compact.isEmpty)
        #expect(YouAuditTrail.text(42) == "42" && YouAuditTrail.text(nil) == "" && YouAuditTrail.text(NSNull()) == "")
        #expect(throws: APIError.self) { try YouAuditTrail.parse(Data("[1,2]".utf8)) }
    }

    @Test func fetchingAsksForTheLimit() async throws {
        server.on("GET", "/api/control/audit", json: YouFixtures.audit)
        let t = try await YouAuditTrail.fetch(server.api, limit: 50)
        #expect(t.entries.count == 3)
        #expect(server.requests("GET", "/api/control/audit").first?.query["limit"] == "50")
    }

    @Test func showOlderAsksFor50MoreUpTo200() async throws {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/control/audit", json: YouFixtures.audit)
        let m = YouAuditModel()
        #expect(!m.hasOlder)
        await m.load(session)
        #expect(m.trail?.entries.count == 3 && m.hasOlder && m.limit == 50)
        for _ in 0..<4 { await m.showOlder(session) }
        #expect(m.limit == 200 && !m.hasOlder)
        #expect(server.requests("GET", "/api/control/audit").map { $0.query["limit"] } == ["50", "100", "150", "200", "200"])
    }

    @Test func aTrailThatIsAllThereHasNothingOlder() async {
        let session = await YouFixtures.session(server)
        var all = YouFixtures.audit
        all["total"] = 3
        server.on("GET", "/api/control/audit", json: all)
        let m = YouAuditModel()
        await m.load(session)
        #expect(!m.hasOlder && m.error == nil)
    }

    @Test func notTheOwnerSaysSo() async {
        let session = await YouFixtures.session(server)
        server.fail("GET", "/api/control/audit", status: 403, "Only the owner reads the audit trail.")
        let m = YouAuditModel()
        await m.load(session)
        #expect(m.error == "Only the owner reads the audit trail." && m.trail == nil)
    }
}
