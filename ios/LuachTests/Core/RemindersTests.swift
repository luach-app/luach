import Foundation
import Testing
import UserNotifications
@testable import Luach

/// A notification center that keeps what it is handed, and answers as the test says.
final class FakeNoticeCenter: NoticeCenter {
    var status: UNAuthorizationStatus
    var grants: Bool
    private(set) var asked = 0
    private(set) var pending: [String: UNNotificationRequest] = [:]
    private(set) var badges: [Int] = []
    private(set) var deliveredCleared: [String] = []

    init(status: UNAuthorizationStatus = .authorized, grants: Bool = true) {
        self.status = status
        self.grants = grants
    }

    func authorization() async -> UNAuthorizationStatus { status }

    func requestAuthorization() async throws -> Bool {
        asked += 1
        status = grants ? .authorized : .denied
        return grants
    }

    func pendingIdentifiers() async -> [String] { Array(pending.keys) }
    func add(_ request: UNNotificationRequest) async throws { pending[request.identifier] = request }
    func removePending(_ identifiers: [String]) { identifiers.forEach { pending[$0] = nil } }
    func removeDelivered(prefix: String) { deliveredCleared.append(prefix) }
    func setBadge(_ count: Int) async { badges.append(count) }

    /// When each pending one fires, seconds from `now`, by identifier.
    func fireTimes() -> [String: TimeInterval] {
        pending.compactMapValues { ($0.trigger as? UNTimeIntervalNotificationTrigger)?.timeInterval }
    }
}

/// The server's reminder rules, worked out on the phone (ReminderPlan), in the member's zone.
@MainActor
struct ReminderPlanTests {
    /// New York, Wednesday 4 November 2026, 09:00.
    let clock = AgendaClock(tz: TimeZone(identifier: "America/New_York")!, locale: Locale(identifier: "en"))
    let now = ISO8601DateFormatter().date(from: "2026-11-04T14:00:00Z")!

    static func event(_ id: String, _ start: String, _ end: String = "", title: String = "Dentist",
                      location: String = "", allDay: Bool = false) -> AgendaEvent {
        let json: [String: Any] = ["id": id, "title": title, "start": start, "end": end, "all_day": allDay, "location": location]
        let data = try! JSONSerialization.data(withJSONObject: json)
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return try! d.decode(AgendaEvent.self, from: data)
    }

    private func settings(lead: Int = 0, evening: Int = -1, weeklyDay: Int = -1, weeklyHour: Int = 18) -> HouseholdArea.ReminderSettings {
        .init(leadMinutes: lead, eveningHour: evening, weeklyDay: weeklyDay, weeklyHour: weeklyHour, byEmail: false)
    }

    @Test func nothingWhenEverythingIsOff() {
        let events = [Self.event("a", "2026-11-04T15:00:00-05:00")]
        #expect(ReminderPlan.make(settings: settings(), events: events, now: now, clock: clock, days: 16).isEmpty)
        #expect(!ReminderPlan.anyOn(settings()))
        #expect(ReminderPlan.anyOn(settings(lead: 15)) && ReminderPlan.anyOn(settings(evening: 20)) && ReminderPlan.anyOn(settings(weeklyDay: 0)))
    }

    @Test func aNudgeBeforeEachTimedEvent() throws {
        let events = [
            Self.event("dentist", "2026-11-04T15:00:00-05:00", "2026-11-04T15:45:00-05:00", location: "Clinic"),
            Self.event("untitled", "2026-11-05T08:00:00-05:00", title: ""),
            Self.event("trip", "2026-11-05", "2026-11-07", title: "Trip", allDay: true),
            Self.event("busy-abc123", "2026-11-04T16:00:00-05:00", title: "Busy"),
            Self.event("gone", "2026-11-04T09:10:00-05:00"), // its nudge (08:40) has passed
        ]
        let plan = ReminderPlan.make(settings: settings(lead: 30), events: events, now: now, clock: clock, days: 16)
        #expect(plan.map(\.kind) == [.event, .event], "not the all-day trip, the busy time or the past one")
        let first = try #require(plan.first)
        #expect(first.id == "luach.event.dentist.2026-11-04T15:00:00-05:00")
        #expect(first.title == "Dentist")
        #expect(first.body.contains("Clinic"), "\(first.body)")
        #expect(first.body.contains("3:00") || first.body.contains("15:00"), "\(first.body)")
        #expect(first.fire == ISO8601DateFormatter().date(from: "2026-11-04T19:30:00Z"))
        #expect(plan[1].title == "Something on the calendar")
    }

