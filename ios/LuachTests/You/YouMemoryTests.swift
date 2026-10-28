import Foundation
import Testing
@testable import Luach

/// What luach remembers: the listing, keeping a fact, forgetting one.
@MainActor
struct YouMemoryTests {
    let server = StubServer()

    private func loaded() async -> (YouMemoryModel, AppSession) {
        let session = await YouFixtures.session(server)
        server.on("GET", "/api/family", json: YouFixtures.family)
        server.on("GET", "/api/memory", json: YouFixtures.memory)
        let m = YouMemoryModel()
        await m.load(session)
        return (m, session)
    }

    @Test func theFactsAndAChildsNameForTheExample() async {
        let (m, _) = await loaded()
        #expect(m.facts?.map(\.fact) == ["Lily feeds the fish every day"] && m.off == nil)
        #expect(m.example == "Ruby")
    }

    @Test func aFamilyThatWillNotLoadKeepsSomeone() async {
        let session = await YouFixtures.session(server)
        server.fail("GET", "/api/family", status: 500, "no")
        server.on("GET", "/api/memory", json: ["facts": []])
        let m = YouMemoryModel()
        await m.load(session)
        #expect(m.example == "someone" && m.facts?.isEmpty == true)
    }

    @Test func aLuachWithoutMemorySaysSoInsteadOfTheForm() async {
        let session = await YouFixtures.session(server)
        server.fail("GET", "/api/memory", status: 503, "Memory is not set up on this luach.")
        let m = YouMemoryModel()
        await m.load(session)
        #expect(m.off == "Memory is not set up on this luach." && m.facts == nil)
    }

    @Test func keepingAFactPostsItTrimmed() async throws {
        let (m, session) = await loaded()
        #expect(!m.canKeep)
        m.draft = "  We keep Friday nights clear \n"
        #expect(m.canKeep)
        server.on("POST", "/api/memory", json: ["facts": [
            ["key": "chores", "topic": "chores", "fact": "Lily feeds the fish every day"],
            ["key": "fridays", "topic": NSNull(), "fact": "We keep Friday nights clear", "saved_at": NSNull()],
        ]])
        await m.add(session)
        let sent = try #require(server.requests("POST", "/api/memory").first)
        #expect(sent.json as? [String: String] == ["fact": "We keep Friday nights clear"])
        #expect(m.facts?.map(\.key) == ["chores", "fridays"] && m.draft.isEmpty && !m.busy)
    }

    @Test func aBlankFactIsNotSent() async {
        let (m, session) = await loaded()
        m.draft = " \n "
        await m.add(session)
        #expect(server.requests("POST", "/api/memory").isEmpty)
    }

    @Test func aRefusedFactKeepsTheDraft() async {
        let (m, session) = await loaded()
        m.draft = "Something"
        server.fail("POST", "/api/memory", status: 400, "That is too long to remember.")
        await m.add(session)
        #expect(m.error == "That is too long to remember." && m.draft == "Something" && m.facts?.count == 1)
    }

    @Test func forgettingDeletesThatKey() async {
        let (m, session) = await loaded()
        server.on("DELETE", "/api/memory/chores", json: ["ok": true, "facts": []])
        await m.forget("chores", session)
        #expect(server.requests("DELETE", "/api/memory/chores").count == 1)
        #expect(m.facts?.isEmpty == true && m.error == nil)

        server.fail("DELETE", "/api/memory/gone", status: 404, "luach does not remember that.")
        await m.forget("gone", session)
        #expect(m.error == "luach does not remember that.")
    }

    @Test func aFactIsAtMost500Characters() {
        let m = YouMemoryModel()
        m.draft = String(repeating: "a", count: 620)
        m.clip()
        #expect(m.draft.count == 500)
        m.draft = "short"
        m.clip()
        #expect(m.draft == "short")
    }
}
