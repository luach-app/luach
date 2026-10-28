import Foundation
import Testing
@testable import Luach

/// Profile: the model menu, what is dirty, and a PATCH of only what changed.
@MainActor
struct YouProfileTests {
    let server = StubServer()

    private func loaded(me: [String: Any]? = nil, models: Bool = true) async -> (YouProfileModel, AppSession) {
        let session = await YouFixtures.session(server, me: me)
        if models { server.on("GET", "/api/models", json: YouFixtures.models) }
        let model = YouProfileModel()
        await model.load(session)
        return (model, session)
    }

    @Test func loadsTheMemberAndTheMenu() async throws {
        let (m, _) = await loaded()
        let me = try #require(m.me)
        #expect(m.displayName == "Robin" && m.timezone == "America/New_York" && m.language == "auto")
        #expect(m.models.count == 3 && m.defaultModel == "qwen3.6-35b")
        #expect(m.shownModel(me) == "qwen3.6-35b", "no pick of their own: the default is ticked")
        #expect(m.label(m.models[0]) == "Home server · Qwen 3.6 (default)")
        #expect(m.label(m.models[1]) == "DeepSeek V4 Flash")
        #expect(!m.dirty && !m.showsSaved && m.loadError == nil)
    }

    @Test func onlyAModelOutsideTheHouseThatIsNotTheDefaultAsksFirst() async throws {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/models", json: YouFixtures.modelsOneDown)
        let m = YouProfileModel()
        await m.load(session)
        let byId = Dictionary(uniqueKeysWithValues: m.models.map { ($0.id, $0) })
        let deepseek = try #require(byId["cloud-deepseek-v4-flash"])
        let shed = try #require(byId["shed-llama"])
        let gemini = try #require(byId["openrouter/google/gemini-3.8-flash"])
        #expect(!m.needsConsent(deepseek), "the household's default, even in the cloud, was the owner's choice")
        #expect(!m.needsConsent(shed), "a model at home sends nothing out")
        #expect(m.needsConsent(gemini))
        YouAIConsent.give(gemini.id)
        defer { YouAIConsent.withdraw(gemini.id) }
        #expect(!m.needsConsent(gemini), "asked once per model")
    }

    @Test func anOlderServerAsksForEveryModelButTheDefault() async throws {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/models", json: YouFixtures.olderModels)
        let m = YouProfileModel()
        await m.load(session)
        #expect(m.models.map { m.needsConsent($0) } == [false, !YouAIConsent.given("cloud-deepseek-v4-flash")])
        #expect(m.models.allSatisfy { m.canPick($0) })
    }

    @Test func aModelNotAnsweringCannotBePicked() async throws {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/models", json: YouFixtures.modelsOneDown)
        let m = YouProfileModel()
        await m.load(session)
        #expect(m.models.map { m.canPick($0) } == [true, true, false])
    }

    @Test func withoutAMenuTheChoiceHides() async {
        let (m, _) = await loaded(models: false)
        #expect(m.models.isEmpty && m.defaultModel.isEmpty && m.me != nil && m.loadError == nil)
    }

    @Test func aMemberThatWillNotLoadSaysWhy() async {
        server.fail("GET", "/api/auth/me", status: 500, "luach is resting")
        let session = AppSession(api: server.api)
        let m = YouProfileModel()
        await m.load(session)
        #expect(m.me == nil && m.loadError == "luach is resting" && !m.dirty)
    }

    @Test func aMemberWithoutAZoneOrLanguageIsUTCAndAutomatic() async throws {
        var me = YouFixtures.me
        me["timezone"] = NSNull()
        me["language"] = NSNull()
        let (m, _) = await loaded(me: me)
        let loaded = try #require(m.me)
        #expect(m.savedZone(loaded) == "UTC" && m.timezone == "UTC")
        #expect(m.savedLanguage(loaded) == "auto" && m.language == "auto")
    }

    @Test func onlyWhatChangedIsSent() async throws {
        let (m, _) = await loaded()
        let me = try #require(m.me)
        m.displayName = "  Robin H  "
        var p = m.patch(me)
        #expect(p.displayName == "Robin H" && p.timezone == nil && p.language == nil && p.model == nil)
        m.displayName = "Robin"
        m.language = "he"
        p = m.patch(me)
        #expect(p.displayName == nil && p.language == "he" && p.timezone == nil)
        m.language = "auto"
        m.timezone = "Asia/Jerusalem"
        #expect(m.patch(me).timezone == "Asia/Jerusalem" && m.dirty)
        m.timezone = "America/New_York"
        #expect(!m.dirty)
    }

