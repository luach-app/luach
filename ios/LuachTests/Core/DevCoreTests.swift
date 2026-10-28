import Foundation
import Testing
@testable import Luach

/// The core calls against a real luach (dev): read-only, so they can run on every build.
@MainActor
@Suite(.dev, .timeLimit(.minutes(3)))
struct DevCoreTests {
    @Test func whoIsSignedIn() async throws {
        let me = try await Dev.api().me()
        #expect(!me.username.isEmpty && !me.name.isEmpty)
    }

    @Test func theHoldsDecode() async throws {
        let rows = try await Dev.api().pending()
        #expect(rows.allSatisfy { !$0.id.isEmpty && !$0.summary.isEmpty })
    }

    @Test func theConversationsDecodeAndOneOpens() async throws {
        let api = try Dev.api()
        let page = try await api.threads()
        if let first = page.threads.first {
            let thread = try await api.thread(first.id)
            #expect(thread.id == first.id)
        }
    }

    @Test func theMailboxStatusDecodes() async throws {
        let st = try await Dev.api().mailStatus()
        #expect(["own", "household", ""].contains(st.via))
    }

    @Test func aTurnStreamsFromTheRealAgent() async throws {
        // A question that changes nothing; the thread it leaves is deleted.
        let api = try Dev.api()
        let c = Conversation()
        c.send("Say the word ready, and nothing else.", api: api) {}
        while c.streaming { try await Task.sleep(for: .milliseconds(100)) }
        let thread = try #require(c.threadID)
        #expect(c.items.contains { if case .footer = $0.kind { true } else { false } })
        #expect(!c.items.contains { if case .error = $0.kind { true } else { false } })
        try await api.deleteThread(thread)
        Conversation.forget()
    }

    @Test func aWrongPasswordIsRefusedWithASentence() async throws {
        let api = try Dev.api()
        await #expect {
            _ = try await api.login(username: "ios-test-nobody", password: "not-a-password")
        } throws: { ($0 as? APIError).map { $0.status == 401 || $0.status == 429 } ?? false }
    }
}
