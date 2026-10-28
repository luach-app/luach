import Foundation
import Testing
@testable import Luach

/// The model menu's shapes, read as the server sends them (and as an older or odder one might),
/// and the rules beside them: the owner's order, a drag, the verdict's tint, the words for
/// context, tools and price, the trial's progress, and what the edit form sends.
@MainActor
struct ModelMenuModelTests {
    typealias H = HouseholdArea
    typealias F = ModelMenuFixtures

    // MARK: Decoding

    @Test func theSnapshotDecodesEveryModel() throws {
        let snap = try F.decode(H.ModelSnapshot.self, F.snapshot(trial: F.trial()))
        #expect(snap.default == "qwen3.6-35b" && snap.configured && snap.trialsLeftToday == 5)
        #expect(snap.catalogue == H.CatalogueSource(configured: true, source: "models.example.com"))
        #expect(snap.models.map(\.id) == ["qwen3.6-35b", "deepseek/deepseek-v4-flash", "openrouter/google/gemini-3.8-flash"])
        let home = snap.models[0]
        #expect(home.local && home.isDefault && home.enabled && home.answering && home.provider.isEmpty)
        #expect(home.meta == H.ModelMeta(contextLength: 131072, tools: true))
        #expect(home.trial?.grade == .good && home.about == "Runs on the household's own machine.")
        let flash = snap.models[1]
        #expect(flash.meta.priceIn == 0.3 && flash.meta.priceOut == 1.2 && flash.trial?.grade == .fair)
        #expect(flash.lastOkAt == "2026-10-28T09:00:00+00:00" && flash.failures == 0 && flash.position == 1)
        let gemini = snap.models[2]
        #expect(!gemini.enabled && !gemini.answering && gemini.trial?.grade == .low && gemini.lastOkAt == nil)
        #expect(gemini.health.reason.hasPrefix("its provider refused it") && gemini.health.since != nil)
        let trial = try #require(snap.trial)
        #expect(trial.running && trial.done == 3 && trial.total == 12 && trial.grade == nil && trial.requestedBy == "robin")
        #expect(trial.finishedAt == nil && trial.startedAt != nil && trial.error == "")
    }

    @Test func aSparseModelStillDecodes() throws {
        let m = try F.decode(H.ManagedModel.self, ["id": "x/y", "name": "", "meta": ["context_length": "big"], "health": 3])
        #expect(m.name == "x/y" && !m.local && !m.enabled && m.position == 0 && m.health == .ok)
        #expect(m.meta == H.ModelMeta() && m.trial == nil && !m.isDefault && m.providerSet.isEmpty)
        let snap = try F.decode(H.ModelSnapshot.self, ["models": [["id": "a"]]])
        #expect(snap.default.isEmpty && !snap.configured && snap.trial == nil && snap.trialsLeftToday == 0 && snap.catalogue == nil)
        #expect(throws: DecodingError.self) { try F.decode(H.ModelSnapshot.self, ["default": "a"]) }
    }

    @Test func aTrialDecodesItsCases() throws {
        let t = try F.decode(H.Trial.self, F.trial(status: "done", done: 2, passed: 1, total: 2, verdict: "low", cases: F.cases))
        #expect(!t.running && t.grade == .low && t.cases.count == 2)
        #expect(t.cases[0].name == "add_event" && t.cases[0].ok && t.cases[0].tools == [["add_event"]] && t.cases[0].id == "add_event")
        #expect(!t.cases[1].ok && t.cases[1].problems == ["called no tool"] && t.cases[1].about.isEmpty)
        let odd = try F.decode(H.Trial.self, ["id": 1, "cases": [["case": "x", "tools": "nope"]], "verdict": "none"])
        #expect(odd.status.isEmpty && odd.grade == nil && odd.cases.first?.tools == [] && odd.model.isEmpty)
        #expect(odd.done == 0 && odd.passed == 0 && odd.total == 0 && odd.error == nil)
    }

    @Test func aRunWithNoCasesHasNoGrade() throws {
        // The server says "none" for a finished run with no cases: no colour, no warning.
        let s = try F.decode(H.TrialScore.self, ["passed": 0, "total": 0, "verdict": "none", "at": NSNull()])
        #expect(s.grade == nil && s.at == nil)
    }

    @Test func theAddedAnswerCarriesTheSnapshot() throws {
        var json = F.snapshot()
        json["added"] = "acme/tiny"
        json["trial_started"] = false
        json["note"] = "a trial is already running; wait for it or cancel it"
        let reply = try F.decode(H.ModelAdded.self, json)
        #expect(reply.added == "acme/tiny" && !reply.trialStarted && reply.note.hasPrefix("a trial"))
        #expect(reply.snapshot.models.count == 3)
        let bare = try F.decode(H.ModelAdded.self, F.snapshot())
        #expect(bare.added.isEmpty && !bare.trialStarted && bare.note.isEmpty)
    }

    @Test func theCatalogueDecodes() throws {
        let c = try F.decode(H.Catalogue.self, F.catalogue)
        #expect(c.configured && c.source == "models.example.com" && c.error.isEmpty && c.models.count == 4)
        let alias = c.models[0]
        #expect(alias.alias && alias.recommended && alias.aliasOfIt.isEmpty && !alias.onMenu)
        #expect(c.models[1].onMenu)
        let pinned = c.models[2]
        #expect(pinned.contextLength == nil && pinned.tools == false && pinned.aliasOfIt == "~deepseek/deepseek-flash-latest")
        let off = try F.decode(H.Catalogue.self, ["configured": false])
        #expect(!off.configured && off.models.isEmpty && off.source.isEmpty && off.error.isEmpty)
        let older = try F.decode(H.CatalogueEntry.self, ["id": "z", "alias": true])
        #expect(older.name == "z" && older.recommended && older.provider.isEmpty)
    }

