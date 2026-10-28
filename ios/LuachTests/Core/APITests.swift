import Foundation
import Testing
@testable import Luach

@MainActor
struct APITests {
    let server = StubServer()

    @Test func signsInAndReadsTheMember() async throws {
        server.on("POST", "/api/auth/login", json: [
            "id": 1, "username": "robin", "display_name": "Robin", "email": "f@example.com",
            "timezone": "America/New_York", "language": "he", "is_owner": true, "last_seen": NSNull(),
        ])
        let member = try await server.api.login(username: "robin", password: "pw")
        #expect(member.name == "Robin" && member.isOwner == true && member.language == "he")
        let sent = try #require(server.requests("POST", "/api/auth/login").first)
        #expect(sent.json["username"] as? String == "robin" && sent.json["password"] as? String == "pw")
        #expect(sent.headers["Content-Type"] == "application/json")
    }

    @Test func aMemberWithoutADisplayNameIsCalledByTheirUsername() throws {
        let m = try JSONDecoder.snake.decode(Member.self, from: Data(#"{"id":2,"username":"ana","display_name":""}"#.utf8))
        #expect(m.name == "ana")
    }

    @Test func theServersSentenceIsTheError() async {
        server.fail("POST", "/api/auth/login", status: 401, "That username and password do not match.")
        await #expect {
            _ = try await server.api.login(username: "x", password: "y")
        } throws: { error in
            let e = error as? APIError
            return e?.status == 401 && e?.localizedDescription == "That username and password do not match."
        }
    }

    @Test func anErrorWithoutABodyStillSaysSomething() async {
        server.on("GET", "/api/auth/me", status: 502, raw: "<html>bad gateway</html>", contentType: "text/html")
        await #expect {
            _ = try await server.api.me()
        } throws: { error in
            (error as? APIError)?.status == 502 && !(error.localizedDescription.isEmpty)
        }
    }

    @Test func a401OutsideSignInSignsTheAppOut() async {
        let api = server.api
        var signedOut = 0
        api.onSignedOut = { signedOut += 1 }
        server.fail("GET", "/api/control/pending", status: 401, "sign in first")
        server.fail("POST", "/api/auth/login", status: 401, "wrong")
        _ = try? await api.pending()
        _ = try? await api.login(username: "a", password: "b")
        #expect(signedOut == 1, "a wrong password is not a lost session")
    }

    @Test func pendingRowsDecodeWhateverTheirSourceIs() async throws {
        server.on("GET", "/api/control/pending", json: ["pending": [
            ["id": "a", "tool": "create_event", "summary": "Add Dentist", "reason": ["ambiguous"],
             "principal": "robin", "door": "web", "status": "pending", "created_at": "2026-10-26T10:00:00+00:00", "source": ""],
            ["id": "b", "tool": "create_event", "summary": "Add Flight", "reason": ["from-your-email"],
             "principal": "robin", "door": "email-scan", "status": "pending",
             "source": ["kind": "email", "subject": "Your flight", "from": "air@example.com"]],
            ["id": "c", "tool": "delete_event", "summary": "Remove", "status": "approved"],
        ]])
        let rows = try await server.api.pending()
        #expect(rows.map(\.id) == ["a", "b", "c"])
        #expect(rows[0].source == nil && rows[1].source?.subject == "Your flight")
        #expect(rows[2].reason.isEmpty && rows[2].principal.isEmpty)
    }

    @Test func decidingPostsToTheRightPath() async throws {
        server.on("POST", "/api/control/pending/h1/approve", json: ["id": "h1", "tool": "t", "summary": "s", "status": "approved"])
        server.on("POST", "/api/control/pending/h2/deny", json: ["id": "h2", "tool": "t", "summary": "s", "status": "denied"])
        #expect(try await server.api.decide("h1", approve: true).status == "approved")
        #expect(try await server.api.decide("h2", approve: false).status == "denied")
    }

    @Test func queriesAreSentAndBodiesAreSnakeCase() async throws {
        struct Body: Encodable { let displayName: String }
        server.on("PATCH", "/api/auth/me", json: ["id": 1, "username": "robin"])
        let _: Member = try await server.api.patch("/api/auth/me", Body(displayName: "F"))
        #expect(server.requests("PATCH", "/api/auth/me").first?.json["display_name"] as? String == "F")

        server.on("GET", "/api/threads", json: ["threads": [], "more": false])
        _ = try await server.api.threads(before: "2026-10-01T00:00:00+00:00")
        #expect(server.requests("GET", "/api/threads").first?.query["before"] == "2026-10-01T00:00:00+00:00")
    }

    @Test func transcribingSendsTheAudioAsIs() async throws {
        server.on("POST", "/api/transcribe", json: ["text": "dentist on tuesday"])
        let audio = Data((0..<2048).map { UInt8($0 % 251) })
        let text = try await server.api.transcribe(audio: audio, contentType: "audio/mp4")
        #expect(text == "dentist on tuesday")
        let sent = try #require(server.requests("POST", "/api/transcribe").first)
        #expect(sent.body == audio && sent.headers["Content-Type"] == "audio/mp4")
    }

    @Test func threadsAreRenamedAndDeleted() async throws {
        server.on("PATCH", "/api/threads/t1", json: ["id": "t1", "title": "Dentist"])
        server.on("DELETE", "/api/threads/t1", json: ["ok": true])
        #expect(try await server.api.renameThread("t1", to: "Dentist") == "Dentist")
        try await server.api.deleteThread("t1")
        #expect(server.requests("DELETE", "/api/threads/t1").count == 1)
    }

    @Test func eventTimesReadBothShapes() throws {
        let instant = try #require(EventTime.parse("2026-09-16T15:00:00-04:00"))
        #expect(instant == Date(timeIntervalSince1970: 1_789_585_200))
        #expect(EventTime.parse("2026-09-16T19:00:00.250Z") != nil)
        let day = try #require(EventTime.parse("2026-09-16"))
        #expect(EventTime.dayString(day) == "2026-09-16")
        #expect(EventTime.parse("next tuesday") == nil)
    }
}
