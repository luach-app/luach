import Foundation

/// luach's answer to a request that did not work: `{"error": "<human sentence>"}`.
struct APIError: LocalizedError {
    let status: Int
    let message: String

    var errorDescription: String? { message }
}

/// The luach HTTP API (docs/API.md). Auth is the `luach_session` cookie the
/// server sets on sign-in; it carries a max-age, so the shared cookie store
/// keeps it across launches and the app stays signed in.
final class API {
    var server: URL
    /// Called on a 401 from anything but sign-in, so the app can return to the sign-in screen.
    var onSignedOut: (() -> Void)?

    private let session: URLSession
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()
    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    /// `protocolClasses`: tests answer requests themselves (LuachTests' StubServer).
    init(server: URL, protocolClasses: [AnyClass] = []) {
        self.server = server
        let config = URLSessionConfiguration.default
        if !protocolClasses.isEmpty { config.protocolClasses = protocolClasses }
        config.httpCookieStorage = .shared
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        session = URLSession(configuration: config, delegate: RedirectGuard(), delegateQueue: nil)
    }

    /// A redirect is followed only to an address the app may use at all: never from https to
    /// plain http, where the session cookie would travel readable.
    final class RedirectGuard: NSObject, URLSessionTaskDelegate {
        func urlSession(
            _ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
            newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void
        ) {
            completionHandler(request.url.map { ServerAddress.isAllowed($0) } == true ? request : nil)
        }
    }

    // MARK: Plain JSON

    func get<T: Decodable>(_ path: String, query: [String: String] = [:]) async throws -> T {
        try await send(request("GET", path, query: query))
    }

    func post<T: Decodable>(_ path: String, _ body: some Encodable) async throws -> T {
        try await send(request("POST", path, body: body))
    }

    func post<T: Decodable>(_ path: String) async throws -> T {
        try await post(path, Empty())
    }

    func patch<T: Decodable>(_ path: String, _ body: some Encodable, query: [String: String] = [:]) async throws -> T {
        try await send(request("PATCH", path, query: query, body: body))
    }

    func put<T: Decodable>(_ path: String, _ body: some Encodable) async throws -> T {
        try await send(request("PUT", path, body: body))
    }

    func delete<T: Decodable>(_ path: String, query: [String: String] = [:]) async throws -> T {
        try await send(request("DELETE", path, query: query))
    }

    struct Empty: Codable {}

    /// Any answer, for calls whose reply the caller does not read (`{"ok": true, …}`).
    struct Ignored: Decodable {}

    /// The decoder every call uses (snake_case keys), for feature code decoding by hand.
    var jsonDecoder: JSONDecoder { decoder }

