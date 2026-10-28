import Foundation
import Testing
@testable import Luach

/// What the Models screen does between the taps and the server: every answer replaces the
/// list; a refused change says why and leaves the list as it was; a drag shows at once and is
/// put back when refused; a running trial is followed until it ends, then the scores are read.
@MainActor
struct ModelMenuStateTests {
    typealias H = HouseholdArea
    typealias F = ModelMenuFixtures
    let server = StubServer()

    private func loaded(_ snapshot: [String: Any] = F.snapshot()) async -> HouseholdModelsModel {
        server.on("GET", "/api/models/manage", json: snapshot)
        let m = HouseholdModelsModel(api: server.api)
        m.pollEvery = .milliseconds(20)
        await m.load()
        return m
    }

    @Test func loadsTheListInOrder() async {
        let m = await loaded()
        #expect(m.models.map(\.name) == ["Home server · Qwen 3.6", "DeepSeek V4 Flash", "Gemini 3.8 Flash"])
        #expect(m.trialsLeft == 5 && m.trial == nil && m.running == nil && m.runningID == nil && m.shownTrial == nil)
        #expect(m.loadError == nil && m.model("qwen3.6-35b")?.isDefault == true && m.model("nope") == nil)
        #expect(m.canTry("deepseek/deepseek-v4-flash") && !m.canTry("nope"))
    }

    @Test func aListThatWillNotLoadSaysWhy() async {
        server.fail("GET", "/api/models/manage", status: 403, "only the owner can do that")
        let m = HouseholdModelsModel(api: server.api)
        await m.load()
        #expect(m.snapshot == nil && m.loadError == "only the owner can do that" && m.models.isEmpty && m.trialsLeft == 0)
    }

    @Test func noTrialsLeftOrOneRunningMeansNoTryIt() async {
        let none = await loaded(F.snapshot(left: 0))
        #expect(!none.canTry("qwen3.6-35b"))
        let busy = await loaded(F.snapshot(trial: F.trial()))
        #expect(!busy.canTry("qwen3.6-35b") && busy.runningID == 7 && busy.shownTrial?.id == 7 && busy.followed == 7)
        let old = await loaded(F.snapshot(trial: F.trial(status: "done", verdict: "good")))
        #expect(old.shownTrial == nil, "a run from before the screen opened is not shown")
        #expect(old.canTry("qwen3.6-35b"))
    }

    @Test func aChangeTakesTheAnswerAndARefusalSaysWhy() async {
        let m = await loaded()
        server.on("PATCH", "/api/models/manage", json: F.snapshot(models: [F.home, F.flash,
            F.model("openrouter/google/gemini-3.8-flash", name: "Gemini", enabled: true, position: 2)]))
        #expect(await m.setEnabled("openrouter/google/gemini-3.8-flash", true))
        #expect(m.model("openrouter/google/gemini-3.8-flash")?.enabled == true && m.error == nil && !m.working)
        #expect(server.requests("PATCH", "/api/models/manage").first?.json as NSDictionary? == ["id": "openrouter/google/gemini-3.8-flash", "enabled": true])

        server.fail("PATCH", "/api/models/manage", status: 400, "that is the household's default: choose another default first")
        #expect(!(await m.setEnabled("qwen3.6-35b", false)))
        #expect(m.error == "that is the household's default: choose another default first")
        #expect(m.model("qwen3.6-35b")?.enabled == true, "the list is as it was")

        server.on("PATCH", "/api/models/manage", json: F.snapshot())
        #expect(await m.save(.init(id: "qwen3.6-35b", name: "Home")))
        #expect(m.error == nil)
    }

    @Test func defaultAndRemove() async {
        let m = await loaded()
        server.on("PUT", "/api/models/manage/default", json: F.snapshot(models: [
            F.model("qwen3.6-35b", name: "Home", local: true, position: 0),
            F.model("deepseek/deepseek-v4-flash", name: "Flash", position: 1, isDefault: true),
        ], default: "deepseek/deepseek-v4-flash"))
        #expect(await m.makeDefault("deepseek/deepseek-v4-flash"))
        #expect(m.model("deepseek/deepseek-v4-flash")?.isDefault == true && m.snapshot?.default == "deepseek/deepseek-v4-flash")
        server.on("POST", "/api/models/manage/remove", json: F.snapshot(models: [F.home]))
        #expect(await m.remove("deepseek/deepseek-v4-flash"))
        #expect(m.models.map(\.id) == ["qwen3.6-35b"])
        server.fail("POST", "/api/models/manage/remove", status: 400, "that is the household's default: choose another default first")
        #expect(!(await m.remove("qwen3.6-35b")) && m.models.count == 1)
    }

