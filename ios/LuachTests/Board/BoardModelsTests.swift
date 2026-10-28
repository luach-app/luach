import Foundation
import SwiftUI
import Testing
@testable import Luach

/// The board's and the task list's shapes, as dev sends them, and the columns made from them.
@MainActor
@Suite(.timeLimit(.minutes(1)))
struct BoardModelsTests {
    @Test func theBoardDayDecodesAsDevSendsIt() throws {
        let day = try BoardFixtures.day()
        #expect(day.canEdit == true && day.viewer == "Robin" && day.today == "2026-10-27" && day.day == "2026-10-27")
        #expect(day.now == "2026-10-27T11:25:03.951184-04:00")
        #expect(day.zone.identifier == "America/New_York" && day.todayISO == "2026-10-27")
        #expect(day.people.map(\.key) == ["robin", "smoke-test", "ruby", "lily"])
        #expect(day.people[2] == BoardPerson(key: "ruby", name: "Ruby", hex: "#33b679", kind: "kid"))
        #expect(day.people[2].id == "ruby")

        let swim = try #require(day.events.first)
        #expect(swim.id == "c6956f0a832e" && swim.title == "Swim" && swim.calendarId == "fake")
        #expect(swim.leaders == ["ruby", "lily"] && swim.leader == "ruby" && swim.readOnly == false)
        #expect(swim.recurring == false && swim.organizer == "" && swim.location == "" && !swim.allDay)
        #expect(!swim.isAllDay)

        let fair = try #require(day.tomorrow.first)
        #expect(fair.allDay && fair.isAllDay && fair.people.isEmpty && fair.end == "2026-10-29")

        #expect(day.tasks.map(\.id) == [132, 133])
    }

    @Test func anOlderBoardWithoutTodayOrEditingStillDecodes() throws {
        var json = BoardFixtures.board(day: "2026-10-29")
        json["today"] = nil
        json["can_edit"] = nil
        json["viewer"] = nil
        json["now"] = nil
        json["timezone"] = "Not/AZone"
        let day = try BoardFixtures.day(json)
        #expect(day.canEdit == nil && day.today == nil && day.viewer == nil && day.now == nil)
        // Without `today` the page is taken to be today; an unknown zone is the phone's.
        #expect(day.todayISO == "2026-10-29")
        #expect(day.zone == .current)
    }

