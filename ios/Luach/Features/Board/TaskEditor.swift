import SwiftUI

/// Which task the sheet is about: one that exists, or a new one for someone ("" is anyone).
enum TaskSheet: Identifiable {
    case open(TaskItem)
    case new(person: String)

    var id: String {
        switch self {
        case .open(let t): "task-\(t.id)"
        case .new(let p): "new-\(p)"
        }
    }
}

/// A task: what it is, whose, and when — a one-off with an optional day it is
/// due, or a chore on some weekdays. Change it, hand it to someone else, or
/// remove it. For someone who may not decide the tasks (a child) it only shows.
struct TaskEditor: View {
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss

    let sheet: TaskSheet
    let people: [BoardPerson]
    let canEdit: Bool
    let routes: TaskRoutes
    var onChanged: () -> Void = {}

    @State private var title = ""
    @State private var person = ""
    @State private var chore = false
    @State private var days: [String] = []
    @State private var hasDue = false
    @State private var due = Calendar.current.startOfDay(for: .now)
    @State private var notes = ""
    @State private var busy = false
    @State private var error: String?
    @State private var confirmRemove = false
    @State private var askDiscard = false
    /// The fields as the sheet opened, for "Discard changes?".
    private let opened: Fields

    private static let maxTitle = 200

    /// Everything the form edits, to tell an edit from none.
    struct Fields: Equatable {
        var title: String, person: String, chore: Bool, days: [String], hasDue: Bool, due: Date, notes: String
    }

    private var fields: Fields {
        Fields(title: title, person: person, chore: chore, days: days, hasDue: hasDue, due: due, notes: notes)
    }

    /// Something typed or chosen that Cancel or a swipe would drop.
    private var dirty: Bool { canEdit && fields != opened }

    init(sheet: TaskSheet, people: [BoardPerson], canEdit: Bool, routes: TaskRoutes, onChanged: @escaping () -> Void = {}) {
        self.sheet = sheet
        self.people = people
        self.canEdit = canEdit
        self.routes = routes
        self.onChanged = onChanged
        let today = Calendar.current.startOfDay(for: .now)
        let f: Fields
        switch sheet {
        case .open(let t):
            f = Fields(title: t.title, person: t.person, chore: t.chore, days: t.days, hasDue: !t.due.isEmpty,
                       due: ISODay.local(t.due) ?? today, notes: t.notes ?? "")
        case .new(let p):
            f = Fields(title: "", person: p, chore: false, days: [], hasDue: false, due: today, notes: "")
        }
        _title = State(initialValue: f.title)
        _person = State(initialValue: f.person)
        _chore = State(initialValue: f.chore)
        _days = State(initialValue: f.days)
        _hasDue = State(initialValue: f.hasDue)
        _due = State(initialValue: f.due)
        _notes = State(initialValue: f.notes)
        opened = f
    }

    private var task: TaskItem? {
        if case .open(let t) = sheet { return t }
        return nil
    }

    private var heading: String { Self.heading(task: task, canEdit: canEdit, person: person, people: people) }

