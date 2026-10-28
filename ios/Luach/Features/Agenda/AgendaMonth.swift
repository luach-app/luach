import SwiftUI

/// A month of days with a dot per event, and the chosen day's events below it
/// (web `agenda/MonthView.tsx`, the phone grid). Swipe the grid or use the arrows
/// to change month; the title opens a picker for any month of any year.
struct AgendaMonth: View {
    @Environment(AppSession.self) private var session
    let clock: AgendaClock
    @Binding var selected: String
    let actions: AgendaActions
    let notice: String?
    @State private var ym = ""
    @State private var picker = false
    private let data = AgendaData.shared

    var body: some View {
        let today = clock.today()
        let month = ym.isEmpty ? AgendaClock.ym(selected) : ym
        let grid = AgendaClock.monthGrid(month, sundayFirst: clock.sundayFirst)
        let events = data.months[month]
        let error = data.monthErrors[month]
        let byDay = clock.byDay(events ?? [], from: grid.first, to: grid.last)
        let loading = events == nil && error == nil

        List {
            if let notice {
                Text(notice).foregroundStyle(.red)
            }
            Section {
                header(month, today: today)
                if let error {
                    HStack {
                        Text(error).font(.subheadline).foregroundStyle(.red)
                        Spacer()
                        Button("Try again") { Task { await load(month, force: true) } }
                            .buttonStyle(.borderless)
                    }
                }
                AgendaMonthGrid(clock: clock, weeks: grid.weeks, month: month, byDay: byDay, loading: loading,
                                today: today, selected: $selected)
                    .simultaneousGesture(
                        DragGesture(minimumDistance: 30).onEnded { g in
                            guard abs(g.translation.width) > abs(g.translation.height) * 1.5,
                                  abs(g.translation.width) > 60 else { return }
                            let forward = g.translation.width < 0
                            withAnimation { goto(AgendaClock.addMonths(month, forward ? 1 : -1)) }
                        }
                    )
            }
            Section(agendaDayHeading(selected, clock)) {
                if loading {
                    ProgressView().frame(maxWidth: .infinity).padding(.vertical, 20)
                } else if let list = byDay[selected], !list.isEmpty {
                    ForEach(list) { AgendaEventItem(event: $0, clock: clock, actions: actions) }
                } else {
                    AgendaEmptyDay(day: selected, clock: clock, actions: actions)
                }
            }
        }
        .refreshable { await load(month, force: true) }
        .task(id: "\(month)|\(data.version)") { await load(month) }
        .onAppear {
            if ym.isEmpty { ym = AgendaClock.ym(selected) }
            #if DEBUG
            if UserDefaults.standard.bool(forKey: "monthPicker") { picker = true }
            #endif
        }
        // Keep the month in step when the selection moves (e.g. from Upcoming).
        .onChange(of: selected) { _, day in ym = AgendaClock.ym(day) }
        .sheet(isPresented: $picker) {
            AgendaMonthPicker(clock: clock, ym: month, todayYm: AgendaClock.ym(today)) { next in
                picker = false
                goto(next)
            }
            .presentationDetents([.medium])
        }
    }

    private func load(_ month: String, force: Bool = false) async {
        await data.loadMonth(month, clock: clock, api: session.api, force: force)
    }

    private func goto(_ next: String) {
        let today = clock.today()
        guard next != ym else { return }
        ym = next
        selected = next == AgendaClock.ym(today) ? today : "\(next)-01"
    }

    private func header(_ month: String, today: String) -> some View {
        HStack(spacing: 4) {
            Button("Previous month", systemImage: "chevron.backward") { goto(AgendaClock.addMonths(month, -1)) }
                .labelStyle(.iconOnly)
                .frame(width: 36, height: 36)
            Button { picker = true } label: {
                Text(clock.monthYear(month)).font(.title3.bold()).foregroundStyle(.primary)
            }
            .accessibilityLabel("\(clock.monthYear(month)), choose month")
            .accessibilityIdentifier("agenda.month")
            Button("Next month", systemImage: "chevron.forward") { goto(AgendaClock.addMonths(month, 1)) }
                .labelStyle(.iconOnly)
                .frame(width: 36, height: 36)
            Spacer()
            Button("Today") {
                ym = AgendaClock.ym(today)
                selected = today
            }
            .disabled(month == AgendaClock.ym(today) && selected == today)
        }
        .buttonStyle(.borderless)
    }
}

