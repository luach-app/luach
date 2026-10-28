import SwiftUI
import UIKit

/// Settings › Meetings › Booking page: the hours, the caps and the link to share.
struct BookingView: View {
    @Environment(AppSession.self) private var session
    @State private var saved: HouseholdArea.Booking?
    @State private var form: HouseholdArea.BookingSettings?
    @State private var rows: [HouseholdArea.BookingRow] = []
    @State private var household: HouseholdArea.Calendars?
    @State private var loadError: String?
    @State private var busy = false
    @State private var error: String?
    @State private var ok = false
    @State private var copied = false
    @State private var cancelling: HouseholdArea.BookingRow?

    var body: some View {
        ScrollViewReader { proxy in
            form(proxy)
        }
    }

    private func form(_ proxy: ScrollViewProxy) -> some View {
        Form {
            if let loadError {
                Section { Text(loadError).foregroundStyle(.red) }
            }
            if let saved, form != nil {
                linkSection(saved)
                publishSection
                lengthSection
                hoursSection.id("hours")
                whereSection(saved).id("where")
                pageSection.id("page")
                if !rows.isEmpty { bookedSection.id("booked") }
                if let error {
                    Section { Text(error).foregroundStyle(.red) }
                } else if ok && !dirty {
                    Section { Label("Saved.", systemImage: "checkmark.circle").foregroundStyle(.green) }
                }
            }
        }
        .overlay { if saved == nil && loadError == nil { ProgressView() } }
        .confirmsDiscard(dirty)
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
            await load()
            #if DEBUG
            // `-householdScroll hours|where|page` shows a lower part in the simulator.
            if let id = UserDefaults.standard.string(forKey: "householdScroll") {
                try? await Task.sleep(for: .milliseconds(300))
                proxy.scrollTo(id, anchor: .top)
            }
            #endif
        }
        .refreshable { await load() }
        .confirmationDialog(
            "Cancel this meeting?",
            isPresented: Binding(get: { cancelling != nil }, set: { if !$0 { cancelling = nil } }),
            titleVisibility: .visible,
            presenting: cancelling
        ) { row in
            Button("Cancel it", role: .destructive) { Task { await drop(row) } }
            Button("Keep", role: .cancel) {}
        } message: { row in
            Text("\(row.name) is told by email, the Zoom link is taken down, and the slot is free again.")
        }
    }

    /// A binding into the form; only used while the form is loaded.
    private func field<T>(_ key: WritableKeyPath<HouseholdArea.BookingSettings, T>) -> Binding<T> {
        Binding(
            get: { form![keyPath: key] },
            set: { form![keyPath: key] = $0; ok = false }
        )
    }

    private var dirty: Bool {
        guard let form, let saved else { return false }
        return form != saved.settings
    }

    // MARK: The link

    private func linkSection(_ saved: HouseholdArea.Booking) -> some View {
        Section {
            HStack {
                Text("Your link").font(.subheadline.weight(.medium))
                Spacer()
                HouseholdArea.Tag(
                    text: saved.settings.enabled ? "live" : "not live yet",
                    tint: saved.settings.enabled ? .green : .secondary
                )
            }
            Text(verbatim: saved.link)
                .font(.callout.monospaced())
                .foregroundStyle(.tint)
                .textSelection(.enabled)
                .lineLimit(2)
            if let url = URL(string: saved.link) {
                ShareLink(item: url) { Label("Share the link", systemImage: "square.and.arrow.up") }
                Button {
                    UIPasteboard.general.url = url
                    copied = true
                    Task {
                        try? await Task.sleep(for: .seconds(2))
                        copied = false
                    }
                } label: {
                    Label(copied ? "Copied" : "Copy link", systemImage: copied ? "checkmark" : "doc.on.doc")
                }
                Link(destination: url) { Label("Open it", systemImage: "safari") }
            }
        } footer: {
            Text("Share one link. People see only the times you are free, and can take at most \(form?.maxPerDay ?? saved.settings.maxPerDay) a day. Times are in \(saved.timezone).")
        }
    }

    private var publishSection: some View {
        Section {
            Toggle("The link is live", isOn: field(\.enabled))
            LabeledContent("Link name") {
                TextField("Link name", text: field(\.slug))
                    .accessibilityIdentifier("booking.slug")
                    .multilineTextAlignment(.trailing)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            }
        } footer: {
            Text("The link name is the last part of the address above: 2–40 letters, digits and dashes.")
        }
    }

    // MARK: Length and limits

    private var lengthSection: some View {
        Section("Meetings") {
            choice("Meeting length", field(\.slotMinutes), [15, 20, 30, 45, 60, 90]) {
                String(localized: "\($0) minutes")
            }
            choice("Most per day", field(\.maxPerDay), [1, 2, 3, 4, 5]) { "\($0)" }
            choice("Gap around meetings", field(\.bufferMinutes), [0, 10, 15, 30, 60]) {
                $0 == 0 ? String(localized: "none") : String(localized: "\($0) minutes")
            }
            choice("Notice needed", field(\.leadHours), [0, 2, 12, 24, 48, 72]) {
                $0 == 0 ? String(localized: "none") : String(localized: "\($0) hours")
            }
            choice("How far ahead", field(\.horizonDays), [7, 14, 21, 30, 60, 90, 120]) {
                String(localized: "\($0) days")
            }
        }
    }

    /// A picker over the web's choices, keeping a saved value that is not one of them.
    private func choice(
        _ title: LocalizedStringKey, _ value: Binding<Int>, _ options: [Int], label: @escaping (Int) -> String
    ) -> some View {
        let all = HouseholdArea.choices(options, keeping: value.wrappedValue)
        return Picker(title, selection: value) {
            ForEach(all, id: \.self) { Text(verbatim: label($0)).tag($0) }
        }
    }

    // MARK: Weekly hours

    private var hoursSection: some View {
        Section {
            ForEach(HouseholdArea.weekdays, id: \.key) { day in
                let windows = form?.hours[day.key] ?? []
                Toggle(isOn: Binding(
                    get: { !windows.isEmpty },
                    set: { on in setDay(day.key, HouseholdArea.Hours.toggled(windows, on: on)) }
                )) {
                    Text(day.label)
                }
                ForEach(windows.indices, id: \.self) { i in
                    windowRow(day: day.key, index: i, windows: windows)
                }
            }
        } header: {
            Text("Hours you are bookable")
        } footer: {
            Text("Swipe a window to remove it, or add a second one for a split day.")
        }
    }

    private func windowRow(day: String, index i: Int, windows: [[String]]) -> some View {
        HStack {
            DatePicker("From", selection: time(day, i, 0), displayedComponents: .hourAndMinute)
                .labelsHidden()
                .accessibilityIdentifier("booking.from.\(day).\(i)")
            Text(verbatim: "–").foregroundStyle(.secondary)
            DatePicker("To", selection: time(day, i, 1), displayedComponents: .hourAndMinute)
                .labelsHidden()
                .accessibilityIdentifier("booking.to.\(day).\(i)")
            Spacer(minLength: 0)
            if i == windows.count - 1 {
                // The next window starts where this one ends, two hours long; none once
                // the day is used up to midnight.
                let next = HouseholdArea.Hours.adding(to: windows)
                Button {
                    if let next { setDay(day, next) }
                } label: {
                    Image(systemName: "plus.circle")
                }
                .buttonStyle(.borderless)
                .disabled(next == nil)
                .accessibilityLabel("Add a window")
                .accessibilityIdentifier("booking.add.\(day)")
            }
        }
        .padding(.leading, 8)
        .swipeActions {
            Button("Remove", role: .destructive) {
                setDay(day, HouseholdArea.Hours.removing(windows, at: i))
            }
        }
    }

    private func setDay(_ day: String, _ windows: [[String]]) {
        form?.hours[day] = windows
        ok = false
    }

    private func time(_ day: String, _ i: Int, _ end: Int) -> Binding<Date> {
        Binding(
            get: { HouseholdArea.Hours.date(HouseholdArea.Hours.time(form?.hours[day], i, end)) },
            set: { date in
                if let windows = HouseholdArea.Hours.setting(form?.hours[day], i, end, to: date) {
                    setDay(day, windows)
                }
            }
        )
    }

    // MARK: Where

    private func whereSection(_ saved: HouseholdArea.Booking) -> some View {
        let calendars = HouseholdArea.bookingCalendars(household)
        let zoomReady = saved.zoomReady != false
        return Section {
            if calendars.count > 1 {
                Picker("Meetings land on", selection: field(\.calendarId)) {
                    Text(HouseholdArea.defaultCalendarLabel(household, calendars)).tag("")
                    ForEach(calendars) { Text($0.name).tag($0.id) }
                    if let id = form?.calendarId, !id.isEmpty, !calendars.contains(where: { $0.id == id }) {
                        Text(verbatim: id).tag(id)
                    }
                }
            }
            Picker("Where you meet", selection: field(\.conferencing)) {
                Text("Wherever I wrote below").tag("none")
                if zoomReady || form?.conferencing == "zoom" {
                    Text("A fresh Zoom link per meeting").tag("zoom")
                }
            }
            Toggle("Email me when someone books", isOn: field(\.notifyHost))
        } header: {
            Text("Where")
        } footer: {
            VStack(alignment: .leading, spacing: 4) {
                if calendars.count > 1 { Text("Keep work meetings off the family calendar.") }
                Text(zoomReady
                     ? "A Zoom link is created on your account for each booking."
                     : "Zoom needs credentials on the server before it can be picked.")
            }
        }
    }

    // MARK: The page

    private var pageSection: some View {
        Section {
            VStack(alignment: .leading, spacing: 4) {
                Text(form?.conferencing == "zoom" ? "Where, if Zoom cannot be reached" : "Where (optional)")
                    .font(.footnote).foregroundStyle(.secondary)
                TextField("my office, a phone call, …", text: field(\.location))
                    .accessibilityIdentifier("booking.location")
            }
            VStack(alignment: .leading, spacing: 4) {
                Text("A line for the page (optional)").font(.footnote).foregroundStyle(.secondary)
                TextField("Looking forward to it.", text: field(\.note), axis: .vertical)
                    .lineLimit(1...4)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text("The event’s title").font(.footnote).foregroundStyle(.secondary)
                TextField("Meeting with {name}", text: field(\.title))
                    .autocorrectionDisabled()
                    .accessibilityIdentifier("booking.title")
            }
        } header: {
            Text("The page")
        } footer: {
            Text("In the title, {name} becomes the name of the person who booked.")
        }
    }

    // MARK: Booked so far

    private var bookedSection: some View {
        Section {
            ForEach(rows) { row in
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(row.name)
                        Spacer()
                        Text(when(row)).font(.subheadline).foregroundStyle(.secondary)
                    }
                    Text(verbatim: row.email).font(.footnote).foregroundStyle(.secondary).lineLimit(1)
                    if let note = row.note, !note.isEmpty {
                        Text(note).font(.footnote).foregroundStyle(.secondary).lineLimit(2)
                    }
                }
                .swipeActions {
                    Button("Cancel", role: .destructive) { cancelling = row }
                }
            }
        } header: {
            Text("Booked so far")
        } footer: {
            Text("Swipe to cancel one. Cancelling tells them by email, takes the Zoom link down, and frees the slot.")
        }
    }

    private func when(_ row: HouseholdArea.BookingRow) -> String {
        HouseholdArea.when(row, in: session.member?.timezone.flatMap(TimeZone.init(identifier:)))
    }

    // MARK: Loading and saving

    private var client: HouseholdArea.Client { HouseholdArea.Client(api: session.api) }

    private func load() async {
        do {
            let b = try await client.booking()
            saved = b
            form = b.settings
            loadError = nil
        } catch is CancellationError {
            return
        } catch {
            loadError = error.localizedDescription
            return
        }
        rows = (try? await client.upcoming()) ?? []
        household = try? await client.calendars()
    }

    private func save() async {
        guard let form else { return }
        busy = true
        error = nil
        defer { busy = false }
        do {
            let next = try await client.saveBooking(form)
            saved = next
            self.form = next.settings
            ok = true
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// The host calling one off: removing the event tells the guest, server-side.
    private func drop(_ row: HouseholdArea.BookingRow) async {
        busy = true
        defer { busy = false }
        do {
            try await client.cancel(row)
            rows.removeAll { $0.eventId == row.eventId }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}