    @Test func aDragShowsAtOnceAndIsSent() async throws {
        let m = await loaded()
        server.on("PUT", "/api/models/manage/order") { req in
            let ids = req.json["ids"] as? [String] ?? []
            let byId = [F.home, F.flash, F.gemini].reduce(into: [String: [String: Any]]()) { $0[$1["id"] as! String] = $1 }
            let models = ids.enumerated().map { n, id in byId[id]!.merging(["position": n]) { _, new in new } }
            return .init(body: F.data(F.snapshot(models: models)))
        }
        await m.move(from: [2], to: 0)
        #expect(m.models.map(\.id) == ["openrouter/google/gemini-3.8-flash", "qwen3.6-35b", "deepseek/deepseek-v4-flash"])
        let sent = try #require(server.requests("PUT", "/api/models/manage/order").first)
        #expect(sent.json["ids"] as? [String] == m.models.map(\.id))
        await m.move(from: [1], to: 1)
        #expect(server.requests("PUT", "/api/models/manage/order").count == 1, "a drag that moved nothing sends nothing")
    }

    @Test func aRefusedDragIsPutBack() async {
        let m = await loaded()
        server.fail("PUT", "/api/models/manage/order", status: 400, "send every model on the list, each once, in the new order")
        let before = m.models.map(\.id)
        await m.move(from: [0], to: 3)
        #expect(m.models.map(\.id) == before && m.error?.hasPrefix("send every model") == true)
    }

    @Test func nothingMovesBeforeTheListLoads() async {
        let m = HouseholdModelsModel(api: server.api)
        await m.move(from: [0], to: 1)
        #expect(server.requests.isEmpty)
    }

    @Test func addingTakesTheListAndSaysWhyNoTrialStarted() async {
        let m = await loaded()
        var reply = F.snapshot(models: [F.home, F.flash, F.gemini, F.model("acme/tiny", name: "Tiny", enabled: false, position: 3)])
        reply["added"] = "acme/tiny"
        reply["trial_started"] = false
        reply["note"] = "that is the 6 trials allowed in a day; try again tomorrow"
        server.on("POST", "/api/models/manage", json: reply)
        #expect(await m.add(.init(id: "acme/tiny", try: true)))
        #expect(m.model("acme/tiny")?.enabled == false)
        #expect(m.notice == "Added, without a trial: that is the 6 trials allowed in a day; try again tomorrow")

        reply["trial_started"] = true
        reply["note"] = ""
        reply["trial"] = F.trial(id: 9, model: "acme/tiny", done: 0, total: 0)
        server.on("POST", "/api/models/manage", json: reply)
        #expect(await m.add(.init(id: "acme/tiny")))
        #expect(m.notice == nil && m.runningID == 9 && m.followed == 9)

        server.fail("POST", "/api/models/manage", status: 400, "that model is already on the list")
        #expect(!(await m.add(.init(id: "acme/tiny"))))
        #expect(m.error == "that model is already on the list")
    }

    @Test func aTrialIsFollowedUntilItEndsAndTheScoresAreReadAgain() async {
        let m = await loaded()
        server.on("POST", "/api/models/manage/trial", json: ["trial": F.trial(done: 0, total: 0), "trials_left_today": 4])
        await m.startTrial("deepseek/deepseek-v4-flash")
        #expect(m.runningID == 7 && m.trialsLeft == 4 && m.error == nil)
        // Three looks: two still running, then done.
        var looks = 0
        server.on("GET", "/api/models/manage/trial") { _ in
            looks += 1
            let t = looks < 3 ? F.trial(done: looks * 4) : F.trial(status: "done", done: 12, passed: 12, verdict: "good")
            return .init(body: F.data(["trial": t, "trials_left_today": 4]))
        }
        let scored = F.model("deepseek/deepseek-v4-flash", name: "DeepSeek V4 Flash", position: 1, trial: F.score(12, 12, "good"))
        server.on("GET", "/api/models/manage", json: F.snapshot(models: [F.home, scored, F.gemini],
                                                                trial: F.trial(status: "done", done: 12, passed: 12, verdict: "good"), left: 4))
        await m.followTrial()
        #expect(looks == 3 && m.running == nil && m.trial?.status == "done")
        #expect(m.model("deepseek/deepseek-v4-flash")?.trial?.grade == .good, "the list is read again for the new score")
        #expect(m.shownTrial?.id == 7, "the run this screen followed stays shown")
        #expect(server.requests("GET", "/api/models/manage").count == 2)
    }

