import Foundation
import Observation

/// Who is signed in, to which luach. Every household runs its own luach, so there is no built-in
/// server: the sign-in screen asks for its address, and the app remembers it once a sign-in there
/// succeeds.
@Observable
final class AppSession {
    enum Phase: Equatable {
        case starting
        case signedOut
        /// The server could not be reached at launch; not the same as signed out.
        case unreachable(String)
        case signedIn(Member)
    }

    private(set) var phase: Phase = .starting
    let api: API
    let pending: PendingStore
    /// The member's reminders as notifications on this phone.
    let reminders: LocalReminders

    /// What the luach said of itself (`GET /api/auth/status`): its household's name and whether
    /// it sends mail, for the sign-in screen. Nil until asked.
    private(set) var status: API.ServerStatus?

    var server: URL { api.server }

    /// Whether the app knows a luach yet: one an earlier sign-in remembered (or `-server` at
    /// launch), or one just checked on the sign-in screen. Until then it asks for the address.
    private(set) var hasServer: Bool

    /// The luach the app was pointed at before "Use another address", to start the address
    /// field from.
    private(set) var previousServer: URL?

    /// How long the launch check waits for the luach before saying it is out of reach. It was
    /// URLSession's minute, on a blank screen, for a phone away from the home network.
    static let launchTimeout: TimeInterval = 12

    var member: Member? {
        if case .signedIn(let m) = phase { return m }
        return nil
    }

    private static let serverKey = "server"
    /// Where the API points while no luach is known. `.invalid` never resolves, and nothing is
    /// sent while `hasServer` is false anyway.
    private static let nowhere = URL(string: "https://luach.invalid")!

    /// `api`: tests hand in one answered by their stub server, which counts as a known luach
    /// unless `hasServer` says otherwise.
    init(api: API? = nil, hasServer known: Bool? = nil, reminders: LocalReminders = LocalReminders()) {
        let saved = Self.savedServer()
        self.api = api ?? API(server: saved ?? Self.nowhere)
        hasServer = known ?? (api != nil || saved != nil)
        pending = PendingStore(api: self.api)
        self.reminders = reminders
        self.api.onSignedOut = { [weak self] in self?.phase = .signedOut }
        #if DEBUG
        // `-signedOut YES` starts at the sign-in screen, whatever the cookie jar holds (UI tests).
        let signedOut = UserDefaults.standard.bool(forKey: "signedOut")
        if signedOut {
            for cookie in HTTPCookieStorage.shared.cookies ?? [] { HTTPCookieStorage.shared.deleteCookie(cookie) }
        }
        // For checking screens in the simulator: launch arguments land in UserDefaults, so
        //   simctl launch <device> <bundle id> -server https://luach.example.com -sessionCookie <token>
        // opens signed in. The token comes from `scripts/verify_dev_pod.py mint`; log it out after.
        if !signedOut, hasServer, let token = UserDefaults.standard.string(forKey: "sessionCookie"), let host = self.api.server.host(),
           let cookie = HTTPCookie(properties: [.name: "luach_session", .value: token, .domain: host, .path: "/", .secure: "TRUE"]) {
            HTTPCookieStorage.shared.setCookie(cookie)
        }
        #endif
    }

    /// The luach an earlier build was signed in to. Builds before the address step remembered a
    /// server only when someone changed it, so a phone that always used the built-in one has no
    /// saved address, only its session cookie: that cookie's host is the luach it was using, and
    /// it is saved, so an update does not sign anyone out.
    /// The luach this phone signs in to, if it may still be used. An address an older build
    /// remembered over plain http is forgotten, with its cookies: the app reaches luach only over
    /// https now (ServerAddress.url), and asks for the address again.
    static func savedServer(_ defaults: UserDefaults = .standard, cookies: HTTPCookieStorage = .shared) -> URL? {
        guard let saved = defaults.string(forKey: serverKey).flatMap(URL.init(string:)) else {
            return signedInBefore(cookies.cookies ?? [])
        }
        guard ServerAddress.isAllowed(saved) else {
            for cookie in cookies.cookies(for: saved) ?? [] { cookies.deleteCookie(cookie) }
            defaults.removeObject(forKey: serverKey)
            return nil
        }
        return saved
    }

    static func signedInBefore(_ cookies: [HTTPCookie]) -> URL? {
        guard let cookie = cookies.first(where: { $0.name == "luach_session" && $0.isSecure }) else { return nil }
        let host = cookie.domain.hasPrefix(".") ? String(cookie.domain.dropFirst()) : cookie.domain
        guard !host.isEmpty, let url = URL(string: "https://\(host)") else { return nil }
        UserDefaults.standard.set(url.absoluteString, forKey: serverKey)
        return url
    }

    func restore() async {
        guard hasServer else {
            phase = .signedOut
            return
        }
        phase = .starting // "Reaching <host>…", on "Try again" too
        do {
            phase = .signedIn(try await api.me(timeout: Self.launchTimeout))
        } catch let error as APIError where error.status == 401 {
            phase = .signedOut
        } catch {
            phase = .unreachable(error.localizedDescription)
        }
    }

