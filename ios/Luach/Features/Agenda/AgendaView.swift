import SwiftUI

/// The household's calendar, as a month or as the next two weeks (web `pages/Agenda.tsx`).
/// The choice is remembered. An event opens to read; it is edited and deleted from
/// there or by swiping its row; + adds one on the selected day.
struct AgendaView: View {
    @Environment(AppSession.self) private var session
    // Upcoming first: the day and the week ahead open warmer than a month of empty squares.
    @AppStorage("luach.agenda.mode") private var mode = "upcoming"
    @State private var selected = ""
    @State private var sheet: AgendaSheet?
    @State private var confirmDelete: AgendaEvent?
    @State private var notice: String?
    @State private var appeared = false
    private let data = AgendaData.shared

    var body: some View {
        let clock = AgendaClock.of(session.member)
        let day = selected.isEmpty ? clock.today() : selected
        let actions = AgendaActions(
            open: { sheet = .view($0) },
            edit: { sheet = .edit($0) },
            delete: { confirmDelete = $0 },
            create: { sheet = .create($0) }
        )
        NavigationStack {
            Group {
                if mode == "upcoming" {
                    AgendaUpcoming(clock: clock, selected: selectedBinding(clock), actions: actions, notice: notice)
                } else {
                    AgendaMonth(clock: clock, selected: selectedBinding(clock), actions: actions, notice: notice)
                }
            }
            .navigationTitle("Agenda")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Picker("Agenda view", selection: $mode) {
                        Text("Month").tag("month")
                        Text("Upcoming").tag("upcoming")
                    }
                    .pickerStyle(.segmented)
                    .fixedSize()
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Add event", systemImage: "plus") { sheet = .create(day) }
                }
            }
            .accountButton()
            .sheet(item: $sheet) { which in
                switch which {
                case .view(let ev):
                    NavigationStack {
                        AgendaEventDetail(event: ev, clock: clock, onEdit: { sheet = .edit(ev) }, onChanged: changed)
                    }
                    .presentationDetents([.medium, .large])
                case .edit(let ev):
                    NavigationStack {
                        EventEditor(mode: .edit(id: ev.id, calendar: ev.calendarId), initial: ev, day: nil, onSaved: saved)
                    }
                case .create(let d):
                    NavigationStack {
                        EventEditor(mode: .create(day: clock.date(ofDay: d)), initial: nil, day: d, onSaved: saved)
                    }
                }
            }
            .confirmationDialog(
                "Delete this event?",
                isPresented: Binding(get: { confirmDelete != nil }, set: { if !$0 { confirmDelete = nil } }),
                titleVisibility: .visible,
                presenting: confirmDelete
            ) { ev in
                // One occurrence of a repeating event: that one, or every one.
                if ev.isOccurrence {
                    Button("This event", role: .destructive) { Task { await remove(ev, scope: .this) } }
                    Button("All events", role: .destructive) { Task { await remove(ev, scope: .series) } }
                } else {
                    Button("Delete for real", role: .destructive) { Task { await remove(ev) } }
                }
                Button("Keep it", role: .cancel) {}
            } message: { ev in
                Text(AgendaWords.deleting(ev))
            }
        }
        .task {
            data.bind(session.member, server: session.server)
            await data.loadBasics(session.api)
            #if DEBUG
            await debugOpen(clock)
            #endif
        }
        .onAppear {
            // Back on the tab: the agent may have changed the calendar meanwhile.
            if appeared { data.invalidate() }
            appeared = true
        }
    }

    private func selectedBinding(_ clock: AgendaClock) -> Binding<String> {
        Binding(get: { selected.isEmpty ? clock.today() : selected }, set: { selected = $0 })
    }

    /// The editor's save or delete: it leaves closing its sheet to us.
    private func saved() {
        sheet = nil
        changed()
    }

    private func changed() {
        notice = nil
        data.invalidate()
    }

    private func remove(_ ev: AgendaEvent, scope: AgendaScope? = nil) async {
        do {
            try await session.api.agendaDelete(ev.id, calendar: ev.calendarId, scope: scope)
            notice = nil
        } catch {
            notice = error.localizedDescription
        }
        await session.pending.refresh()
        data.invalidate()
    }

    #if DEBUG
    /// Simulator checks: `-agendaMode month|upcoming`, `-agendaDay YYYY-MM-DD`,
    /// `-openEvent <id>`, `-editEvent <id>`, `-createEvent 1`.
    private func debugOpen(_ clock: AgendaClock) async {
        let d = UserDefaults.standard
        if let m = d.string(forKey: "agendaMode") { mode = m }
        if let day = d.string(forKey: "agendaDay") { selected = day }
        if let id = d.string(forKey: "openEvent"), let ev = try? await session.api.agendaEvent(id, calendar: nil) {
            sheet = .view(ev)
        } else if let id = d.string(forKey: "editEvent"), let ev = try? await session.api.agendaEvent(id, calendar: nil) {
            sheet = .edit(ev)
        } else if d.string(forKey: "createEvent") != nil {
            sheet = .create(selected.isEmpty ? clock.today() : selected)
        }
    }
    #endif
}

