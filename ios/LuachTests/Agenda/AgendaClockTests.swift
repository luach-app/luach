import Foundation
import Testing
@testable import Luach

/// Days as the member sees them: plain day arithmetic, then the member's zone, then words.
@Suite(.timeLimit(.minutes(1)))
struct AgendaClockDayTests {
    @Test func aDayIsTenDigitsAndDashes() {
        #expect(AgendaClock.isDay("2026-10-26"))
        #expect(!AgendaClock.isDay("2026-10-26T15:00"))
        #expect(!AgendaClock.isDay("26-10-2026"))
        #expect(!AgendaClock.isDay("abcd-ef-gh"))
        #expect(!AgendaClock.isDay(""))
    }

    @Test func daysAddAcrossMonthsYearsAndLeapDays() {
        #expect(AgendaClock.addDays("2026-10-31", 1) == "2026-11-01")
        #expect(AgendaClock.addDays("2026-12-31", 1) == "2027-01-01")
        #expect(AgendaClock.addDays("2026-03-01", -1) == "2026-02-28")
        #expect(AgendaClock.addDays("2028-03-01", -1) == "2028-02-29")
        #expect(AgendaClock.addDays("2026-11-01", 7) == "2026-11-08", "a DST change is not a day")
        #expect(AgendaClock.addDays("2026-10-26", 0) == "2026-10-26")
    }

    @Test func monthsAddAcrossYears() {
        #expect(AgendaClock.ym("2026-10-26") == "2026-10")
        #expect(AgendaClock.addMonths("2026-12", 1) == "2027-01")
        #expect(AgendaClock.addMonths("2026-01", -1) == "2025-12")
        #expect(AgendaClock.addMonths("2026-10", 14) == "2027-12")
        #expect(AgendaClock.addMonths("2026-10", 0) == "2026-10")
    }

    @Test func weekdaysCountFromMonday() {
        #expect(AgendaClock.weekdayMon("2026-10-26") == 0) // Monday
        #expect(AgendaClock.weekdayMon("2026-11-03") == 1) // Tuesday
        #expect(AgendaClock.weekdayMon("2026-10-31") == 5) // Saturday
        #expect(AgendaClock.weekdayMon("2026-11-01") == 6) // Sunday
    }

    @Test func noonIsMiddayUTCAndANonDayIsLongAgo() {
        #expect(AgendaClock.noon("2026-10-26") == Date(timeIntervalSince1970: 1_792_972_800 + 12 * 3600))
        #expect(AgendaClock.noon("not a day") < Date(timeIntervalSince1970: 0))
    }

    @Test(arguments: [
        ("2026-10", "2026-09-28", "2026-11-01", 5), // Thursday to Saturday
        ("2026-02", "2026-01-26", "2026-03-01", 5), // a Sunday start
        ("2027-02", "2027-02-01", "2027-02-28", 4), // Monday to Sunday, 28 days: four rows
        ("2026-03", "2026-02-23", "2026-04-05", 6), // a Sunday start and 31 days: six rows
    ])
    func theMonthGridIsWholeWeeks(ym: String, first: String, last: String, rows: Int) {
        let grid = AgendaClock.monthGrid(ym)
        #expect(grid.first == first && grid.last == last && grid.weeks.count == rows)
        #expect(grid.weeks.allSatisfy { $0.count == 7 })
        #expect(grid.weeks.first?.first == first && grid.weeks.last?.last == last)
        #expect(grid.weeks.allSatisfy { AgendaClock.weekdayMon($0[0]) == 0 })
        let days = grid.weeks.flatMap { $0 }
        #expect(zip(days, days.dropFirst()).allSatisfy { AgendaClock.addDays($0, 1) == $1 })
        #expect(days.filter { $0.hasPrefix(ym) }.count == Int(AgendaClock.addDays("\(AgendaClock.addMonths(ym, 1))-01", -1).suffix(2)))
    }
}

@Suite(.timeLimit(.minutes(1)))
struct AgendaClockZoneTests {
    let ny = AgendaFixtures.newYork
    let tokyo = AgendaClock(tz: TimeZone(identifier: "Asia/Tokyo")!, locale: Locale(identifier: "en_US"))

