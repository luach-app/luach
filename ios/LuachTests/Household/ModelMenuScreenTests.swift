import Foundation
import SwiftUI
import Testing
import UIKit
@testable import Luach

/// Settings › Household › Models drawn in a window over a stub luach (dev has no model menu to
/// change, and must not have one changed by a test): the list in its states, one model's sheet,
/// "Add a model" with its search, each pressed through accessibility as VoiceOver would.
/// Serialized: the `-modelsOpen` case sets the shared UserDefaults.
@MainActor
@Suite(.serialized, .timeLimit(.minutes(3)))
struct ModelMenuScreenTests {
    typealias H = HouseholdArea
    typealias F = ModelMenuFixtures
    let server = StubServer()

    private func session() async -> AppSession {
        server.on("GET", "/api/auth/me", json: HouseholdFixtures.member)
        let s = AppSession(api: server.api)
        await s.restore()
        return s
    }

    private func model(_ snapshot: [String: Any] = F.snapshot()) async -> HouseholdModelsModel {
        server.on("GET", "/api/models/manage", json: snapshot)
        let m = HouseholdModelsModel(api: server.api)
        m.pollEvery = .milliseconds(50)
        await m.load()
        return m
    }

    private func host(_ view: some View, stack: Bool = true) async -> ScreenHost {
        let h = ScreenHost(view, session: await session(), stack: stack)
        await h.settle()
        return h
    }

    /// Presses the element with accessibility identifier `id` (a row whose label is many lines).
    @discardableResult
    private func press(id: String, in host: ScreenHost) async -> Bool {
        let end = Date().addingTimeInterval(3)
        var target: NSObject?
        while target == nil && Date() < end {
            target = host.elements.last { Self.identifier($0) == id }
            if target == nil { await host.settle(.milliseconds(150)) }
        }
        guard let target else {
            Issue.record("no element \(id) among \(host.elements.compactMap(Self.identifier)) / \(host.labels)")
            return false
        }
        let pressed = target.accessibilityActivate()
        await host.settle()
        return pressed
    }

    /// An element's accessibility identifier: SwiftUI's elements answer the selector without
    /// declaring the protocol.
    private static func identifier(_ element: NSObject) -> String? {
        let selector = NSSelectorFromString("accessibilityIdentifier")
        guard element.responds(to: selector) else { return nil }
        return element.perform(selector)?.takeUnretainedValue() as? String
    }

    /// The dialog up over the screen, if any (a confirmationDialog is an alert controller).
    private func dialog(_ host: ScreenHost) -> UIAlertController? {
        var controller = host.window.rootViewController
        while let c = controller {
            if let alert = c as? UIAlertController { return alert }
            controller = c.presentedViewController
        }
        return nil
    }

    /// Chooses `title` in the dialog up: an action sheet's buttons do not activate in-process,
    /// so the action's own handler is run, as a tap does (YouHost does the same).
    @discardableResult
    private func choose(_ title: String, in host: ScreenHost) async -> Bool {
        let end = Date().addingTimeInterval(3)
        while dialog(host) == nil && Date() < end { await host.settle(.milliseconds(150)) }
        guard let alert = dialog(host), let action = alert.actions.first(where: { $0.title == title }),
              let block = action.value(forKey: "handler") else { return false }
        typealias Handler = @convention(block) (UIAlertAction) -> Void
        let handler = unsafeBitCast(block as AnyObject, to: Handler.self)
        alert.dismiss(animated: false)
        handler(action)
        await host.settle()
        return true
    }