    /// After the member changed something about themselves (PATCH /api/auth/me).
    func setMember(_ member: Member) {
        if case .signedIn = phase { phase = .signedIn(member) }
    }

    /// Checks that `address` (as typed: "luach.example.com" or a full URL) is a luach someone can
    /// sign in to, and points the app at it for the sign-in that follows. It is remembered only
    /// once that sign-in succeeds.
    @discardableResult
    func connect(to address: String) async throws -> URL {
        let url = try ServerAddress.url(from: address)
        let status = try await api.status(of: url)
        guard status.usersExist else { throw ServerAddress.Problem.noAccounts(ServerAddress.display(url)) }
        if url != api.server { await forgetHere() }
        api.server = url
        hasServer = true
        self.status = status
        return url
    }

    /// Asks the known luach about itself again, for the sign-in screen (its name, its mail).
    /// Quiet when it does not answer: the sign-in that follows says why.
    func refreshStatus() async {
        guard hasServer else { return }
        let asked = api.server
        if let fresh = try? await api.status(of: asked), asked == api.server { status = fresh }
    }

    func login(username: String, password: String) async throws {
        let member = try await api.login(username: username, password: password)
        let before = UserDefaults.standard.string(forKey: Self.serverKey)
        if before != api.server.absoluteString { await forgetHere() }
        UserDefaults.standard.set(api.server.absoluteString, forKey: Self.serverKey)
        phase = .signedIn(member)
    }

    func logout() async {
        await api.logout()
        await forgetHere()
        phase = .signedOut
    }

    /// The account was deleted (Settings › Delete account): the server signed every session
    /// out; this phone forgets the cookie and everything it kept.
    func accountDeleted() async {
        dropCookies()
        await forgetHere()
        phase = .signedOut
    }

    /// "Use another address", from the out-of-reach screen: back to the address step of
    /// sign-in. The luach that did not answer is remembered until a sign-in elsewhere succeeds.
    func useAnotherAddress() async {
        previousServer = api.server
        hasServer = false
        status = nil
        await forgetHere()
        phase = .signedOut
    }

    /// "Sign out", from the out-of-reach screen. The luach cannot be told, so this phone
    /// forgets its session (the server's copy expires on its own) and the open conversation.
    func signOutHere() async {
        dropCookies()
        await forgetHere()
        phase = .signedOut
    }

    private func dropCookies() {
        for cookie in HTTPCookieStorage.shared.cookies(for: api.server) ?? [] {
            HTTPCookieStorage.shared.deleteCookie(cookie)
        }
    }

    /// Everything this phone kept of a household and its member: the agenda's cache, the open
    /// conversation, the held actions, and the reminders iOS would still show. Nothing of one
    /// household may show for the next one signed in here.
    func forgetHere() async {
        AgendaData.shared.forget()
        Conversation.forget()
        pending.clear()
        await reminders.clear()
    }

    // MARK: Notifications

    /// The member's reminders and the Approvals count on the icon, worked out again.
    func refreshReminders() async {
        guard let member else { return }
        await reminders.refresh(api: api, member: member)
        await reminders.badge(pending.items.count)
    }

    /// iOS woke the app for a moment (BGAppRefreshTask): what is waiting, and the reminders.
    func backgroundRefresh() async {
        if member == nil, hasServer, let me = try? await api.me(timeout: Self.launchTimeout) {
            phase = .signedIn(me)
        }
        guard member != nil else { return }
        await pending.refresh()
        await refreshReminders()
    }
}

/// Held actions, shared by the Approvals tab (and its badge) and the Ask view.
@Observable
final class PendingStore {
    private(set) var items: [PendingAction] = []
    private(set) var error: String?
    /// The last approval that did not go through: it leaves the list like any decided
    /// one, so this is where the person learns nothing changed. Cleared by the next.
    private(set) var failure: String?
    private let api: API
    /// Bumped by `clear()`: a list asked for before then is not shown after.
    private var generation = 0

    init(api: API) {
        self.api = api
    }

    func refresh() async {
        let mine = generation
        do {
            let fresh = try await api.pending().filter { $0.status == "pending" }
            guard mine == generation else { return }
            items = fresh
            error = nil
        } catch {
            guard mine == generation, !AgendaData.cancelled(error) else { return }
            self.error = error.localizedDescription
        }
    }

    /// Signed out: nothing of the last household's waits here.
    func clear() {
        generation += 1
        items = []
        error = nil
        failure = nil
    }

    func decide(_ id: String, approve: Bool) async throws -> PendingAction {
        defer { Task { await refresh() } }
        failure = nil
        let row = try await api.decide(id, approve: approve)
        // An approval ran the held call: the agenda (and the reminders worked out from it) change.
        if approve && !row.failed { AgendaData.shared.invalidate() }
        if row.failed {
            let why = row.failure.map { ": \($0)" } ?? ""
            failure = String(localized: "It did not go through") + why
        }
        return row
    }
}