    @Test func instantsReadEveryShapeTheServerSends() throws {
        #expect(ny.instant("2026-11-03T15:00:00-05:00") == Date(timeIntervalSince1970: 1_793_736_000))
        #expect(ny.instant("2026-11-03T20:00:00Z") == Date(timeIntervalSince1970: 1_793_736_000))
        #expect(ny.instant("2026-11-03T20:00:00.250Z") == Date(timeIntervalSince1970: 1_793_736_000.25))
        // Microseconds, as Python writes them.
        let micro = try #require(ny.instant("2026-10-27T15:24:42.384019+00:00"))
        #expect(abs(micro.timeIntervalSince1970 - 1_793_114_682) < 1)
        #expect(ny.instant("2026-10-27T15:24:42.123456789+00:00") != nil, "however many digits")
        #expect(ny.instant("2026-11-03") == nil)
        #expect(ny.instant("soon") == nil)
    }

    @Test func aMomentIsOnTheMembersDayNotThePhones() throws {
        let lateInNewYork = try #require(ny.instant("2026-11-04T03:00:00Z"))
        #expect(ny.day(of: lateInNewYork) == "2026-11-03")
        #expect(tokyo.day(of: lateInNewYork) == "2026-11-04")
    }

    @Test func aDayStartsAtTheMembersMidnight() {
        #expect(ny.date(ofDay: "2026-11-03") == Date(timeIntervalSince1970: 1_793_682_000)) // 05:00Z
        #expect(ny.date(ofDay: "2026-11-01") == Date(timeIntervalSince1970: 1_793_505_600)) // EDT: 04:00Z
        #expect(ny.input(ny.date(ofDay: "2026-11-03")) == "2026-11-03T00:00")
        // Not a day: now, rather than nothing.
        #expect(abs(ny.date(ofDay: "never").timeIntervalSinceNow) < 5)
    }

    @Test func theWriteShapeIsAWallClockInTheMembersZone() throws {
        let three = try #require(ny.instant("2026-11-03T15:00:00-05:00"))
        #expect(ny.input(three) == "2026-11-03T15:00")
        #expect(tokyo.input(three) == "2026-11-04T05:00")
        #expect(ny.date(fromInput: "2026-11-03T15:00") == three)
        #expect(ny.date(fromInput: "2026-11-03 15:00") == nil)
    }

    @Test func todayIsTheMembersToday() {
        #expect(ny.today() == ny.day(of: .now))
        #expect(tokyo.today() == tokyo.day(of: .now))
    }

    @Test func aNewEventStartsAtTheTopOfTheNextHour() {
        let top = ny.nextHour()
        let parts = ny.calendar.dateComponents([.minute, .second, .nanosecond], from: top)
        #expect(parts.minute == 0 && parts.second == 0)
        #expect(top > .now && top <= .now.addingTimeInterval(2 * 3600))
        let onDay = ny.nextHour(on: "2030-01-15")
        #expect(ny.day(of: onDay) == "2030-01-15")
        #expect(ny.input(onDay).suffix(5) == ny.input(top).suffix(5), "the same time of day")
    }

    @Test func aClockIsSharedWhileTheMembersZoneAndLanguageStay() {
        let he = Member(id: 1, username: "a", displayName: nil, email: nil, timezone: "Asia/Jerusalem", language: "he", isOwner: nil)
        let clock = AgendaClock.of(he)
        #expect(clock.tz.identifier == "Asia/Jerusalem" && clock.locale.identifier == "he")
        #expect(AgendaClock.of(he) === clock)
        // Hebrew counts the week from Sunday, as the web board does.
        #expect(clock.calendar.firstWeekday == 1 && clock.calendar.timeZone.identifier == "Asia/Jerusalem")

        let es = Member(id: 1, username: "a", displayName: nil, email: nil, timezone: "Europe/Madrid", language: "es", isOwner: nil)
        let other = AgendaClock.of(es)
        #expect(other !== clock && other.locale.identifier == "es")

        // "auto", an unknown zone, or nobody: the phone's own.
        let auto = Member(id: 1, username: "a", displayName: nil, email: nil, timezone: "Mars/Olympus", language: "auto", isOwner: nil)
        #expect(AgendaClock.of(auto).tz == .current && AgendaClock.of(auto).locale == .current)
        #expect(AgendaClock.of(nil).tz == .current)
    }
}

@Suite(.timeLimit(.minutes(1)))
struct AgendaClockWordTests {
    let ny = AgendaFixtures.newYork