    /// "Task" to change one; its title for someone who may only look; "A task for Noa" for a new one.
    static func heading(task: TaskItem?, canEdit: Bool, person: String, people: [BoardPerson]) -> String {
        if let task { return canEdit ? String(localized: "Task") : task.title }
        if let whose = people.first(where: { $0.key == person }) { return String(localized: "A task for \(whose.name)") }
        return String(localized: "A task")
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("What") {
                    TextField("Something to do", text: $title, axis: .vertical)
                        .accessibilityIdentifier("task-title")
                        .onChange(of: title) { _, new in
                            if new.count > Self.maxTitle { title = String(new.prefix(Self.maxTitle)) }
                        }
                }
                Section("For") {
                    WrapLayout(spacing: 8) {
                        chip(key: "", name: String(localized: "Anyone"), hex: "")
                        ForEach(people) { p in chip(key: p.key, name: p.name, hex: p.hex) }
                    }
                    .padding(.vertical, 2)
                    .accessibilityElement(children: .contain)
                    .accessibilityLabel("Task for")
                }
                Section {
                    Toggle("A chore that repeats", isOn: $chore.animation())
                    if chore {
                        weekdays
                    } else {
                        Toggle("Due date", isOn: $hasDue.animation())
                        if hasDue {
                            DatePicker("Due", selection: $due, displayedComponents: .date)
                        }
                    }
                } footer: {
                    if !chore && !hasDue {
                        Text("Without a date it shows at once, until someone ticks it.")
                    }
                }
                Section("Notes") {
                    TextField("Optional", text: $notes, axis: .vertical)
                        .lineLimit(1...5)
                        .accessibilityIdentifier("task-notes")
                }
                if let error {
                    Section { Text(error).foregroundStyle(.red) }
                }
                if task != nil && canEdit {
                    Section {
                        Button("Remove", role: .destructive) { confirmRemove = true }
                            .frame(maxWidth: .infinity)
                    }
                }
            }
            .disabled(!canEdit || busy)
            .navigationTitle(heading)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(canEdit ? "Cancel" : "Close") { if dirty { askDiscard = true } else { dismiss() } }
                        .accessibilityIdentifier("task-cancel")
                }
                if canEdit {
                    ToolbarItem(placement: .confirmationAction) {
                        if busy {
                            ProgressView()
                        } else {
                            Button(task == nil ? "Add task" : "Save") { save() }
                        }
                    }
                }
            }
            .confirmsDiscard(dirty, asking: $askDiscard)
            .confirmationDialog("Remove “\(title)”?", isPresented: $confirmRemove, titleVisibility: .visible) {
                Button("Remove", role: .destructive) { remove() }
                Button("Keep", role: .cancel) {}
            }
        }
    }

    private func chip(key: String, name: String, hex: String) -> some View {
        let on = key == person
        let color = Color(luachHex: hex)
        return Button { person = key } label: {
            HStack(spacing: 6) {
                if let color, !on {
                    Circle().fill(color).frame(width: 10, height: 10)
                }
                Text(name).fontWeight(on ? .semibold : .regular)
            }
            .padding(.horizontal, 12)
            .frame(minHeight: 36)
            .foregroundStyle(on ? (color == nil ? Color.accentOn : Color.ink(on: hex)) : Color.primary)
            .background(Capsule().fill(on ? (color ?? .accentColor) : .clear))
            .overlay(Capsule().strokeBorder(on ? .clear : Color.secondary.opacity(0.4)))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(on ? .isSelected : [])
    }

    private var weekdays: some View {
        HStack(spacing: 6) {
            ForEach(Weekday.codes, id: \.self) { code in
                let on = days.contains(code)
                Button {
                    days = on ? days.filter { $0 != code } : Weekday.sorted(days + [code])
                } label: {
                    Text(Weekday.initial(code))
                        .font(.body.weight(on ? .semibold : .regular))
                        .frame(maxWidth: 44, minHeight: 40)
                        .frame(maxWidth: .infinity)
                        .foregroundStyle(on ? Color.accentOn : Color.primary)
                        .background(Circle().fill(on ? Color.accentColor : .clear))
                        .overlay(Circle().strokeBorder(on ? .clear : Color.secondary.opacity(0.4)))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Weekday.name(code))
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Repeats on")
    }

    /// What is missing before the task can be saved, in a sentence; nil when nothing is.
    static func problem(title: String, chore: Bool, days: [String]) -> String? {
        if title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return String(localized: "Give it a name.") }
        if chore && days.isEmpty { return String(localized: "Pick the days it falls on.") }
        return nil
    }

    /// What Save sends: every field, so a to-do turned chore (or back) loses what no longer applies.
    static func input(title: String, person: String, chore: Bool, days: [String], hasDue: Bool, due: Date, notes: String) -> TaskInput {
        TaskInput(
            title: title.trimmingCharacters(in: .whitespacesAndNewlines),
            person: person,
            due: chore || !hasDue ? "" : ISODay.fromLocal(due),
            days: chore ? Weekday.sorted(days) : [],
            notes: notes.trimmingCharacters(in: .whitespacesAndNewlines)
        )
    }

    private func save() {
        if let problem = Self.problem(title: title, chore: chore, days: days) { error = problem; return }
        let input = Self.input(title: title, person: person, chore: chore, days: days, hasDue: hasDue, due: due, notes: notes)
        run {
            if let task {
                _ = try await routes.update(session.api, task.id, input)
            } else {
                _ = try await routes.add(session.api, input)
            }
        }
    }

    private func remove() {
        guard let task else { return }
        run { try await routes.remove(session.api, task.id) }
    }

    private func run(_ work: @escaping () async throws -> Void) {
        busy = true
        error = nil
        Task {
            defer { busy = false }
            do {
                try await work()
                onChanged()
                dismiss()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

/// Rows of chips that wrap onto the next line, so every person shows at once.
struct WrapLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(width: proposal.width ?? .infinity, subviews)
        let height = rows.last.map { $0.y + $0.height } ?? 0
        let width = rows.map(\.width).max() ?? 0
        return CGSize(width: proposal.width ?? width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        for row in arrange(width: bounds.width, subviews) {
            var x = bounds.minX
            for i in row.items {
                let size = subviews[i].sizeThatFits(.unspecified)
                subviews[i].place(at: CGPoint(x: x, y: bounds.minY + row.y), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
        }
    }

    private struct Row { var items: [Int] = []; var y: CGFloat = 0; var width: CGFloat = 0; var height: CGFloat = 0 }

    private func arrange(width: CGFloat, _ subviews: Subviews) -> [Row] {
        var rows: [Row] = [Row()]
        for i in subviews.indices {
            let size = subviews[i].sizeThatFits(.unspecified)
            var row = rows[rows.count - 1]
            if !row.items.isEmpty && row.width + spacing + size.width > width {
                let y = row.y + row.height + spacing
                rows.append(Row(y: y))
                row = rows[rows.count - 1]
            }
            row.width += (row.items.isEmpty ? 0 : spacing) + size.width
            row.height = max(row.height, size.height)
            row.items.append(i)
            rows[rows.count - 1] = row
        }
        return rows
    }
}
