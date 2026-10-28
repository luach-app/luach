import SwiftUI

/// The family's tasks, by person: a day's list (paged a day at a time), or every
/// open to-do and chore. Anyone ticks; the grown-ups add, change and remove
/// (`may_assign`), and a child's account is told so instead.
struct TasksView: View {
    @Environment(AppSession.self) private var session

    enum Mode: String, CaseIterable, Identifiable {
        case day, all
        var id: String { rawValue }
        var label: LocalizedStringKey { self == .day ? "Day" : "Everything" }
    }

    @State private var mode: Mode = .day
    /// The day shown; "" until the server has said which day today is in the member's zone.
    @State private var day = ""
    @State private var today = ""
    @State private var list: [TaskItem] = []
    @State private var people: [BoardPerson] = []
    @State private var mayAssign = false
    @State private var loaded = false
    @State private var error: String?
    @State private var sheet: TaskSheet?

    var body: some View {
        List {
            Section {
                Picker("Show", selection: $mode) {
                    ForEach(Mode.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
                .listRowSeparator(.hidden)
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
                if mode == .day && !day.isEmpty {
                    dayNav
                        .listRowBackground(Color.clear)
                        .listRowInsets(EdgeInsets(top: 8, leading: 0, bottom: 0, trailing: 0))
                }
            }
            if let error {
                Section { Text(error).foregroundStyle(.red) }
            }
            ForEach(columns) { column in
                Section {
                    if column.tasks.isEmpty {
                        Text(mode == .day ? "Nothing today." : "Nothing open.").foregroundStyle(.secondary)
                    }
                    ForEach(column.tasks) { task in
                        TaskRow(
                            task: task, hex: column.hex,
                            onTick: { tick(task) },
                            onOpen: mayAssign ? { sheet = .open(task) } : nil
                        )
                        .swipeActions(edge: .trailing) {
                            if mayAssign {
                                Button("Remove", systemImage: "trash", role: .destructive) { remove(task) }
                            }
                        }
                    }
                } header: {
                    HStack {
                        PersonHeading(name: column.name, hex: column.hex)
                        Spacer()
                        if !column.tasks.isEmpty {
                            Text("\(column.tasks.filter(\.done).count)/\(column.tasks.count)")
                                .monospacedDigit()
                        }
                    }
                }
            }
            if loaded && !mayAssign {
                Section {
                    Text("Tick what you have done. A grown-up hands out the tasks.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .listRowBackground(Color.clear)
                }
            }
        }
        .navigationTitle("Tasks")
        .toolbar {
            if mayAssign {
                ToolbarItem(placement: .primaryAction) {
                    Button("New task", systemImage: "plus") { sheet = .new(person: "") }
                }
            }
        }
        .overlay { if !loaded { ProgressView() } }
        .refreshable { await load() }
        .task(id: "\(mode.rawValue)|\(day)") { await load() }
        .task { await loadPeople() }
        .sheet(item: $sheet) { sheet in
            TaskEditor(sheet: sheet, people: people, canEdit: mayAssign, routes: .tasks) {
                Task { await load() }
            }
        }
        #if DEBUG
        .task { await debugOpen() }
        #endif
    }

    private var dayNav: some View {
        HStack {
            Button("Previous day", systemImage: "chevron.backward") { day = ISODay.add(day, -1) }
                .labelStyle(.iconOnly)
            Spacer()
            Text(day == today ? String(localized: "Today") : ISODay.long(day))
                .font(.headline)
                .accessibilityIdentifier("tasks-day")
            Spacer()
            Button("Next day", systemImage: "chevron.forward") { day = ISODay.add(day, 1) }
                .labelStyle(.iconOnly)
        }
        .overlay(alignment: .trailing) {
            if day != today {
                Button("Today") { day = today }
                    .font(.footnote)
                    .accessibilityIdentifier("tasks-today")
                    .padding(.trailing, 36)
            }
        }
        .buttonStyle(.borderless)
        .font(.title3)
    }

    private var columns: [BoardColumn] { Self.columns(people: people, list: list) }

    /// One column per person, in the family's order, then whoever-gets-to-it.
    static func columns(people: [BoardPerson], list: [TaskItem]) -> [BoardColumn] {
        let known = Set(people.map(\.key))
        var cols = people.map { p in
            BoardColumn(key: p.key, name: p.name, hex: p.hex, events: [], tasks: list.filter { $0.person == p.key })
        }
        let anyone = list.filter { $0.person.isEmpty || !known.contains($0.person) }
        if !anyone.isEmpty {
            cols.append(BoardColumn(key: "", name: String(localized: "Anyone"), hex: "", events: [], tasks: anyone))
        }
        return cols
    }

    /// The day a tick is for: the page in the day list, today in the full list.
    private var tickDay: String { mode == .day ? day : today }

    private func load() async {
        do {
            let answer = mode == .all ? try await session.api.tasksAll() : try await session.api.tasksDay(day.isEmpty ? nil : day)
            if day.isEmpty, let first = answer.day {
                today = first
                day = first
            }
            if today.isEmpty { today = ISODay.today(in: TimeZone(identifier: session.member?.timezone ?? "") ?? .current) }
            list = answer.tasks
            mayAssign = answer.mayAssign
            error = nil
        } catch {
            if Task.isCancelled || (error as? URLError)?.code == .cancelled { return }
            self.error = error.localizedDescription
        }
        loaded = true
    }

    private func loadPeople() async {
        do {
            people = try await session.api.family()
        } catch {
            if (error as? URLError)?.code != .cancelled { self.error = error.localizedDescription }
        }
    }

    private func tick(_ task: TaskItem) {
        guard let i = list.firstIndex(where: { $0.id == task.id }) else { return }
        // Shown at once; put back if the server says no.
        list[i].done.toggle()
        let done = list[i].done
        let when = tickDay.isEmpty ? ISODay.today(in: .current) : tickDay
        Task {
            do {
                try await session.api.tick(task.id, done: done, day: when)
            } catch {
                // Reloaded first: a load that works clears the error, and the box would spring
                // back without a word of why.
                await load()
                self.error = error.localizedDescription
            }
        }
    }

    private func remove(_ task: TaskItem) {
        Task {
            do {
                try await TaskRoutes.tasks.remove(session.api, task.id)
                await load()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    #if DEBUG
    /// Simulator checks: `-tasksMode all`, `-tasksDay 1` (days ahead), `-tasksEdit new|<id>`.
    private func debugOpen() async {
        let defaults = UserDefaults.standard
        if defaults.string(forKey: "tasksMode") == "all" { mode = .all }
        for _ in 0..<20 where !loaded { try? await Task.sleep(for: .milliseconds(250)) }
        if let n = defaults.string(forKey: "tasksDay").flatMap(Int.init), !day.isEmpty { day = ISODay.add(day, n) }
        if let which = defaults.string(forKey: "tasksEdit") {
            for _ in 0..<20 where people.isEmpty { try? await Task.sleep(for: .milliseconds(250)) }
            if which == "new" { sheet = .new(person: "") }
            else if let id = Int(which), let t = list.first(where: { $0.id == id }) { sheet = .open(t) }
        }
    }
    #endif
}
