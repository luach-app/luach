import AuthenticationServices
import SwiftUI

struct MailStatus: Decodable {
    struct Scan: Decodable {
        /// Whether this luach runs the scan at all.
        let available: Bool
        let enabled: Bool
        /// When it was turned on: mail from before is not read.
        let since: String
        let minutes: Int
        let read: Int?
        let proposed: Int?
        let lastRead: String?
    }

    let connected: Bool
    /// The Gmail address when connected here; "" for the household grant.
    let address: String
    /// `own` (connected here) or `household` (the owner's mailbox the email door reads).
    let via: String
    let canConnect: Bool
    let scan: Scan?
}

extension API {
    func mailStatus() async throws -> MailStatus {
        try await get("/api/mail")
    }

    /// Google's consent URL for a connect the app starts (POST /api/mail/connect/app).
    func mailConsentURL() async throws -> URL {
        struct Reply: Decodable { let url: String }
        let reply: Reply = try await post("/api/mail/connect/app")
        guard let url = URL(string: reply.url) else { throw URLError(.badURL) }
        return url
    }

    /// Claims the grant a connect from this app left waiting under `nonce` (POST
    /// /api/mail/connect/app/finish). The nonce comes back only through `luach://mail`, and
    /// only the session that started the connect can claim it.
    func finishMailConnect(nonce: String) async throws -> MailStatus {
        struct Body: Encodable { let nonce: String }
        return try await post("/api/mail/connect/app/finish", Body(nonce: nonce))
    }

    func setMailScan(_ enabled: Bool) async throws -> MailStatus {
        struct Body: Encodable { let enabled: Bool }
        return try await patch("/api/mail/scan", Body(enabled: enabled))
    }

    func disconnectMail() async throws -> MailStatus {
        try await delete("/api/mail")
    }
}

/// Settings › You › Your Gmail. Each person connects their own, read-only; the chat
/// searches that mailbox for them and nobody else.
struct MailboxView: View {
    @Environment(AppSession.self) private var session
    @Environment(\.webAuthenticationSession) private var webAuth
    @State private var status: MailStatus?
    @State private var unavailable: String?
    @State private var came: String?
    @State private var busy = false
    @State private var error: String?
    /// The browser sheet, as a function: a test stands in for Google's consent with its own.
    private let signIn: ((URL) async throws -> URL)?

    init(signIn: ((URL) async throws -> URL)? = nil) {
        self.signIn = signIn
    }