    @Test func theEveningListOfTomorrow() throws {
        let events = [
            Self.event("school", "2026-11-05T08:30:00-05:00", title: "School trip"),
            Self.event("trip", "2026-11-05", "2026-11-06", title: "Trip", allDay: true),
            Self.event("piano", "2026-11-07T16:00:00-05:00", title: "Piano"),
        ]
        let plan = ReminderPlan.make(settings: settings(evening: 20), events: events, now: now, clock: clock, days: 4)
        // Wed evening lists Thu (two things); Thu evening has nothing for Fri, so no list;
        // Fri evening lists Sat's piano; Sat evening would need Sun, which was not read.
        #expect(plan.map(\.id) == ["luach.evening.2026-11-04", "luach.evening.2026-11-06"])
        let wed = try #require(plan.first)
        #expect(wed.title == "Tomorrow: 2 things")
        #expect(wed.body.hasPrefix("All day · Trip; ") && wed.body.contains("School trip"), "\(wed.body)")
        #expect(wed.fire == clock.at("2026-11-04", hour: 20))
        #expect(plan[1].title == "Tomorrow: 1 thing")
    }

    @Test func tonightsListOnlyWhileItIsStillToCome() {
        let events = [Self.event("school", "2026-11-05T08:30:00-05:00")]
        let late = clock.at("2026-11-04", hour: 21)!
        let plan = ReminderPlan.make(settings: settings(evening: 20), events: events, now: late, clock: clock, days: 3)
        #expect(plan.isEmpty, "20:00 has passed today")
    }

    @Test func theWeekAhead() throws {
        // Fridays (4) at 18:00: 6 Nov lists Sat 7 – Fri 13.
        let events = [
            Self.event("piano", "2026-11-07T16:00:00-05:00", title: "Piano"),
            Self.event("late", "2026-11-14T10:00:00-05:00", title: "Too late"),
        ]
        // The week of the 13th needs the 20th, which 16 days from the 4th do not reach.
        let short = ReminderPlan.make(settings: settings(weeklyDay: 4, weeklyHour: 18), events: events, now: now, clock: clock, days: 16)
        #expect(short.map(\.id) == ["luach.weekly.2026-11-06"])
        let plan = ReminderPlan.make(settings: settings(weeklyDay: 4, weeklyHour: 18), events: events, now: now, clock: clock, days: 17)
        #expect(plan.map(\.id) == ["luach.weekly.2026-11-06", "luach.weekly.2026-11-13"])
        let week = try #require(plan.first)
        #expect(week.title == "The week ahead: 1 thing")
        #expect(week.body.contains("Piano") && !week.body.contains("Too late"), "\(week.body)")
        #expect(week.fire == clock.at("2026-11-06", hour: 18))
        #expect(plan[1].body.contains("Too late"))
    }

    @Test func anEmptyWeekIsStillSaid() {
        let plan = ReminderPlan.make(settings: settings(weeklyDay: 4), events: [], now: now, clock: clock, days: 10)
        #expect(plan.map(\.body) == ["Nothing on the calendar yet."], "as the server mails it")
        #expect(plan.first?.title == "The week ahead: 0 things")
    }