    @Test func daysAreNamedInTheMembersLanguage() {
        #expect(ny.dayName("2026-10-26") == "Mon")
        #expect(ny.dayName("2026-10-26", long: true) == "Monday")
        #expect(ny.dayNumber("2026-10-06") == "6")
        #expect(ny.dateLong("2026-10-26") == "Monday, October 26")
        #expect(ny.dateShort("2026-10-26") == "Mon, Oct 26")
        #expect(ny.monthYear("2026-10") == "October 2026")
        #expect(ny.monthShort(3) == "Mar")
        #expect(ny.weekdayLetters() == ["M", "T", "W", "T", "F", "S", "S"])
        // Asked twice, from the cache.
        #expect(ny.dateLong("2026-10-27") == "Tuesday, October 27")
    }

    @Test func hebrewIsHebrew() {
        let he = AgendaClock(tz: TimeZone(identifier: "Asia/Jerusalem")!, locale: Locale(identifier: "he"))
        #expect(he.dayName("2026-10-26", long: true).unicodeScalars.contains { (0x0590...0x05FF).contains($0.value) })
        #expect(he.weekdayLetters().count == 7)
    }

    @Test func timesAreInTheMembersZone() throws {
        let three = try #require(ny.instant("2026-11-03T15:00:00-05:00"))
        #expect(ny.time(three).hasPrefix("3:00") && ny.time(three).hasSuffix("PM"))
        #expect(ny.dateTime(three).hasPrefix("Tue, Nov 3"))
    }
}

/// Events on days: which days they touch, their order, and how their time reads.
@Suite(.timeLimit(.minutes(1)))
struct AgendaClockEventTests {
    let ny = AgendaFixtures.newYork
    typealias F = AgendaFixtures

    @Test func anEventStartsOnTheMembersDay() throws {
        #expect(try ny.startDay(try F.event("a", "2026-11-03T23:30:00-05:00")) == "2026-11-03")
        #expect(try ny.startDay(try F.event("a", "2026-11-04T02:00:00Z")) == "2026-11-03")
        #expect(try ny.startDay(try F.event("a", "2026-11-05", "2026-11-07")) == "2026-11-05")
        #expect(try ny.startDay(try F.event("a", "2026-11-05T09:00", allDay: true)) == "2026-11-05")
        #expect(try ny.startDay(try F.event("a", "garbage!garbage")) == "garbage!ga", "unreadable: its first ten characters")
        #expect(try ny.startDay(try F.event("a", "")) == "")
    }

    @Test func anEventTouchesEveryDayItSpans() throws {
        let night = try F.event("a", "2026-11-03T22:00:00-05:00", "2026-11-04T01:00:00-05:00")
        #expect(ny.days(night, from: "2026-11-01", to: "2026-11-30") == ["2026-11-03", "2026-11-04"])
        let trip = try F.event(F.allDay)
        #expect(ny.days(trip, from: "2026-11-01", to: "2026-11-30") == ["2026-11-05", "2026-11-06"], "the end is exclusive")
        // Clipped to the range on both sides.
        #expect(ny.days(trip, from: "2026-11-06", to: "2026-11-30") == ["2026-11-06"])
        #expect(ny.days(trip, from: "2026-11-01", to: "2026-11-05") == ["2026-11-05"])
        #expect(ny.days(trip, from: "2026-12-01", to: "2026-12-31").isEmpty)
    }

