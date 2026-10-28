import SwiftUI

/// The family's board, one day at a time: today or any of the next 30 days, paged
/// with the chips or the arrows. Each person's events and tasks; tick a task off,
/// tap an event or a task to open it, and each person's + adds something of theirs.
/// Hold a row to give it to someone else or move it to another day, with Undo.
struct BoardView: View {
    @Environment(AppSession.self) private var session
    @Environment(\.scenePhase) private var scenePhase

    @State private var day: BoardDay?
    /// The page asked for; nil is today.
    @State private var page: String?
    @State private var stale = false
    @State private var loadError: String?
    @State private var problem: String?
    /// Whether this member may decide the tasks (not a child). The board itself lets
    /// any member edit; the task routes then refuse a child, so ask once and say so up front.
    @State private var mayAssign = true
    @State private var taskSheet: TaskSheet?
    @State private var eventSheet: EventSheetItem?
    @State private var toast: Toast?

    /// How often a tick on someone else's phone reaches this one.
    private static let refresh: Duration = .seconds(20)
    /// The server pages today and the 30 days after it.
    private static let ahead = 30
    private static let tomorrowShown = 6

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(day.map { ISODay.chip($0.day, today: $0.todayISO) } ?? String(localized: "Board"))
                .accountButton()
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        NavigationLink {
                            TasksView().navigationTitle("Tasks")
                        } label: {
                            Label("Tasks", systemImage: "checklist")
                        }
                    }
                }
                .task(id: page) {
                    while !Task.isCancelled {
                        await load()
                        try? await Task.sleep(for: Self.refresh)
                    }
                }
                .task { await loadMayAssign() }
                .onChange(of: scenePhase) { _, phase in
                    if phase == .active { Task { await load() } }
                }
                .refreshable { await load() }
                .sheet(item: $taskSheet) { sheet in
                    TaskEditor(
                        sheet: sheet,
                        people: day?.people ?? [],
                        canEdit: canEditTasks,
                        routes: .board,
                        onChanged: { Task { await load() } }
                    )
                }
                .sheet(item: $eventSheet) { item in
                    NavigationStack {
                        EventEditor(mode: item.mode) {
                            eventSheet = nil
                            Task { await load() }
                        }
                    }
                }
                .overlay(alignment: .bottom) { toastView }
                .task(id: toast?.id) {
                    guard toast != nil else { return }
                    try? await Task.sleep(for: .seconds(6))
                    if !Task.isCancelled { withAnimation { toast = nil } }
                }
        }
        #if DEBUG
        .task { await debugOpen() }
        #endif
    }

    @ViewBuilder
    private var content: some View {
        if let day {
            board(day)
        } else if let loadError {
            ContentUnavailableView {
                Label("The board did not load", systemImage: "wifi.exclamationmark")
            } description: {
                Text(loadError)
            } actions: {
                Button("Try again") { Task { await load() } }
                    .prominentAccent()
            }
        } else {
            ProgressView()
        }
    }

    private var canEdit: Bool { day?.canEdit ?? false }
    private var canEditTasks: Bool { canEdit && mayAssign }

    // MARK: The page

    private func board(_ day: BoardDay) -> some View {
        let isToday = day.day == day.todayISO
        return List {
            Section {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(alignment: .firstTextBaseline) {
                        TimelineView(.everyMinute) { context in
                            Text(Self.dateLine(day, now: context.date, isToday: isToday))
                                .font(.headline)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if !isToday {
                            Button("Back to today") { go(nil) }
                                .buttonStyle(.bordered)
                                .buttonBorderShape(.capsule)
                                .controlSize(.small)
                        }
                    }
                    chips(day)
                        // One line of day chips: past this size they would wrap.
                        .dynamicTypeSize(...DynamicTypeSize.xxLarge)
                    if stale {
                        Text("offline — showing the last known day").font(.footnote).foregroundStyle(.red)
                    }
                    if let problem {
                        Text(problem).font(.footnote).foregroundStyle(.red)
                    }
                }
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 4, trailing: 16))
            }

            if day.people.isEmpty {
                Section {
                    Text("No one is on the board yet. The owner adds the people it shows under Settings › Household › Family.")
                        .foregroundStyle(.secondary)
                }
            }

            let columns = day.columns(withFamily: canEdit)
            let everyoneFree = !columns.isEmpty && columns.allSatisfy { $0.events.isEmpty && $0.tasks.isEmpty }
            if everyoneFree {
                // One kind line for a free day, not the same one under every name.
                Section {
                    QuietDay(title: "A free day.", message: isToday
                             ? "Nothing on anyone's board today."
                             : "Nothing on anyone's board that day.")
                }
            }
            ForEach(columns) { column in
                Section {
                    ForEach(column.events) { event in
                        eventRow(event, in: column, day: day)
                    }
                    ForEach(column.tasks) { task in
                        TaskRow(task: task, hex: column.hex, onTick: { tick(task) }, onOpen: { taskSheet = .open(task) })
                            .contextMenu { taskMenu(task, in: column, day: day) }
                    }
                    if column.events.isEmpty && column.tasks.isEmpty && !everyoneFree {
                        Text("A free day.").foregroundStyle(.secondary)
                    }
                } header: {
                    columnHeader(column, day: day)
                }
            }

            if !day.tomorrow.isEmpty {
                Section(isToday ? LocalizedStringKey("Tomorrow") : "The day after") {
                    ForEach(day.tomorrow.prefix(Self.tomorrowShown)) { event in
                        HStack(alignment: .firstTextBaseline, spacing: 12) {
                            Text(Self.timeOf(event, day.zone))
                                .font(.subheadline.monospacedDigit())
                                .foregroundStyle(.secondary)
                                .frame(minWidth: 64, alignment: .leading)
                            Text(event.title + Self.names(event, day.people))
                                .foregroundStyle(.secondary)
                        }
                    }
                    if let more = Self.more(day.tomorrow.count) {
                        Text("+\(more) more").foregroundStyle(.secondary)
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    static func dateLine(_ day: BoardDay, now: Date, isToday: Bool) -> String {
        guard isToday else { return ISODay.long(day.day) }
        var date = Date.FormatStyle.dateTime.weekday(.wide).month(.wide).day()
        date.timeZone = day.zone
        var time = Date.FormatStyle(date: .omitted, time: .shortened)
        time.timeZone = day.zone
        return "\(now.formatted(date)) · \(now.formatted(time))"
    }

    private func chips(_ day: BoardDay) -> some View {
        let today = day.todayISO
        let last = ISODay.add(today, Self.ahead)
        return HStack(spacing: 8) {
            Button("Previous day", systemImage: "chevron.backward") { step(-1, day) }
                .labelStyle(.iconOnly)
                .disabled(day.day <= today)
            ScrollViewReader { proxy in
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(0...Self.ahead, id: \.self) { i in
                            let iso = ISODay.add(today, i)
                            let on = iso == day.day
                            Button { go(iso == today ? nil : iso) } label: {
                                Text(ISODay.chip(iso, today: today))
                                    .font(.subheadline.weight(on ? .semibold : .regular))
                                    .padding(.horizontal, 12)
                                    .padding(.vertical, 6)
                                    .foregroundStyle(on ? Color.accentOn : Color.primary)
                                    .background(Capsule().fill(on ? Color.accentColor : Color(.secondarySystemGroupedBackground)))
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("chip-\(iso)")
                            .id(iso)
                            .accessibilityAddTraits(on ? .isSelected : [])
                        }
                    }
                }
                .onAppear { proxy.scrollTo(day.day, anchor: .center) }
                .onChange(of: day.day) { _, iso in
                    withAnimation { proxy.scrollTo(iso, anchor: .center) }
                }
            }
            Button("Next day", systemImage: "chevron.forward") { step(1, day) }
                .labelStyle(.iconOnly)
                .disabled(day.day >= last)
        }
        .buttonStyle(.borderless)
        .font(.title3)
    }

    private func columnHeader(_ column: BoardColumn, day: BoardDay) -> some View {
        HStack {
            PersonHeading(name: column.name, hex: column.hex.isEmpty ? "" : column.hex)
                .font(.title3.bold())
                .foregroundStyle(.primary)
                .textCase(nil)
            Spacer()
            if canEdit {
                Menu {
                    Button("Event", systemImage: "calendar.badge.plus") {
                        eventSheet = EventSheetItem(mode: .create(day: ISODay.local(day.day) ?? .now, leader: column.key.isEmpty ? nil : column.key))
                    }
                    if mayAssign {
                        Button("Task", systemImage: "checklist") { taskSheet = .new(person: column.key) }
                    }
                } label: {
                    Image(systemName: "plus.circle.fill")
                        .font(.title2)
                        .foregroundStyle(Color(luachHex: column.hex) == nil ? Color.accentOn : Color.ink(on: column.hex), personColor(column.hex))
                }
                .accessibilityLabel(column.key.isEmpty ? Text("Add for the family") : Text("Add for \(column.name)"))
            }
        }
    }

    private func eventRow(_ event: BoardEvent, in column: BoardColumn, day: BoardDay) -> some View {
        Button {
            eventSheet = EventSheetItem(mode: .edit(id: event.id, calendar: event.calendarId))
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(Self.timeOf(event, day.zone))
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .frame(minWidth: 64, alignment: .leading)
                Text(event.title.isEmpty ? String(localized: "(no title)") : event.title)
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.leading, 10)
            .overlay(alignment: .leading) {
                RoundedRectangle(cornerRadius: 2).fill(personColor(column.hex)).frame(width: 4)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text("Open \(event.title)"))
        .contextMenu { eventMenu(event, in: column, day: day) }
    }

    static func timeOf(_ event: BoardEvent, _ zone: TimeZone) -> String {
        if event.isAllDay { return String(localized: "All day") }
        guard let start = EventTime.parse(event.start) else { return "" }
        var style = Date.FormatStyle(date: .omitted, time: .shortened)
        style.timeZone = zone
        return start.formatted(style)
    }

    /// " (Noa and Sam)" — everyone an event is for.
    static func names(_ event: BoardEvent, _ people: [BoardPerson]) -> String {
        let found = event.people.compactMap { k in people.first { $0.key == k }?.name }
        return found.isEmpty ? "" : " (\(found.formatted(.list(type: .and))))"
    }

    // MARK: Moving things by hand

    @ViewBuilder
    private func taskMenu(_ task: TaskItem, in column: BoardColumn, day: BoardDay) -> some View {
        if canEditTasks {
            giveMenu(day: day, from: column.key) { to in move(.task(task, .person(to)), day) }
            if task.chore {
                Text("This one repeats — change it in the editor.")
            } else {
                dayMenu(day) { iso in move(.task(task, .day(iso)), day) }
            }
        }
    }

    @ViewBuilder
    private func eventMenu(_ event: BoardEvent, in column: BoardColumn, day: BoardDay) -> some View {
        if canEdit {
            if event.readOnly == true {
                Text("Only the organizer can change this.")
            } else {
                giveMenu(day: day, from: column.key) { to in move(.event(event, from: column.key, .person(to)), day) }
                if event.recurring == true {
                    Text("This one repeats — change it in the editor.")
                } else {
                    dayMenu(day) { iso in move(.event(event, from: column.key, .day(iso)), day) }
                }
            }
        }
    }

    private func giveMenu(day: BoardDay, from: String, _ action: @escaping (String) -> Void) -> some View {
        Menu("Give to", systemImage: "person.crop.circle.badge.plus") {
            ForEach(day.people.filter { $0.key != from }) { p in
                Button(p.name) { action(p.key) }
            }
            if !from.isEmpty {
                Button("The family") { action("") }
            }
        }
    }

    private func dayMenu(_ day: BoardDay, _ action: @escaping (String) -> Void) -> some View {
        Menu("Move to", systemImage: "calendar") {
            ForEach(0...Self.ahead, id: \.self) { i in
                let iso = ISODay.add(day.todayISO, i)
                if iso != day.day {
                    Button(i < 2 ? ISODay.chip(iso, today: day.todayISO) : ISODay.long(iso)) { action(iso) }
                }
            }
        }
    }

    enum Target: Equatable {
        case person(String)
        case day(String)
    }

    enum Move {
        case task(TaskItem, Target)
        case event(BoardEvent, from: String, Target)
    }

    /// A change made from the menu, and how to take it back.
    struct Planned {
        let title: String
        let target: Target
        let apply: (API) async throws -> Void
        let undo: (API) async throws -> Void
        let preview: (inout BoardDay) -> Void
    }

    static func plan(_ move: Move, _ day: BoardDay) -> Planned? {
        switch move {
        case .task(let task, let to):
            let routes = TaskRoutes.board
            switch to {
            case .person(let key):
                return Planned(
                    title: task.title, target: to,
                    apply: { _ = try await routes.update($0, task.id, TaskInput(person: key)) },
                    undo: { _ = try await routes.update($0, task.id, TaskInput(person: task.person)) },
                    preview: { d in
                        if let i = d.tasks.firstIndex(where: { $0.id == task.id }) { d.tasks[i].person = key }
                    }
                )
            case .day(let iso):
                return Planned(
                    title: task.title, target: to,
                    apply: { _ = try await routes.update($0, task.id, TaskInput(due: iso)) },
                    undo: { _ = try await routes.update($0, task.id, TaskInput(due: task.due)) },
                    preview: { d in
                        if iso > d.day {
                            d.tasks.removeAll { $0.id == task.id }
                        } else if let i = d.tasks.firstIndex(where: { $0.id == task.id }) {
                            d.tasks[i].due = iso
                            d.tasks[i].overdue = false
                        }
                    }
                )
            }
        case .event(let event, let from, let to):
            switch to {
            case .person(let key):
                let had = event.people
                let next = Self.handOver(had, from: from, to: key)
                if Set(had) == Set(next) && had.count == next.count { return nil }
                return Planned(
                    title: event.title, target: to,
                    apply: { try await $0.boardMoveEvent(event, EventPatch(leaders: next)) },
                    undo: { try await $0.boardMoveEvent(event, EventPatch(leaders: had)) },
                    preview: { d in
                        if let i = d.events.firstIndex(where: { $0.id == event.id }) {
                            d.events[i].leaders = next
                            d.events[i].leader = next.first ?? ""
                        }
                    }
                )
            case .day(let iso):
                let shifted = Self.shift(event, days: ISODay.between(day.day, iso), zone: day.zone)
                return Planned(
                    title: event.title, target: to,
                    apply: { try await $0.boardMoveEvent(event, shifted) },
                    undo: { try await $0.boardMoveEvent(event, EventPatch(start: event.start, end: event.end.isEmpty ? nil : event.end)) },
                    preview: { d in d.events.removeAll { $0.id == event.id } }
                )
            }
        }
    }

    /// The one it was taken from gives it to the one it is put on; the family's is nobody's.
    static func handOver(_ leaders: [String], from: String, to: String) -> [String] {
        if to.isEmpty { return [] }
        if from.isEmpty { return [to] }
        var out: [String] = []
        for k in leaders.map({ $0 == from ? to : $0 }) where !out.contains(k) { out.append(k) }
        if !out.contains(to) { out.append(to) }
        return out
    }

    /// The same event `days` later, at the same time of day in the household's zone.
    static func shift(_ event: BoardEvent, days: Int, zone: TimeZone) -> EventPatch {
        if event.isAllDay {
            let start = ISODay.add(String(event.start.prefix(10)), days)
            let end = event.end.isEmpty ? ISODay.add(start, 1) : ISODay.add(String(event.end.prefix(10)), days)
            return EventPatch(start: start, end: end)
        }
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = zone
        let iso = ISO8601DateFormatter()
        func moved(_ s: String) -> String? {
            guard let d = EventTime.parse(s), let m = cal.date(byAdding: .day, value: days, to: d) else { return nil }
            return iso.string(from: m)
        }
        return EventPatch(start: moved(event.start) ?? event.start, end: event.end.isEmpty ? nil : moved(event.end))
    }

    private func move(_ move: Move, _ day: BoardDay) {
        guard let planned = Self.plan(move, day) else { return }
        let before = day
        var after = day
        planned.preview(&after)
        withAnimation { self.day = after }
        problem = nil
        toast = nil
        Task {
            do {
                try await planned.apply(session.api)
                let text: String
                switch planned.target {
                case .day(let iso): text = String(localized: "\(planned.title) moved to \(ISODay.long(iso)).")
                case .person(let key) where key.isEmpty: text = String(localized: "\(planned.title) is now the family’s.")
                case .person(let key):
                    let name = before.people.first { $0.key == key }?.name ?? key
                    text = String(localized: "\(planned.title) is now \(name)’s.")
                }
                withAnimation { toast = Toast(text: text, undo: planned) }
            } catch {
                withAnimation { self.day = before }
                problem = String(localized: "“\(planned.title)” did not save: \(error.localizedDescription)")
            }
            await load()
        }
    }

    private func undo(_ planned: Planned) {
        withAnimation { toast = nil }
        Task {
            do {
                try await planned.undo(session.api)
                withAnimation { toast = Toast(text: String(localized: "\(planned.title) is back where it was."), undo: nil) }
            } catch {
                problem = String(localized: "“\(planned.title)” did not save: \(error.localizedDescription)")
            }
            await load()
        }
    }

    struct Toast {
        let id = UUID()
        let text: String
        let undo: Planned?
    }

    @ViewBuilder
    private var toastView: some View {
        if let toast {
            HStack(spacing: 12) {
                Text(toast.text).frame(maxWidth: .infinity, alignment: .leading)
                if let planned = toast.undo {
                    Button("Undo") { undo(planned) }
                        .fontWeight(.semibold)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
            .shadow(radius: 8, y: 2)
            .padding(.horizontal, 16)
            .padding(.bottom, 12)
            .transition(.move(edge: .bottom).combined(with: .opacity))
            .accessibilityAddTraits(.updatesFrequently)
            .accessibilityIdentifier("board-toast")
        }
    }

    // MARK: Loading and ticking

    private func go(_ iso: String?) {
        problem = nil
        page = iso
    }

    /// Lines past the first few of the day after: the "+N more" under them, nil when none are hidden.
    static func more(_ count: Int) -> Int? {
        count > tomorrowShown ? count - tomorrowShown : nil
    }

    private func step(_ n: Int, _ day: BoardDay) {
        let next = ISODay.add(day.day, n)
        guard next >= day.todayISO, next <= ISODay.add(day.todayISO, Self.ahead) else { return }
        go(next == day.todayISO ? nil : next)
    }

    private func load() async {
        do {
            let loaded = try await session.api.boardDay(page)
            day = loaded
            stale = false
            loadError = nil
        } catch {
            if Task.isCancelled || (error as? URLError)?.code == .cancelled { return }
            if day == nil { loadError = error.localizedDescription } else { stale = true }
        }
    }

    private func loadMayAssign() async {
        if let answer = try? await session.api.tasksDay(nil) { mayAssign = answer.mayAssign }
    }

    private func tick(_ task: TaskItem) {
        guard var d = day, let i = d.tasks.firstIndex(where: { $0.id == task.id }) else { return }
        let done = !task.done
        d.tasks[i].done = done
        day = d
        let isToday = d.day == d.todayISO
        let shown = d.day
        Task {
            do {
                try await session.api.boardTick(task.id, done: done, day: isToday ? nil : shown)
                problem = nil
            } catch {
                // The box springs back when the day reloads; say why, or it looks like the tap was missed.
                problem = String(localized: "“\(task.title)” did not save: \(error.localizedDescription)")
                await load()
            }
        }
    }

    #if DEBUG
    /// Simulator checks: `-boardDay 2` opens two days ahead; `-boardTask new` or
    /// `-boardTask <id>` opens the task sheet; `-boardToast` shows the undo bar.
    private func debugOpen() async {
        let defaults = UserDefaults.standard
        if let offset = defaults.string(forKey: "boardDay").flatMap(Int.init), offset > 0 {
            page = ISODay.add(ISODay.today(in: day?.zone ?? .current), offset)
        }
        guard let which = defaults.string(forKey: "boardTask") else {
            if defaults.bool(forKey: "boardToast") {
                toast = Toast(text: "ios-test is now Ruby’s.", undo: Planned(title: "", target: .person(""), apply: { _ in }, undo: { _ in }, preview: { _ in }))
            }
            return
        }
        for _ in 0..<20 where day == nil { try? await Task.sleep(for: .milliseconds(250)) }
        if which == "new" {
            taskSheet = .new(person: day?.people.first?.key ?? "")
        } else if let id = Int(which), let t = day?.tasks.first(where: { $0.id == id }) {
            taskSheet = .open(t)
        }
    }
    #endif
}

/// The event editor the Agenda area owns, opened from the board.
struct EventSheetItem: Identifiable {
    let id = UUID()
    let mode: EventEditorMode
}