    @Test func aLookThatFailsIsTriedAgain() async {
        let m = await loaded(F.snapshot(trial: F.trial()))
        var looks = 0
        let failed = F.trial(status: "failed", error: "interrupted")
        server.on("GET", "/api/models/manage/trial") { _ in
            looks += 1
            if looks == 1 { return .init(status: 502, body: F.data(["error": "bad gateway"])) }
            return .init(body: F.data(["trial": failed, "trials_left_today": 5]))
        }
        server.on("GET", "/api/models/manage", json: F.snapshot(trial: failed))
        await m.followTrial()
        #expect(looks == 2 && m.trial?.status == "failed" && m.trial?.error == "interrupted" && m.error == nil)
    }

    @Test func onlyTheLatestFollowerAsks() async {
        let m = await loaded(F.snapshot(trial: F.trial()))
        m.pollEvery = .milliseconds(400)
        server.on("GET", "/api/models/manage/trial", json: ["trial": F.trial(), "trials_left_today": 5])
        let first = Task { await m.followTrial() }
        try? await Task.sleep(for: .milliseconds(50))
        let second = Task { await m.followTrial() }
        await first.value
        #expect(server.requests("GET", "/api/models/manage/trial").isEmpty, "the first follower stopped without asking")
        second.cancel()
        await second.value
    }

    @Test func aRefusedTrialSaysWhy() async {
        let m = await loaded()
        server.fail("POST", "/api/models/manage/trial", status: 409, "a trial is already running; wait for it or cancel it")
        await m.startTrial("qwen3.6-35b")
        #expect(m.error == "a trial is already running; wait for it or cancel it" && m.runningID == nil && !m.working)
    }

    @Test func cancellingTakesTheAnswer() async {
        let m = await loaded(F.snapshot(trial: F.trial()))
        server.on("POST", "/api/models/manage/trial/cancel", json: ["cancelled": true, "trial": F.trial(status: "cancelled")])
        await m.cancelTrial()
        #expect(m.trial?.status == "cancelled" && m.running == nil && m.shownTrial?.status == "cancelled")
        #expect(server.requests("GET", "/api/models/manage/trial").isEmpty)
    }

    @Test func aCancelElsewhereIsLookedUp() async {
        // Another copy of luach runs it: this one cancels nothing, and looks again.
        let m = await loaded(F.snapshot(trial: F.trial()))
        server.on("POST", "/api/models/manage/trial/cancel", json: ["cancelled": false, "trial": F.trial()])
        server.on("GET", "/api/models/manage/trial", json: ["trial": F.trial(done: 6), "trials_left_today": 5])
        await m.cancelTrial()
        #expect(server.requests("GET", "/api/models/manage/trial").count == 1 && m.trial?.done == 6)
        server.fail("POST", "/api/models/manage/trial/cancel", status: 403, "only the owner can do that")
        await m.cancelTrial()
        #expect(m.error == "only the owner can do that")
    }

    @Test func aCheckUpdatesTheModelsHealth() async {
        let m = await loaded()
        let healed = F.model("openrouter/google/gemini-3.8-flash", name: "Gemini 3.8 Flash", enabled: false, position: 2)
        server.on("POST", "/api/models/manage/check", json: ["ok": true, "reason": "", "health": F.ok, "models": [F.home, F.flash, healed]])
        await m.check("openrouter/google/gemini-3.8-flash")
        #expect(m.checked["openrouter/google/gemini-3.8-flash"]?.ok == true && m.checking == nil)
        #expect(m.model("openrouter/google/gemini-3.8-flash")?.answering == true)

        server.on("POST", "/api/models/manage/check", json: ["ok": false, "reason": "timed out after 20s", "health": F.ok])
        await m.check("qwen3.6-35b")
        #expect(m.checked["qwen3.6-35b"]?.reason == "timed out after 20s" && m.models.count == 3)

        server.fail("POST", "/api/models/manage/check", status: 404, "that model is not on the list")
        await m.check("gone")
        #expect(m.error == "that model is not on the list" && m.checked["gone"] == nil)
    }

    @Test func answersBeforeTheListLoadsAreKeptOutOfIt() async {
        let m = HouseholdModelsModel(api: server.api)
        server.on("POST", "/api/models/manage/trial", json: ["trial": F.trial(), "trials_left_today": 4])
        await m.startTrial("a")
        #expect(m.snapshot == nil && m.trial == nil)
        server.on("POST", "/api/models/manage/trial/cancel", json: ["cancelled": true, "trial": F.trial(status: "cancelled")])
        await m.cancelTrial()
        server.on("POST", "/api/models/manage/check", json: ["ok": true, "models": [F.home]])
        await m.check("a")
        #expect(m.snapshot == nil && m.checked["a"]?.ok == true)
        await m.followTrial()
    }
}
