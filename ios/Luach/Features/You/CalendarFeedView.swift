import SwiftUI
import UIKit

/// Settings › Calendar feed: luach's events in this iPhone's own Calendar app, read-only,
/// through a secret link the Calendar app subscribes to (`webcal://`). The server keeps only a
/// fingerprint of the link, so it is shown once, when it is made; a lost or leaked link is
/// reset, which makes a new one and stops the old.
struct CalendarFeedView: View {
    @Environment(AppSession.self) private var session
    @Environment(\.openURL) private var openURL
    @State private var model: YouFeedModel
    @State private var confirming: YouFeedModel.Confirm?

    init(model: YouFeedModel = YouFeedModel()) {
        _model = State(initialValue: model)
    }

    var body: some View {
        Form {
            Section {
                Text("Show luach’s events in this iPhone’s own Calendar app, read-only. It holds a month back and a year ahead: titles, places, notes and whom each event is for. Never who is invited, nothing waiting for approval, and not your work calendar.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            if let status = model.status {
                Section {
                    Picker("What it shows", selection: Binding(
                        get: { model.scope },
                        set: { scope in Task { await model.choose(scope, session) } }
                    )) {
                        Text("The whole household").tag(YouFeedModel.Scope.household)
                        Text("Only mine").tag(YouFeedModel.Scope.mine)
                    }
                    .accessibilityIdentifier("feed.scope")
                } footer: {
                    if model.scope == .mine {
                        Text("The events that are yours, and the ones that are everyone’s.")
                    } else {
                        Text("Every event, with whom each one is for.")
                    }
                }

                if let link = model.link {
                    Section {
                        Text(link.url)
                            .font(.footnote.monospaced())
                            .textSelection(.enabled)
                            .accessibilityIdentifier("feed.url")
                        Button("Add to Calendar", systemImage: "calendar.badge.plus") {
                            if let url = URL(string: link.webcal) { openURL(url) }
                        }
                        Button { model.copy() } label: {
                            if model.copied {
                                Label("Copied", systemImage: "checkmark")
                            } else {
                                Label("Copy link", systemImage: "doc.on.doc")
                            }
                        }
                    } header: {
                        Text("Your link")
                    } footer: {
                        Text("Add to Calendar subscribes this iPhone. In Google Calendar on the web: Other calendars › + › From URL, and paste the link. luach keeps only a fingerprint of it, so this is the one time it is shown.")
                    }
                } else if status.enabled {
                    Section {
                        LabeledContent("Last read by a calendar", value: model.lastRead)
                    } footer: {
                        Text("The link was shown once, when it was made. To add it somewhere new, reset it.")
                    }
                }

                Section {
                    if status.enabled {
                        Button("Reset link") { confirming = .reset }
                        Button("Turn off", role: .destructive) { confirming = .off }
                    } else {
                        Button("Turn on") { Task { await model.turnOn(session) } }
                            .accessibilityIdentifier("feed.on")
                    }
                } footer: {
                    Text("Anyone with the link can read the calendar, so keep it like a password. Reset link makes a new one, and the old one stops working at once.")
                }
            }
            if let error = model.error {
                Section { YouError(message: error) }
            }
        }
        .disabled(model.busy)
        .overlay { if model.status == nil && model.error == nil { ProgressView() } }
        .task { await model.load(session) }
        .refreshable { await model.load(session) }
        .confirmationDialog(
            confirming == .off ? Text("Turn the feed off?") : Text("Make a new link?"),
            isPresented: Binding(get: { confirming != nil }, set: { if !$0 { confirming = nil } }),
            titleVisibility: .visible,
            presenting: confirming
        ) { which in
            switch which {
            case .reset:
                Button("Reset link") { Task { await model.reset(session) } }
            case .off:
                Button("Turn off", role: .destructive) { Task { await model.turnOff(session) } }
            }
            Button("Keep it", role: .cancel) {}
        } message: { which in
            switch which {
            case .reset: Text("Calendars subscribed to the old link stop updating; add the new one to them.")
            case .off: Text("Calendars subscribed to it stop updating, and the link stops working.")
            }
        }
    }
}

/// What the calendar feed screen shows and changes; the view only lays it out.
@Observable
final class YouFeedModel {
    enum Scope: String, Codable, Hashable { case household, mine }
    enum Confirm: Hashable { case reset, off }

    /// `GET /api/feed`: whether it is on, what it holds, when a calendar last read it. Never
    /// the link.
    struct Status: Decodable, Equatable {
        let enabled: Bool
        let scope: Scope
        let createdAt: String?
        let lastRead: String?
    }

    /// Turn on and Reset: the link, this once, and the webcal:// form a phone subscribes to.
    struct Link: Decodable, Equatable {
        let enabled: Bool
        let scope: Scope
        let createdAt: String?
        let lastRead: String?
        let url: String
        let webcal: String

        var status: Status { Status(enabled: enabled, scope: scope, createdAt: createdAt, lastRead: lastRead) }
    }

    private struct Body: Encodable { let scope: String }

    private(set) var status: Status?
    private(set) var link: Link?
    private(set) var scope: Scope = .household
    private(set) var busy = false
    private(set) var error: String?
    private(set) var copied = false
    /// Where Copy link puts it; a test hands in its own.
    var pasteboard: (String) -> Void = { UIPasteboard.general.string = $0 }

    var lastRead: String {
        guard let read = status?.lastRead, !read.isEmpty else { return String(localized: "not yet") }
        return YouKit.relative(read)
    }

    func load(_ session: AppSession) async {
        do {
            let got: Status = try await session.api.get("/api/feed")
            status = got
            scope = got.scope
            error = nil
        } catch is CancellationError {
            return
        } catch {
            self.error = error.localizedDescription
        }
    }

    func turnOn(_ session: AppSession) async {
        await made { try await session.api.post("/api/feed", Body(scope: self.scope.rawValue)) }
    }

    func reset(_ session: AppSession) async {
        await made { try await session.api.post("/api/feed/reset") }
    }

    func turnOff(_ session: AppSession) async {
        await run {
            let got: Status = try await session.api.delete("/api/feed")
            self.status = got
            self.link = nil
            self.copied = false
        }
    }

    /// What it holds, on the same link; off, it is only the choice Turn on will send.
    func choose(_ next: Scope, _ session: AppSession) async {
        let before = scope
        scope = next
        guard status?.enabled == true, next != before else { return }
        await run {
            let got: Status = try await session.api.patch("/api/feed", Body(scope: next.rawValue))
            self.status = got
            self.scope = got.scope
        }
        if error != nil { scope = before }
    }

    func copy() {
        guard let link else { return }
        pasteboard(link.url)
        copied = true
    }

    private func made(_ call: @escaping () async throws -> Link) async {
        await run {
            let got = try await call()
            self.link = got
            self.status = got.status
            self.scope = got.scope
            self.copied = false
        }
    }

    private func run(_ work: () async throws -> Void) async {
        busy = true
        error = nil
        defer { busy = false }
        do {
            try await work()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
