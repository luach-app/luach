import SwiftUI
import UIKit

/// Settings › Household › Members (owner): who shares the household calendar,
/// inviting by email, the invitations waiting, and — as on the web's Members
/// page — the family and the house boards, each a screen of its own.
struct MembersView: View {
    @Environment(AppSession.self) private var session
    @State private var model: YouMembersModel
    @State private var pushFamily = false
    @State private var pushBoards = false

    init(model: YouMembersModel = YouMembersModel()) {
        _model = State(initialValue: model)
    }

    var body: some View {
        List {
            Section {
                NavigationLink {
                    YouFamilyView()
                } label: {
                    Label("Family", systemImage: "person.3")
                }
                NavigationLink {
                    YouHouseBoardsView()
                } label: {
                    Label("House boards", systemImage: "rectangle.on.rectangle")
                }
            } footer: {
                Text("Who events and tasks are for, and the screens on the wall.")
            }

            Section {
                TextField("name@example.com", text: $model.email)
                    .keyboardType(.emailAddress)
                    .textContentType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.send)
                    .onSubmit { Task { await model.invite(session) } }
                    .accessibilityIdentifier("members.invite")
                Button {
                    Task { await model.invite(session) }
                } label: {
                    HStack {
                        Text("Send invitation")
                        if model.inviting {
                            Spacer()
                            ProgressView()
                        }
                    }
                }
                .disabled(!model.canInvite)
                YouError(message: model.inviteError)
                if let result = model.result {
                    if let link = result.link {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Mail is not configured — share this link yourself:")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                            Text(link)
                                .font(.caption.monospaced())
                                .lineLimit(2)
                                .truncationMode(.middle)
                                .textSelection(.enabled)
                            HStack(spacing: 16) {
                                Button(model.copied ? "Copied" : "Copy", systemImage: "doc.on.doc") {
                                    model.copy(link)
                                }
                                .accessibilityLabel("Copy invitation link")
                                if let url = URL(string: link) {
                                    ShareLink(item: url) { Label("Share", systemImage: "square.and.arrow.up") }
                                }
                            }
                            .buttonStyle(.borderless)
                        }
                    } else {
                        YouDone("Invitation sent.")
                    }
                }
            } header: {
                Text("Invite by email")
            }

            if let error = model.error {
                Section { YouError(message: error) }
            }
            if let actError = model.actError {
                Section { YouError(message: actError) }
            }

