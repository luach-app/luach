import Foundation
import Testing
@testable import Luach

/// The editor's form: how it starts, how it changes, and the body it sends.
@Suite(.timeLimit(.minutes(1)))
struct EventFormTests {
    let ny = AgendaFixtures.newYork
    typealias F = AgendaFixtures

    private func instant(_ s: String) -> Date { ny.instant(s)! }

    // MARK: Starting

    @Test func aNewEventIsAnHourFromTheTopOfTheNextHour() {
        let f = EventForm.new(on: "2030-01-15", clock: ny)
        #expect(f.start == ny.nextHour(on: "2030-01-15") && f.end == f.start.addingTimeInterval(3600))
        #expect(f.startDay == ny.date(ofDay: "2030-01-15") && f.endDay == f.startDay)
        #expect(f.title.isEmpty && !f.allDay && f.repeats == .none && f.leaders.isEmpty && f.attendees.isEmpty)
    }

    @Test func anEventOpensWithWhatItHas() throws {
        let f = EventForm(try F.event(F.timed), clock: ny)
        #expect(f.title == "Dentist" && !f.allDay && f.location == "Clinic")
        #expect(f.start == instant("2026-11-03T15:00:00-05:00") && f.end == instant("2026-11-03T15:45:00-05:00"))
        #expect(f.startDay == ny.date(ofDay: "2026-11-03") && f.endDay == f.startDay)
        #expect(f.description == "See the page (https://example.com/x)", "notes are edited as text")
        #expect(f.repeats == .weekly && f.keptRule == "RRULE:FREQ=WEEKLY;BYDAY=TU")
        #expect(f.leaders == ["ruby", "lily"] && f.calendarId == "fake" && f.attendees.isEmpty)
    }

    @Test func anAllDayEventOpensOnItsDays() throws {
        let f = EventForm(try F.event(F.allDay), clock: ny)
        #expect(f.allDay)
        #expect(f.startDay == ny.date(ofDay: "2026-11-05") && f.endDay == ny.date(ofDay: "2026-11-06"), "the last day, inclusive")
        #expect(f.start == ny.nextHour(on: "2026-11-05"), "a time ready should it stop being all day")
        let noEnd = EventForm(try F.event("x", "2026-11-05", "", allDay: true), clock: ny)
        #expect(noEnd.endDay == noEnd.startDay)
        let backwards = EventForm(try F.event("x", "2026-11-05", "2026-11-01"), clock: ny)
        #expect(backwards.endDay == backwards.startDay)
    }