    @Test func aMissingOrBackwardsEndIsOneDay() throws {
        #expect(try ny.days(try F.event("a", "2026-11-05", "", allDay: true), from: "2026-11-01", to: "2026-11-30") == ["2026-11-05"])
        #expect(try ny.days(try F.event("a", "2026-11-05", "2026-11-05"), from: "2026-11-01", to: "2026-11-30") == ["2026-11-05"])
        #expect(try ny.days(try F.event("a", "2026-11-05T10:00:00-05:00", "2026-11-01T10:00:00-05:00"),
                        from: "2026-11-01", to: "2026-11-30") == ["2026-11-05"])
        #expect(try ny.days(try F.event("a", "2026-11-05T10:00:00-05:00"), from: "2026-11-01", to: "2026-11-30") == ["2026-11-05"])
        #expect(try ny.days(try F.event("a", ""), from: "2026-11-01", to: "2026-11-30").isEmpty)
    }

    @Test func aDayListsAllDayFirstThenByStart() throws {
        let late = try F.event("late", "2026-11-03T18:00:00-05:00", "2026-11-03T19:00:00-05:00")
        let early = try F.event("early", "2026-11-03T08:00:00-05:00", "2026-11-03T09:00:00-05:00")
        let trip = try F.event("trip", "2026-11-03", "2026-11-05")
        let next = try F.event("next", "2026-11-04T07:00:00-05:00", "2026-11-04T07:30:00-05:00")
        let before = try F.event("before", "2026-11-02T23:00:00-05:00", "2026-11-03T00:30:00-05:00")
        #expect(ny.sorted([next, late, trip, early, before]).map(\.id) == ["before", "trip", "early", "late", "next"])
        let map = ny.byDay([next, late, trip, early, before], from: "2026-11-01", to: "2026-11-30")
        #expect(map["2026-11-02"]?.map(\.id) == ["before"])
        #expect(map["2026-11-03"]?.map(\.id) == ["before", "trip", "early", "late"])
        #expect(map["2026-11-04"]?.map(\.id) == ["trip", "next"])
        #expect(map["2026-11-05"] == nil)
    }

    @Test func aRangeReadsAsAPersonSaysIt() throws {
        let dentist = try F.event(F.timed)
        let r = ny.range(dentist)
        #expect(r.hasPrefix("3:00") && r.contains(" – 3:45") && r.hasSuffix("PM"))
        #expect(try ny.range(try F.event("a", "2026-11-05", "2026-11-06")) == "All day")
        #expect(try ny.range(try F.event("a", "2026-11-05", "", allDay: true)) == "All day")
        #expect(try ny.range(try F.event(F.allDay)) == "Thu, Nov 5 – Fri, Nov 6")
        #expect(try ny.range(try F.event("a", "")) == "")
        #expect(try ny.range(try F.event("a", "tomorrow at three")) == "tomorrow at three")
        #expect(try ny.range(try F.event("a", "2026-11-03T15:00:00-05:00")).hasPrefix("3:00"))
        let night = ny.range(try F.event("a", "2026-11-03T22:00:00-05:00", "2026-11-04T01:00:00-05:00"))
        #expect(night.hasPrefix("Tue, Nov 3") && night.contains(" – Wed, Nov 4"))
    }

    @Test func aDayHeadingSaysToday() {
        let today = ny.today()
        #expect(agendaDayHeading(today, ny) == ny.dateLong(today) + " · today")
        #expect(agendaDayHeading("2026-10-26", ny) == (ny.today() == "2026-10-26" ? "Monday, October 26 · today" : "Monday, October 26"))
    }
}

/// In Hebrew the week starts on Sunday, as the web board and Israeli calendars do.
struct AgendaSundayFirstTests {
    @Test func theGridStartsOnSundayInHebrew() {
        let grid = AgendaClock.monthGrid("2026-11", sundayFirst: true)
        #expect(grid.first == "2026-11-01", "1 November 2026 is a Sunday")
        #expect(grid.weeks.allSatisfy { AgendaClock.weekdayMon($0[0], sundayFirst: true) == 0 })
        #expect(AgendaClock.monthGrid("2026-11").first == "2026-10-26", "and Monday-first otherwise")
    }

    @Test func theLanguageDecidesTheFirstDay() {
        #expect(AgendaClock.sundayFirst(Locale(identifier: "he_IL")))
        #expect(!AgendaClock.sundayFirst(Locale(identifier: "en_US")))
        #expect(!AgendaClock.sundayFirst(Locale(identifier: "es_ES")))
        let he = AgendaClock(tz: TimeZone(identifier: "Asia/Jerusalem")!, locale: Locale(identifier: "he_IL"))
        let en = AgendaClock(tz: TimeZone(identifier: "America/New_York")!, locale: Locale(identifier: "en_US"))
        #expect(he.weekdayLetters().count == 7 && en.weekdayLetters().count == 7)
        #expect(he.weekdayLetters().first == he.calendar.veryShortStandaloneWeekdaySymbols.first, "Sunday first")
        #expect(en.weekdayLetters().last == en.calendar.veryShortStandaloneWeekdaySymbols.first, "Sunday last")
    }
}