            if let data = model.data {
                Section("Household") {
                    ForEach(data.members) { m in
                        memberRow(m)
                    }
                }
                if !data.invites.isEmpty {
                    Section {
                        ForEach(data.invites) { i in
                            inviteRow(i)
                        }
                    } header: {
                        Text("Invitations")
                    } footer: {
                        Text("Swipe an invitation to revoke it.")
                    }
                }
            }
        }
        .overlay { if model.data == nil && model.error == nil { ProgressView() } }
        .confirmationDialog(
            "Remove \(model.confirmRemove?.name ?? "")?",
            isPresented: Binding(get: { model.confirmRemove != nil }, set: { if !$0 { model.confirmRemove = nil } }),
            titleVisibility: .visible,
            presenting: model.confirmRemove
        ) { m in
            Button("Remove", role: .destructive) { Task { await model.remove(m.id, session) } }
            Button("Keep", role: .cancel) { model.confirmRemove = nil }
        } message: { _ in
            Text("They will no longer be able to sign in to the household.")
        }
        .navigationDestination(isPresented: $pushFamily) { YouFamilyView() }
        .navigationDestination(isPresented: $pushBoards) { YouHouseBoardsView() }
        .refreshable { await model.load(session) }
        .task {
            #if DEBUG
            // `-youPush family` or `-youPush boards` opens that screen (simulator checks).
            switch YouDebug.value("youPush") {
            case "family": pushFamily = true
            case "boards": pushBoards = true
            default: break
            }
            #endif
            await model.load(session)
        }
    }

    private func memberRow(_ m: YouKit.Housemate) -> some View {
        HStack(spacing: 12) {
            Text(String(m.name.prefix(1)).uppercased())
                .font(.headline)
                .foregroundStyle(.tint)
                .frame(width: 40, height: 40)
                .background(Color.accentColor.opacity(0.15), in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(m.name).font(.body.weight(.medium)).lineLimit(1)
                    if m.isOwner == true { YouBadge("owner", tint: .accentColor) }
                }
                Text("@\(m.username)").font(.subheadline).foregroundStyle(.secondary)
                ForEach(Array(m.allEmails.enumerated()), id: \.element) { index, address in
                    Text(address)
                        .font(.subheadline.weight(index == 0 ? .semibold : .regular))
                        .foregroundStyle(index == 0 ? .primary : .secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                Text("Last seen \(YouKit.relative(m.lastSeen))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
        .swipeActions {
            if m.isOwner != true {
                Button("Remove", role: .destructive) { model.ask(m) }
            }
        }
        .contextMenu {
            if m.isOwner != true {
                Button("Remove", systemImage: "person.badge.minus", role: .destructive) { model.ask(m) }
            }
        }
    }

    private func inviteRow(_ i: YouKit.Invite) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(i.email).lineLimit(1).truncationMode(.middle)
                Text(YouMembersModel.inviteLine(i))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 4)
            if i.expired {
                YouBadge("expired", tint: .red)
            } else {
                YouBadge("pending", tint: .accentColor)
            }
        }
        .swipeActions {
            Button("Revoke", role: .destructive) { Task { await model.revoke(i.email, session) } }
        }
        .contextMenu {
            Button("Revoke invitation", systemImage: "xmark.circle", role: .destructive) { Task { await model.revoke(i.email, session) } }
        }
    }
}

/// What Members shows, invites and removes; the view only lays it out.
@Observable
final class YouMembersModel {
    struct InviteResult: Decodable {
        let sent: Bool
        let link: String?
    }

    private(set) var data: YouKit.MembersReply?
    private(set) var error: String?
    var email = ""
    private(set) var inviting = false
    private(set) var inviteError: String?
    private(set) var result: InviteResult?
    private(set) var copied = false
    var confirmRemove: YouKit.Housemate?
    private(set) var busy = false
    private(set) var actError: String?

    var canInvite: Bool { !inviting && !email.trimmingCharacters(in: .whitespaces).isEmpty }

    /// "Expires in 6 days · sent 3 days ago", or "Expired · sent …".
    static func inviteLine(_ i: YouKit.Invite) -> String {
        let state = i.expired ? String(localized: "Expired") : String(localized: "Expires \(YouKit.relative(i.expiresAt))")
        return String(localized: "\(state) · sent \(YouKit.relative(i.createdAt))")
    }

    func ask(_ m: YouKit.Housemate) {
        actError = nil
        confirmRemove = m
    }

    func copy(_ link: String) {
        UIPasteboard.general.string = link
        copied = true
    }

    func load(_ session: AppSession) async {
        do {
            data = try await session.api.get("/api/members")
            error = nil
        } catch is CancellationError {
            return
        } catch {
            self.error = error.localizedDescription
        }
    }

    private struct EmailBody: Encodable { let email: String }

    func invite(_ session: AppSession) async {
        let value = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        result = nil
        copied = false
        inviteError = nil
        inviting = true
        defer { inviting = false }
        do {
            result = try await session.api.post("/api/members/invite", EmailBody(email: value))
            email = ""
            await load(session)
        } catch {
            inviteError = error.localizedDescription
        }
    }

    func remove(_ id: Int, _ session: AppSession) async {
        confirmRemove = nil
        await act("/api/members/\(id)", session)
    }

    func revoke(_ address: String, _ session: AppSession) async {
        await act("/api/members/invite/\(address)", session)
    }

    /// A DELETE, then the list again.
    private func act(_ path: String, _ session: AppSession) async {
        busy = true
        actError = nil
        defer { busy = false }
        do {
            let _: API.Ignored = try await session.api.delete(path)
            await load(session)
        } catch {
            actError = error.localizedDescription
        }
    }
}