    @Test func checkAndCancelAnswersDecode() throws {
        let check = try F.decode(H.CheckReply.self, ["ok": false, "reason": "timed out", "health": F.down, "models": [F.flash]])
        #expect(!check.ok && check.reason == "timed out" && check.health?.answering == false && check.models?.count == 1)
        let cancel = try F.decode(H.TrialCancelled.self, ["cancelled": true, "trial": F.trial(status: "cancelled")])
        #expect(cancel.cancelled && cancel.trial?.status == "cancelled")
        let reply = try F.decode(H.TrialReply.self, ["trial": NSNull(), "trials_left_today": 2])
        #expect(reply.trial == nil && reply.trialsLeftToday == 2)
    }

    @Test func whatTheOwnerSendsIsSnakeCaseAndOnlyWhatIsSet() throws {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        func json(_ v: some Encodable) throws -> NSDictionary {
            try #require(try JSONSerialization.jsonObject(with: e.encode(v)) as? NSDictionary)
        }
        #expect(try json(H.NewModel(id: "a/b", name: "B", local: false, try: false)) == ["id": "a/b", "name": "B", "local": false, "try": false])
        #expect(try json(H.ModelChange(id: "a/b", enabled: true)) == ["id": "a/b", "enabled": true])
        #expect(H.ModelChange(id: "a").isEmpty && !H.ModelChange(id: "a", local: true).isEmpty)
    }

    // MARK: Rules

    @Test func theListIsInTheOwnersOrder() throws {
        let snap = try F.decode(H.ModelSnapshot.self, F.snapshot(models: [
            F.model("c", name: "C", position: 2), F.model("a", name: "A", position: 0),
            F.model("b1", name: "B1", position: 1), F.model("b2", name: "B2", position: 1),
        ]))
        #expect(H.ordered(snap.models).map(\.id) == ["a", "b1", "b2", "c"])
    }

    @Test func aDragMovesOneId() {
        let ids = ["a", "b", "c", "d"]
        #expect(H.moved(ids, from: [3], to: 0) == ["d", "a", "b", "c"])
        #expect(H.moved(ids, from: [0], to: 2) == ["b", "a", "c", "d"])
        #expect(H.moved(ids, from: [1], to: 1) == ids)
    }

    @Test func whereAModelRuns() {
        #expect(H.whereItRuns(.init(id: "a", name: "A", local: true, provider: "ignored")) == "At home")
        #expect(H.whereItRuns(.init(id: "a", name: "A", provider: "DeepSeek")) == "DeepSeek")
        #expect(H.whereItRuns(.init(id: "a", name: "A")) == "A cloud provider")
    }

    @Test func theScoreAndItsTint() {
        #expect(H.scoreText(11, 12) == "11 of 12 passed")
        #expect(H.tint(.good) == .green && H.tint(.fair) == .orange && H.tint(.low) == .red && H.tint(nil) == .secondary)
    }

    @Test func contextToolsAndPriceInWords() throws {
        #expect(H.contextText(nil) == nil && H.contextText(0) == nil)
        #expect(H.contextText(900) == "900 tokens of context")
        #expect(H.contextText(131072) == "131K tokens of context")
        #expect(H.contextText(1_048_576) == "1M tokens of context")
        #expect(H.contextText(1_500_000) == "1.5M tokens of context")
        #expect(H.toolsText(nil) == nil && H.toolsText(true) == "Can use tools" && H.toolsText(false) == "Cannot use tools")
        #expect(H.priceText(nil, 1) == nil && H.priceText(1, nil) == nil)
        #expect(H.priceText(0, 0) == "No charge")
        let price = try #require(H.priceText(0.3, 1.2))
        #expect(price.contains("0.30") && price.contains("1.20") && price.hasSuffix("per million tokens"))
    }

    @Test func aTrialsProgress() throws {
        #expect(H.progress(try F.decode(H.Trial.self, F.trial(done: 3, total: 12))) == 0.25)
        #expect(H.progress(try F.decode(H.Trial.self, F.trial(done: 0, total: 0))) == nil, "not known before the cases are counted")
        #expect(H.progress(try F.decode(H.Trial.self, F.trial(done: 14, total: 12))) == 1)
    }

    @Test func aModelsNameOrItsId() throws {
        let snap = try F.decode(H.ModelSnapshot.self, F.snapshot())
        #expect(H.modelName("deepseek/deepseek-v4-flash", in: snap.models) == "DeepSeek V4 Flash")
        #expect(H.modelName("gone/model", in: snap.models) == "gone/model")
    }

    @Test func theEditFormSendsOnlyWhatChanged() {
        let m = H.ManagedModel(id: "a/b", name: "B", about: "Fast.", provider: "Acme", providerSet: "Acme")
        #expect(H.change(of: m, name: " B ", about: "Fast.", local: false, provider: "Acme") == nil)
        #expect(H.change(of: m, name: "Bee", about: "Fast.", local: false, provider: "Acme") == .init(id: "a/b", name: "Bee"))
        #expect(H.change(of: m, name: "B", about: " Quick. ", local: false, provider: "Acme ") == .init(id: "a/b", about: "Quick."))
        #expect(H.change(of: m, name: "B", about: "Fast.", local: false, provider: "") == .init(id: "a/b", provider: ""))
        // At home: the provider is no longer the point, and is not sent.
        #expect(H.change(of: m, name: "B", about: "Fast.", local: true, provider: "Other") == .init(id: "a/b", local: true))
    }
}
