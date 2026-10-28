import Foundation
import Testing
@testable import Luach

/// The editing rules behind the Household screens: ticking calendars and the default that
/// follows, the "Always invite" box, the weekly hours, and the menus that keep odd values.
@MainActor
struct HouseholdLogicTests {
    typealias H = HouseholdArea
    typealias F = HouseholdFixtures

    private func calendars(_ json: [String: Any] = F.calendars) throws -> H.Calendars {
        try F.decode(H.Calendars.self, json)
    }

    // MARK: Household form

    @Test func aFreshFormIsWhatWasSavedAndNotDirty() throws {
        let data = try calendars()
        let form = H.HouseholdForm(data)
        #expect(form.enabled == data.calendars && form.defaultCalendar == data.defaultCalendar)
        #expect(form.attendees == ["grandma@example.com"] && form.draft.isEmpty && !form.draftBad)
        #expect(!form.isDirty(against: data))
        #expect(H.HouseholdForm() == H.HouseholdForm(try calendars(["available": [], "calendars": [],
                                                                    "default_calendar": "", "default_attendees": []])))
    }

    @Test func tickingAndUntickingTheSameCalendarIsNotAChange() throws {
        let data = try calendars()
        var form = H.HouseholdForm(data)
        form.toggle("local")
        #expect(form.enabled.last == "local" && form.isDirty(against: data))
        form.toggle("local")
        #expect(!form.isDirty(against: data))
    }

    @Test func untickingTheDefaultMovesItToTheFirstLeft() throws {
        let data = try calendars()
        var form = H.HouseholdForm(data)
        form.toggle("family@group.calendar.google.com")
        #expect(form.defaultCalendar == "ana@example.com")
        // Untick everything: the default stays where it was, and Save will refuse.
        form.toggle("ana@example.com")
        form.toggle("holidays@group.v.calendar.google.com")
        #expect(form.enabled.isEmpty && form.defaultCalendar == "holidays@group.v.calendar.google.com")
        #expect(form.patch == nil)
        // Ticking one back makes it the default.
        form.toggle("local")
        #expect(form.defaultCalendar == "local")
    }

    @Test func withNoDefaultTheFirstTickedBecomesIt() throws {
        let data = try calendars(F.devCalendars)
        var form = H.HouseholdForm(data)
        form.defaultCalendar = ""
        form.toggle("local")
        #expect(form.defaultCalendar == "fake", "the first in the list, which dev already uses")
    }

    @Test func anAddressIsCheckedLowercasedAndAddedOnce() throws {
        let data = try calendars()
        var form = H.HouseholdForm(data)
        form.draft = "   "
        var added = form.commitDraft()
        #expect(!added && !form.draftBad)
        form.draft = "not an address"
        added = form.commitDraft()
        #expect(!added && form.draftBad && form.draft == "not an address")
        #expect(!form.isDirty(against: data))
        form.draftBad = false
        form.draft = "  Ana@Example.com "
        #expect(form.cleanDraft == "ana@example.com" && form.isDirty(against: data), "a whole address counts before Add")
        added = form.commitDraft()
        #expect(added)
        #expect(form.attendees == ["grandma@example.com", "ana@example.com"] && form.draft.isEmpty)
        form.draft = "ANA@example.com"
        added = form.commitDraft()
        #expect(added)
        #expect(form.attendees.count == 2, "no duplicate")
    }

    @Test func thePatchCarriesTheFormAndAnAddressStillInTheBox() throws {
        let data = try calendars()
        var form = H.HouseholdForm(data)
        form.draft = "Uncle@Example.com"
        let p = try #require(form.patch)
        #expect(p.calendars == data.calendars && p.defaultCalendar == data.defaultCalendar)
        #expect(p.defaultAttendees == ["grandma@example.com", "uncle@example.com"])
        form.draft = "grandma@example.com"
        #expect(form.patch?.defaultAttendees == ["grandma@example.com"])
        form.draft = "half@"
        #expect(form.patch?.defaultAttendees == ["grandma@example.com"])
        form.defaultCalendar = ""
        #expect(form.patch?.defaultCalendar == data.calendars[0], "no default: the first calendar")
    }

    @Test func theListShowsEverythingSeenOrTheHouseholdsOwn() throws {
        let data = try calendars()
        #expect(H.listed(data).map(\.id) == data.available.map(\.id))
        let none = try calendars(["available": [], "calendars": ["x"], "default_calendar": "x", "default_attendees": []])
        #expect(H.listed(none).isEmpty)
        #expect(H.name(of: "ana@example.com", in: data) == "Ana")
        #expect(H.name(of: "fake", in: data) == "fake", "an unseen calendar is called by its id")
        let choices = H.defaultChoices(data, enabled: data.calendars)
        #expect(choices.map(\.name) == ["Family", "Ana"], "read-only and unticked calendars are not offered")
        #expect(H.defaultChoices(data, enabled: []).isEmpty)
    }

    // MARK: Weekly hours

    @Test func timesGoBothWays() {
        let d = H.Hours.date("14:05")
        #expect(H.Hours.hhmm(d) == "14:05")
        #expect(Calendar.current.isDateInToday(d))
        #expect(H.Hours.hhmm(H.Hours.date("7")) == "07:00")
        #expect(H.Hours.hhmm(H.Hours.date("")) == "09:00", "nothing readable is nine")
        #expect(H.Hours.hhmm(H.Hours.date("23:59")) == "23:59")
        let day = Date(timeIntervalSince1970: 1_789_585_200)
        #expect(Calendar.current.isDate(H.Hours.date("10:30", on: day), inSameDayAs: day))
    }

    @Test func aDaySwitchedOnGetsNineToFiveOrKeepsItsFirst() {
        #expect(H.Hours.toggled([], on: true) == [["09:00", "17:00"]])
        #expect(H.Hours.toggled([["08:00", "12:00"], ["13:00", "15:00"]], on: true) == [["08:00", "12:00"]])
        #expect(H.Hours.toggled([["08:00", "12:00"]], on: false) == [])
    }

    @Test func aNewWindowStartsWhereTheLastEndsForTwoHours() {
        #expect(H.Hours.adding(to: [["09:00", "12:00"]]) == [["09:00", "12:00"], ["12:00", "14:00"]])
        #expect(H.Hours.adding(to: [["09:00", "12:00"], ["13:00", "15:30"]])?.last == ["15:30", "17:30"])
        #expect(H.Hours.adding(to: []) == [["17:00", "19:00"]])
        #expect(H.Hours.adding(to: [["09:00", "22:30"]])?.last == ["22:30", "23:59"], "cut at the end of the day")
        #expect(H.Hours.adding(to: [["09:00", "23:59"]]) == nil, "no room left: no empty window")
        #expect(H.Hours.adding(to: [["09:00"]])?.last == ["17:00", "19:00"], "a broken window reads as 5pm")
    }

    @Test func removingAWindowLeavesTheOthersInOrder() {
        let w = [["08:00", "10:00"], ["11:00", "12:00"], ["14:00", "16:00"]]
        #expect(H.Hours.removing(w, at: 1) == [["08:00", "10:00"], ["14:00", "16:00"]])
        #expect(H.Hours.removing(w, at: 0).count == 2)
        #expect(H.Hours.removing(w, at: 5) == w)
        #expect(H.Hours.removing([["08:00", "10:00"]], at: 0) == [])
    }

    @Test func aWindowsTimesReadWithNineToFiveForMissingOnes() {
        let w = [["08:15", "10:45"]]
        #expect(H.Hours.time(w, 0, 0) == "08:15" && H.Hours.time(w, 0, 1) == "10:45")
        #expect(H.Hours.time(w, 1, 0) == "09:00" && H.Hours.time(w, 1, 1) == "17:00")
        #expect(H.Hours.time(nil, 0, 0) == "09:00" && H.Hours.time([["08:00"]], 0, 1) == "17:00")
    }

    @Test func movingAStartOrEndChangesOnlyThatOne() {
        let w = [["08:00", "10:00"], ["11:00", "12:00"]]
        #expect(H.Hours.setting(w, 1, 1, to: H.Hours.date("13:30")) == [["08:00", "10:00"], ["11:00", "13:30"]])
        #expect(H.Hours.setting(w, 0, 0, to: H.Hours.date("07:45")) == [["07:45", "10:00"], ["11:00", "12:00"]])
        #expect(H.Hours.setting(w, 2, 0, to: .now) == nil)
        #expect(H.Hours.setting(nil, 0, 0, to: .now) == nil)
        #expect(H.Hours.setting([["08:00"]], 0, 1, to: .now) == nil)
    }

    // MARK: Menus

    @Test func aMenuKeepsAValueItDoesNotOffer() {
        #expect(H.choices([15, 30, 60], keeping: 30) == [15, 30, 60])
        #expect(H.choices([15, 30, 60], keeping: 25) == [15, 25, 30, 60])
        #expect(H.choices([15, 30, 60], keeping: 240) == [15, 30, 60, 240])
        #expect(H.offMenu(45, known: [0, 15, 30]) == 45)
        #expect(H.offMenu(15, known: [0, 15, 30]) == nil)
        #expect(H.offMenu(nil, known: [0]) == nil)
    }

    // MARK: Where a booking lands

    @Test func bookingsLandOnTheHouseholdsWritableCalendars() throws {
        let data = try calendars()
        let cals = H.bookingCalendars(data)
        #expect(cals.map(\.name) == ["Family", "Ana"])
        #expect(H.bookingCalendars(nil).isEmpty)
        #expect(H.defaultCalendarLabel(data, cals) == String(localized: "The household default (Family)"))
        #expect(H.defaultCalendarLabel(try calendars(F.devCalendars), []) == String(localized: "The household default (fake)"))
        #expect(H.defaultCalendarLabel(nil, cals) == String(localized: "The household default"))
        let none = try calendars(["available": [], "calendars": [], "default_calendar": "", "default_attendees": []])
        #expect(H.defaultCalendarLabel(none, []) == String(localized: "The household default"))
    }

    @Test func aBookingIsShownInTheMembersZone() throws {
        let rows = try F.decode(H.BookingRows.self, F.upcoming).bookings
        let ny = TimeZone(identifier: "America/New_York")!
        let said = H.when(rows[0], in: ny)
        var style = Date.FormatStyle.dateTime.weekday(.abbreviated).day().month(.abbreviated).hour().minute()
        style.timeZone = ny
        #expect(said == EventTime.parse(rows[0].start)!.formatted(style))
        #expect(said.contains("10"), "10am in New York")
        let tokyo = H.when(rows[0], in: TimeZone(identifier: "Asia/Tokyo"))
        #expect(tokyo != said)
        #expect(!H.when(rows[0], in: nil).isEmpty)
        let odd = H.BookingRow(start: "soon", day: nil, name: "x", email: "x@example.com", note: nil, eventId: "e")
        #expect(H.when(odd, in: ny) == "soon")
    }
}
