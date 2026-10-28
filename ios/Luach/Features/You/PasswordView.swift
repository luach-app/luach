import SwiftUI

/// Settings › Security › Password: the current one, then the new one twice.
struct PasswordView: View {
    @Environment(AppSession.self) private var session
    @State private var model: YouPasswordModel

    init(model: YouPasswordModel = YouPasswordModel()) {
        _model = State(initialValue: model)
    }

    var body: some View {
        Form {
            Section("Current password") {
                SecureField("Current password", text: $model.current)
                    .textContentType(.password)
                    .accessibilityIdentifier("password.current")
            }
            Section {
                SecureField("New password", text: $model.next)
                    .textContentType(.newPassword)
                    .accessibilityIdentifier("password.new")
                SecureField("Repeat new password", text: $model.confirm)
                    .textContentType(.newPassword)
                    .accessibilityIdentifier("password.repeat")
            } header: {
                Text("New password")
            } footer: {
                Text("At least 8 characters.")
            }
            Section {
                Button {
                    Task { await model.submit(session) }
                } label: {
                    HStack {
                        Text("Update password")
                        if model.busy {
                            Spacer()
                            ProgressView()
                        }
                    }
                }
                .disabled(model.busy || !model.filled)
                .accessibilityIdentifier("password.submit")
            }
            if model.error != nil || model.done {
                Section {
                    YouError(message: model.error)
                    if model.done { YouDone("Password changed.") }
                }
            }
        }
        .onChange(of: [model.current, model.next, model.confirm]) { model.edited() }
        .confirmsDiscard(!model.done && !(model.current + model.next + model.confirm).isEmpty)
    }
}

/// The password form's checks and its one call; the view only lays it out.
@Observable
final class YouPasswordModel {
    var current = ""
    var next = ""
    var confirm = ""
    private(set) var busy = false
    private(set) var error: String?
    private(set) var done = false

    var filled: Bool { !current.isEmpty && !next.isEmpty && !confirm.isEmpty }

    /// Typing again takes "Password changed." away (clearing the form after the change does not).
    func edited() {
        if !current.isEmpty || !next.isEmpty { done = false }
    }

    /// What is wrong with the new password before asking the server, if anything.
    var problem: String? {
        if next != confirm { return String(localized: "The two new passwords do not match.") }
        // The web form's minlength, before the server says the same.
        if next.count < 8 { return String(localized: "The new password must be at least 8 characters.") }
        return nil
    }

    struct Change: Encodable {
        let current: String
        let new: String
    }

    func submit(_ session: AppSession) async {
        done = false
        error = nil
        if let problem {
            error = problem
            return
        }
        busy = true
        defer { busy = false }
        do {
            let _: API.Ignored = try await session.api.post("/api/auth/password", Change(current: current, new: next))
            current = ""
            next = ""
            confirm = ""
            done = true
        } catch {
            self.error = error.localizedDescription
        }
    }
}
