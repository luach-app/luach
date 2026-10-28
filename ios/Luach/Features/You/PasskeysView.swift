import SwiftUI

/// Settings › Security › Passkeys: the member's passkeys, and removing one.
/// Making one needs the app's associated domain (`webcredentials:`), which waits
/// on Apple signing, so "Add a passkey" opens the web app in Safari meanwhile.
struct PasskeysView: View {
    @Environment(AppSession.self) private var session
    @State private var model: YouPasskeysModel

    init(model: YouPasskeysModel = YouPasskeysModel()) {
        _model = State(initialValue: model)
    }

    var body: some View {
        List {
            Section {
                if let loadError = model.loadError {
                    YouError(message: loadError)
                } else if let list = model.list, list.isEmpty {
                    Text("No passkeys yet.").foregroundStyle(.secondary)
                }
                ForEach(model.list ?? []) { key in
                    row(key)
                }
            } footer: {
                Text("Face ID, Touch ID or your phone — no password to type.")
            }
            Section {
                Link(destination: session.server) {
                    Label("Add a passkey", systemImage: "person.badge.key")
                }
            } footer: {
                Text("Opens the web app in Safari: this app can make passkeys once Apple has signed it.")
            }
            if let error = model.error {
                Section { YouError(message: error) }
            }
        }
        .overlay { if model.list == nil && model.loadError == nil { ProgressView() } }
        .confirmationDialog(
            "Remove this passkey?",
            isPresented: Binding(get: { model.confirm != nil }, set: { if !$0 { model.confirm = nil } }),
            titleVisibility: .visible,
            presenting: model.confirm
        ) { key in
            Button("Remove \(YouPasskeysModel.name(key))", role: .destructive) {
                Task { await model.remove(key.id, session) }
            }
            Button("Keep", role: .cancel) { model.confirm = nil }
        } message: { _ in
            Text("It will no longer sign you in. Your password and other passkeys still will.")
        }
        .refreshable { await model.load(session) }
        .task { await model.load(session) }
    }

    private func row(_ key: YouKit.Passkey) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "key.fill").foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(YouPasskeysModel.name(key))
                Text(YouPasskeysModel.detail(key, zone: session.member?.timezone))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .swipeActions {
            Button("Remove", role: .destructive) { model.ask(key) }
        }
        .contextMenu {
            Button("Remove", systemImage: "trash", role: .destructive) { model.ask(key) }
        }
    }
}

/// What the passkeys screen shows and removes; the view only lays it out.
@Observable
final class YouPasskeysModel {
    private(set) var list: [YouKit.Passkey]?
    private(set) var loadError: String?
    var confirm: YouKit.Passkey?
    private(set) var busy = false
    private(set) var error: String?

    /// A passkey's name, or "Passkey" for one made without.
    static func name(_ key: YouKit.Passkey) -> String {
        (key.name ?? "").isEmpty ? String(localized: "Passkey") : key.name!
    }

    /// "Added 26 Oct, 10:07 · used 3 days ago" (or "never used").
    static func detail(_ key: YouKit.Passkey, zone: String?) -> String {
        let used = key.lastUsed.map { String(localized: "used \(YouKit.relative($0))") } ?? String(localized: "never used")
        return String(localized: "Added \(YouKit.timestamp(key.createdAt, zone: zone)) · \(used)")
    }

    func ask(_ key: YouKit.Passkey) {
        error = nil
        confirm = key
    }

    func load(_ session: AppSession) async {
        do {
            let l: YouKit.PasskeyListing = try await session.api.get("/api/auth/passkeys")
            list = l.passkeys
            loadError = nil
        } catch is CancellationError {
            return
        } catch {
            loadError = error.localizedDescription
        }
    }

    func remove(_ id: String, _ session: AppSession) async {
        confirm = nil
        busy = true
        error = nil
        defer { busy = false }
        do {
            let l: YouKit.PasskeyListing = try await session.api.delete("/api/auth/passkeys/\(id)")
            list = l.passkeys
        } catch {
            self.error = error.localizedDescription
        }
    }
}
