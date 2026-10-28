import Foundation
@testable import Luach

/// A luach that answers from the test: each test gets its own host, so tests run in
/// parallel without seeing each other's routes or requests.
///
///     let server = StubServer()
///     server.on("GET", "/api/tasks/all", json: ["tasks": [], "may_assign": true])
///     let api = server.api
///     … then `server.requests` holds what the app sent.
final class StubServer: @unchecked Sendable {
    struct Reply {
        var status = 200
        var body = Data()
        var contentType = "application/json"
    }

    struct Request {
        let method: String
        let path: String
        let query: [String: String]
        let body: Data
        let headers: [String: String]
        /// How long the app said it would wait for this answer.
        var timeout: TimeInterval = 60

        /// The JSON body the app sent, as a dictionary.
        var json: [String: Any] {
            (try? JSONSerialization.jsonObject(with: body)) as? [String: Any] ?? [:]
        }
    }

    let host = "t\(UUID().uuidString.prefix(8).lowercased()).test"
    var url: URL { URL(string: "https://\(host)")! }

    /// An API pointed at this server, its requests answered by `StubProtocol`.
    @MainActor var api: API { API(server: url, protocolClasses: [StubProtocol.self]) }

    private let lock = NSLock()
    private var routes: [(method: String, path: String, reply: (Request) -> Reply)] = []
    private var seen: [Request] = []

    init() {
        StubProtocol.register(self)
    }

    deinit {
        StubProtocol.unregister(host)
    }

    var requests: [Request] { lock.withLock { seen } }

    func requests(_ method: String, _ path: String) -> [Request] {
        requests.filter { $0.method == method && $0.path == path }
    }

    /// Answer `method path` (exact path; the query is ignored) with a reply built per request.
    func on(_ method: String, _ path: String, _ reply: @escaping (Request) -> Reply) {
        lock.withLock { routes.append((method, path, reply)) }
    }

    func on(_ method: String, _ path: String, status: Int = 200, json: Any) {
        let body = (try? JSONSerialization.data(withJSONObject: json, options: [.fragmentsAllowed])) ?? Data()
        on(method, path) { _ in Reply(status: status, body: body) }
    }

    func on(_ method: String, _ path: String, status: Int = 200, raw: String, contentType: String = "application/json") {
        on(method, path) { _ in Reply(status: status, body: Data(raw.utf8), contentType: contentType) }
    }

    /// luach's error shape: `{"error": "<human sentence>"}`.
    func fail(_ method: String, _ path: String, status: Int, _ sentence: String) {
        on(method, path, status: status, json: ["error": sentence])
    }

    /// An `/api/agent/stream` answer: one `data:` line per frame, with a keepalive comment
    /// between, as the server sends them.
    func stream(_ frames: [[String: Any]], path: String = "/api/agent/stream") {
        let body = frames.map { frame -> String in
            let data = try! JSONSerialization.data(withJSONObject: frame)
            return ": keepalive\ndata: \(String(decoding: data, as: UTF8.self))\n\n"
        }.joined()
        on("POST", path, raw: body, contentType: "text/event-stream")
    }

    fileprivate func answer(_ request: Request) -> Reply {
        let route = lock.withLock { () -> ((Request) -> Reply)? in
            seen.append(request)
            // The last route registered for a path wins, so a test can change its mind.
            return routes.last { $0.method == request.method && $0.path == request.path }?.reply
        }
        return route?(request) ?? Reply(status: 404, body: Data(#"{"error":"no such route"}"#.utf8))
    }
}

nonisolated final class StubProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var servers: [String: StubServer] = [:]

    static func register(_ server: StubServer) {
        lock.withLock { servers[server.host] = server }
    }

    static func unregister(_ host: String) {
        lock.withLock { _ = servers.removeValue(forKey: host) }
    }

    override class func canInit(with request: URLRequest) -> Bool {
        guard let host = request.url?.host() else { return false }
        return lock.withLock { servers[host] != nil }
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let url = request.url, let host = url.host(),
              let server = Self.lock.withLock({ Self.servers[host] }) else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost))
            return
        }
        let query = Dictionary(
            (URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []).map { ($0.name, $0.value ?? "") },
            uniquingKeysWith: { _, last in last })
        let incoming = StubServer.Request(
            method: request.httpMethod ?? "GET",
            path: url.path(percentEncoded: false),
            query: query,
            body: Self.body(of: request),
            headers: request.allHTTPHeaderFields ?? [:],
            timeout: request.timeoutInterval)
        let reply = server.answer(incoming)
        let response = HTTPURLResponse(url: url, statusCode: reply.status, httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Type": reply.contentType])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: reply.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    /// URLSession moves a body into a stream before a protocol sees it.
    private static func body(of request: URLRequest) -> Data {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return Data() }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 16_384)
        while stream.hasBytesAvailable {
            let n = stream.read(&buffer, maxLength: buffer.count)
            if n <= 0 { break }
            data.append(buffer, count: n)
        }
        return data
    }
}
