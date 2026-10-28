import SwiftUI

/// Settings › Security › Delete account: the member deletes their own account on this luach,
/// after typing their password again (`DELETE /api/auth/me`). What goes and what stays is said
/// before anything is pressed; the owner is told the server's answer when others still belong.
struct DeleteAccountView: View {
    @Environment(AppSession.self) private var session
    @State private var password = ""
    @State private var busy = false
    @State private var error: String?
    @State private var confirming = false

    var body: some View {
        Form {
            Section {
                Text("Your account on \(host) is deleted for good: you are signed out everywhere, and your conversations, addresses, passkeys, reminders, busy calendars, booking page, Gmail connection and what luach remembers about you go with it.")
                Text("The household’s calendar stays as it is, with the events on it. Your entry in the family stays until the owner removes it.")
                    .foregroundStyle(.secondary)
                if session.member?.isOwner == true {
                    Text("You own this household: remove the other members first. Deleting the last account returns this luach to its first-run setup.")
                        .foregroundStyle(.secondary)
                }
            }

            Section {
                SecureField("Password", text: $password)
                    .textContentType(.password)
                    .submitLabel(.done)
                    .accessibilityIdentifier("delete.password")
            } header: {
                Text("Type your password to confirm")
            } footer: {
                if let error {
                    Text(error).foregroundStyle(.red)
                }
            }

            Section {
                Button(role: .destructive) { confirming = true } label: {
                    HStack {
                        Spacer()
                        if busy { ProgressView() } else { Text("Delete my account").bold() }
                        Spacer()
                    }
                }
                .disabled(busy || password.isEmpty)
                .accessibilityIdentifier("delete.button")
            }
        }
        .confirmationDialog("Delete your account?", isPresented: $confirming, titleVisibility: .visible) {
            Button("Delete my account", role: .destructive) { Task { await delete() } }
            Button("Keep it", role: .cancel) {}
        } message: {
            Text("This cannot be undone.")
        }
        .interactiveDismissDisabled(busy)
    }

    private var host: String { ServerAddress.display(session.server) }

    private func delete() async {
        guard !busy, !password.isEmpty else { return }
        busy = true
        error = nil
        defer { busy = false }
        do {
            try await session.api.deleteAccount(password: password)
            password = ""
            await session.accountDeleted()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
