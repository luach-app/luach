import SwiftUI

/// Settings › Reminders: a nudge before a thing, the evening-before list and the week ahead.
/// On this iPhone they are notifications the app schedules itself (LocalReminders); turning one
/// on is when iOS is asked to allow them.
struct RemindersView: View {
    @Environment(AppSession.self) private var session
    @Environment(\.openURL) private var openURL
    @State private var saved: HouseholdArea.ReminderSettings?
    @State private var form: HouseholdArea.ReminderSettings?
    @State private var loadError: String?
    @State private var busy = false
    @State private var error: String?
    @State private var done = false

    private static let leads: [(Int, LocalizedStringKey)] = [
        (0, "Never"), (15, "15 minutes before"), (30, "30 minutes before"),
        (60, "An hour before"), (120, "Two hours before"), (1440, "A day before"),
    ]
    private static let days: [(Int, LocalizedStringKey)] = [
        (-1, "Never"), (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
        (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
    ]

    var body: some View {
        Form {
            if let loadError {
                Section { Text(loadError).foregroundStyle(.red) }
            }
            if form != nil {
                Section {
                    Picker("Before something starts", selection: field(\.leadMinutes)) {
                        ForEach(Self.leads, id: \.0) { Text($0.1).tag($0.0) }
                        extra(form?.leadMinutes, in: Self.leads.map(\.0)) { String(localized: "\($0) minutes before") }
                    }
                    Picker("The evening before, a list of tomorrow", selection: field(\.eveningHour)) {
                        Text("Never").tag(-1)
                        ForEach(17...22, id: \.self) { Text(verbatim: "\($0):00").tag($0) }
                        extra(form?.eveningHour, in: [-1] + Array(17...22)) { "\($0):00" }
                    }
                } footer: {
                    Text("Times are in \(timezone). Only you get yours.")
                }

                Section {
                    Picker("The week ahead, on", selection: field(\.weeklyDay)) {
                        ForEach(Self.days, id: \.0) { Text($0.1).tag($0.0) }
                    }
                    Picker("at", selection: field(\.weeklyHour)) {
                        ForEach(0..<24, id: \.self) { Text(verbatim: String(format: "%02d:00", $0)).tag($0) }
                    }
                    .disabled((form?.weeklyDay ?? -1) < 0)
                } footer: {
                    Text("The week ahead is emailed too, when this luach sends mail: a list is easier to read in an inbox.")
                }

                Section {
                    Toggle("Email them to me as well", isOn: field(\.byEmail))
                }

                onThisPhone

                if let error {
                    Section { Text(error).foregroundStyle(.red) }
                } else if done && !dirty {
                    Section { Label("Saved.", systemImage: "checkmark.circle").foregroundStyle(.green) }
                }
            }
        }
        .overlay { if form == nil && loadError == nil { ProgressView() } }
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if busy {
                    ProgressView()
                } else {
                    Button("Save") { Task { await save() } }.disabled(!dirty)
                }
            }
        }
        .task {
            await session.reminders.readPermission()
            await load()
        }
        .refreshable { await load() }
        .confirmsDiscard(dirty)
    }

    /// What this iPhone does with them: notifications the app schedules from the calendar as it
    /// last saw it, and browsers where notifications are on get them from luach as well.
    @ViewBuilder private var onThisPhone: some View {
        let reminders = session.reminders
        Section {
            switch reminders.permission {
            case .denied:
                Label("Notifications are off for luach on this iPhone.", systemImage: "bell.slash")
                Button("Open iOS Settings") {
                    if let url = URL(string: UIApplication.openNotificationSettingsURLString) { openURL(url) }
                }
            case .notDetermined:
                Label("Not shown on this iPhone yet.", systemImage: "bell")
                if let saved, ReminderPlan.anyOn(saved) {
                    Button("Allow notifications") { Task { await allow() } }
                        .accessibilityIdentifier("reminders.allow")
                }
            default:
                if reminders.scheduled > 0 {
                    Label("\(reminders.scheduled) coming up on this iPhone", systemImage: "bell.badge")
                } else {
                    Label("Notifications are on for luach on this iPhone.", systemImage: "bell")
                }
                if let problem = reminders.problem {
                    Text(problem).foregroundStyle(.red)
                }
            }
        } header: {
            Text("On this iPhone")
        } footer: {
            Text("This iPhone shows them as notifications, worked out from the calendar each time luach opens or refreshes in the background, so a change made elsewhere arrives when it next does. Browsers where you turned notifications on get them from luach too.")
        }
        .accessibilityIdentifier("reminders.phone")
    }

    /// Asks iOS, once, and schedules them when allowed.
    private func allow() async {
        if await session.reminders.requestPermission() {
            await session.refreshReminders()
        }
    }

    private var timezone: String { session.member?.timezone ?? "UTC" }

    private var dirty: Bool { form != nil && form != saved }

    /// A saved value the menu does not offer (set by asking luach), kept rather than lost.
    @ViewBuilder
    private func extra(_ value: Int?, in known: [Int], label: (Int) -> String) -> some View {
        if let value = HouseholdArea.offMenu(value, known: known) {
            Text(verbatim: label(value)).tag(value)
        }
    }

    private func field<T>(_ key: WritableKeyPath<HouseholdArea.ReminderSettings, T>) -> Binding<T> {
        Binding(
            get: { form![keyPath: key] },
            set: { form![keyPath: key] = $0; done = false }
        )
    }

    private func load() async {
        do {
            let r = try await HouseholdArea.Client(api: session.api).reminders()
            saved = r
            form = r
            loadError = nil
        } catch is CancellationError {
        } catch {
            loadError = error.localizedDescription
        }
    }

    private func save() async {
        guard let form else { return }
        busy = true
        error = nil
        defer { busy = false }
        do {
            let next = try await HouseholdArea.Client(api: session.api).saveReminders(form)
            saved = next
            self.form = next
            done = true
            // Turning a reminder on is the moment to ask iOS; then the phone's own follow.
            if ReminderPlan.anyOn(next) { await session.reminders.requestPermission() }
            await session.refreshReminders()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