/// Day numbers in Mon–Sun rows, each with up to three dots in its events' colours.
struct AgendaMonthGrid: View {
    let clock: AgendaClock
    let weeks: [[String]]
    let month: String
    let byDay: [String: [AgendaEvent]]
    let loading: Bool
    let today: String
    @Binding var selected: String

    var body: some View {
        VStack(spacing: 4) {
            HStack(spacing: 0) {
                ForEach(Array(clock.weekdayLetters().enumerated()), id: \.offset) { _, letter in
                    Text(letter)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity)
                }
            }
            .accessibilityHidden(true)
            ForEach(weeks, id: \.self) { week in
                HStack(spacing: 0) {
                    ForEach(week, id: \.self) { day in
                        cell(day).frame(maxWidth: .infinity)
                    }
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func cell(_ day: String) -> some View {
        let list = byDay[day] ?? []
        let on = day == selected
        let inMonth = day.hasPrefix(month)
        return Button { selected = day } label: {
            VStack(spacing: 3) {
                Text(clock.dayNumber(day))
                    .font(.system(size: 16, weight: on ? .semibold : .regular))
                    .monospacedDigit()
                HStack(spacing: 2) {
                    if loading {
                        Circle().fill(Color.secondary.opacity(0.25)).frame(width: 5, height: 5)
                    } else {
                        ForEach(Array(list.prefix(3).enumerated()), id: \.offset) { _, ev in
                            Circle()
                                .fill(on ? Color.accentOn.opacity(0.75) : AgendaData.shared.color(ev))
                                .frame(width: 5, height: 5)
                        }
                    }
                }
                .frame(height: 5)
            }
            .frame(width: 44, height: 44)
            .foregroundStyle(on ? Color.accentOn : inMonth ? Color.primary : Color.secondary.opacity(0.6))
            .background {
                if on {
                    Circle().fill(Color.accentColor)
                } else if day == today {
                    Circle().strokeBorder(Color.accentColor, lineWidth: 2)
                }
            }
            .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(clock.dateLong(day))\(list.isEmpty ? "" : String(localized: ", \(list.count) events"))")
        .accessibilityIdentifier("agenda.day.\(day)")
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// A year stepper (typable, 1000–9999) and the twelve months (web `agenda/MonthPicker.tsx`).
struct AgendaMonthPicker: View {
    let clock: AgendaClock
    let ym: String
    let todayYm: String
    let onPick: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var year = 0
    @State private var draft = ""
    @FocusState private var typing: Bool

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                HStack(spacing: 12) {
                    Button("Previous year", systemImage: "chevron.backward") { setYear(year - 1) }
                        .labelStyle(.iconOnly)
                    TextField("Year", text: $draft)
                        .keyboardType(.numberPad)
                        .multilineTextAlignment(.center)
                        .font(.title3.weight(.semibold).monospacedDigit())
                        .frame(width: 96)
                        .padding(.vertical, 8)
                        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12))
                        .focused($typing)
                        .accessibilityIdentifier("agenda.picker.year")
                        .onSubmit { setYear(Int(draft) ?? year) }
                        .onChange(of: typing) { _, on in if !on { setYear(Int(draft) ?? year) } }
                    Button("Next year", systemImage: "chevron.forward") { setYear(year + 1) }
                        .labelStyle(.iconOnly)
                }
                .font(.title3)
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 8) {
                    ForEach(1...12, id: \.self) { m in
                        let key = String(format: "%04d-%02d", year, m)
                        let current = key == ym
                        Button { onPick(key) } label: {
                            Text(clock.monthShort(m))
                                .font(.subheadline.weight(.medium))
                                .frame(maxWidth: .infinity, minHeight: 44)
                                .foregroundStyle(current ? Color.accentOn : Color.primary)
                                .background(current ? Color.accentColor : Color(.secondarySystemBackground),
                                            in: RoundedRectangle(cornerRadius: 12))
                                .overlay {
                                    RoundedRectangle(cornerRadius: 12)
                                        .strokeBorder(key == todayYm && !current ? Color.accentColor.opacity(0.5) : Color.clear, lineWidth: 1.5)
                                }
                        }
                        .buttonStyle(.plain)
                        .accessibilityAddTraits(current ? .isSelected : [])
                        .accessibilityIdentifier("agenda.picker.\(key)")
                    }
                }
                Spacer(minLength: 0)
            }
            .padding()
            .navigationTitle("Go to")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
            .onAppear { setYear(Int(ym.prefix(4)) ?? 2026) }
        }
    }

    private func setYear(_ y: Int) {
        year = min(9999, max(1000, y))
        draft = String(year)
    }
}