    @Test func atMostSixtyFourTheNearestFirst() {
        var events: [AgendaEvent] = []
        for day in 5...14 {
            for hour in 8...15 {
                events.append(Self.event("e\(day)-\(hour)", String(format: "2026-11-%02dT%02d:00:00-05:00", day, hour)))
            }
        }
        let plan = ReminderPlan.make(settings: settings(lead: 15, evening: 20), events: events, now: now, clock: clock, days: 16)
        #expect(plan.count == ReminderPlan.limit)
        #expect(plan == plan.sorted { $0.fire < $1.fire })
        #expect(plan.first?.id == "luach.evening.2026-11-04", "tonight's list comes first")
        #expect(!plan.contains { $0.id.hasPrefix("luach.event.e14") }, "the furthest are the ones left out")
    }

    @Test func linesSayTheDayForTheWeek() {
        let ev = Self.event("p", "2026-11-07T16:00:00-05:00", title: "Piano")
        #expect(ReminderPlan.line(ev, clock, withDay: false).hasSuffix("· Piano"))
        #expect(ReminderPlan.line(ev, clock, withDay: true).contains("Sat"))
        let trip = Self.event("t", "2026-11-07", "2026-11-08", title: "", allDay: true)
        #expect(ReminderPlan.line(trip, clock, withDay: false) == "All day · (untitled)")
        #expect(ReminderPlan.line(trip, clock, withDay: true).hasPrefix("Sat"))
        let broken = Self.event("x", "soon", title: "Odd")
        #expect(ReminderPlan.line(broken, clock, withDay: false) == "Odd")
    }

    @Test func aRequestFiresAtItsTime() throws {
        let r = PlannedReminder(id: "luach.event.x", kind: .event, fire: now.addingTimeInterval(600), title: "T", body: "B")
        let request = r.request(from: now)
        #expect(request.identifier == "luach.event.x" && request.content.title == "T" && request.content.body == "B")
        #expect(request.content.threadIdentifier == "luach.event")
        let trigger = try #require(request.trigger as? UNTimeIntervalNotificationTrigger)
        #expect(trigger.timeInterval == 600 && !trigger.repeats)
        let due = PlannedReminder(id: "luach.event.y", kind: .event, fire: now, title: "T", body: "B").request(from: now)
        #expect((due.trigger as? UNTimeIntervalNotificationTrigger)?.timeInterval == 1, "never zero, which iOS refuses")
    }
}

/// LocalReminders against a stub luach and a fake notification center.
@MainActor
@Suite(.serialized)
struct LocalRemindersTests {
    let server = StubServer()
    let member = Member(id: 1, username: "robin", displayName: "Robin", email: nil, timezone: "America/New_York",
                        language: "en", isOwner: true)
    let now = ISO8601DateFormatter().date(from: "2026-11-04T14:00:00Z")!

    private func reminders(_ center: FakeNoticeCenter) -> LocalReminders {
        let r = LocalReminders(center: center)
        r.now = { now }
        return r
    }

    private func serve(lead: Int = 30, evening: Int = -1) {
        server.on("GET", "/api/reminders", json: [
            "lead_minutes": lead, "evening_hour": evening, "weekly_day": -1, "weekly_hour": 18, "by_email": false,
        ])
        server.on("GET", "/api/calendar/events", json: ["events": [
            ["id": "dentist", "title": "Dentist", "start": "2026-11-04T15:00:00-05:00", "end": "2026-11-04T15:45:00-05:00"],
            ["id": "piano", "title": "Piano", "start": "2026-11-05T16:00:00-05:00", "end": "2026-11-05T17:00:00-05:00"],
        ]])
    }

    @Test func scheduledFromTheSettingsAndTheCalendar() async throws {
        serve()
        let center = FakeNoticeCenter()
        let r = reminders(center)
        await r.refresh(api: server.api, member: member)
        #expect(r.scheduled == 2 && r.problem == nil)
        #expect(Set(center.pending.keys) == ["luach.event.dentist.2026-11-04T15:00:00-05:00", "luach.event.piano.2026-11-05T16:00:00-05:00"])
        #expect(center.fireTimes()["luach.event.dentist.2026-11-04T15:00:00-05:00"] == 5.5 * 3600)
        let asked = try #require(server.requests("GET", "/api/calendar/events").first)
        #expect(asked.query == ["start": "2026-11-04", "end": "2026-11-20"], "the next 16 days, in the member's zone")
    }

