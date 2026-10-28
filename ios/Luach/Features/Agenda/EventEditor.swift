import SwiftUI

/// Create or edit an event. The Agenda area owns it; the Board opens it too, so
/// its shape is fixed: `.create(day:leader:)` starts on that day (for that family
/// member, a key or a comma list, when given), `.edit(id:calendar:)` loads the event
/// itself. `onSaved` runs after a save or a delete.
enum EventEditorMode: Hashable {
    case create(day: Date, leader: String? = nil)
    case edit(id: String, calendar: String?)
}

/// The event form (web `EventSheet`'s form): title, whose it is, all day or the
/// times, how it repeats, where, which calendar (a new one), who is invited, notes.
///
/// The caller presents it in a `.sheet` wrapped in a `NavigationStack`; its Cancel and
/// Save sit in that stack's bar. Cancel dismisses; after a save or a delete it calls
/// `onSaved`, and the caller closes the sheet there. An event luach may not change
/// (an invitation from someone else, a calendar luach only reads, busy time) opens
/// read-only, saying why, with Done.
struct EventEditor: View {
    let mode: EventEditorMode
    var onSaved: () -> Void
    private let initial: AgendaEvent?
    private let createDay: String?

    init(mode: EventEditorMode, onSaved: @escaping () -> Void = {}) {
        self.init(mode: mode, initial: nil, day: nil, onSaved: onSaved)
    }

    /// From the agenda: the event it already has, or the day as the member's own `YYYY-MM-DD`.
    init(mode: EventEditorMode, initial: AgendaEvent?, day: String?, onSaved: @escaping () -> Void) {
        self.mode = mode
        self.initial = initial
        self.createDay = day
        self.onSaved = onSaved
    }

    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss
    @State private var f = EventForm()
    @State private var original: AgendaEvent?
    @State private var ready = false
    @State private var loadError: String?
    @State private var error: String?
    @State private var busy = false
    /// A new event takes the household's calendar and invitees once they are known.
    @State private var seeded = false
    @State private var draft = ""
    @State private var badEmail = false
    @State private var confirmDelete = false
    /// One occurrence of a repeating event: the body waiting on "this event or all events?".
    @State private var askScope: AgendaEventInput?
    /// The form as it opened (with the household's calendar and invitees once seeded): what
    /// Cancel compares against before it lets edits go.
    @State private var baseline: EventForm?
    @State private var askDiscard = false
    private let data = AgendaData.shared

    /// Anything typed or chosen that a Cancel or a swipe would drop.
    var dirty: Bool {
        guard ready, let baseline else { return false }
        return baseline != f || !draft.trimmingCharacters(in: .whitespaces).isEmpty
    }

    /// One occurrence of a repeating event: a save or a delete asks which.
    private var isOccurrence: Bool { original?.isOccurrence ?? false }

    private var isEdit: Bool {
        if case .edit = mode { return true }
        return false
    }

