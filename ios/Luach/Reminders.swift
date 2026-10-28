import Foundation
import Observation
import UserNotifications

/// The member's reminders as notifications on this iPhone. luach pushes reminders to browsers
/// (Web Push) and mails them when asked; the phone has no push from luach, so the app works out
/// the same reminders itself from the member's settings (`/api/reminders`) and the calendar's
/// next two weeks, and hands them to iOS to show at their time. They are as fresh as the last
/// time the app looked: at launch, coming forward, after any change made here, and when iOS
/// lets it refresh in the background.
@Observable
final class LocalReminders {
    /// What iOS lets luach show. `.notDetermined` until the member is asked.
    private(set) var permission: UNAuthorizationStatus = .notDetermined
    /// How many are waiting to be shown.
    private(set) var scheduled = 0
    /// Why the last refresh did not finish, in the server's words; nil when it did.
    private(set) var problem: String?

    @ObservationIgnored let center: NoticeCenter
    @ObservationIgnored var now: () -> Date = { .now }
    /// Each refresh's number: one that started earlier and finishes later does not win.
    @ObservationIgnored private var generation = 0

    /// Every notification the app schedules has an identifier starting with this.
    static let prefix = "luach."
    /// How many days of the calendar are read ahead (the evening and weekly lists need the days
    /// after the one they are sent on).
    static let daysAhead = 16

    init(center: NoticeCenter = SystemNoticeCenter()) {
        self.center = center
    }

    var allowed: Bool {
        [.authorized, .provisional, .ephemeral].contains(permission)
    }

    func readPermission() async {
        permission = await center.authorization()
    }

    /// Asks iOS once whether luach may show notifications (and the Approvals count on its icon):
    /// when the member turns a reminder on, not at first launch. True when allowed.
    @discardableResult
    func requestPermission() async -> Bool {
        if permission == .notDetermined {
            _ = try? await center.requestAuthorization()
        }
        await readPermission()
        return allowed
    }

    /// Works out the member's reminders again and replaces what iOS holds. Nothing is scheduled
    /// without permission or a member; everything of luach's is removed then.
    func refresh(api: API, member: Member?) async {
        generation += 1
        let mine = generation
        await readPermission()
        guard let member, allowed else {
            await clear()
            return
        }
        let clock = AgendaClock.of(member)
        do {
            let settings = try await HouseholdArea.Client(api: api).reminders()
            var events: [AgendaEvent] = []
            if ReminderPlan.anyOn(settings) {
                let today = clock.day(of: now())
                events = try await api.agendaEvents(from: today, to: AgendaClock.addDays(today, Self.daysAhead))
            }
            guard mine == generation else { return }
            let plan = ReminderPlan.make(settings: settings, events: events, now: now(), clock: clock, days: Self.daysAhead)
            await apply(plan)
            problem = nil
        } catch {
            if AgendaData.cancelled(error) || mine != generation { return }
            // What is already scheduled stays: an old reminder beats none.
            problem = error.localizedDescription
        }
    }

    /// Replaces luach's pending notifications with `plan`.
    func apply(_ plan: [PlannedReminder]) async {
        let keep = Set(plan.map(\.id))
        let stale = await center.pendingIdentifiers().filter { $0.hasPrefix(Self.prefix) && !keep.contains($0) }
        if !stale.isEmpty { center.removePending(stale) }
        let at = now()
        for reminder in plan {
            // The same identifier replaces what iOS holds, so a moved event moves its reminder.
            try? await center.add(reminder.request(from: at))
        }
        scheduled = plan.count
    }

    /// Everything of luach's gone from this phone: signed out, or another luach.
    func clear() async {
        generation += 1
        let mine = await center.pendingIdentifiers().filter { $0.hasPrefix(Self.prefix) }
        if !mine.isEmpty { center.removePending(mine) }
        center.removeDelivered(prefix: Self.prefix)
        scheduled = 0
        await center.setBadge(0)
    }

    /// The Approvals count on the app's icon, when iOS allows it.
    func badge(_ count: Int) async {
        guard allowed else { return }
        await center.setBadge(count)
    }
}

/// One reminder the phone will show.
struct PlannedReminder: Equatable {
    enum Kind: String { case event, evening, weekly }

    let id: String
    let kind: Kind
    let fire: Date
    let title: String
    let body: String

    func request(from now: Date) -> UNNotificationRequest {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        content.threadIdentifier = LocalReminders.prefix + kind.rawValue
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: max(1, fire.timeIntervalSince(now)), repeats: false)
        return UNNotificationRequest(identifier: id, content: content, trigger: trigger)
    }
}

/// The server's reminder rules (`luach/reminders.py`), worked out ahead on the phone: a nudge
/// `lead_minutes` before each timed event; at `evening_hour`, tomorrow's list when it has
/// anything; on `weekly_day` at `weekly_hour`, the seven days that follow. In the member's zone.
enum ReminderPlan {
    /// iOS keeps at most 64 pending notifications per app; the nearest are the ones kept.
    static let limit = 64

    static func anyOn(_ s: HouseholdArea.ReminderSettings) -> Bool {
        s.leadMinutes > 0 || s.eveningHour >= 0 || s.weeklyDay >= 0
    }