    @Test func aToDoAndAChoreDecode() throws {
        let todo = try BoardFixtures.task()
        #expect(todo == TaskItem(id: 132, title: "Library books", person: "ruby", due: "2026-10-26", days: [],
                                 notes: "the blue bag", done: false, overdue: true, chore: false))
        var chore = BoardFixtures.chore
        chore["notes"] = NSNull()
        let c = try BoardFixtures.task(chore)
        #expect(c.chore && c.days.count == 7 && c.notes == nil && c.person.isEmpty && c.due.isEmpty)
    }

    @Test func anEventsPeopleAreItsLeadersOrElseItsLeader() throws {
        var e = try BoardFixtures.event()
        #expect(e.people == ["ruby", "lily"])
        e.leaders = []
        #expect(e.people == ["ruby"], "an empty list falls back to the one leader")
        e.leaders = nil
        #expect(e.people == ["ruby"], "older servers send only leader")
        e.leader = ""
        #expect(e.people.isEmpty)
        e.leader = nil
        #expect(e.people.isEmpty)
    }

    @Test func aDateWithoutATimeIsAllDayWhateverTheFlagSays() throws {
        var json = BoardFixtures.timedEvent
        json["start"] = "2026-10-27"
        json["all_day"] = false
        // Fields a server may leave out.
        for key in ["leaders", "leader", "read_only", "organizer", "recurring", "calendar_id", "location"] {
            json[key] = nil
        }
        let e = try BoardFixtures.event(json)
        #expect(e.isAllDay && e.people.isEmpty && e.readOnly == nil && e.calendarId == nil && e.location == nil)
    }

    @Test func theTaskListAndTheFamilyDecode() throws {
        let day = try BoardFixtures.decode(TaskDay.self, ["day": "2026-10-27", "tasks": [BoardFixtures.todo], "may_assign": true])
        #expect(day.day == "2026-10-27" && day.tasks.count == 1 && day.mayAssign)
        let all = try BoardFixtures.decode(TaskDay.self, ["tasks": [], "may_assign": false])
        #expect(all.day == nil && all.tasks.isEmpty && !all.mayAssign)
        let family = try BoardFixtures.decode(FamilyList.self, BoardFixtures.family)
        #expect(family.people.map(\.name) == ["Robin", "Ruby"] && family.people[1].kind == "kid")
    }

    @Test func aTaskInputSendsOnlyWhatIsSet() throws {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let json = try JSONSerialization.jsonObject(with: encoder.encode(TaskInput(person: "lily"))) as? [String: Any]
        #expect(json?.count == 1 && json?["person"] as? String == "lily")
        let patch = try JSONSerialization.jsonObject(with: encoder.encode(EventPatch(leaders: []))) as? [String: Any]
        #expect(patch?.count == 1 && (patch?["leaders"] as? [String])?.isEmpty == true)
    }

    // MARK: Columns

    @Test func eachPersonHasAColumnThenTheFamily() throws {
        var json = BoardFixtures.board()
        var stranger = BoardFixtures.todo
        stranger["id"] = 140
        stranger["person"] = "someone-gone"
        var lilys = BoardFixtures.todo
        lilys["id"] = 141
        lilys["person"] = "lily"
        json["tasks"] = [BoardFixtures.todo, BoardFixtures.chore, stranger, lilys]
        var nobodys = BoardFixtures.timedEvent
        nobodys["id"] = "e2"
        nobodys["leaders"] = ["someone-gone"]
        nobodys["leader"] = "someone-gone"
        json["events"] = [BoardFixtures.timedEvent, nobodys]
        let cols = try BoardFixtures.day(json).columns(withFamily: false)

        #expect(cols.map(\.key) == ["robin", "smoke-test", "ruby", "lily", ""])
        #expect(cols.map(\.name).last == String(localized: "Family") && cols.last?.hex == "")
        // An event for two people is in both columns.
        #expect(cols[2].events.map(\.id) == ["c6956f0a832e"] && cols[3].events.map(\.id) == ["c6956f0a832e"])
        #expect(cols[2].tasks.map(\.id) == [132] && cols[3].tasks.map(\.id) == [141])
        // Whoever-gets-to-it and anyone no longer in the family land with the family.
        #expect(cols[4].tasks.map(\.id) == [133, 140] && cols[4].events.map(\.id) == ["e2"])
        #expect(cols[0].events.isEmpty && cols[0].tasks.isEmpty)
        #expect(cols[4].id == "\u{0}family" && cols[2].id == "ruby")
    }

    @Test func anEmptyFamilyColumnIsKeptOnlyWhereTheViewerCanAdd() throws {
        let day = try BoardFixtures.day(BoardFixtures.board(events: [], tomorrow: [], tasks: [BoardFixtures.todo]))
        #expect(day.columns(withFamily: false).map(\.key) == ["robin", "smoke-test", "ruby", "lily"])
        #expect(day.columns(withFamily: true).map(\.key) == ["robin", "smoke-test", "ruby", "lily", ""])
    }

    @Test func theTaskListHasAnAnyoneColumnOnlyWhenSomethingIsInIt() throws {
        let people = try BoardFixtures.day().people
        let todo = try BoardFixtures.task()
        let chore = try BoardFixtures.task(BoardFixtures.chore)
        var lost = todo
        lost.person = "someone-gone"
        let cols = TasksView.columns(people: people, list: [todo, chore, lost])
        #expect(cols.map(\.key) == ["robin", "smoke-test", "ruby", "lily", ""])
        #expect(cols.last?.name == String(localized: "Anyone") && cols.last?.tasks.map(\.person) == ["", "someone-gone"])
        #expect(cols[2].tasks == [todo] && cols.allSatisfy(\.events.isEmpty))
        #expect(TasksView.columns(people: people, list: [todo]).map(\.key) == ["robin", "smoke-test", "ruby", "lily"])
        #expect(TasksView.columns(people: [], list: []).isEmpty)
    }

    @Test func aRowsSmallerLinesAreReadOutUnderItsTitle() throws {
        func details(_ json: [String: Any]) throws -> String {
            TaskRow(task: try BoardFixtures.task(json), hex: "", onTick: {}).details
        }
        #expect(try details(BoardFixtures.todo) == "late — was due \(ISODay.short("2026-10-26")), the blue bag")
        #expect(try details(BoardFixtures.chore) == Weekday.describe(Weekday.codes))
        var dated = BoardFixtures.todo
        dated["overdue"] = false
        dated["notes"] = NSNull()
        #expect(try details(dated) == "due \(ISODay.short("2026-10-26"))")
        dated["due"] = ""
        #expect(try details(dated) == "")
    }

    @Test func theTasksModesAreDayAndEverything() {
        #expect(TasksView.Mode.allCases.map(\.id) == ["day", "all"])
        #expect(TasksView.Mode.day.label == "Day" && TasksView.Mode.all.label == "Everything")
    }

    @Test func aSheetIsNamedForItsTaskOrItsPerson() throws {
        #expect(TaskSheet.open(try BoardFixtures.task()).id == "task-132")
        #expect(TaskSheet.new(person: "lily").id == "new-lily")
        #expect(TaskSheet.new(person: "").id == "new-")
        #expect(EventSheetItem(mode: .create(day: .now, leader: nil)).id != EventSheetItem(mode: .create(day: .now, leader: nil)).id)
    }
}

