import SwiftUI

/// Settings, in the web app's sections: who I am, what the household shares,
/// how people book me, what luach tells me, and the record.
struct AccountSheet: View {
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if let member = session.member {
                    Section {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(member.name).font(.title3.bold())
                            Text("@\(member.username)\(member.isOwner == true ? " · " + String(localized: "owner") : "")")
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                group("You", [.profile, .emails, .mailbox, .notify, .memory])
                // luach's events in this iPhone's own Calendar app (a webcal:// subscription).
                group("Calendar feed", [.calendarFeed])
                if session.member?.isOwner == true {
                    group("Household", [.members, .household, .models])
                }
                group("Meetings", [.booking, .busy])
                // Reminders show on this iPhone as notifications the app schedules (LocalReminders).
                group("Reminders", [.reminders])
                group("Security", session.member?.isOwner == true
                      ? [.passkeys, .password, .audit, .deleteAccount] : [.passkeys, .password, .deleteAccount])
                Section {
                    Link(destination: session.server) {
                        Label("Open the web app", systemImage: "safari")
                    }
                    LabeledContent("Server", value: session.server.host() ?? session.server.absoluteString)
                }
                Section {
                    Button("Sign out", role: .destructive) {
                        Task { await session.logout() }
                    }
                } footer: {
                    Text("luach \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "") (\(Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? ""))")
                        .frame(maxWidth: .infinity)
                        .padding(.top, 8)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: Screen.self) { screen in
                screen.view.navigationTitle(screen.title)
            }
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func group(_ title: LocalizedStringKey, _ screens: [Screen]) -> some View {
        Section(title) {
            ForEach(screens) { screen in
                NavigationLink(value: screen) {
                    Label(screen.title, systemImage: screen.symbol)
                }
            }
        }
    }
}