    @Test func pickingTheDefaultSavesNothingOrAnEmptyPick() async throws {
        // Following the default already: picking it changes nothing.
        let (m, _) = await loaded()
        let saved = try #require(m.me)
        m.model = "qwen3.6-35b"
        #expect(!m.dirty && m.patch(saved).model == nil)
        m.model = "cloud-deepseek-v4-flash"
        #expect(m.dirty && m.patch(saved).model == "cloud-deepseek-v4-flash")

        // A pick of their own: choosing "(default)" goes back to following it, as "".
        let (own, _) = await loaded(me: YouFixtures.me(["model": "cloud-deepseek-v4-flash"]))
        let me = try #require(own.me)
        #expect(own.shownModel(me) == "cloud-deepseek-v4-flash")
        own.model = "qwen3.6-35b"
        #expect(own.dirty && own.patch(me).model == "")
    }

    @Test func savingPatchesTheChangeAndTellsTheApp() async throws {
        let (m, session) = await loaded()
        m.displayName = " Robin Harper "
        m.language = "es"
        server.on("PATCH", "/api/auth/me", json: YouFixtures.me(["display_name": "Robin Harper", "language": "es"]))
        await m.save(session)
        let sent = try #require(server.requests("PATCH", "/api/auth/me").first)
        #expect(sent.keys == ["display_name", "language"])
        #expect(sent.json["display_name"] as? String == "Robin Harper" && sent.json["language"] as? String == "es")
        #expect(session.member?.displayName == "Robin Harper" && session.member?.language == "es")
        #expect(m.displayName == "Robin Harper" && !m.dirty && m.showsSaved && !m.busy)
        m.edited()
        #expect(m.showsSaved, "the answer is not an edit")
        m.displayName = "Robin"
        m.edited()
        #expect(!m.showsSaved)
        m.displayName = "Robin Harper"
        m.edited()
        #expect(!m.showsSaved, "changing it back does not bring Saved. back")
    }

    @Test func savedStaysAfterAModelChange() async throws {
        // The answer resets the pick to "" (the saved one shows): that is not an edit.
        let (m, session) = await loaded()
        m.model = "openrouter/google/gemini-3.8-flash"
        server.on("PATCH", "/api/auth/me", json: YouFixtures.me(["model": "openrouter/google/gemini-3.8-flash"]))
        await m.save(session)
        #expect(server.requests("PATCH", "/api/auth/me").first?.keys == ["model"])
        let reply = try #require(m.me)
        #expect(m.model.isEmpty && m.shownModel(reply) == "openrouter/google/gemini-3.8-flash")
        m.edited()
        #expect(m.showsSaved)
    }

    @Test func aRefusedSaveShowsTheSentenceAndKeepsTheEdit() async {
        let (m, session) = await loaded()
        m.timezone = "Mars/Olympus"
        server.fail("PATCH", "/api/auth/me", status: 400, "That is not a time zone.")
        await m.save(session)
        #expect(m.error == "That is not a time zone." && m.timezone == "Mars/Olympus" && m.dirty && !m.showsSaved)
        #expect(session.member?.timezone == "America/New_York")
    }

    @Test func nothingIsSavedBeforeTheMemberLoads() async {
        let m = YouProfileModel()
        await m.save(AppSession(api: server.api))
        #expect(server.requests.isEmpty && !m.dirty)
    }

    @Test func theZoneListIsSearchable() {
        let all = YouTimeZonePicker.zones(matching: "", selection: "America/New_York")
        #expect(all == TimeZone.knownTimeZoneIdentifiers)
        #expect(YouTimeZonePicker.zones(matching: "new york", selection: "").contains("America/New_York"))
        #expect(YouTimeZonePicker.zones(matching: "JERUSALEM", selection: "") == ["Asia/Jerusalem"])
        #expect(YouTimeZonePicker.zones(matching: "zzz", selection: "").isEmpty)
        // A zone the phone does not know still shows, first, so the saved one is never lost.
        #expect(YouTimeZonePicker.zones(matching: "", selection: "Mars/Olympus").first == "Mars/Olympus")
        #expect(YouTimeZonePicker.zones(matching: "olympus", selection: "Mars/Olympus") == ["Mars/Olympus"])
    }
}