    @Test func whatNoLongerAppliesIsTakenAway() async {
        serve()
        let center = FakeNoticeCenter()
        try? await center.add(UNNotificationRequest(identifier: "luach.event.moved.x", content: .init(), trigger: nil))
        try? await center.add(UNNotificationRequest(identifier: "someone-else", content: .init(), trigger: nil))
        let r = reminders(center)
        await r.refresh(api: server.api, member: member)
        #expect(center.pending["luach.event.moved.x"] == nil)
        #expect(center.pending["someone-else"] != nil, "only luach's own are touched")
        #expect(center.pending.count == 3)
    }

    @Test func remindersOffMeansNothingIsReadOrShown() async {
        serve(lead: 0)
        let center = FakeNoticeCenter()
        let r = reminders(center)
        await r.refresh(api: server.api, member: member)
        #expect(r.scheduled == 0 && center.pending.isEmpty)
        #expect(server.requests("GET", "/api/calendar/events").isEmpty, "the calendar is not read for nothing")
    }

    @Test func withoutPermissionNothingIsScheduledAndNothingIsAsked() async {
        serve()
        let center = FakeNoticeCenter(status: .notDetermined)
        let r = reminders(center)
        await r.refresh(api: server.api, member: member)
        #expect(center.pending.isEmpty && center.asked == 0, "permission is asked when reminders are turned on, not here")
        #expect(server.requests.isEmpty)
        #expect(!r.allowed && r.permission == .notDetermined)
    }

    @Test func signedOutClearsEverything() async {
        serve()
        let center = FakeNoticeCenter()
        let r = reminders(center)
        await r.refresh(api: server.api, member: member)
        await r.refresh(api: server.api, member: nil)
        #expect(center.pending.isEmpty && r.scheduled == 0)
        #expect(center.badges.last == 0 && center.deliveredCleared == ["luach."])
    }

    @Test func aServerThatDoesNotAnswerKeepsWhatWasScheduled() async {
        serve()
        let center = FakeNoticeCenter()
        let r = reminders(center)
        await r.refresh(api: server.api, member: member)
        server.fail("GET", "/api/calendar/events", status: 502, "the calendar could not be reached")
        await r.refresh(api: server.api, member: member)
        #expect(center.pending.count == 2, "an old reminder beats none")
        #expect(r.problem == "the calendar could not be reached")
    }

    @Test func permissionIsAskedOnceAndRemembered() async {
        let center = FakeNoticeCenter(status: .notDetermined, grants: false)
        let r = reminders(center)
        #expect(await r.requestPermission() == false)
        #expect(await r.requestPermission() == false)
        #expect(center.asked == 1 && r.permission == .denied, "iOS asks only once; after that it is Settings")
        let yes = FakeNoticeCenter(status: .notDetermined)
        #expect(await reminders(yes).requestPermission())
    }

    @Test func theBadgeOnlyWhenAllowed() async {
        let off = FakeNoticeCenter(status: .denied)
        let r = reminders(off)
        await r.readPermission()
        await r.badge(3)
        #expect(off.badges.isEmpty)
        let on = FakeNoticeCenter()
        let r2 = reminders(on)
        await r2.readPermission()
        await r2.badge(3)
        #expect(on.badges == [3])
    }

    @Test func theSystemCenterAnswers() async {
        // The real one, as the app uses it: asked nothing that would show a prompt.
        let system = SystemNoticeCenter()
        _ = await system.authorization()
        let before = await system.pendingIdentifiers()
        let request = UNNotificationRequest(identifier: "luach.test.\(UUID())", content: .init(),
                                            trigger: UNTimeIntervalNotificationTrigger(timeInterval: 3600, repeats: false))
        try? await system.add(request)
        system.removePending([request.identifier])
        system.removeDelivered(prefix: "luach.test.")
        await system.setBadge(0)
        _ = before
    }
}