    var body: some View {
        let clock = AgendaClock.of(session.member)
        Group {
            if let original, original.readOnly {
                AgendaEventDetail(event: original, clock: clock, onEdit: {}, onChanged: onSaved)
            } else {
                Group {
                    if ready {
                        form(clock)
                    } else if let loadError {
                        ContentUnavailableView("Could not open this event", systemImage: "calendar.badge.exclamationmark", description: Text(loadError))
                    } else {
                        ProgressView()
                    }
                }
                .navigationTitle(isEdit ? "Edit event" : "New event")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Cancel") { if dirty { askDiscard = true } else { dismiss() } }
                            .disabled(busy)
                            .accessibilityIdentifier("editor.cancel")
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        if busy {
                            ProgressView()
                        } else {
                            Button(isEdit ? "Save" : "Add") { Task { await submit(clock) } }
                                .disabled(!ready)
                        }
                    }
                }
            }
        }
        .interactiveDismissDisabled(busy)
        .confirmsDiscard(dirty, asking: $askDiscard)
        .task { await load(clock) }
        .onChange(of: data.household == nil) { _, _ in seed() }
    }

    // MARK: The form

    private func form(_ clock: AgendaClock) -> some View {
        let calendars = data.enabledCalendars.filter(\.writable)
        return Form {
            Section {
                TextField("Title", text: $f.title)
                    .font(.body.weight(.medium))
                    .submitLabel(.done)
            }
            if !data.people.isEmpty {
                leaderSection
            }
            Section {
                Toggle("All day", isOn: $f.allDay)
                if f.allDay {
                    DatePicker("From", selection: startDayBinding, displayedComponents: .date)
                    DatePicker("To", selection: $f.endDay, in: f.startDay..., displayedComponents: .date)
                } else {
                    DatePicker("Starts", selection: startBinding)
                    DatePicker("Ends", selection: $f.end, in: f.start...)
                }
                Picker("Repeats", selection: $f.repeats) {
                    ForEach(AgendaRepeat.offered) { Text($0.label).tag($0) }
                    if f.repeats == .custom {
                        Text("\(AgendaRepeat.describe(f.keptRule.split(separator: " ").map(String.init), locale: clock.locale)) (kept)")
                            .tag(AgendaRepeat.custom)
                    }
                }
            } footer: {
                VStack(alignment: .leading, spacing: 4) {
                    if isEdit && f.repeats != .none {
                        Text("Changing this changes every occurrence, past and future.")
                    }
                    Text("Times are in \(clock.tz.identifier).")
                }
            }
            Section {
                TextField("Location", text: $f.location)
                if !isEdit && calendars.count > 1 {
                    Picker("Calendar", selection: $f.calendarId) {
                        ForEach(calendars) { c in Text(c.name).tag(c.id) }
                    }
                }
            }
            inviteSection
            Section("Notes") {
                TextField("Notes", text: $f.description, axis: .vertical)
                    .lineLimit(3...12)
                    .accessibilityIdentifier("editor.notes")
            }
            if let error {
                Section { Text(error).foregroundStyle(.red) }
            }
            if isEdit {
                Section {
                    Button("Delete event", role: .destructive) { confirmDelete = true }
                }
            }
        }
        .environment(\.timeZone, clock.tz)
        .environment(\.calendar, clock.calendar)
        .disabled(busy)
        .confirmationDialog("Delete this event?", isPresented: $confirmDelete, titleVisibility: .visible) {
            if isOccurrence {
                Button("This event", role: .destructive) { Task { await remove(scope: .this) } }
                Button("All events", role: .destructive) { Task { await remove(scope: .series) } }
            } else {
                Button("Delete for real", role: .destructive) { Task { await remove() } }
            }
            Button("Keep it", role: .cancel) {}
        } message: {
            if let original { Text(AgendaWords.deleting(original)) }
        }
        .confirmationDialog(
            "Save this change for this event only, or for every one?",
            isPresented: Binding(get: { askScope != nil }, set: { if !$0 { askScope = nil } }),
            titleVisibility: .visible,
            presenting: askScope
        ) { body in
            Button("This event") { Task { await send(body, scope: .this) } }
            Button("All events") { Task { await send(body, scope: .series) } }
            Button("Cancel", role: .cancel) {}
        }
    }

    /// Everyone, or any of the family: tap several for "Noa and Sam".
    private var leaderSection: some View {
        let people = data.people
        let chosen = people.filter { f.leaders.contains($0.key) }
        let invited = chosen.filter { !$0.email.isEmpty }
        return Section {
            leaderRow(name: String(localized: "Everyone"), hex: "", on: f.leaders.isEmpty) { f.leaders = [] }
            ForEach(people) { p in
                leaderRow(name: p.name, hex: p.hex, on: f.leaders.contains(p.key)) {
                    f.toggleLeader(p.key, family: people.map(\.key))
                }
            }
        } header: {
            Text("For")
        } footer: {
            if let first = chosen.first {
                Text(String(localized: "On \(AgendaWords.names(chosen.map(\.name)))’s board, in \(first.name)’s colour.")
                     + (invited.isEmpty ? "" : " " + (invited.count > 1
                        ? String(localized: "\(AgendaWords.names(invited.map(\.name))) are invited.")
                        : String(localized: "\(AgendaWords.names(invited.map(\.name))) is invited."))))
            }
        }
    }

    private func leaderRow(name: String, hex: String, on: Bool, toggle: @escaping () -> Void) -> some View {
        Button(action: toggle) {
            HStack {
                if let color = AgendaPalette.color(hex) {
                    Circle().fill(color).frame(width: 12, height: 12)
                } else {
                    Image(systemName: "person.3").font(.caption).foregroundStyle(.secondary).frame(width: 12)
                }
                Text(name).foregroundStyle(.primary)
                Spacer()
                if on { Image(systemName: "checkmark").foregroundStyle(Color.accentColor).fontWeight(.semibold) }
            }
        }
        .foregroundStyle(.primary)
        .accessibilityAddTraits(on ? .isSelected : [])
    }

    private var inviteSection: some View {
        Section {
            ForEach(f.attendees, id: \.self) { email in
                Text(email)
            }
            .onDelete { f.attendees.remove(atOffsets: $0) }
            HStack {
                TextField("name@example.com", text: $draft)
                    .keyboardType(.emailAddress)
                    .textContentType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.done)
                    .accessibilityIdentifier("editor.invite")
                    .onSubmit { _ = commitDraft() }
                    .onChange(of: draft) { _, text in
                        badEmail = false
                        // Comma, semicolon or space ends an address, as on the web.
                        if let last = text.last, [",", ";", " "].contains(last) { _ = commitDraft() }
                    }
                if !draft.isEmpty {
                    Button("Add", systemImage: "plus.circle.fill") { _ = commitDraft() }
                        .labelStyle(.iconOnly)
                        .accessibilityIdentifier("editor.invite.add")
                        .buttonStyle(.borderless)
                }
            }
        } header: {
            Text("Invite")
        } footer: {
            if badEmail {
                Text("That is not an email address.").foregroundStyle(.red)
            } else if isEdit {
                Text("Everyone here gets a Google Calendar invitation.")
            } else {
                Text("Prefilled with the household’s usual people and your “also notify” addresses; remove anyone who should not get this one.")
            }
        }
    }

    /// The address being typed becomes a row; false when it is not an address.
    private func commitDraft() -> Bool {
        guard let email = EventForm.address(draft) else {
            badEmail = true
            return false
        }
        if !email.isEmpty { f.invite(email) }
        draft = ""
        badEmail = false
        return true
    }

    /// Moving the start keeps the length: the end moves with it.
    private var startBinding: Binding<Date> {
        Binding(get: { f.start }, set: { f.moveStart(to: $0) })
    }

    private var startDayBinding: Binding<Date> {
        Binding(get: { f.startDay }, set: { f.moveStartDay(to: $0) })
    }

    // MARK: Loading

    private func load(_ clock: AgendaClock) async {
        if ready { return }
        data.bind(session.member, server: session.server)
        switch mode {
        case .create(let date, let leader):
            let day = createDay ?? Self.dayOnPhone(date)
            f = EventForm.new(on: day, clock: clock)
            f.leaders = EventForm.leaders(from: leader)
            baseline = f
            ready = true
            await data.loadBasics(session.api)
            seed()
        case .edit(let id, let calendar):
            async let basics: Void = data.loadBasics(session.api)
            do {
                let ev: AgendaEvent
                if let initial { ev = initial } else { ev = try await session.api.agendaEvent(id, calendar: calendar) }
                original = ev
                f = EventForm(ev, clock: clock)
                baseline = f
                ready = true
            } catch {
                loadError = error.localizedDescription
            }
            await basics
        }
        #if DEBUG
        await debugAuto(clock)
        #endif
    }

    #if DEBUG
    /// Simulator checks of the write path: `-editorTitle <t>`, `-editorLeader <keys>`,
    /// `-editorRepeat weekly`, `-editorAllDay 1`, then `-editorAutoSave 1` or `-editorAutoDelete 1`
    /// (on an occurrence, with `-editorScope this|series`, or the question is asked).
    private func debugAuto(_ clock: AgendaClock) async {
        let d = UserDefaults.standard
        guard ready else { return }
        if let t = d.string(forKey: "editorTitle") { f.title = t }
        if let l = d.string(forKey: "editorLeader") { f.leaders = l.split(separator: ",").map(String.init) }
        if let r = d.string(forKey: "editorRepeat").flatMap(AgendaRepeat.init(rawValue:)) { f.repeats = r }
        if d.bool(forKey: "editorAllDay") { f.allDay = true }
        // `-editorScope this|series` answers "this event or all events?" for an occurrence.
        let scope = d.string(forKey: "editorScope").flatMap(AgendaScope.init(rawValue:))
        if d.bool(forKey: "editorAutoSave") { await submit(clock, scope: scope) }
        if d.bool(forKey: "editorAutoDelete") { await remove(scope: scope) }
    }
    #endif

    /// A day handed in as a `Date` (the Board's), read on the phone's own calendar.
    static func dayOnPhone(_ date: Date) -> String {
        let c = Calendar.current.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year ?? 1970, c.month ?? 1, c.day ?? 1)
    }

    /// A new event starts on the default calendar with the household's usual invitees and the member's own.
    private func seed() {
        guard !isEdit, !seeded, let household = data.household else { return }
        let writable = data.enabledCalendars.filter(\.writable)
        f.seed(household, writable: writable, notify: data.notifyEmails)
        // Seeding is not an edit: the form as it opened has the same calendar and invitees.
        baseline?.seed(household, writable: writable, notify: data.notifyEmails)
        seeded = true
    }

    // MARK: Saving

    /// `scope`: the answer to "this event or all events?", when it is already known.
    private func submit(_ clock: AgendaClock, scope: AgendaScope? = nil) async {
        guard commitDraft() else {
            error = String(localized: "That is not an email address.")
            return
        }
        let body: AgendaEventInput
        switch f.input(clock: clock, isEdit: isEdit, seeded: seeded, original: original) {
        case .success(let made): body = made
        case .failure(let problem):
            error = problem.message
            return
        }
        guard isOccurrence else { return await send(body, scope: nil) }
        // How it repeats is the series': a new repeat chosen on one occurrence is every one's.
        if f.repeatsChanged { return await send(body, scope: .series) }
        if let scope { return await send(body, scope: scope) }
        askScope = body
    }

    private func send(_ body: AgendaEventInput, scope: AgendaScope?) async {
        busy = true
        defer { busy = false }
        do {
            switch mode {
            case .edit(let id, let calendar):
                _ = try await session.api.agendaUpdate(id, calendar: original?.calendarId ?? calendar, body, scope: scope)
            case .create:
                _ = try await session.api.agendaCreate(body)
            }
            error = nil
            await session.pending.refresh()
            data.invalidate()
            onSaved()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func remove(scope: AgendaScope? = nil) async {
        guard case .edit(let id, let calendar) = mode else { return }
        if isOccurrence && scope == nil {
            confirmDelete = true
            return
        }
        busy = true
        defer { busy = false }
        do {
            try await session.api.agendaDelete(id, calendar: original?.calendarId ?? calendar, scope: scope)
            await session.pending.refresh()
            data.invalidate()
            onSaved()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// What the form holds while it is being filled in.
struct EventForm: Equatable {
    var title = ""
    var allDay = false
    var start = Date.now
    var end = Date.now.addingTimeInterval(3600)
    /// All-day: the first and the last day (inclusive), each midnight in the member's zone.
    var startDay = Date.now
    var endDay = Date.now
    var location = ""
    var description = ""
    var calendarId = ""
    var attendees: [String] = []
    var repeats = AgendaRepeat.none
    /// How it repeated when the form opened: the rule is sent only when `repeats` changes.
    var repeatsAtFirst = AgendaRepeat.none
    var keptRule = ""
    var leaders: [String] = []

    /// A new event on `day`, at the top of the next hour, for an hour.
    static func new(on day: String, clock: AgendaClock) -> EventForm {
        var f = EventForm()
        f.start = clock.nextHour(on: day)
        f.end = f.start.addingTimeInterval(3600)
        f.startDay = clock.date(ofDay: day)
        f.endDay = f.startDay
        return f
    }

    init() {}

    init(_ ev: AgendaEvent, clock: AgendaClock) {
        title = ev.title
        allDay = ev.isAllDay
        if allDay {
            let first = String(ev.start.prefix(10))
            start = clock.nextHour(on: first)
            end = start.addingTimeInterval(3600)
            startDay = clock.date(ofDay: first)
            endDay = AgendaClock.isDay(ev.end) ? clock.date(ofDay: AgendaClock.addDays(ev.end, -1)) : startDay
            if endDay < startDay { endDay = startDay }
        } else {
            start = clock.instant(ev.start) ?? clock.nextHour()
            end = clock.instant(ev.end) ?? start.addingTimeInterval(3600)
            startDay = clock.date(ofDay: clock.day(of: start))
            endDay = startDay
        }
        location = ev.location
        description = AgendaNotes.asText(ev.description)
        calendarId = ev.calendarId
        attendees = ev.attendees
        repeats = AgendaRepeat.of(ev.recurrence)
        repeatsAtFirst = repeats
        keptRule = ev.recurrence.joined(separator: " ")
        leaders = ev.leaderKeys
    }

    // MARK: Changes

    /// The person chose another repeat (never a kept rule, which is not sent).
    var repeatsChanged: Bool { repeats != repeatsAtFirst && repeats != .custom }

    /// Moving the start keeps the length: the end moves with it.
    mutating func moveStart(to new: Date) {
        let length = end > start ? end.timeIntervalSince(start) : 3600
        start = new
        end = new.addingTimeInterval(length)
    }

    /// An all-day start past the last day takes the last day with it.
    mutating func moveStartDay(to new: Date) {
        startDay = new
        if endDay < new { endDay = new }
    }

    /// Tap someone in or out; kept in the family's order, so the first is the colour it wears.
    mutating func toggleLeader(_ key: String, family: [String]) {
        let next = leaders.contains(key) ? leaders.filter { $0 != key } : leaders + [key]
        leaders = family.filter(next.contains)
    }

    mutating func invite(_ email: String) {
        if !attendees.contains(email) { attendees.append(email) }
    }

    /// A new event starts on the default calendar with the household's usual invitees and the member's own.
    mutating func seed(_ household: AgendaHousehold, writable: [AgendaCalendarInfo], notify: [String]) {
        calendarId = household.defaultCalendar.isEmpty ? writable.first?.id ?? "" : household.defaultCalendar
        var list: [String] = []
        for email in household.defaultAttendees + notify where !list.contains(email) { list.append(email) }
        attendees = list
    }

    /// The Board's leader, a key or a comma list, as keys.
    static func leaders(from leader: String?) -> [String] {
        (leader ?? "").split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }

    /// The address being typed, cleaned: "" when nothing is typed, nil when it is not an address.
    static func address(_ draft: String) -> String? {
        let email = draft.trimmingCharacters(in: .whitespaces).lowercased()
            .trimmingCharacters(in: CharacterSet(charactersIn: ",; "))
        if email.isEmpty { return "" }
        return email.wholeMatch(of: AgendaWords.emailPattern) != nil ? email : nil
    }

    /// Why the form cannot be saved yet.
    enum Problem: Error, Equatable {
        case noTitle, endBeforeStart

        var message: String {
            switch self {
            case .noTitle: String(localized: "Give it a title.")
            case .endBeforeStart: String(localized: "The end is before the start.")
            }
        }
    }

    /// The body of the POST or PATCH. `seeded`: the household's invitees were put in, so the
    /// list is the member's; otherwise a new event leaves its invitees to the server's default.
    func input(clock: AgendaClock, isEdit: Bool, seeded: Bool, original: AgendaEvent?) -> Result<AgendaEventInput, Problem> {
        let named = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !named.isEmpty else { return .failure(.noTitle) }
        let firstDay = clock.day(of: startDay)
        let lastDay = max(clock.day(of: endDay), firstDay)
        var body = AgendaEventInput(
            title: named,
            start: allDay ? firstDay : clock.input(start),
            end: allDay ? AgendaClock.addDays(lastDay, 1) : clock.input(end),
            location: location.trimmingCharacters(in: .whitespacesAndNewlines),
            description: description.trimmingCharacters(in: .whitespacesAndNewlines),
            attendees: isEdit || seeded ? attendees : nil
        )
        if !allDay, let until = body.end, until < body.start { return .failure(.endBeforeStart) }
        // Only when the person changed it: an occurrence opened as "Does not repeat" sent that
        // back and stopped its series. The menu's word: the server puts it on the event's own
        // day. A repeat luach's menu cannot say is never sent, so it stays as it was.
        if repeatsChanged { body.recurrence = repeats.word }
        if !isEdit && !calendarId.isEmpty { body.calendarId = calendarId }
        // Sent only when it says something: a new event someone leads, or a change of hands.
        let had = original?.leaderKeys.joined(separator: ",") ?? ""
        let now = leaders.joined(separator: ",")
        if now != had { body.leader = now }
        return .success(body)
    }
}