    private func until(_ seconds: Double = 3, _ done: () -> Bool) async -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while !done() && Date() < end { try? await Task.sleep(for: .milliseconds(50)) }
        return done()
    }

    // MARK: The list

    @Test func theListShowsEveryModelsState() async throws {
        let m = await model(F.snapshot(trial: F.trial(cases: F.cases), configured: false, default: "set/by-env"))
        let h = await host(HouseholdModelsList(model: m))
        #expect(await h.waitFor("Home server · Qwen 3.6"), "\(h.labels)")
        #expect(h.shows("At home") && h.shows("DeepSeek") && h.shows("Google, through OpenRouter"))
        #expect(h.shows("Default") && h.shows("On the menu") && h.shows("Off"))
        #expect(h.shows("Not answering") && h.shows("its provider refused it"))
        #expect(h.shows("Tried: 12 of 12 passed") && h.shows("Tried: 6 of 12 passed"))
        #expect(h.shows("members may get wrong answers"))
        #expect(h.shows("No model server is set up"))
        #expect(h.shows("set/by-env"), "a default set in luach's own settings is named")
        #expect(h.shows("Trying DeepSeek V4 Flash") && h.shows("3 of 12 cases"))
        #expect(h.shows("Trials left today: 5"))
        // The cases so far, opened.
        #expect(await h.press("What it was asked"))
        #expect(await h.waitFor("Adds an event on a day") && h.shows("called no tool"))
        // Cancel.
        server.on("POST", "/api/models/manage/trial/cancel", json: ["cancelled": true, "trial": F.trial(status: "cancelled")])
        #expect(await press(id: "models.cancelTrial", in: h))
        #expect(await h.waitFor("was cancelled"))
        #expect(server.requests("POST", "/api/models/manage/trial/cancel").count == 1)
        h.close()
    }

    @Test func aRunningTrialIsFollowedOnScreen() async throws {
        let m = await model(F.snapshot(trial: F.trial(done: 0, total: 0)))
        var looks = 0
        let done = F.trial(status: "done", done: 12, passed: 8, verdict: "low")
        server.on("GET", "/api/models/manage/trial") { _ in
            looks += 1
            return .init(body: F.data(["trial": looks < 2 ? F.trial(done: 6) : done, "trials_left_today": 4]))
        }
        // Read again once it ends: the latest trial is the one that ended.
        server.on("GET", "/api/models/manage") { _ in
            .init(body: F.data(F.snapshot(trial: looks < 2 ? F.trial(done: 0, total: 0) : done, left: 4)))
        }
        let h = await host(HouseholdModelsList(model: m))
        #expect(await h.waitFor("was tried", seconds: 5), "\(h.labels)")
        #expect(h.shows("Tried: 8 of 12 passed") && h.shows("members may get wrong answers"))
        #expect(looks >= 2)
        h.close()
    }

    @Test func aTrialThatStoppedSaysWhy() async throws {
        let m = await model(F.snapshot(trial: F.trial()))
        let failed = F.trial(status: "failed", error: "the trial stopped after 3 of 12 cases")
        var looked = false
        server.on("GET", "/api/models/manage/trial") { _ in
            looked = true
            return .init(body: F.data(["trial": failed, "trials_left_today": 4]))
        }
        server.on("GET", "/api/models/manage") { _ in
            .init(body: F.data(F.snapshot(trial: looked ? failed : F.trial(), left: 4)))
        }
        let h = await host(HouseholdModelsList(model: m))
        #expect(await h.waitFor("the trial stopped after 3 of 12 cases", seconds: 5), "\(h.labels)")
        #expect(h.shows("The trial of DeepSeek V4 Flash stopped."))
        h.close()
    }

    @Test func aListThatWillNotLoadSaysWhyAndTriesAgain() async throws {
        server.fail("GET", "/api/models/manage", status: 403, "only the owner can do that")
        let h = await host(HouseholdModelsView())
        #expect(await h.waitFor("only the owner can do that"), "\(h.labels)")
        server.on("GET", "/api/models/manage", json: F.snapshot(models: []))
        #expect(await h.press("Try again"))
        #expect(await h.waitFor("No models on the list yet."), "\(h.labels)")
        h.close()
    }

    @Test func swipesTurnAModelOnAndRemoveOne() async throws {
        let m = await model()
        let h = await host(HouseholdModelsList(model: m))
        #expect(await h.waitFor("Gemini 3.8 Flash"))
        server.on("PATCH", "/api/models/manage", json: F.snapshot())
        #expect(await h.action("Turn on", on: "Gemini 3.8 Flash"))
        #expect(await until { !server.requests("PATCH", "/api/models/manage").isEmpty })
        #expect(server.requests("PATCH", "/api/models/manage").first?.json as NSDictionary? == ["id": "openrouter/google/gemini-3.8-flash", "enabled": true])
        #expect(await h.action("Turn off", on: "DeepSeek V4 Flash"))
        #expect(await until { server.requests("PATCH", "/api/models/manage").count == 2 })

        server.on("POST", "/api/models/manage/remove", json: F.snapshot(models: [F.home, F.gemini]))
        #expect(await h.action("Remove", on: "DeepSeek V4 Flash"))
        #expect(await choose("Remove", in: h))
        #expect(await until { m.model("deepseek/deepseek-v4-flash") == nil })
        #expect(server.requests("POST", "/api/models/manage/remove").first?.json as NSDictionary? == ["id": "deepseek/deepseek-v4-flash"])
        #expect(!(await h.action("Remove", on: "Home server")), "the default has no Remove")
        h.close()
    }

    @Test func aRefusedChangeIsShownOnTheList() async throws {
        let m = await model()
        server.fail("PATCH", "/api/models/manage", status: 400, "that model is not on the list")
        let h = await host(HouseholdModelsList(model: m))
        #expect(await h.action("Turn on", on: "Gemini 3.8 Flash"))
        #expect(await h.waitFor("that model is not on the list"), "\(h.labels)")
        h.close()
    }

    @Test func theRowsOpenTheirSheet() async throws {
        let m = await model()
        let h = await host(HouseholdModelsList(model: m))
        // Edit (the drag) is there; a bar button does not activate in-process, so the drag's
        // effect is covered by the state tests.
        #expect(await h.waitFor("Edit"))
        #expect(await press(id: "models.row.deepseek/deepseek-v4-flash", in: h))
        #expect(await h.waitFor("On the members' menu"), "\(h.labels)")
        #expect(await h.press("Done"))
        await h.settle(.milliseconds(700))
        #expect(await press(id: "models.add", in: h))
        #expect(await h.waitFor("Add a model"))
        h.close()
    }

    @Test func aDebugLaunchOpensASheet() async throws {
        server.on("GET", "/api/models/catalogue", json: F.catalogue)
        UserDefaults.standard.set("add", forKey: "modelsOpen")
        defer { UserDefaults.standard.removeObject(forKey: "modelsOpen") }
        let m = await model()
        let h = await host(HouseholdModelsList(model: m))
        #expect(await h.waitFor("Search models") || h.shows("DeepSeek Flash (latest)"), "\(h.labels)")
        h.close()
    }

    // MARK: One model

    @Test func theDefaultsSheet() async throws {
        let m = await model()
        let h = await host(HouseholdModelDetail(model: m, id: "qwen3.6-35b"), stack: false)
        #expect(await h.waitFor("The household's default"), "\(h.labels)")
        #expect(h.shows("Answering") && h.shows("Last answered") && h.shows("Tried: 12 of 12 passed"))
        #expect(h.shows("131K tokens of context") && h.shows("Can use tools"))
        #expect(!h.shows("Remove from the list"), "the default cannot be removed")
        // Check: answered.
        server.on("POST", "/api/models/manage/check", json: ["ok": true, "reason": "", "health": F.ok, "models": [F.home, F.flash, F.gemini]])
        #expect(await press(id: "model.check", in: h))
        #expect(await h.waitFor("It answered."))
        // Try it.
        server.on("POST", "/api/models/manage/trial", json: ["trial": F.trial(model: "qwen3.6-35b"), "trials_left_today": 4])
        #expect(await press(id: "model.try", in: h))
        #expect(await h.waitFor("Trying Home server · Qwen 3.6"), "\(h.labels)")
        #expect(server.requests("POST", "/api/models/manage/trial").first?.json as NSDictionary? == ["id": "qwen3.6-35b"])
        h.close()
    }

    @Test func aCloudModelsSheetEditsAndBecomesTheDefault() async throws {
        let m = await model()
        let h = await host(HouseholdModelDetail(model: m, id: "deepseek/deepseek-v4-flash"), stack: false)
        #expect(await h.waitFor("Make default"), "\(h.labels)")
        #expect(h.shows("Tried: 10 of 12 passed") && h.shows("per million tokens"))
        // Name and provider.
        server.on("PATCH", "/api/models/manage", json: F.snapshot())
        #expect(await h.type("DeepSeek Flash", into: "Name"))
        #expect(await h.type("DeepSeek, direct", into: "DeepSeek"), "the provider's placeholder is luach's own words")
        #expect(await press(id: "model.save", in: h))
        #expect(await until { !server.requests("PATCH", "/api/models/manage").isEmpty })
        let sent = server.requests("PATCH", "/api/models/manage").first?.json as NSDictionary?
        #expect(sent == ["id": "deepseek/deepseek-v4-flash", "name": "DeepSeek Flash", "provider": "DeepSeek, direct"])
        // Off the menu, from the toggle.
        #expect(await press(id: "model.enabled", in: h))
        #expect(await until { server.requests("PATCH", "/api/models/manage").count == 2 })
        // Default: asked first, since it runs outside the house.
        server.on("PUT", "/api/models/manage/default", json: F.snapshot())
        #expect(await press(id: "model.makeDefault", in: h))
        #expect(await choose("Make default", in: h))
        #expect(await until { !server.requests("PUT", "/api/models/manage/default").isEmpty })
        // Check: not answering.
        server.on("POST", "/api/models/manage/check", json: ["ok": false, "reason": "timed out after 20s", "health": F.down])
        #expect(await press(id: "model.check", in: h))
        #expect(await h.waitFor("timed out after 20s"))
        h.close()
    }

    @Test func aModelNotAnsweringCannotBeTheDefaultAndCanBeRemoved() async throws {
        let m = await model(F.snapshot(trial: F.trial(model: "qwen3.6-35b")))
        let h = await host(HouseholdModelDetail(model: m, id: "openrouter/google/gemini-3.8-flash"), stack: false)
        #expect(await h.waitFor("cannot be the default"), "\(h.labels)")
        #expect(h.shows("Not answering since") && h.shows("members may get wrong answers"))
        #expect(h.shows("Another trial is running."))
        #expect(!h.shows("Last answered"))
        // Marked as running at home: the provider field goes, and only `local` is sent.
        server.on("PATCH", "/api/models/manage", json: F.snapshot())
        #expect(await press(id: "model.local", in: h))
        #expect(await press(id: "model.save", in: h))
        #expect(await until { !server.requests("PATCH", "/api/models/manage").isEmpty })
        #expect(server.requests("PATCH", "/api/models/manage").first?.json as NSDictionary? == ["id": "openrouter/google/gemini-3.8-flash", "local": true])
        // Refused: the sentence shows in the sheet.
        server.fail("POST", "/api/models/manage/remove", status: 400, "that model is not on the list")
        #expect(await press(id: "model.remove", in: h))
        #expect(await choose("Remove", in: h))
        #expect(await h.waitFor("that model is not on the list"))
        h.close()
    }

    @Test func removingFromItsSheet() async throws {
        let m = await model()
        server.on("POST", "/api/models/manage/remove", json: F.snapshot(models: [F.home, F.flash]))
        let h = await host(HouseholdModelDetail(model: m, id: "openrouter/google/gemini-3.8-flash"), stack: false)
        #expect(await press(id: "model.remove", in: h))
        #expect(await choose("Remove", in: h))
        #expect(await until { m.model("openrouter/google/gemini-3.8-flash") == nil })
        #expect(await h.waitFor("This model is no longer on the list."))
        h.close()
    }

    @Test func aLocalModelBecomesTheDefaultWithoutAQuestion() async throws {
        let shed = F.model("shed/llama", name: "Shed Llama", local: true, position: 3)
        let m = await model(F.snapshot(models: [F.home, F.flash, F.gemini, shed]))
        server.on("PUT", "/api/models/manage/default", json: F.snapshot())
        let h = await host(HouseholdModelDetail(model: m, id: "shed/llama"), stack: false)
        #expect(await h.waitFor("Not tried yet."))
        #expect(await press(id: "model.makeDefault", in: h))
        #expect(await until { !server.requests("PUT", "/api/models/manage/default").isEmpty })
        #expect(dialog(h) == nil)
        h.close()
    }

    @Test func aSheetForAModelThatWentAway() async throws {
        let m = await model()
        let h = await host(HouseholdModelDetail(model: m, id: "gone/model"), stack: false)
        #expect(await h.waitFor("This model is no longer on the list."))
        h.close()
    }

    // MARK: Adding

    @Test func theCatalogueIsSearchedAndAModelAdded() async throws {
        server.on("GET", "/api/models/catalogue", json: F.catalogue)
        let m = await model()
        let h = await host(HouseholdAddModelView(model: m, query: "deepseek"), stack: false)
        #expect(await h.waitFor("DeepSeek Flash (latest)"), "\(h.labels)")
        #expect(server.requests("GET", "/api/models/catalogue").first?.query == ["q": "deepseek"])
        #expect(h.shows("Recommended: always the newest version") && h.shows("On the list"))
        #expect(h.shows("Cannot use tools") && h.shows("luach needs a model that can use tools") && h.shows("No charge"))
        #expect(h.shows("From models.example.com") && h.shows("Add “deepseek” by its id"))
        // The pinned version offers its always-current name.
        #expect(await press(id: "catalogue.deepseek/deepseek-v3.2", in: h))
        #expect(await h.waitFor("Use ~deepseek/deepseek-flash-latest instead"), "\(h.labels)")
        #expect(await press(id: "add.useAlias", in: h))
        #expect(await h.waitFor("Recommended: always the newest version"), "the alias's own entry: \(h.labels)")
        #expect(await h.type("DeepSeek", into: "DeepSeek, through OpenRouter"))
        #expect(await press(id: "add.try", in: h))
        var reply = F.snapshot()
        reply["added"] = "~deepseek/deepseek-flash-latest"
        reply["trial_started"] = false
        reply["note"] = ""
        server.on("POST", "/api/models/manage", json: reply)
        #expect(await press(id: "add.confirm", in: h))
        #expect(await until { !server.requests("POST", "/api/models/manage").isEmpty })
        let sent = server.requests("POST", "/api/models/manage").first?.json as NSDictionary?
        #expect(sent == ["id": "~deepseek/deepseek-flash-latest", "name": "DeepSeek Flash (latest)",
                         "local": false, "provider": "DeepSeek", "try": false])
        h.close()
    }

    @Test func aModelIsAddedByItsIdAtHome() async throws {
        server.on("GET", "/api/models/catalogue", json: ["configured": false, "source": "", "models": [], "error": ""])
        let m = await model(F.snapshot(catalogue: false))
        let h = await host(HouseholdAddModelView(model: m, query: "shed/llama"), stack: false)
        #expect(await h.waitFor("No catalogue is set up"), "\(h.labels)")
        #expect(await press(id: "catalogue.byId", in: h))
        #expect(await h.waitFor("Try it once added"))
        #expect(await press(id: "add.local", in: h))
        server.fail("POST", "/api/models/manage", status: 400, "that model is already on the list")
        #expect(await press(id: "add.confirm", in: h))
        #expect(await h.waitFor("that model is already on the list"))
        #expect(server.requests("POST", "/api/models/manage").first?.json as NSDictionary? == ["id": "shed/llama", "local": true, "try": true])
        h.close()
    }

    @Test func aCatalogueThatFailsSaysWhy() async throws {
        server.on("GET", "/api/models/catalogue", json: ["configured": true, "source": "models.example.com", "models": [], "error": "the catalogue did not answer"])
        let m = await model()
        let h = await host(HouseholdAddModelView(model: m), stack: false)
        #expect(await h.waitFor("the catalogue did not answer"), "\(h.labels)")
        server.fail("GET", "/api/models/catalogue", status: 403, "only the owner can do that")
        let h2 = await host(HouseholdAddModelView(model: m, query: "x"), stack: false)
        #expect(await h2.waitFor("only the owner can do that"), "\(h2.labels)")
        server.on("GET", "/api/models/catalogue", json: ["configured": true, "source": "", "models": [], "error": ""])
        let h3 = await host(HouseholdAddModelView(model: m), stack: false)
        #expect(await h3.waitFor("Nothing matches."), "\(h3.labels)")
        #expect(await h3.press("Cancel"))
        h.close()
        h2.close()
        h3.close()
    }
}