    func request(
        _ method: String, _ path: String, query: [String: String] = [:], body: (any Encodable)? = nil
    ) throws -> URLRequest {
        // Nothing, the session cookie least of all, goes to a luach over plain http.
        guard ServerAddress.isAllowed(server) else { throw ServerAddress.Problem.notSecure }
        var url = server.appending(path: path)
        if !query.isEmpty {
            url.append(queryItems: query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) })
        }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try encoder.encode(body)
        }
        return req
    }

    func send<T: Decodable>(_ req: URLRequest) async throws -> T {
        let (data, response) = try await session.data(for: req)
        try check(response, data, path: req.url?.path ?? "")
        return try decoder.decode(T.self, from: data)
    }

    func check(_ response: URLResponse, _ data: Data, path: String) throws {
        guard let http = response as? HTTPURLResponse, http.statusCode >= 400 else { return }
        struct Body: Decodable { let error: String }
        let message = (try? decoder.decode(Body.self, from: data))?.error
            ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
        if http.statusCode == 401, !path.hasPrefix("/api/auth/") {
            onSignedOut?()
        }
        throw APIError(status: http.statusCode, message: message)
    }

    // MARK: Auth

    /// What `GET /api/auth/status` says of a luach, asked before anyone signs in to it.
    struct ServerStatus: Decodable, Equatable {
        /// Whether this luach sends mail, and if not, how its owner resets a password by hand.
        struct Mail: Decodable, Equatable {
            var enabled = true
            /// What mail cannot do here, in a sentence; "" when it works.
            var limitation = ""
            /// The command whoever runs the server types to set a password without mail.
            var offlineReset = ""

            init(enabled: Bool = true, limitation: String = "", offlineReset: String = "") {
                self.enabled = enabled
                self.limitation = limitation
                self.offlineReset = offlineReset
            }

            init(from decoder: Decoder) throws {
                let c = try decoder.container(keyedBy: CodingKeys.self)
                enabled = (try? c.decodeIfPresent(Bool.self, forKey: .enabled)) ?? true
                limitation = (try? c.decodeIfPresent(String.self, forKey: .limitation)) ?? ""
                offlineReset = (try? c.decodeIfPresent(String.self, forKey: .offlineReset)) ?? ""
            }

            private enum CodingKeys: String, CodingKey { case enabled, limitation, offlineReset }
        }

        let usersExist: Bool
        /// The household's name, "" when it has none (an older luach does not say).
        var household = ""
        var mail = Mail()

        init(usersExist: Bool, household: String = "", mail: Mail = Mail()) {
            self.usersExist = usersExist
            self.household = household
            self.mail = mail
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            usersExist = try c.decode(Bool.self, forKey: .usersExist)
            household = ((try? c.decodeIfPresent(String.self, forKey: .household)) ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            mail = (try? c.decodeIfPresent(Mail.self, forKey: .mail)) ?? Mail()
        }

        private enum CodingKeys: String, CodingKey { case usersExist, household, mail }
    }

    /// Asks `server` (not necessarily this API's own) whether it is a luach, before the sign-in
    /// screen asks for a password for it. The status is open: no session is needed.
    func status(of server: URL) async throws -> ServerStatus {
        let host = server.host() ?? server.absoluteString
        guard ServerAddress.isAllowed(server) else { throw ServerAddress.Problem.notSecure }
        var req = URLRequest(url: server.appending(path: "/api/auth/status"))
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.timeoutInterval = 20
        let reply: (Data, URLResponse)
        do {
            reply = try await session.data(for: req)
        } catch {
            throw ServerAddress.Problem.unreachable(host, error.localizedDescription)
        }
        let (data, response) = reply
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        if code == 200, let status = try? decoder.decode(ServerStatus.self, from: data) {
            return status
        }
        // A luach that is there but cannot answer says why in its own words ("luach is starting").
        struct Refusal: Decodable { let error: String }
        if code >= 400, let refusal = try? decoder.decode(Refusal.self, from: data) {
            throw ServerAddress.Problem.unreachable(host, refusal.error)
        }
        throw ServerAddress.Problem.notALuach(host)
    }

    /// `timeout`: how long to wait for an answer before giving up (URLSession's own is a minute).
    func me(timeout: TimeInterval? = nil) async throws -> Member {
        var req = try request("GET", "/api/auth/me")
        if let timeout { req.timeoutInterval = timeout }
        return try await send(req)
    }

    func login(username: String, password: String) async throws -> Member {
        struct Body: Encodable { let username: String; let password: String }
        return try await post("/api/auth/login", Body(username: username, password: password))
    }

    /// "Forgot your password?": luach mails a reset link if `email` is a member's. The answer
    /// is the same either way, so no one learns from it who is a member.
    func forgot(email: String) async throws {
        struct Body: Encodable { let email: String }
        let _: Ignored = try await post("/api/auth/forgot", Body(email: email))
    }

    /// Deletes the signed-in member's own account, after they typed their password again
    /// (`DELETE /api/auth/me`). The server signs every session of theirs out.
    func deleteAccount(password: String) async throws {
        struct Body: Encodable { let password: String }
        let _: Ignored = try await send(request("DELETE", "/api/auth/me", body: Body(password: password)))
    }

    func logout() async {
        _ = try? await post("/api/auth/logout") as Ignored
        for cookie in HTTPCookieStorage.shared.cookies(for: server) ?? [] {
            HTTPCookieStorage.shared.deleteCookie(cookie)
        }
    }

    // MARK: Holds

    func pending() async throws -> [PendingAction] {
        let list: PendingList = try await get("/api/control/pending")
        return list.pending
    }

    /// Approve runs the exact call that was held; deny drops it. 409 once someone else decided.
    func decide(_ id: String, approve: Bool) async throws -> PendingAction {
        try await post("/api/control/pending/\(id)/\(approve ? "approve" : "deny")")
    }

    func thread(_ id: String) async throws -> ThreadDetail {
        try await get("/api/threads/\(id)")
    }

    // MARK: Voice

    func transcribe(audio: Data, contentType: String) async throws -> String {
        struct Reply: Decodable { let text: String }
        var req = try request("POST", "/api/transcribe")
        req.setValue(contentType, forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.upload(for: req, from: audio)
        try check(response, data, path: "/api/transcribe")
        return try decoder.decode(Reply.self, from: data).text
    }

    // MARK: The agent

    /// One turn of `POST /api/agent/stream`, frame by frame. Cancelling the
    /// consuming task closes the connection; luach keeps the turn, ending `(stopped)`.
    func ask(_ text: String, threadID: String?) -> AsyncThrowingStream<StreamFrame, Error> {
        struct Body: Encodable { let text: String; let threadId: String? }
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var req = try request("POST", "/api/agent/stream", body: Body(text: text, threadId: threadID))
                    req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    req.timeoutInterval = 300
                    let (bytes, response) = try await session.bytes(for: req)
                    if let http = response as? HTTPURLResponse, http.statusCode >= 400 {
                        var data = Data()
                        for try await byte in bytes { data.append(byte) }
                        try check(response, data, path: "/api/agent/stream")
                    }
                    // `data: <json>` per line; `: keepalive` comments are not frames.
                    for try await line in bytes.lines where line.hasPrefix("data:") {
                        let json = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
                        if let frame = try? decoder.decode(StreamFrame.self, from: Data(json.utf8)) {
                            continuation.yield(frame)
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
