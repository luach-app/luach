import SwiftUI

/// Sign-in, to the household's own luach: first its address (when the app does not know one yet),
/// checked before anyone types a password for it; then the username and password, with the
/// address shown small underneath and a way to change it.
struct LoginView: View {
    @Environment(AppSession.self) private var session
    @State private var address = ""
    /// Pressed "Change": asking for an address although the app knows one.
    @State private var changing = false
    @State private var username = ""
    @State private var password = ""
    @State private var busy = false
    @State private var error: String?
    @State private var forgot = false
    @FocusState private var focus: Field?

    private enum Field { case address, username, password }

    /// The luach this sign-in is for, or nil while the screen asks for one.
    private var luach: URL? {
        session.hasServer && !changing ? session.server : nil
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(spacing: 6) {
                        Text("לוח")
                            .font(.system(size: 56, weight: .heavy))
                            .foregroundStyle(.tint)
                        Text(Self.householdLine(luach == nil ? nil : session.status?.household))
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .accessibilityIdentifier("login.household")
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .listRowBackground(Color.clear)
                }

                if let luach {
                    credentials(luach)
                } else {
                    whereIsIt
                }
            }
            .onAppear {
                // Back from "Use another address": start from the one that did not answer.
                if address.isEmpty, !session.hasServer, let previous = session.previousServer {
                    address = ServerAddress.display(previous)
                }
            }
            // A luach remembered from an earlier sign-in: its name, and whether it sends mail.
            .task(id: luach) {
                if luach != nil, session.status == nil { await session.refreshStatus() }
            }
            .navigationDestination(isPresented: $forgot) {
                ForgotPasswordView(mail: session.status?.mail)
            }
        }
    }

    /// "The Rivera household calendar" once the address is checked and the household has a name;
    /// "The household calendar" otherwise.
    static func householdLine(_ name: String?) -> String {
        guard let name = name?.trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty else {
            return String(localized: "The household calendar")
        }
        return String(localized: "The \(name) household calendar")
    }

    // MARK: The address

    @ViewBuilder private var whereIsIt: some View {
        Section {
            TextField("luach.example.com", text: $address)
                .keyboardType(.URL)
                .textContentType(.URL)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($focus, equals: .address)
                .submitLabel(.continue)
                .onSubmit(check)
        } header: {
            Text("Your luach's address")
                .font(.headline)
                .foregroundStyle(.primary)
                .textCase(nil)
        } footer: {
            VStack(alignment: .leading, spacing: 8) {
                if let error {
                    Text(error).foregroundStyle(.red)
                }
                Text("luach runs on your household's own server. Ask whoever set it up for its address.")
                Link("What's luach?", destination: ServerAddress.about)
            }
        }

        Section {
            Button(action: check) {
                HStack {
                    Spacer()
                    if busy { ProgressView() } else { Text("Continue").bold() }
                    Spacer()
                }
            }
            .disabled(busy || address.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }

    private func check() {
        guard !busy, !address.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        busy = true
        error = nil
        Task {
            defer { busy = false }
            do {
                try await session.connect(to: address)
                changing = false
                focus = .username
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    // MARK: Signing in

    @ViewBuilder private func credentials(_ luach: URL) -> some View {
        Section {
            TextField("Username or email", text: $username)
                .textContentType(.username)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($focus, equals: .username)
                .submitLabel(.next)
                .onSubmit { focus = .password }
            SecureField("Password", text: $password)
                .textContentType(.password)
                .focused($focus, equals: .password)
                .submitLabel(.go)
                .onSubmit(signIn)
        } footer: {
            if let error {
                Text(error).foregroundStyle(.red)
            }
        }

        Section {
            Button(action: signIn) {
                HStack {
                    Spacer()
                    if busy { ProgressView() } else { Text("Sign in").bold() }
                    Spacer()
                }
            }
            .disabled(busy || username.isEmpty || password.isEmpty)
        } footer: {
            Button("Forgot your password?") {
                error = nil
                forgot = true
            }
            .font(.footnote)
            .frame(maxWidth: .infinity)
            .padding(.top, 8)
            .disabled(busy)
            .accessibilityIdentifier("login.forgot")
        }

        Section {
            HStack {
                Label(ServerAddress.display(luach), systemImage: "house")
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer()
                Button("Change") {
                    address = ServerAddress.display(luach)
                    error = nil
                    changing = true
                    focus = .address
                }
                .buttonStyle(.borderless)
                .disabled(busy)
            }
            .font(.footnote)
            .listRowBackground(Color.clear)
        }
    }

    private func signIn() {
        guard !busy, !username.isEmpty, !password.isEmpty else { return }
        busy = true
        error = nil
        Task {
            defer { busy = false }
            do {
                try await session.login(username: username, password: password)
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

/// "Forgot your password?": a reset link by mail, as on the web. A luach that sends no mail
/// says so instead, with what its owner runs on the server, rather than promising a link that
/// would never come.
struct ForgotPasswordView: View {
    @Environment(AppSession.self) private var session
    let mail: API.ServerStatus.Mail?
    @State private var email = ""
    @State private var busy = false
    @State private var sent = false
    @State private var error: String?

    var body: some View {
        Form {
            if let mail, !mail.enabled {
                withoutMail(mail)
            } else if sent {
                Section {
                    Label("If that address is a member, a reset link is on its way by email. It expires in 30 minutes.",
                          systemImage: "envelope.badge")
                } footer: {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Open the link on this phone or any browser, choose a new password there, then sign in here with it.")
                        if let limitation = mail?.limitation, !limitation.isEmpty { Text(limitation) }
                    }
                }
            } else {
                Section {
                    TextField("Email", text: $email)
                        .keyboardType(.emailAddress)
                        .textContentType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .submitLabel(.send)
                        .onSubmit(send)
                        .accessibilityIdentifier("forgot.email")
                } header: {
                    Text("The email address of your account")
                } footer: {
                    VStack(alignment: .leading, spacing: 8) {
                        if let error { Text(error).foregroundStyle(.red) }
                        Text("We will email you a reset link if that address belongs to a member. It expires in 30 minutes.")
                        if let limitation = mail?.limitation, !limitation.isEmpty { Text(limitation) }
                    }
                }
                Section {
                    Button(action: send) {
                        HStack {
                            Spacer()
                            if busy { ProgressView() } else { Text("Send the link").bold() }
                            Spacer()
                        }
                    }
                    .disabled(busy || email.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .navigationTitle("Reset your password")
        .navigationBarTitleDisplayMode(.inline)
    }

    @ViewBuilder private func withoutMail(_ mail: API.ServerStatus.Mail) -> some View {
        Section {
            Text("This luach does not send email, so a reset link cannot reach you.")
                .font(.headline)
            Text("Ask whoever runs luach to set a new password for you. On the server, they run:")
            Text(verbatim: mail.offlineReset.isEmpty ? "docker compose exec luach python -m luach.passwd <username>" : mail.offlineReset)
                .font(.footnote.monospaced())
                .textSelection(.enabled)
                .environment(\.layoutDirection, .leftToRight)
                .accessibilityIdentifier("forgot.offline")
        }
    }

    private func send() {
        let address = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !busy, !address.isEmpty else { return }
        busy = true
        error = nil
        Task {
            defer { busy = false }
            do {
                try await session.api.forgot(email: address)
                sent = true
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}