enum AgendaSheet: Identifiable {
    case view(AgendaEvent)
    case edit(AgendaEvent)
    case create(String)

    var id: String {
        switch self {
        case .view(let ev): "view-\(ev.id)"
        case .edit(let ev): "edit-\(ev.id)"
        case .create(let day): "create-\(day)"
        }
    }
}

/// What a row can ask the agenda for.
struct AgendaActions {
    var open: (AgendaEvent) -> Void
    var edit: (AgendaEvent) -> Void
    var delete: (AgendaEvent) -> Void
    var create: (String) -> Void
}

/// One event in a list (web `EventCard`): its colour, title, time, whose it is, where.
struct EventRow: View {
    let event: AgendaEvent
    let clock: AgendaClock

    var body: some View {
        let data = AgendaData.shared
        let color = event.isAllDay ? Color.green : data.color(event)
        let who = data.person(event.leader)?.name
        HStack(alignment: .top, spacing: 12) {
            Circle().fill(color).frame(width: 10, height: 10).padding(.top, 6)
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(event.displayTitle).font(.body.weight(.medium)).foregroundStyle(.primary)
                    if event.isRecurring {
                        Image(systemName: "repeat").font(.caption).foregroundStyle(.secondary)
                            .accessibilityLabel("Recurring")
                    }
                }
                Group {
                    if let who {
                        Text("\(clock.range(event)) · \(Text(who).fontWeight(.medium).foregroundStyle(AgendaPalette.color(data.person(event.leader)?.hex ?? "") ?? .secondary))")
                    } else {
                        Text(clock.range(event))
                    }
                }
                .font(.subheadline)
                .foregroundStyle(.secondary)
                if !event.location.isEmpty {
                    Label(event.location, systemImage: "mappin")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .labelStyle(AgendaTightLabel())
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 2)
        .contentShape(Rectangle())
    }
}

struct AgendaTightLabel: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            configuration.icon.font(.caption)
            configuration.title
        }
    }
}

/// An event's row in a list: tap opens it; swipe edits or deletes what luach may change.
struct AgendaEventItem: View {
    let event: AgendaEvent
    let clock: AgendaClock
    let actions: AgendaActions

    var body: some View {
        Button { actions.open(event) } label: { EventRow(event: event, clock: clock) }
            .foregroundStyle(.primary)
            .accessibilityLabel("\(event.displayTitle), \(clock.range(event))")
            .accessibilityIdentifier("agenda.event")
            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                if !event.readOnly {
                    Button("Delete", systemImage: "trash") { actions.delete(event) }.tint(.red)
                    Button("Edit", systemImage: "pencil") { actions.edit(event) }.tint(.accentColor)
                }
            }
    }
}

/// "Nothing on Tuesday." and a way to add something there.
struct AgendaEmptyDay: View {
    let day: String
    let clock: AgendaClock
    let actions: AgendaActions

    var body: some View {
        QuietDay(
            title: day == clock.today() ? "Nothing on today." : "Nothing on \(clock.dayName(day, long: true)).",
            symbol: day == clock.today() ? "sun.max.fill" : "calendar",
            action: ("Add something", { actions.create(day) }))
    }
}

/// "Monday, October 26 · today".
func agendaDayHeading(_ day: String, _ clock: AgendaClock) -> String {
    clock.dateLong(day) + (day == clock.today() ? String(localized: " · today") : "")
}
