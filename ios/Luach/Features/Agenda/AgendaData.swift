import SwiftUI
import Observation

/// What the agenda and the event editor share (web `monthCache`, `household`, `family`):
/// the household's calendars, the family, the member's also-notify inboxes, and the
/// events of every month looked at. A month that is refreshing keeps showing what it
/// had, so the grid does not blank on every change. `invalidate()` after any write.
@Observable
final class AgendaData {
    static let shared = AgendaData()

    private(set) var household: AgendaHousehold?
    private(set) var people: [AgendaPerson] = []
    private(set) var notifyEmails: [String] = []
    private(set) var basicsLoaded = false
    /// Events per month grid, keyed "YYYY-MM".
    private(set) var months: [String: [AgendaEvent]] = [:]
    private(set) var monthErrors: [String: String] = [:]
    /// The next two weeks, for Upcoming.
    private(set) var upcoming: [AgendaEvent]?
    private(set) var upcomingFrom = ""
    private(set) var upcomingError: String?
    /// Bumped by every change; views reload on it.
    private(set) var version = 0

    @ObservationIgnored private var fresh: Set<String> = []
    /// Whose all this is: the luach and the member. Another household's people and calendars
    /// must never show for the next one signed in on this phone.
    @ObservationIgnored private var owner: String?

    /// Forget everything when someone else signs in on this phone, or the same username on
    /// another luach.
    func bind(_ member: Member?, server: URL? = nil) {
        let key = member.map { "\(server?.absoluteString ?? "")#\($0.id)" }
        guard key != owner else { return }
        forget()
        owner = key
    }

    /// Nothing kept: signed out, or pointed at another luach.
    func forget() {
        owner = nil
        household = nil
        people = []
        notifyEmails = []
        basicsLoaded = false
        months = [:]
        monthErrors = [:]
        upcoming = nil
        upcomingFrom = ""
        upcomingError = nil
        fresh = []
        version += 1
    }

    func invalidate() {
        fresh = []
        version += 1
    }

    /// The household, the family and the member's own inboxes. A part that will not
    /// load is not worth an error on the agenda: events keep their calendar's colour.
    func loadBasics(_ api: API, force: Bool = false) async {
        if basicsLoaded && !force { return }
        let whose = owner
        async let household = try? api.agendaHousehold()
        async let people = try? api.agendaFamily()
        async let notify = try? api.agendaNotifyEmails()
        let (h, p, n) = await (household, people, notify)
        // Signed out, or someone else signed in, while it loaded: not theirs to see.
        guard owner == whose else { return }
        if let h { self.household = h }
        if let p { self.people = p }
        if let n { self.notifyEmails = n }
        basicsLoaded = h != nil
    }

    func loadMonth(_ ym: String, clock: AgendaClock, api: API, force: Bool = false) async {
        if fresh.contains(ym) && !force { return }
        let grid = AgendaClock.monthGrid(ym)
        let whose = owner
        do {
            // From the day before the Monday grid's first cell, so a Sunday-first grid (Hebrew) is
            // covered too; `end` is the day after the last cell, an exclusive bound.
            let events = try await api.agendaEvents(from: AgendaClock.addDays(grid.first, -1), to: AgendaClock.addDays(grid.last, 1))
            guard owner == whose else { return }
            months[ym] = clock.sorted(events)
            monthErrors[ym] = nil
            fresh.insert(ym)
        } catch {
            if Self.cancelled(error) || owner != whose { return }
            monthErrors[ym] = error.localizedDescription
        }
    }

    func loadUpcoming(from today: String, days: Int, clock: AgendaClock, api: API) async {
        let whose = owner
        do {
            let events = try await api.agendaEvents(from: today, to: AgendaClock.addDays(today, days))
            guard owner == whose else { return }
            upcoming = clock.sorted(events)
            upcomingFrom = today
            upcomingError = nil
        } catch {
            if Self.cancelled(error) || owner != whose { return }
            upcomingError = error.localizedDescription
        }
    }

    static func cancelled(_ error: Error) -> Bool {
        error is CancellationError || (error as? URLError)?.code == .cancelled
    }

    // MARK: Lookups

    func person(_ key: String) -> AgendaPerson? {
        key.isEmpty ? nil : people.first { $0.key == key }
    }

    func leaders(of ev: AgendaEvent) -> [AgendaPerson] {
        ev.leaderKeys.compactMap(person)
    }

    func calendar(_ id: String) -> AgendaCalendarInfo? {
        id.isEmpty ? nil : household?.available.first { $0.id == id }
    }

    /// The calendars the household uses, default first.
    var enabledCalendars: [AgendaCalendarInfo] {
        (household?.available ?? []).filter(\.enabled).sorted {
            $0.isDefault != $1.isDefault ? $0.isDefault : $0.name.localizedCompare($1.name) == .orderedAscending
        }
    }

    /// An event wears its leader's colour; otherwise its calendar's; otherwise the accent.
    func color(_ ev: AgendaEvent) -> Color {
        AgendaPalette.color(person(ev.leader)?.hex ?? "")
            ?? AgendaPalette.color(calendar(ev.calendarId)?.color ?? "")
            ?? .accentColor
    }
}