    @Test func aRuleTheMenuCannotSayIsKept() throws {
        let ev = try F.event(["id": "x", "start": "2026-11-03T15:00:00-05:00", "end": "2026-11-03T16:00:00-05:00",
                              "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3;BYDAY=TU", "EXDATE:20261110T150000"]])
        let f = EventForm(ev, clock: ny)
        #expect(f.repeats == .custom && f.keptRule == "RRULE:FREQ=WEEKLY;COUNT=3;BYDAY=TU EXDATE:20261110T150000")
    }

    @Test func anUnreadableTimeStartsAtTheNextHour() throws {
        let f = EventForm(try F.event("x", "soon", "later"), clock: ny)
        #expect(f.start == ny.nextHour() && f.end == f.start.addingTimeInterval(3600))
    }

    // MARK: Changing

    @Test func movingTheStartKeepsTheLength() {
        var f = EventForm.new(on: "2030-01-15", clock: ny)
        f.end = f.start.addingTimeInterval(45 * 60)
        let later = f.start.addingTimeInterval(2 * 3600)
        f.moveStart(to: later)
        #expect(f.start == later && f.end == later.addingTimeInterval(45 * 60))
        // An end not after the start: an hour.
        f.end = f.start
        f.moveStart(to: later.addingTimeInterval(600))
        #expect(f.end == f.start.addingTimeInterval(3600))
    }

    @Test func anAllDayStartPastTheEndTakesTheEndAlong() {
        var f = EventForm.new(on: "2030-01-15", clock: ny)
        f.endDay = ny.date(ofDay: "2030-01-17")
        f.moveStartDay(to: ny.date(ofDay: "2030-01-16"))
        #expect(f.endDay == ny.date(ofDay: "2030-01-17"), "still after: left alone")
        f.moveStartDay(to: ny.date(ofDay: "2030-01-20"))
        #expect(f.startDay == ny.date(ofDay: "2030-01-20") && f.endDay == f.startDay)
    }

    @Test func leadersStayInTheFamilysOrder() {
        var f = EventForm()
        let family = ["robin", "ruby", "lily"]
        f.toggleLeader("lily", family: family)
        f.toggleLeader("robin", family: family)
        #expect(f.leaders == ["robin", "lily"])
        f.toggleLeader("robin", family: family)
        #expect(f.leaders == ["lily"])
        f.toggleLeader("ghost", family: family)
        #expect(f.leaders == ["lily"], "someone no longer in the family is not kept")
    }

    @Test func anAddressIsInvitedOnce() {
        var f = EventForm()
        f.invite("ana@example.com")
        f.invite("sam@example.com")
        f.invite("ana@example.com")
        #expect(f.attendees == ["ana@example.com", "sam@example.com"])
    }

    @Test func aNewEventTakesTheHouseholdsCalendarAndInvitees() throws {
        let household = try JSONDecoder.snake.decode(AgendaHousehold.self,
                                                     from: JSONSerialization.data(withJSONObject: F.household))
        var f = EventForm()
        f.seed(household, writable: household.available.filter(\.writable), notify: ["work@example.com", "grandma@example.com"])
        #expect(f.calendarId == "fake")
        #expect(f.attendees == ["grandma@example.com", "work@example.com"], "each address once")

        let noDefault = try JSONDecoder.snake.decode(AgendaHousehold.self, from: Data(#"{"default_calendar":""}"#.utf8))
        f.seed(noDefault, writable: household.available.filter(\.writable), notify: [])
        #expect(f.calendarId == "family@example.com" && f.attendees.isEmpty)
        f.seed(noDefault, writable: [], notify: [])
        #expect(f.calendarId.isEmpty)
    }

    @Test func theBoardsLeaderIsAKeyOrACommaList() {
        #expect(EventForm.leaders(from: nil) == [])
        #expect(EventForm.leaders(from: "") == [])
        #expect(EventForm.leaders(from: "ruby") == ["ruby"])
        #expect(EventForm.leaders(from: " ruby , lily,, ") == ["ruby", "lily"])
    }

    @Test func aTypedAddressIsCleanedOrRefused() {
        #expect(EventForm.address("") == "")
        #expect(EventForm.address("  ,; ") == "")
        #expect(EventForm.address(" Ana@Example.com,") == "ana@example.com")
        #expect(EventForm.address("sam@example.com;") == "sam@example.com")
        #expect(EventForm.address("not an address") == nil)
        #expect(EventForm.address("ana@example") == nil)
    }

    @Test func aDayFromTheBoardIsReadOnThePhonesCalendar() {
        let c = DateComponents(calendar: .current, year: 2026, month: 11, day: 3, hour: 23, minute: 59)
        #expect(EventEditor.dayOnPhone(c.date!) == "2026-11-03")
    }

    // MARK: The body

    @Test func aNewTimedEventIsSentAsWallClocks() throws {
        var f = EventForm()
        f.title = "  Dentist \n"
        f.start = instant("2026-11-03T15:00:00-05:00")
        f.end = instant("2026-11-03T15:45:00-05:00")
        f.location = " Clinic "
        f.description = "\nBring the forms.\n"
        let body = try f.input(clock: ny, isEdit: false, seeded: false, original: nil).get()
        #expect(body.title == "Dentist" && body.start == "2026-11-03T15:00" && body.end == "2026-11-03T15:45")
        #expect(body.location == "Clinic" && body.description == "Bring the forms.")
        #expect(body.recurrence == nil, "no repeat chosen: none sent")
        #expect(body.attendees == nil, "never seeded: the server's default invitees")
        #expect(body.calendarId == nil && body.leader == nil)
    }

    @Test func aSeededNewEventSendsItsListAndCalendar() throws {
        var f = EventForm.new(on: "2030-01-15", clock: ny)
        f.title = "x"
        f.calendarId = "fake"
        f.attendees = []
        f.leaders = ["ruby", "lily"]
        let body = try f.input(clock: ny, isEdit: false, seeded: true, original: nil).get()
        #expect(body.attendees == [], "an emptied list is nobody")
        #expect(body.calendarId == "fake" && body.leader == "ruby,lily")
    }

    @Test func anAllDayEventIsSentAsDaysWithAnExclusiveEnd() throws {
        var f = EventForm.new(on: "2026-11-05", clock: ny)
        f.title = "Trip"
        f.allDay = true
        f.endDay = ny.date(ofDay: "2026-11-06")
        f.repeats = .weekly
        let body = try f.input(clock: ny, isEdit: false, seeded: false, original: nil).get()
        #expect(body.start == "2026-11-05" && body.end == "2026-11-07")
        #expect(body.recurrence == "weekly", "the word: the server puts it on the day it starts")
        // A last day before the first is the first.
        f.endDay = ny.date(ofDay: "2026-11-01")
        #expect(try f.input(clock: ny, isEdit: false, seeded: false, original: nil).get().end == "2026-11-06")
    }

    @Test func aRepeatIsSentAsTheMenusWord() throws {
        // The server anchors it on the event's own day: 23:30 on Tuesday in New York is
        // Wednesday in UTC, and the day is not the phone's to work out.
        var f = EventForm()
        f.title = "Late"
        f.start = instant("2026-11-03T23:30:00-05:00")
        f.end = f.start.addingTimeInterval(1800)
        f.repeats = .biweekly
        #expect(try f.input(clock: ny, isEdit: false, seeded: false, original: nil).get().recurrence == "biweekly")
        f.repeats = .custom
        #expect(try f.input(clock: ny, isEdit: true, seeded: false, original: nil).get().recurrence == nil,
                "a kept rule is not sent")
    }

    @Test func anOccurrenceOpensOnItsSeriesRuleAndSendsItOnlyWhenChanged() throws {
        // An occurrence used to open as "Does not repeat" and send "", which stopped the series.
        let original = try F.event(F.occurrence)
        var f = EventForm(original, clock: ny)
        #expect(f.repeats == .weekly && !f.repeatsChanged)
        f.title = "Dentist, early"
        #expect(try f.input(clock: ny, isEdit: true, seeded: false, original: original).get().recurrence == nil)
        f.repeats = .none
        #expect(f.repeatsChanged)
        #expect(try f.input(clock: ny, isEdit: true, seeded: false, original: original).get().recurrence == "",
                "stopping it is said as an empty rule")
        f.repeats = .weekly
        #expect(!f.repeatsChanged, "chosen back: no change")
    }

    @Test func itWillNotSaveWithoutATitleOrWithTheEndFirst() {
        var f = EventForm.new(on: "2030-01-15", clock: ny)
        f.title = "   "
        #expect(throws: EventForm.Problem.noTitle) { try f.input(clock: ny, isEdit: false, seeded: false, original: nil).get() }
        f.title = "x"
        f.end = f.start.addingTimeInterval(-60)
        #expect(throws: EventForm.Problem.endBeforeStart) { try f.input(clock: ny, isEdit: false, seeded: false, original: nil).get() }
        // All day, the times do not matter.
        f.allDay = true
        #expect((try? f.input(clock: ny, isEdit: false, seeded: false, original: nil).get()) != nil)
        #expect(EventForm.Problem.noTitle.message == "Give it a title.")
        #expect(EventForm.Problem.endBeforeStart.message == "The end is before the start.")
    }

    @Test func anEditSendsItsInviteesAndOnlyAChangeOfHands() throws {
        let original = try F.event(F.timed)
        var f = EventForm(original, clock: ny)
        var body = try f.input(clock: ny, isEdit: true, seeded: false, original: original).get()
        #expect(body.attendees == [] && body.calendarId == nil, "an edit names no calendar")
        #expect(body.leader == nil, "the same people: not sent")
        #expect(body.recurrence == nil, "the repeat it had: not sent")
        f.toggleLeader("lily", family: ["robin", "ruby", "lily"])
        body = try f.input(clock: ny, isEdit: true, seeded: false, original: original).get()
        #expect(body.leader == "ruby")
        f.leaders = []
        body = try f.input(clock: ny, isEdit: true, seeded: false, original: original).get()
        #expect(body.leader == "", "nobody's now")
    }
}
