import SwiftUI

/// Settings › Household (owner only): which calendars luach uses, where new
/// things go, who is always invited — and the family and the screens on the wall.
struct HouseholdView: View {
    @Environment(AppSession.self) private var session
    @State private var data: HouseholdArea.Calendars?
    @State private var loadError: String?
    @State private var form = HouseholdArea.HouseholdForm()
    @State private var busy = false
    @State private var error: String?
    @State private var saved = false
    @State private var debugPush: String?

    var body: some View {
        Form {
            if let loadError, data == nil {
                Section {
                    Text(loadError).foregroundStyle(.red)
                    Button("Try again") { Task { await load() } }
                }
            }
            if let data {
                calendarsSection(data)
                defaultSection(data)
                attendeesSection
                if let error {
                    Section { Text(error).foregroundStyle(.red) }
                } else if saved && !dirty {
                    Section { Label("Saved.", systemImage: "checkmark.circle").foregroundStyle(.green) }
                }
            }
            Section {
                NavigationLink {
                    YouFamilyView().navigationTitle("Family")
                } label: {
                    Label("Family", systemImage: "figure.2.and.child.holdinghands")
                }
                NavigationLink {
                    YouHouseBoardsView().navigationTitle("House boards")
                } label: {
                    Label("House boards", systemImage: "rectangle.on.rectangle")
                }
            } footer: {
                Text("Who events and tasks are for, and the screens on the wall that show everyone's day.")
            }
        }
        .overlay { if data == nil && loadError == nil { ProgressView() } }
        .confirmsDiscard(dirty)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if busy {
                    ProgressView()
                } else {
                    Button("Save") { Task { await save() } }
                        .disabled(!dirty || data == nil)
                }
            }
        }
        .task {
            #if DEBUG
            // `-householdPush family|boards` opens a sub-screen in the simulator.
            debugPush = UserDefaults.standard.string(forKey: "householdPush")
            #endif
            await load()
        }
        .navigationDestination(isPresented: Binding(get: { debugPush != nil }, set: { if !$0 { debugPush = nil } })) {
            if debugPush == "boards" {
                YouHouseBoardsView().navigationTitle("House boards")
            } else {
                YouFamilyView().navigationTitle("Family")
            }
        }
        .refreshable { await load() }
    }

    // MARK: Sections

    private func calendarsSection(_ data: HouseholdArea.Calendars) -> some View {
        Section {
            ForEach(listed(data)) { cal in
                let on = form.enabled.contains(cal.id)
                Button {
                    toggle(cal.id)
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: on ? "checkmark.circle.fill" : "circle")
                            .font(.title3)
                            .foregroundStyle(on ? Color.accentColor : Color.secondary)
                        Circle()
                            .fill(Color(householdHex: cal.color) ?? .accentColor)
                            .frame(width: 12, height: 12)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(cal.name).foregroundStyle(.primary)
                            if !cal.writable {
                                Text("read only").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        Spacer(minLength: 0)
                        if cal.id == form.defaultCalendar && on {
                            Text("default").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                .tint(.primary)
                .accessibilityLabel(Text("Use \(cal.name)"))
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        } header: {
            Text("Calendars")
        } footer: {
            Text("The calendars luach reads. Tick the ones luach should see.")
        }
    }

    private func defaultSection(_ data: HouseholdArea.Calendars) -> some View {
        let choices = HouseholdArea.defaultChoices(data, enabled: form.enabled)
        let current = form.defaultCalendar
        return Section {
            Picker("New events go to", selection: $form.defaultCalendar) {
                if !choices.contains(where: { $0.id == current }) {
                    Text(current.isEmpty ? String(localized: "None") : HouseholdArea.name(of: current, in: data))
                        .tag(current)
                }
                ForEach(choices) { cal in
                    Text(cal.name).tag(cal.id)
                }
            }
            .onChange(of: form.defaultCalendar) { saved = false }
        }
    }

    private var attendeesSection: some View {
        Section {
            ForEach(form.attendees, id: \.self) { email in
                Text(email)
            }
            .onDelete { offsets in
                form.attendees.remove(atOffsets: offsets)
                saved = false
            }
            HStack {
                TextField("name@example.com", text: $form.draft)
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .onSubmit { commitDraft() }
                    .accessibilityIdentifier("household.invite")
                    .onChange(of: form.draft) { form.draftBad = false }
                Button("Add") { commitDraft() }
                    .disabled(form.draft.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            if form.draftBad {
                Text("That is not an email address.").font(.footnote).foregroundStyle(.red)
            }
        } header: {
            Text("Always invite")
        } footer: {
            Text("Every new event sends these people a Google Calendar invitation unless someone says otherwise. Swipe an address to remove it.")
        }
    }

    // MARK: State

    private func listed(_ data: HouseholdArea.Calendars) -> [HouseholdArea.CalendarInfo] {
        HouseholdArea.listed(data)
    }

    private var dirty: Bool {
        guard let data else { return false }
        return form.isDirty(against: data)
    }

    private func toggle(_ id: String) {
        saved = false
        form.toggle(id)
    }

    private func commitDraft() {
        if form.commitDraft() { saved = false }
    }

    private func load() async {
        do {
            let d = try await HouseholdArea.Client(api: session.api).calendars()
            data = d
            // A refresh keeps an address being typed.
            let draft = form.draft
            form = HouseholdArea.HouseholdForm(d)
            form.draft = draft
            loadError = nil
        } catch is CancellationError {
        } catch {
            loadError = error.localizedDescription
        }
    }

    private func save() async {
        saved = false
        error = nil
        guard let patch = form.patch else {
            error = String(localized: "Keep at least one calendar.")
            return
        }
        busy = true
        defer { busy = false }
        do {
            try await HouseholdArea.Client(api: session.api).saveHousehold(patch)
            form.draft = ""
            await load()
            saved = true
        } catch {
            self.error = error.localizedDescription
        }
    }
}
