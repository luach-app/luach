import Foundation
import Testing
@testable import Luach

/// The You screens' models against dev. Reads of everything; the only writes are an
/// `ios-test…` fact and an `ios-test…` child (each removed before the test ends) and
/// PATCHes that set what is already there.
@MainActor
@Suite(.dev, .serialized, .timeLimit(.minutes(3)))
struct YouDevTests {
    private func session() async throws -> AppSession {
        let session = AppSession(api: try Dev.api())
        await session.restore()
        #expect(session.member != nil, "the run's session signs in")
        return session
    }

    // MARK: Reads

    @Test func profileReadsTheMemberAndTheModels() async throws {
        let s = try await session()
        let m = YouProfileModel()
        await m.load(s)
        let me = try #require(m.me, "\(m.loadError ?? "")")
        #expect(me.member.id == s.member?.id && !m.timezone.isEmpty)
        #expect(YouKit.languages.map(\.value).contains(m.language))
        #expect(!m.dirty, "freshly loaded")
        if m.models.count > 1 {
            #expect(m.models.contains { $0.id == m.defaultModel }, "the default is on the menu")
            #expect(m.models.contains { m.label($0).hasSuffix("(default)") })
            #expect(m.models.contains { $0.id == m.shownModel(me) }, "the shown pick is on the menu")
        }
        #expect(me.emails.contains(me.member.email ?? ""), "the primary is among the addresses")
    }

    @Test func addressesListThePrimaryFirst() async throws {
        let s = try await session()
        let m = YouEmailsModel()
        await m.load(s)
        let listing = try #require(m.listing, "\(m.loadError ?? "")")
        #expect(m.rows.first == .init(email: listing.primary, verified: true))
        #expect(listing.primary == s.member?.email)
        #expect(Set(m.rows.map(\.email)).count == m.rows.count, "each address once")
        #expect(m.rows.allSatisfy { YouKit.isEmail($0.email) })
    }

    @Test func alsoNotifyReads() async throws {
        let s = try await session()
        let m = YouNotifyModel()
        await m.load(s)
        #expect(m.me != nil && m.loadError == nil && !m.dirty)
        #expect(m.list.allSatisfy { YouKit.isEmail($0) })
    }

    @Test func passkeysRead() async throws {
        let m = YouPasskeysModel()
        await m.load(try await session())
        let list = try #require(m.list, "\(m.loadError ?? "")")
        #expect(list.allSatisfy { !$0.id.isEmpty && !YouPasskeysModel.name($0).isEmpty })
    }

    @Test func theAuditChainVerifies() async throws {
        let s = try await session()
        let m = YouAuditModel()
        await m.load(s)
        let trail = try #require(m.trail, "\(m.error ?? "")")
        #expect(trail.verified, "dev's chain_verified")
        #expect(!trail.entries.isEmpty && trail.entries.count <= 50 && trail.total >= trail.entries.count)
        #expect(trail.entries.map(\.seq) == trail.entries.map(\.seq).sorted(by: >), "newest first")
        #expect(trail.entries.allSatisfy { !$0.eventType.isEmpty && $0.hash.count == 64 && YouKit.date($0.ts) != nil })
        #expect(trail.head.count == 64, "the chain's head hash")
        if m.hasOlder {
            await m.showOlder(s)
            #expect(m.trail?.entries.count == min(100, trail.total) && m.limit == 100)
        }
    }

    @Test func membersReadWithTheOwner() async throws {
        let s = try await session()
        let m = YouMembersModel()
        await m.load(s)
        let data = try #require(m.data, "\(m.error ?? "")")
        #expect(data.members.contains { $0.id == s.member?.id })
        #expect(data.members.filter { $0.isOwner == true }.count == 1)
        #expect(data.members.allSatisfy { !$0.name.isEmpty && !$0.allEmails.isEmpty })
        #expect(data.invites.allSatisfy { YouKit.date($0.expiresAt) != nil })
    }