    var body: some View {
        Form {
            Section {
                Text("Connect your Gmail and ask the chat about it — “when is our flight?”, “what did the school send?” — and have it add what it finds. luach only reads, only when you ask, and only your own mailbox: nobody else in the family can search it, and you cannot search theirs.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            if came == "connected" {
                Label("Your email is connected.", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
            } else if came == "failed" {
                Label("Connecting your email did not work. Try again, or ask whoever set luach up.", systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
            } else if came == "not-yours" {
                Label("That Gmail is not one of your addresses here, so it was not connected. Add it under your addresses and confirm it, then connect again — or choose your own account when Google asks.", systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
            }

            if let unavailable {
                Text(unavailable).foregroundStyle(.secondary)
            } else if let status {
                connection(status)
                if status.connected, let scan = status.scan, scan.available {
                    scanSection(scan)
                }
            } else {
                ProgressView().frame(maxWidth: .infinity)
            }

            if let error {
                Text(error).foregroundStyle(.red)
            }
        }
        .disabled(busy)
        .task { await refresh() }
        .refreshable { await refresh() }
    }

    @ViewBuilder
    private func connection(_ st: MailStatus) -> some View {
        if st.connected {
            Section {
                VStack(alignment: .leading, spacing: 4) {
                    Text(st.address.isEmpty ? "Connected" : "Connected as **\(st.address)**")
                    if st.via == "household" {
                        Text("The household mailbox, the one you forward things to.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                if st.via == "own" {
                    Button("Disconnect", role: .destructive) { Task { await disconnect() } }
                }
            }
            // The owner reads the household mailbox until they connect their own; once
            // they do, theirs is the one every search and the scan use.
            if st.via == "household" && st.canConnect {
                Section {
                    Button("Connect my own Gmail") { Task { await connect() } }
                } footer: {
                    Text("This is the household's shared connection. Connect your own to have luach read your Gmail through its own access, which you can disconnect here at any time.")
                }
            }
        } else if st.canConnect {
            Section {
                Button {
                    Task { await connect() }
                } label: {
                    Label("Connect my Gmail", systemImage: "envelope.badge")
                }
            }
        } else {
            Section {
                Text("Connecting email is not set up on this luach yet.").foregroundStyle(.secondary)
            }
        }
    }

    private func scanSection(_ scan: MailStatus.Scan) -> some View {
        Section {
            Toggle(isOn: Binding(get: { scan.enabled }, set: { on in Task { await setScan(on) } })) {
                Text("Look through new mail for things to add")
            }
            if scan.enabled, scan.read != nil {
                Label(ScanLine.text(scan), systemImage: "circle.fill")
                    .labelStyle(DotLabel())
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        } footer: {
            Text(scanFooter(scan))
        }
    }

    private func scanFooter(_ scan: MailStatus.Scan) -> String {
        var s = String(localized: "Every \(scan.minutes) minutes luach reads what has arrived — not promotions or social mail — and when it finds an appointment, a booking or a date, it asks you under Approvals. Nothing is added until you say yes, and only you see what it found.")
        if scan.enabled, let since = ScanLine.date(scan.since) {
            s += " " + String(localized: "Reading mail from \(since.formatted(date: .abbreviated, time: .omitted)) on.")
        }
        return s
    }

    private func refresh() async {
        do {
            status = try await session.api.mailStatus()
            unavailable = nil
        } catch is CancellationError {
        } catch {
            unavailable = error.localizedDescription
        }
    }

    /// Google's consent opens in a browser sheet; luach sends it back to `luach://mail`,
    /// which closes the sheet. The sheet has no luach session: the state carries who, and
    /// the way back carries a one-time nonce this app claims with its own session — so a
    /// consent link finished on anyone else's phone connects nothing.
    private func connect() async {
        came = nil
        error = nil
        busy = true
        defer { busy = false }
        do {
            let consent = try await session.api.mailConsentURL()
            let back: URL
            if let signIn {
                back = try await signIn(consent)
            } else {
                back = try await webAuth.authenticate(
                    using: consent, callbackURLScheme: "luach", preferredBrowserSession: .shared)
            }
            switch MailReturn(back) {
            case .confirm(let nonce):
                status = try await session.api.finishMailConnect(nonce: nonce)
                came = "connected"
            case .connected:
                came = "connected"
            case .notYours:
                came = "not-yours"
            case .failed:
                came = "failed"
            }
        } catch let e as ASWebAuthenticationSessionError where e.code == .canceledLogin {
            // Closed the sheet: nothing happened, nothing to say.
        } catch {
            self.error = error.localizedDescription
        }
        await refresh()
    }

    private func disconnect() async {
        busy = true
        defer { busy = false }
        do { status = try await session.api.disconnectMail() } catch { self.error = error.localizedDescription }
    }

    private func setScan(_ on: Bool) async {
        busy = true
        defer { busy = false }
        do { status = try await session.api.setMailScan(on) } catch { self.error = error.localizedDescription }
    }
}

/// Where luach's way back from Google (`luach://mail?…`) leaves a connect the app started.
enum MailReturn: Equatable {
    /// Google said yes: claim the grant with this nonce (`finishMailConnect`).
    case confirm(String)
    /// Stored already (a luach from before the nonce).
    case connected
    /// The Gmail signed in to is not one of this member's addresses.
    case notYours
    case failed

    init(_ url: URL) {
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func value(_ name: String) -> String? { items.first { $0.name == name }?.value }
        switch value("mail") {
        case "confirm":
            if let nonce = value("nonce"), !nonce.isEmpty { self = .confirm(nonce) } else { self = .failed }
        case "connected":
            self = .connected
        case "failed" where value("reason") == "not-yours":
            self = .notYours
        default:
            self = .failed
        }
    }
}

/// The email scan, seen working (web lib/scan.ts): it read 120 emails and proposed 6
/// events before anyone could tell it was running.
enum ScanLine {
    static func text(_ scan: MailStatus.Scan) -> String {
        var parts = [String(localized: "Reading your email every \(scan.minutes) minutes")]
        if let last = scan.lastRead.flatMap({ date($0) }) {
            parts.append(String(localized: "last \(last.formatted(date: .abbreviated, time: .shortened))"))
        }
        if let read = scan.read { parts.append(String(localized: "\(read) read")) }
        if let found = scan.proposed { parts.append(String(localized: "\(found) found")) }
        return parts.joined(separator: " · ")
    }

    /// luach's times are UTC; older rows come without the offset.
    static func date(_ s: String) -> Date? {
        guard !s.isEmpty else { return nil }
        let withZone = s.hasSuffix("Z") || s.contains("+") || s.dropFirst(19).contains("-") ? s : s + "Z"
        return EventTime.parse(withZone)
    }
}

/// A small green dot before the text, as the web shows a scan that is running.
private struct DotLabel: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) {
            Circle().fill(.green).frame(width: 6, height: 6)
            configuration.title
        }
    }
}
