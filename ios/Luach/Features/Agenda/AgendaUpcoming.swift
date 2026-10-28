import SwiftUI

/// The two-week strip, the chosen day, and what is coming up this week (web `agenda/Upcoming.tsx`).
struct AgendaUpcoming: View {
    @Environment(AppSession.self) private var session
    let clock: AgendaClock
    @Binding var selected: String
    let actions: AgendaActions
    let notice: String?
    private let data = AgendaData.shared

    private static let stripDays = 14
    private static let comingUpDays = 7

    /// "2 things today · 5 more this week", or the quiet version of it.
    func summary(today: Int?, week: Int) -> String {
        guard let today else { return String(localized: "Looking at the week…") }
        switch (today, week) {
        case (0, 0): return String(localized: "Nothing on today or this week.")
        case (0, _): return String(localized: "A clear day today · \(week) this week")
        case (_, 0): return String(localized: "\(today) today · the rest of the week is clear")
        default: return String(localized: "\(today) today · \(week) more this week")
        }
    }

    var body: some View {
        let today = clock.today()
        let days = (0..<Self.stripDays).map { AgendaClock.addDays(today, $0) }
        let last = AgendaClock.addDays(today, Self.stripDays)
        // A day outside the strip (picked in the month) shows today instead.
        let day = selected >= today && selected < last ? selected : today
        let events = data.upcomingFrom == today ? data.upcoming : nil
        let byDay = clock.byDay(events ?? [], from: today, to: last)
        let comingUp = (1...Self.comingUpDays).map { AgendaClock.addDays(today, $0) }.filter { !(byDay[$0] ?? []).isEmpty }

        List {
            if let member = session.member {
                // The day opened like a person would: who it is for, and how full it is.
                VStack(alignment: .leading, spacing: 4) {
                    Text(Greeting.text(member.name)).font(.title2.bold())
                    Text(summary(today: byDay[today]?.count, week: comingUp.reduce(0) { $0 + (byDay[$1]?.count ?? 0) }))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets(top: 4, leading: 20, bottom: 0, trailing: 20))
            }
            if let notice {
                Text(notice).foregroundStyle(.red)
            }
            Section {
                strip(days, day: day, today: today, byDay: byDay)
                    // Fixed-size day chips: past this size their words would wrap inside them.
                    .dynamicTypeSize(...DynamicTypeSize.xxLarge)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
            }
            if let error = data.upcomingError {
                Text(error).foregroundStyle(.red)
            }
            Section(agendaDayHeading(day, clock)) {
                if events == nil {
                    if data.upcomingError == nil {
                        ProgressView().frame(maxWidth: .infinity).padding(.vertical, 20)
                    }
                } else if let list = byDay[day], !list.isEmpty {
                    ForEach(list) { AgendaEventItem(event: $0, clock: clock, actions: actions) }
                } else {
                    AgendaEmptyDay(day: day, clock: clock, actions: actions)
                }
            }
            if events != nil {
                Section("Coming up") {
                    if comingUp.isEmpty {
                        Text("A quiet week ahead.").foregroundStyle(.secondary)
                    }
                    ForEach(comingUp, id: \.self) { d in
                        Button(clock.dateLong(d)) { selected = d }
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.primary)
                        ForEach(byDay[d] ?? []) { AgendaEventItem(event: $0, clock: clock, actions: actions) }
                    }
                }
            }
        }
        .refreshable { await load() }
        .task(id: data.version) { await load() }
        .task {
            // The web polls every two minutes while it is on screen.
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(120))
                if Task.isCancelled { break }
                await load()
            }
        }
    }

    private func load() async {
        await data.loadUpcoming(from: clock.today(), days: Self.stripDays, clock: clock, api: session.api)
    }

    private func strip(_ days: [String], day: String, today: String, byDay: [String: [AgendaEvent]]) -> some View {
        ScrollViewReader { proxy in
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(days, id: \.self) { d in
                        chip(d, on: d == day, isToday: d == today, count: byDay[d]?.count ?? 0)
                            .id(d)
                    }
                }
                .padding(.horizontal, 4)
                .padding(.vertical, 4)
            }
            .onAppear { proxy.scrollTo(day, anchor: .center) }
            .onChange(of: day) { _, d in withAnimation { proxy.scrollTo(d, anchor: .center) } }
        }
    }

    private func chip(_ d: String, on: Bool, isToday: Bool, count: Int) -> some View {
        Button { selected = d } label: {
            VStack(spacing: 2) {
                Text(clock.dayName(d).uppercased()).font(.caption2)
                Text(clock.dayNumber(d)).font(.title3.weight(.semibold)).monospacedDigit()
                Circle()
                    .fill(count == 0 ? Color.clear : on ? Color.accentOn.opacity(0.7) : Color.accentColor)
                    .frame(width: 6, height: 6)
                    .padding(.top, 2)
            }
            .frame(width: 52)
            .padding(.vertical, 10)
            .foregroundStyle(on ? Color.accentOn : isToday ? Color.primary : Color.secondary)
            .background(on ? Color.accentColor : Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
            .overlay {
                RoundedRectangle(cornerRadius: 16)
                    .strokeBorder(isToday && !on ? Color.accentColor.opacity(0.5) : Color.clear, lineWidth: 1.5)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(clock.dayName(d, long: true)) \(clock.dayNumber(d))\(count > 0 ? String(localized: ", \(count) events") : "")")
        .accessibilityIdentifier("agenda.chip.\(d)")
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}