    @Test func familyAndBoardsRead() async throws {
        let s = try await session()
        let f = YouFamilyModel()
        await f.load(s)
        let family = try #require(f.family, "\(f.loadError ?? "")")
        #expect(family.colors.count == 11 && family.people.allSatisfy { $0.hex.hasPrefix("#") })
        #expect(family.colors.allSatisfy { !$0.name.isEmpty })
        let b = YouBoardsModel()
        await b.load(s)
        #expect(b.boards != nil && b.loadError == nil)
        let memory = YouMemoryModel()
        await memory.load(s)
        #expect(memory.example == family.exampleName)
    }

    // MARK: Writes that leave nothing behind

    @Test func memoryKeepsAFactAndForgetsIt() async throws {
        let s = try await session()
        let m = YouMemoryModel()
        await m.load(s)
        try #require(m.off == nil, "memory is on in dev: \(m.off ?? "")")
        let text = Dev.title("fact")
        m.draft = "  \(text)  "
        await m.add(s)
        let kept = m.facts?.first { $0.fact.contains(text) }
        // Whatever happens next, the fact does not stay on dev.
        defer {
            if let kept, m.facts?.contains(where: { $0.key == kept.key }) == true {
                Task { @MainActor in let _: API.Ignored? = try? await s.api.delete("/api/memory/\(kept.key)") }
            }
        }
        let fact = try #require(kept, "\(m.error ?? "kept, but not listed")")
        #expect(m.draft.isEmpty && m.error == nil)
        await m.forget(fact.key, s)
        #expect(m.error == nil && m.facts?.contains { $0.key == fact.key } == false)
        await m.forget(fact.key, s)
        #expect(m.error != nil, "forgetting it twice: luach says it does not remember it")
    }

    @Test func profilePatchesWhatIsAlreadyThere() async throws {
        let s = try await session()
        let m = YouProfileModel()
        await m.load(s)
        let me = try #require(m.me)
        // Every field set to the value it has: a PATCH that changes nothing.
        let same = YouProfileModel.Patch(displayName: me.member.displayName ?? "", timezone: m.savedZone(me),
                                         language: m.savedLanguage(me))
        let reply: YouKit.Me = try await s.api.patch("/api/auth/me", same)
        #expect(reply.member == me.member && reply.model == me.model && reply.notifyEmails == me.notifyEmails)
        // Save with nothing changed sends `{}`, and comes back the same.
        await m.save(s)
        #expect(m.error == nil && m.showsSaved && m.me?.member == me.member)
        #expect(s.member == me.member)
    }

    @Test func alsoNotifySavesTheSameList() async throws {
        let s = try await session()
        let m = YouNotifyModel()
        await m.load(s)
        // Only an empty list is saved back: one with addresses waiting could mail them again.
        guard m.list.isEmpty else { return }
        await m.save(s)
        #expect(m.error == nil && m.showsSaved && m.list.isEmpty)
    }

    @Test func familyAddsAChildRecoloursAndRemovesThem() async throws {
        let s = try await session()
        let f = YouFamilyModel()
        await f.load(s)
        let colors = try #require(f.family?.colors)
        let name = Dev.title("child")
        f.name = name
        f.kid = true
        let made = await f.add(s)
        defer {
            if let made, f.family?.people.contains(where: { $0.key == made.key }) == true {
                Task { @MainActor in let _: API.Ignored? = try? await s.api.delete("/api/family/\(made.key)") }
            }
        }
        let person = try #require(made, "\(f.addError ?? "")")
        #expect(person.name == name && person.isKid && person.email.isEmpty && person.userId == nil)
        #expect(f.family?.people.contains { $0.key == person.key } == true)

        var reloaded = 0
        let editor = YouPersonModel(person: person) { reloaded += 1; await f.load(s) }
        let other = try #require(colors.first { $0.id != person.color })
        await editor.save(.init(color: other.id), s)
        #expect(editor.error == nil && editor.person.color == other.id && editor.person.hex == other.hex)
        #expect(f.family?.people.first { $0.key == person.key }?.color == other.id && reloaded == 1)

        #expect(await editor.remove(s), "\(editor.error ?? "")")
        #expect(f.family?.people.contains { $0.key == person.key } == false)
    }
}