    static func make(
        settings s: HouseholdArea.ReminderSettings, events: [AgendaEvent], now: Date, clock: AgendaClock, days: Int
    ) -> [PlannedReminder] {
        // Busy time from a member's feed is only "busy": the server reminds of none of it.
        let events = events.filter { !$0.id.hasPrefix("busy-") }
        let today = clock.day(of: now)
        // The calendar was read up to this day (exclusive); a list needing later days waits.
        let known = AgendaClock.addDays(today, days)
        var out: [PlannedReminder] = []

        if s.leadMinutes > 0 {
            for ev in events where !ev.isAllDay {
                guard let start = clock.instant(ev.start) else { continue }
                let fire = start.addingTimeInterval(-Double(s.leadMinutes) * 60)
                guard fire > now else { continue }
                let where_ = ev.location.trimmingCharacters(in: .whitespaces)
                out.append(PlannedReminder(
                    id: LocalReminders.prefix + "event.\(ev.id).\(ev.start)",
                    kind: .event,
                    fire: fire,
                    title: ev.title.isEmpty ? String(localized: "Something on the calendar") : ev.title,
                    body: clock.dateTime(start) + (where_.isEmpty ? "" : " · " + where_)
                ))
            }
        }

        for offset in 0..<days {
            let day = AgendaClock.addDays(today, offset)
            if s.eveningHour >= 0, AgendaClock.addDays(day, 1) < known,
               let fire = clock.at(day, hour: s.eveningHour), fire > now {
                let tomorrow = on([AgendaClock.addDays(day, 1)], events, clock)
                if !tomorrow.isEmpty {
                    out.append(PlannedReminder(
                        id: LocalReminders.prefix + "evening.\(day)",
                        kind: .evening,
                        fire: fire,
                        title: String(localized: "Tomorrow: \(tomorrow.count) things"),
                        body: tomorrow.prefix(10).map { line($0, clock, withDay: false) }.joined(separator: "; ")
                    ))
                }
            }
            if s.weeklyDay >= 0, AgendaClock.weekdayMon(day) == s.weeklyDay, AgendaClock.addDays(day, 7) < known,
               let fire = clock.at(day, hour: s.weeklyHour), fire > now {
                let week = on((1...7).map { AgendaClock.addDays(day, $0) }, events, clock)
                out.append(PlannedReminder(
                    id: LocalReminders.prefix + "weekly.\(day)",
                    kind: .weekly,
                    fire: fire,
                    title: String(localized: "The week ahead: \(week.count) things"),
                    body: week.isEmpty
                        ? String(localized: "Nothing on the calendar yet.")
                        : week.prefix(25).map { line($0, clock, withDay: true) }.joined(separator: "; ")
                ))
            }
        }
        return Array(out.sorted { $0.fire != $1.fire ? $0.fire < $1.fire : $0.id < $1.id }.prefix(limit))
    }

    /// The events on any of `days` (member's `YYYY-MM-DD`, consecutive), each once, all-day
    /// first, then by time.
    static func on(_ days: [String], _ events: [AgendaEvent], _ clock: AgendaClock) -> [AgendaEvent] {
        guard let first = days.first, let last = days.last else { return [] }
        return clock.sorted(events.filter { !clock.days($0, from: first, to: last).isEmpty })
    }

    /// "07:10 · Breakfast", "All day · Trip", or with the day for the week ahead.
    static func line(_ ev: AgendaEvent, _ clock: AgendaClock, withDay: Bool) -> String {
        let title = ev.title.isEmpty ? String(localized: "(untitled)") : ev.title
        if ev.isAllDay {
            let day = String(ev.start.prefix(10))
            let stamp = withDay ? clock.dateShort(day) : String(localized: "All day")
            return "\(stamp) · \(title)"
        }
        guard let start = clock.instant(ev.start) else { return title }
        return "\(withDay ? clock.dateTime(start) : clock.time(start)) · \(title)"
    }
}

// MARK: - The notification center

/// What luach asks of iOS's notification center; tests hand in their own.
protocol NoticeCenter: AnyObject {
    func authorization() async -> UNAuthorizationStatus
    func requestAuthorization() async throws -> Bool
    func pendingIdentifiers() async -> [String]
    func add(_ request: UNNotificationRequest) async throws
    func removePending(_ identifiers: [String])
    func removeDelivered(prefix: String)
    func setBadge(_ count: Int) async
}

final class SystemNoticeCenter: NoticeCenter {
    private var center: UNUserNotificationCenter { .current() }

    func authorization() async -> UNAuthorizationStatus {
        await center.notificationSettings().authorizationStatus
    }

    func requestAuthorization() async throws -> Bool {
        try await center.requestAuthorization(options: [.alert, .sound, .badge])
    }

    func pendingIdentifiers() async -> [String] {
        await center.pendingNotificationRequests().map(\.identifier)
    }

    func add(_ request: UNNotificationRequest) async throws {
        try await center.add(request)
    }

    func removePending(_ identifiers: [String]) {
        center.removePendingNotificationRequests(withIdentifiers: identifiers)
    }

    func removeDelivered(prefix: String) {
        Task {
            let shown = await center.deliveredNotifications().map(\.request.identifier).filter { $0.hasPrefix(prefix) }
            center.removeDeliveredNotifications(withIdentifiers: shown)
        }
    }

    func setBadge(_ count: Int) async {
        try? await center.setBadgeCount(count)
    }
}

extension AgendaClock {
    /// `hour`:00 on `day` in the member's zone.
    func at(_ day: String, hour: Int) -> Date? {
        date(fromInput: "\(day)T\(String(format: "%02d", hour)):00")
    }
}
