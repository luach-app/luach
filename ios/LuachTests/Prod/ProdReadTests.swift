import Foundation
import Testing
@testable import Luach

/// The app's own reads against the family's luach, with the app's own decoders, so a shape prod
/// sends that the app cannot read is found here before a person meets it.
///
/// Read-only, every one: GETs through the same functions the screens call. No turn with the
/// agent, no tick, no save, nothing decided. The member is `ios-test`, who is not the owner, so
/// what only the owner may read must be refused, and that is checked too.
@MainActor
@Suite(.prod, .serialized, .timeLimit(.minutes(3)))
struct ProdReadTests {
    private func api() throws -> API { try Prod.api() }

    private func today(plus days: Int = 0) -> String {
        EventTime.dayString(Calendar.current.date(byAdding: .day, value: days, to: .now)!)
    }

    @Test func whoIsSignedInIsTheTestMemberNotTheOwner() async throws {
        let me = try await api().me()
        #expect(me.username == "ios-test", "the prod check must run as its own member, never a person's")
        #expect(me.isOwner != true)
        let full: YouKit.Me = try await api().get("/api/auth/me")
        #expect(full.member.username == "ios-test")
    }

    @Test func theAgendaReadsAMonth() async throws {
        let events = try await api().agendaEvents(from: today(), to: today(plus: 31))
        #expect(events.allSatisfy { !$0.id.isEmpty })
        _ = try await api().agendaHousehold()
        _ = try await api().agendaFamily()
    }

    @Test func theBoardReadsTodayAndAWeekAhead() async throws {
        let day = try await api().boardDay(nil)
        #expect(!day.day.isEmpty)
        _ = try await api().boardDay(today(plus: 7))
        _ = try await api().family()
    }

    @Test func tasksRead() async throws {
        _ = try await api().tasksDay(nil)
        _ = try await api().tasksAll()
    }

    @Test func holdsAndConversationsRead() async throws {
        let rows = try await api().pending()
        #expect(rows.allSatisfy { !$0.id.isEmpty })
        let page = try await api().threads()
        if let first = page.threads.first {
            _ = try await api().thread(first.id)
        }
    }

    @Test func theMailboxStatusReads() async throws {
        let st = try await api().mailStatus()
        #expect(["own", "household", ""].contains(st.via))
    }

    @Test func meetingsAndRemindersRead() async throws {
        let client = HouseholdArea.Client(api: try api())
        _ = try await client.booking()
        _ = try await client.upcoming()
        _ = try await client.busy()
        _ = try await client.reminders()
        _ = try await client.calendars()
    }

    @Test func theMembersOwnSettingsRead() async throws {
        let a = try api()
        let _: YouKit.ModelMenu = try await a.get("/api/models")
        let _: YouKit.EmailListing = try await a.get("/api/auth/emails")
        let _: YouKit.PasskeyListing = try await a.get("/api/auth/passkeys")
        let _: YouKit.Family = try await a.get("/api/family")
        // Memory may be off on a luach (503 with a sentence); either answer is a good one.
        do { let _: YouKit.MemoryListing = try await a.get("/api/memory") } catch let e as APIError where e.status == 503 {}
    }

    @Test func whatOnlyTheOwnerMayReadIsRefused() async throws {
        let a = try api()
        for path in ["/api/members", "/api/boards"] {
            await #expect(throws: APIError.self, "\(path) answered a member who is not the owner") {
                let _: API.Ignored = try await a.get(path)
            }
        }
    }

    /// Every member reads the audit chain; only the owner reads the addresses in it.
    @Test func theAuditAMemberReadsHasNoAddressesInIt() async throws {
        let trail: JSONValue = try await api().get("/api/control/audit", query: ["limit": "200"])
        let text = String(decoding: try JSONEncoder().encode(trail), as: UTF8.self)
        let address = try Regex(#"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"#)
        #expect(text.firstMatch(of: address) == nil, "an address in the audit a member reads")
    }
}
