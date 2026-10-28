import SwiftUI

/// Settings › You › Addresses you sign in with: the primary plus any extras.
/// Every call answers with the whole listing; a new address is mailed a
/// confirmation link and does nothing until it is followed.
struct EmailsView: View {
    @Environment(AppSession.self) private var session
    @State private var model: YouEmailsModel

    init(model: YouEmailsModel = YouEmailsModel()) {
        _model = State(initialValue: model)
    }

    var body: some View {
        List {
            Section {
                if let loadError = model.loadError {
                    YouError(message: loadError)
                }
                ForEach(Array(model.rows.enumerated()), id: \.element.id) { index, row in
                    rowView(row, primary: index == 0)
                }
            } footer: {
                Text("You can sign in with any of these once confirmed. Mail you send from them is yours.")
            }

            Section {
                TextField("name@example.com", text: $model.draft)
                    .keyboardType(.emailAddress)
                    .textContentType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.send)
                    .onSubmit { Task { await model.add(session) } }
                    .accessibilityIdentifier("emails.draft")
                Button("Add") { Task { await model.add(session) } }
                    .disabled(!model.canAdd)
                    .accessibilityIdentifier("emails.add")
            } header: {
                Text("Add an address")
            } footer: {
                Text("A new address gets a confirmation link and does nothing until you follow it.")
            }

            if let error = model.error {
                Section { YouError(message: error) }
            }
        }
        .overlay { if model.listing == nil && model.loadError == nil { ProgressView() } }
        .confirmationDialog(
            "Remove \(model.confirmRemove ?? "")?",
            isPresented: Binding(get: { model.confirmRemove != nil }, set: { if !$0 { model.confirmRemove = nil } }),
            titleVisibility: .visible,
            presenting: model.confirmRemove
        ) { email in
            Button("Remove", role: .destructive) { Task { await model.remove(email, session) } }
            Button("Keep", role: .cancel) { model.confirmRemove = nil }
        } message: { _ in
            Text("You will no longer be able to sign in with it.")
        }
        .refreshable { await model.load(session) }
        .task { await model.load(session) }
    }

    @ViewBuilder
    private func rowView(_ row: YouEmailsModel.Row, primary: Bool) -> some View {
        HStack(spacing: 8) {
            Text(row.email)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: 4)
            if !row.verified {
                YouBadge("unconfirmed", tint: .orange)
                Button(model.sentTo == row.email ? "Sent" : "Resend") { Task { await model.resend(row.email, session) } }
                    .buttonStyle(.borderless)
                    .disabled(model.busy || model.sentTo == row.email)
            } else if primary {
                YouBadge("primary", tint: .accentColor)
            } else {
                Menu {
                    Button("Make primary", systemImage: "star") { Task { await model.makePrimary(row.email, session) } }
                    Button("Remove", systemImage: "trash", role: .destructive) { model.askRemove(row.email) }
                } label: {
                    Image(systemName: "ellipsis.circle").imageScale(.large)
                }
                .disabled(model.busy)
                .accessibilityLabel("Actions for \(row.email)")
            }
        }
        .swipeActions(edge: .trailing) {
            if !primary {
                Button("Remove", role: .destructive) { model.askRemove(row.email) }
            }
        }
        .swipeActions(edge: .leading) {
            if !primary && row.verified {
                Button("Make primary") { Task { await model.makePrimary(row.email, session) } }.tint(.accentColor)
            }
        }
    }
}

/// What the addresses screen shows and changes; the view only lays it out.
@Observable
final class YouEmailsModel {
    struct Row: Identifiable, Equatable {
        let email: String
        let verified: Bool
        var id: String { email }
    }

    private(set) var listing: YouKit.EmailListing?
    private(set) var loadError: String?
    var draft = ""
    var confirmRemove: String?
    private(set) var sentTo = ""
    private(set) var busy = false
    private(set) var error: String?

    /// The primary first (confirmed by definition), then the others as listed.
    var rows: [Row] {
        guard let listing else { return [] }
        return [Row(email: listing.primary, verified: true)]
            + listing.emails.filter { $0.email != listing.primary }
                .map { Row(email: $0.email, verified: $0.verified != false) }
    }

    var canAdd: Bool { !busy && !draft.trimmingCharacters(in: .whitespaces).isEmpty && listing != nil }

    func askRemove(_ email: String) {
        error = nil
        confirmRemove = email
    }

    func load(_ session: AppSession) async {
        do {
            listing = try await session.api.get("/api/auth/emails")
            loadError = nil
        } catch is CancellationError {
            return
        } catch {
            loadError = error.localizedDescription
        }
    }

    /// Take a new listing, and tell the rest of the app (the primary is `member.email`).
    private func adopt(_ l: YouKit.EmailListing, _ session: AppSession) async {
        listing = l
        confirmRemove = nil
        if let member = try? await session.api.me() { session.setMember(member) }
    }

    private enum Change {
        case add(String), remove(String), primary(String)
    }

    private struct EmailBody: Encodable { let email: String }

    /// Every change answers with the whole listing.
    private func apply(_ change: Change, _ session: AppSession) async {
        busy = true
        error = nil
        defer { busy = false }
        do {
            let l: YouKit.EmailListing
            switch change {
            case .add(let email):
                l = try await session.api.post("/api/auth/emails", EmailBody(email: email))
                draft = ""
            case .remove(let email):
                l = try await session.api.delete("/api/auth/emails/\(email)")
            case .primary(let email):
                l = try await session.api.post("/api/auth/emails/primary", EmailBody(email: email))
            }
            await adopt(l, session)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func add(_ session: AppSession) async {
        let value = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        await apply(.add(value), session)
    }

    func remove(_ email: String, _ session: AppSession) async {
        confirmRemove = nil
        await apply(.remove(email), session)
    }

    func makePrimary(_ email: String, _ session: AppSession) async {
        await apply(.primary(email), session)
    }

    private struct ResendBody: Encodable { let email: String }

    func resend(_ email: String, _ session: AppSession) async {
        busy = true
        error = nil
        defer { busy = false }
        do {
            let _: API.Ignored = try await session.api.post("/api/auth/emails/resend", ResendBody(email: email))
            sentTo = email
        } catch {
            self.error = error.localizedDescription
        }
    }
}
