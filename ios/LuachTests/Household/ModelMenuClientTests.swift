import Foundation
import Testing
@testable import Luach

/// Every call the owner's model menu makes, against a stub luach: the method and path, the JSON
/// body it sends (with its Content-Type, which the server's CSRF check will require), what it
/// reads back, and the server's sentence when it refuses.
@MainActor
struct ModelMenuClientTests {
    typealias H = HouseholdArea
    typealias F = ModelMenuFixtures
    let server = StubServer()
    var client: H.Client { H.Client(api: server.api) }

    private func refuses(_ status: Int, _ sentence: String, _ call: () async throws -> Void) async {
        await #expect {
            try await call()
        } throws: { error in
            (error as? APIError)?.status == status && error.localizedDescription == sentence
        }
    }

    /// The one request sent to `method path`, which carried JSON.
    private func sent(_ method: String, _ path: String) throws -> StubServer.Request {
        let all = server.requests(method, path)
        #expect(all.count == 1)
        let req = try #require(all.first)
        #expect(req.headers["Content-Type"] == "application/json", "\(method) \(path) sent no JSON Content-Type")
        return req
    }

    @Test func theListIsRead() async throws {
        server.on("GET", "/api/models/manage", json: F.snapshot())
        let snap = try await client.manageModels()
        #expect(snap.models.count == 3)
        #expect(server.requests("GET", "/api/models/manage").first?.body.isEmpty == true)
    }

    @Test func addingSendsTheIdAndTheOwnersWords() async throws {
        var reply = F.snapshot(trial: F.trial(model: "acme/tiny"))
        reply["added"] = "acme/tiny"
        reply["trial_started"] = true
        reply["note"] = ""
        server.on("POST", "/api/models/manage", json: reply)
        let added = try await client.addModel(.init(id: "acme/tiny", name: "Tiny", about: "Small.", local: false, provider: "Acme", try: true))
        #expect(added.added == "acme/tiny" && added.trialStarted)
        let req = try sent("POST", "/api/models/manage")
        #expect(req.json as NSDictionary == ["id": "acme/tiny", "name": "Tiny", "about": "Small.", "local": false, "provider": "Acme", "try": true])
    }

    @Test func eachChangeSendsItsBody() async throws {
        for (method, path) in [("PATCH", "/api/models/manage"), ("POST", "/api/models/manage/remove"),
                               ("PUT", "/api/models/manage/order"), ("PUT", "/api/models/manage/default")] {
            server.on(method, path, json: F.snapshot())
        }
        _ = try await client.changeModel(.init(id: "a/b", name: "B", enabled: false))
        _ = try await client.removeModel("a/b")
        _ = try await client.reorderModels(["b", "a"])
        _ = try await client.makeDefault("a/b")
        #expect(try sent("PATCH", "/api/models/manage").json as NSDictionary == ["id": "a/b", "name": "B", "enabled": false])
        #expect(try sent("POST", "/api/models/manage/remove").json as NSDictionary == ["id": "a/b"])
        #expect(try sent("PUT", "/api/models/manage/order").json as NSDictionary == ["ids": ["b", "a"]])
        #expect(try sent("PUT", "/api/models/manage/default").json as NSDictionary == ["id": "a/b"])
    }

    @Test func theTrialIsStartedReadCancelled() async throws {
        server.on("POST", "/api/models/manage/trial", json: ["trial": F.trial(), "trials_left_today": 4])
        server.on("GET", "/api/models/manage/trial", json: ["trial": F.trial(done: 5), "trials_left_today": 4])
        server.on("POST", "/api/models/manage/trial/cancel", json: ["cancelled": true, "trial": F.trial(status: "cancelled")])
        let started = try await client.startTrial("deepseek/deepseek-v4-flash")
        #expect(started.trial?.running == true && started.trialsLeftToday == 4)
        #expect(try sent("POST", "/api/models/manage/trial").json as NSDictionary == ["id": "deepseek/deepseek-v4-flash"])
        #expect(try await client.trial().trial?.done == 5)
        let cancelled = try await client.cancelTrial()
        #expect(cancelled.cancelled && cancelled.trial?.status == "cancelled")
        #expect(try sent("POST", "/api/models/manage/trial/cancel").json.isEmpty, "an empty JSON object")
    }

    @Test func aCheckAsksOneModel() async throws {
        server.on("POST", "/api/models/manage/check", json: ["ok": true, "reason": "", "health": F.ok, "models": [F.home]])
        let reply = try await client.checkModel("qwen3.6-35b")
        #expect(reply.ok && reply.models?.first?.id == "qwen3.6-35b")
        #expect(try sent("POST", "/api/models/manage/check").json as NSDictionary == ["id": "qwen3.6-35b"])
    }

    @Test func theCatalogueIsSearchedWithTheWordsTrimmed() async throws {
        server.on("GET", "/api/models/catalogue", json: F.catalogue)
        _ = try await client.catalogue("")
        _ = try await client.catalogue("  deepseek flash \n")
        _ = try await client.catalogue(String(repeating: "x", count: 150))
        let asked = server.requests("GET", "/api/models/catalogue")
        #expect(asked.count == 3)
        #expect(asked[0].query.isEmpty, "no words: the whole list")
        #expect(asked[1].query == ["q": "deepseek flash"])
        #expect(asked[2].query["q"]?.count == 100, "the server reads 100 characters at most")
    }

    @Test func refusalsAreTheServersSentences() async {
        server.fail("GET", "/api/models/manage", status: 403, "only the owner can do that")
        await refuses(403, "only the owner can do that") { _ = try await client.manageModels() }
        server.fail("POST", "/api/models/manage", status: 400, "that model is already on the list")
        await refuses(400, "that model is already on the list") { _ = try await client.addModel(.init(id: "a")) }
        server.fail("PATCH", "/api/models/manage", status: 400, "that is the household's default: choose another default first")
        await refuses(400, "that is the household's default: choose another default first") {
            _ = try await client.changeModel(.init(id: "a", enabled: false))
        }
        server.fail("POST", "/api/models/manage/trial", status: 409, "a trial is already running; wait for it or cancel it")
        await refuses(409, "a trial is already running; wait for it or cancel it") { _ = try await client.startTrial("a") }
        server.fail("PUT", "/api/models/manage/default", status: 400, "that model is not answering: check it, or choose another")
        await refuses(400, "that model is not answering: check it, or choose another") { _ = try await client.makeDefault("a") }
        server.fail("POST", "/api/models/manage/check", status: 404, "that model is not on the list")
        await refuses(404, "that model is not on the list") { _ = try await client.checkModel("a") }
        server.fail("GET", "/api/models/catalogue", status: 403, "the model menu is changed by the owner, signed in")
        await refuses(403, "the model menu is changed by the owner, signed in") { _ = try await client.catalogue("x") }
    }
}