/// Days as the server writes them, the board's chips, chores' weekdays and people's colours.
@MainActor
@Suite(.timeLimit(.minutes(1)))
struct BoardDayMathsTests {
    private var english: Bool { Locale.current.language.languageCode == .english }

    @Test func daysAddAcrossMonthsYearsAndLeapDays() {
        #expect(ISODay.add("2026-10-27", 1) == "2026-10-28")
        #expect(ISODay.add("2026-10-31", 1) == "2026-11-01")
        #expect(ISODay.add("2026-12-31", 1) == "2027-01-01")
        #expect(ISODay.add("2028-02-28", 1) == "2028-02-29")
        #expect(ISODay.add("2026-03-01", -1) == "2026-02-28")
        #expect(ISODay.add("2026-10-27", 30) == "2026-11-26")
        // Through the clocks changing (Nov 1 in America), a day is still a day.
        #expect(ISODay.add("2026-10-31", 2) == "2026-11-02")
        // An instant is read for its date; anything else comes back as it was.
        #expect(ISODay.add("2026-10-27T23:30:00-04:00", 1) == "2026-10-28")
        #expect(ISODay.add("not a day", 1) == "not a day")
    }

    @Test func daysBetween() {
        #expect(ISODay.between("2026-10-27", "2026-10-29") == 2)
        #expect(ISODay.between("2026-10-29", "2026-10-27") == -2)
        #expect(ISODay.between("2026-10-27", "2026-11-26") == 30)
        #expect(ISODay.between("2026-10-27", "2026-10-27") == 0)
        #expect(ISODay.between("x", "2026-10-27") == 0)
    }

    @Test func aDayIsTheSameDayInEveryZone() throws {
        let d = try #require(ISODay.date("2026-10-27"))
        // Noon UTC: the same date from UTC-11 to UTC+11 (the board formats it in UTC, so it is right everywhere).
        for zone in ["Asia/Tokyo", "Pacific/Pago_Pago", "UTC", "America/New_York", "America/Los_Angeles"] {
            var c = Calendar(identifier: .gregorian)
            c.timeZone = try #require(TimeZone(identifier: zone))
            #expect(c.component(.day, from: d) == 27, "\(zone)")
        }
        #expect(ISODay.date("27/10/2026") == nil)
    }

    @Test func todayIsTheZonesToday() throws {
        let far = try #require(TimeZone(identifier: "Pacific/Kiritimati"))   // UTC+14
        let behind = try #require(TimeZone(identifier: "Pacific/Pago_Pago")) // UTC-11
        let ahead = ISODay.today(in: far)
        let back = ISODay.today(in: behind)
        #expect(ahead.count == 10 && back.count == 10)
        #expect(ISODay.between(back, ahead) == 1 || ISODay.between(back, ahead) == 2)
        #expect(ISODay.today(in: .current) == EventTime.dayString(.now))
    }

