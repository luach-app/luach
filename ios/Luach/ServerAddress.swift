import Foundation

/// A household's luach, as someone types its address on the sign-in screen. There is no built-in
/// server: every household runs its own, so the app asks for it before anything else.
enum ServerAddress {
    /// What "What's luach?" opens: the project's page, which says what luach is and how a household
    /// runs one.
    static let about = URL(string: "https://github.com/luach-app/luach")!

    /// Why an address cannot be used, in words for the person typing it.
    enum Problem: LocalizedError, Equatable {
        case notAnAddress
        /// Plain http. luach is reached over https only, at home too.
        case notSecure
        /// Something answered, but not as a luach does.
        case notALuach(String)
        /// Nothing answered, or the luach could not say: the host and why.
        case unreachable(String, String)
        /// A luach no one has signed up to yet.
        case noAccounts(String)

        var errorDescription: String? {
            switch self {
            case .notAnAddress:
                return String(localized: "That does not look like an address. Try something like luach.example.com.")
            case .notSecure:
                return String(localized: "Use an https:// address. The app signs in to luach only over https, at home too: whoever set it up can put it behind a reverse proxy with a certificate.")
            case .notALuach(let host):
                return String(localized: "\(host) answered, but it is not a luach. Check the address with whoever set it up.")
            case .unreachable(let host, let why):
                return String(localized: "Could not reach \(host): \(why)")
            case .noAccounts(let host):
                return String(localized: "No one has an account on \(host) yet. Make the first one there in a browser, then sign in here.")
            }
        }
    }

    /// The luach `text` names: "luach.example.com" or a full URL, https:// when no scheme is given.
    ///
    /// Plain http is refused, even to a private address. A password and the session cookie would
    /// cross the network readable, and "192.168.1.20" names a different machine on every network:
    /// a phone that remembered a luach at home would send its session to whatever answers that
    /// address in a café. https proves which server it is. Debug builds alone may reach this
    /// device's own loopback (`allowsLoopback`), for the simulator and the screenshots.
    static func url(from text: String) throws -> URL {
        var typed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if !typed.contains("://") { typed = "https://" + typed }
        guard !typed.contains(where: \.isWhitespace),
              var parts = URLComponents(string: typed),
              let scheme = parts.scheme?.lowercased(), ["https", "http"].contains(scheme),
              let host = parts.host, !host.isEmpty, parts.user == nil else {
            throw Problem.notAnAddress
        }
        parts.scheme = scheme
        while parts.path.hasSuffix("/") { parts.path.removeLast() }
        parts.query = nil
        parts.fragment = nil
        guard let url = parts.url else { throw Problem.notAnAddress }
        guard isAllowed(url) else { throw Problem.notSecure }
        return url
    }

    /// Whether the app may talk to `url` at all: https, or (debug builds only) http to this
    /// device's loopback. Every request checks it (`API.request`), so a saved address from an
    /// older build cannot send anything in the clear.
    static func isAllowed(_ url: URL, loopback: Bool = allowsLoopback) -> Bool {
        switch url.scheme?.lowercased() {
        case "https": return url.host() != nil
        case "http": return loopback && isLoopback(url.host() ?? "")
        default: return false
        }
    }

    /// Debug builds reach a luach on this device over plain http (the simulator's demo
    /// household for the App Store screenshots); a release build never does.
    #if DEBUG
    static let allowsLoopback = true
    #else
    static let allowsLoopback = false
    #endif

    /// The address as a person would say it: the host (and port and path, if any) for https, the
    /// whole URL for http, so a plain connection is never mistaken for a safe one.
    static func display(_ url: URL) -> String {
        guard url.scheme == "https", let host = url.host() else { return url.absoluteString }
        let port = url.port.map { ":\($0)" } ?? ""
        let path = url.path() == "/" ? "" : url.path()
        return host + port + path
    }

    /// This device itself: `localhost`, 127.0.0.0/8 or ::1. Not a private network, which is
    /// shared with whoever else is on it.
    static func isLoopback(_ host: String) -> Bool {
        let host = host.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
        if host == "localhost" || host == "::1" { return true }
        let quads = host.split(separator: ".", omittingEmptySubsequences: false).map { UInt8($0) }
        return quads.count == 4 && quads.allSatisfy { $0 != nil } && quads[0] == 127
    }
}
