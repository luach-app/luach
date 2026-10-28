import SwiftUI

/// Every screen outside the tab roots, by name: the account sheet links to them
/// and debug builds open one directly with `-screen <name>` (see AppSession).
enum Screen: String, CaseIterable, Identifiable {
    // Board
    case tasks
    // You
    case profile, emails, mailbox, notify, memory
    // Calendar feed
    case calendarFeed
    // Household (owner)
    case members, household, models
    // Meetings
    case booking, busy
    // Reminders
    case reminders
    // Security
    case passkeys, password, audit, deleteAccount

    var id: String { rawValue }

    var title: LocalizedStringKey {
        switch self {
        case .tasks: "Tasks"
        case .profile: "Profile"
        case .emails: "Your email addresses"
        case .mailbox: "Your Gmail"
        case .notify: "Also notify"
        case .memory: "What luach remembers"
        case .calendarFeed: "Calendar feed"
        case .members: "Members"
        case .household: "Household"
        case .models: "Models"
        case .booking: "Booking page"
        case .busy: "Busy calendars"
        case .reminders: "Reminders"
        case .passkeys: "Passkeys"
        case .password: "Password"
        case .audit: "Audit trail"
        case .deleteAccount: "Delete account"
        }
    }

    var symbol: String {
        switch self {
        case .tasks: "checklist"
        case .profile: "person.text.rectangle"
        case .emails: "at"
        case .mailbox: "envelope.open"
        case .notify: "bell.badge"
        case .memory: "brain"
        case .calendarFeed: "calendar.badge.checkmark"
        case .members: "person.2"
        case .household: "house"
        case .models: "cpu"
        case .booking: "calendar.badge.plus"
        case .busy: "calendar.badge.clock"
        case .reminders: "alarm"
        case .passkeys: "person.badge.key"
        case .password: "key"
        case .audit: "list.bullet.rectangle"
        case .deleteAccount: "person.crop.circle.badge.xmark"
        }
    }

    @ViewBuilder
    var view: some View {
        switch self {
        case .tasks: TasksView()
        case .profile: ProfileView()
        case .emails: EmailsView()
        case .mailbox: MailboxView()
        case .notify: NotifyEmailsView()
        case .memory: MemoryView()
        case .calendarFeed: CalendarFeedView()
        case .members: MembersView()
        case .household: HouseholdView()
        case .models: HouseholdModelsView()
        case .booking: BookingView()
        case .busy: BusyCalendarsView()
        case .reminders: RemindersView()
        case .passkeys: PasskeysView()
        case .password: PasswordView()
        case .audit: AuditView()
        case .deleteAccount: DeleteAccountView()
        }
    }
}

/// The person button at the top of every tab: opens the account sheet.
struct AccountButton: View {
    @State private var open = false

    var body: some View {
        Button("Account and settings", systemImage: "person.crop.circle") { open = true }
            .sheet(isPresented: $open) { AccountSheet() }
    }
}

extension View {
    /// Puts the account button in the leading corner of a tab's navigation bar.
    func accountButton() -> some View {
        toolbar {
            ToolbarItem(placement: .topBarLeading) { AccountButton() }
        }
    }
}