    @Test func theChipsSayTodayTomorrowThenTheWeekday() {
        #expect(ISODay.chip("2026-10-27", today: "2026-10-27") == String(localized: "Today"))
        #expect(ISODay.chip("2026-10-28", today: "2026-10-27") == String(localized: "Tomorrow"))
        let later = ISODay.chip("2026-10-29", today: "2026-10-27")
        #expect(later.contains("29") && later != ISODay.chip("2026-10-30", today: "2026-10-27"))
        if english { #expect(later == "Thu 29") }
        #expect(ISODay.chip("soon", today: "2026-10-27") == "soon")
    }

    @Test func longAndShortDays() {
        if english {
            #expect(ISODay.long("2026-10-29") == "Thursday, October 29")
            #expect(ISODay.short("2026-10-29") == "Oct 29")
        }
        #expect(ISODay.long("2026-10-29").contains("29") && ISODay.short("2026-01-02").contains("2"))
        #expect(ISODay.long("x") == "x" && ISODay.short("x") == "x")
    }

    @Test func theDatePickersDayGoesAndComesBack() throws {
        let local = try #require(ISODay.local("2026-10-29T10:00:00-04:00"))
        #expect(Calendar.current.component(.hour, from: local) == 0, "local midnight")
        #expect(ISODay.fromLocal(local) == "2026-10-29")
        #expect(ISODay.local("") == nil)
    }

    @Test func weekdaysAreNamedOnThePhonesCalendar() {
        let cal = Calendar.current
        // Monday first in the codes, Sunday first in Foundation's symbols.
        #expect(Weekday.name("MO") == cal.standaloneWeekdaySymbols[1])
        #expect(Weekday.name("SU") == cal.standaloneWeekdaySymbols[0])
        #expect(Weekday.short("SA") == cal.shortStandaloneWeekdaySymbols[6])
        #expect(Weekday.initial("TH") == cal.veryShortStandaloneWeekdaySymbols[4])
        if english { #expect(Weekday.name("WE") == "Wednesday" && Weekday.short("FR") == "Fri") }
        // A code the app does not know is shown as it came.
        #expect(Weekday.name("XX") == "XX" && Weekday.short("XX") == "XX" && Weekday.initial("XX") == "XX")
    }

    @Test func aChoresDaysAreSaidInWords() {
        #expect(Weekday.describe(Weekday.codes) == String(localized: "every day"))
        #expect(Weekday.describe(["MO", "TU", "WE", "TH", "FR"]) == String(localized: "weekdays"))
        #expect(Weekday.describe(["SA", "SU"]) == String(localized: "weekends"))
        #expect(Weekday.describe(["MO", "TH"]) == "\(Weekday.short("MO")), \(Weekday.short("TH"))")
        #expect(Weekday.describe([]) == "")
    }

    @Test func picksAreKeptInTheWeeksOrder() {
        #expect(Weekday.sorted(["SU", "MO", "WE"]) == ["MO", "WE", "SU"])
        #expect(Weekday.sorted(["XX", "TU"]) == ["TU"])
        #expect(Weekday.sorted([]) == [])
    }

    @Test func coloursAreReadFromHex() {
        #expect(Color(luachHex: "#039be5") == Color(red: 3 / 255, green: 155 / 255, blue: 229 / 255))
        #expect(Color(luachHex: "039be5") == Color(luachHex: "#039be5"))
        #expect(Color(luachHex: " #fff ") == Color(red: 1, green: 1, blue: 1))
        #expect(Color(luachHex: "#f00") == Color(luachHex: "#ff0000"))
        for bad in ["", "#", "#12", "#12345", "#1234567", "#ggg", "blue"] {
            #expect(Color(luachHex: bad) == nil, "\(bad)")
        }
    }

    @Test func inkIsWhicheverReadsBetterOnThePersonsColour() {
        #expect(Color.ink(on: "#ffffff") == .black)
        #expect(Color.ink(on: "#f6bf26") == .black, "Banana")
        #expect(Color.ink(on: "#33b679") == .black, "Sage")
        #expect(Color.ink(on: "#000000") == .white)
        #expect(Color.ink(on: "#3f51b5") == .white, "Blueberry")
        #expect(Color.ink(on: "#d50000") == .white, "Tomato")
        #expect(Color.ink(on: "") == .white, "no colour: the accent, which is dark")
    }

    @Test func aPersonsColourOrTheAccent() {
        #expect(personColor("#8e24aa") == Color(luachHex: "#8e24aa"))
        #expect(personColor("") == .accentColor)
        #expect(personColor("purple") == .accentColor)
    }
}
