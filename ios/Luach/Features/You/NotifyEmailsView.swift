import SwiftUI

/// Settings › You › Also notify: inboxes that get a Google Calendar invitation to
/// every event you create. The list is replaced on Save (PATCH /api/auth/me
/// `notify_emails`); a new address is mailed a confirmation link first.
struct NotifyEmailsView: View {
    @Environment(AppSession.self) private var session
    @State private var model: YouNotifyModel

    init(model: YouNotifyModel = YouNotifyModel()) {
        _model = State(initialValue: model)
    }

    var body: some View {
        List {
            Section {
                Text("Every event *you* add — here, by asking, or by email — also sends a Google Calendar invitation to these addresses, such as a work inbox. Nobody else's events reach them.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            if let loadError = model.loadError {
                Section { YouError(message: loadError) }
            } else if model.me != nil {
                Section {
                    ForEach(model.list, id: \.self) { email in
                        row(email)
                    }
                    .onDelete { model.delete(at: $0) }
                    TextField("you@work.com", text: $model.draft)
                        .keyboardType(.emailAddress)
                        .textContentType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .submitLabel(.next)
                        .onSubmit { model.commit() }
                        .onChange(of: model.draft) { model.bad = false }
                        .accessibilityIdentifier("notify.draft")
                } header: {
                    Text("Addresses")
                } footer: {
                    if model.bad {
                        Text("That is not an email address.").foregroundStyle(.red)
                    } else {
                        Text("Press return after each address. Say “don’t invite anyone” to skip them for one event.")
                    }
                }
                if !model.pending.isEmpty {
                    Section {
                        Text("Waiting for confirmation — these are invited to nothing until the link is followed.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
                if model.error != nil || model.showsSaved {
                    Section {
                        YouError(message: model.error)
                        if model.showsSaved { YouDone("Saved.") }
                    }
                }
            }
        }
        .overlay { if model.me == nil && model.loadError == nil { ProgressView() } }
        .confirmsDiscard(model.dirty)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if model.busy {
                    ProgressView()
                } else {
                    Button("Save") { Task { await model.save(session) } }
                        .disabled(!model.dirty)
                        .accessibilityIdentifier("notify.save")
                }
            }
        }
        .task { await model.load(session) }
    }

    private func row(_ email: String) -> some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                Text(email).lineLimit(1).truncationMode(.middle)
                if model.pending.contains(email) {
                    Text("Waiting for confirmation").font(.caption).foregroundStyle(.orange)
                }
            }
            Spacer(minLength: 4)
            if model.pending.contains(email) {
                Button(model.sentTo == email ? "Sent" : "Resend") { Task { await model.resend(email, session) } }
                    .buttonStyle(.borderless)
                    .disabled(model.busy || model.sentTo == email)
            }
        }
    }
}

/// What Also notify shows and saves; the view only lays it out.
@Observable
final class YouNotifyModel {
    private(set) var me: YouKit.Me?
    private(set) var loadError: String?
    private(set) var list: [String] = []
    var draft = ""
    var bad = false
    private(set) var sentTo = ""
    private(set) var busy = false
    private(set) var error: String?
    private(set) var done = false

    var saved: [String] { (me?.notifyEmails ?? []) + (me?.notifyPending ?? []) }
    var pending: [String] { me?.notifyPending ?? [] }
    /// The address typed but not yet added, when it is one: Save counts it.
    var draftEmail: String {
        let e = YouKit.cleanEmail(draft)
        return YouKit.isEmail(e) && !list.contains(e) ? e : ""
    }
    var dirty: Bool { list != saved || !draftEmail.isEmpty }
    var showsSaved: Bool { done && !dirty }

    func delete(at offsets: IndexSet) {
        list.remove(atOffsets: offsets)
        done = false
    }

    /// The draft becomes a row when it is an address; otherwise say so.
    func commit() {
        let email = YouKit.cleanEmail(draft)
        guard !email.isEmpty else { return }
        guard YouKit.isEmail(email) else {
            bad = true
            return
        }
        if !list.contains(email) { list.append(email) }
        draft = ""
        bad = false
        done = false
    }

    func load(_ session: AppSession) async {
        do {
            let me: YouKit.Me = try await session.api.get("/api/auth/me")
            self.me = me
            list = saved
            loadError = nil
        } catch is CancellationError {
            return
        } catch {
            loadError = error.localizedDescription
        }
    }

    struct Patch: Encodable { let notifyEmails: [String] }

    /// The whole list, the draft too when it is an address.
    var patch: Patch { Patch(notifyEmails: draftEmail.isEmpty ? list : list + [draftEmail]) }

    func save(_ session: AppSession) async {
        done = false
        error = nil
        let body = patch
        busy = true
        defer { busy = false }
        do {
            let reply: YouKit.Me = try await session.api.patch("/api/auth/me", body)
            session.setMember(reply.member)
            me = reply
            list = reply.notifyEmails + reply.notifyPending
            draft = ""
            done = true
        } catch {
            self.error = error.localizedDescription
        }
    }

    private struct EmailBody: Encodable { let email: String }

    func resend(_ email: String, _ session: AppSession) async {
        error = nil
        busy = true
        defer { busy = false }
        do {
            let _: API.Ignored = try await session.api.post("/api/auth/emails/resend", EmailBody(email: email))
            sentTo = email
        } catch {
            self.error = error.localizedDescription
        }
    }
}
