import Foundation
import Testing
@testable import Luach

/// The Household area against a real luach (dev). Reads everything; changes only this
/// member's reminders and booking page (recorded first, put back exactly, and checked), and
/// one `ios-test…` busy feed it adds and removes. The household's calendars and default
/// invitees are never written, and no booking is made or cancelled.
@MainActor
@Suite(.dev, .serialized, .timeLimit(.minutes(3)))
struct HouseholdDevTests {
    typealias H = HouseholdArea
    /// A feed anyone may read: Google's public US holidays (all-day, so it blocks nothing).
    static let publicFeed = "https://calendar.google.com/calendar/ical/en.usa%23holiday%40group.v.calendar.google.com/public/basic.ics"

    private func client() throws -> H.Client { H.Client(api: try Dev.api()) }

    // MARK: Reads

    @Test func theHouseholdsCalendarsDecode() async throws {
        let c = try await client().calendars()
        #expect(!c.calendars.isEmpty, "a household reads at least one calendar")
        #expect(!c.defaultCalendar.isEmpty)
        #expect(c.defaultAttendees.allSatisfy { H.isEmail($0) })
        #expect(c.enabledList.allSatisfy { $0.enabled })
        // A fresh form over it is not a change, so the screen opens with Save off.
        #expect(!H.HouseholdForm(c).isDirty(against: c))
    }

    @Test func theBookingPageAndItsBookingsDecode() async throws {
        let api = try client()
        let b = try await api.booking()
        #expect(b.link.hasSuffix("/book/\(b.settings.slug)"))
        #expect(TimeZone(identifier: b.timezone) != nil)
        #expect(Set(b.settings.hours.keys).isSubset(of: Set(H.weekdays.map(\.key))))
        #expect(b.settings.hours.values.joined().allSatisfy { $0.count == 2 })
        let rows = try await api.upcoming()
        #expect(rows.allSatisfy { !$0.eventId.isEmpty && EventTime.parse($0.start) != nil })
    }

    @Test func theBusyFeedsAndRemindersDecode() async throws {
        let api = try client()
        let feeds = try await api.busy()
        #expect(feeds.allSatisfy { !$0.url.isEmpty })
        let r = try await api.reminders()
        #expect((-1...23).contains(r.eveningHour) && (-1...6).contains(r.weeklyDay) && (0...23).contains(r.weeklyHour))
    }

    // MARK: Reminders

    @Test func remindersAreChangedReadBackAndPutBack() async throws {
        let api = try client()
        let before = try await api.reminders()
        var changed = before
        changed.byEmail.toggle()
        changed.leadMinutes = before.leadMinutes == 60 ? 15 : 60
        changed.weeklyDay = before.weeklyDay == 4 ? 2 : 4
        do {
            let saved = try await api.saveReminders(changed)
            #expect(saved == changed)
            #expect(try await api.reminders() == changed, "read back as saved")
        } catch {
            Issue.record(error)
        }
        // Put back whatever happened above.
        let restored = try await api.saveReminders(before)
        #expect(restored == before)
        #expect(try await api.reminders() == before, "dev's reminders are as they were")
    }

    @Test func anOutOfRangeReminderIsRefusedWithASentenceAndChangesNothing() async throws {
        let api = try client()
        let before = try await api.reminders()
        var bad = before
        bad.leadMinutes = -5
        await #expect {
            _ = try await api.saveReminders(bad)
        } throws: { error in
            (error as? APIError)?.status == 400 && error.localizedDescription.contains("between")
        }
        #expect(try await api.reminders() == before)
    }

    // MARK: Booking

    @Test func theBookingIsChangedReadBackAndPutBack() async throws {
        let api = try client()
        let before = try await api.booking().settings
        var changed = before
        changed.maxPerDay = before.maxPerDay == 3 ? 4 : 3
        changed.notifyHost.toggle()
        changed.note = "ios-test note"
        // A split Saturday, sent out of order: luach keeps them sorted.
        changed.hours["sat"] = [["14:00", "16:00"], ["09:00", "11:00"]]
        do {
            let saved = try await api.saveBooking(changed).settings
            #expect(saved.maxPerDay == changed.maxPerDay && saved.notifyHost == changed.notifyHost)
            #expect(saved.note == "ios-test note")
            #expect(saved.hours["sat"] == [["09:00", "11:00"], ["14:00", "16:00"]])
            #expect(try await api.booking().settings == saved, "read back as saved")
        } catch {
            Issue.record(error)
        }
        let restored = try await api.saveBooking(before).settings
        #expect(restored == before)
        #expect(try await api.booking().settings == before, "dev's booking page is as it was")
    }

    @Test func aBadLinkNameIsRefusedWithASentenceAndChangesNothing() async throws {
        let api = try client()
        let before = try await api.booking().settings
        var bad = before
        bad.slug = "a"
        await #expect {
            _ = try await api.saveBooking(bad)
        } throws: { error in
            (error as? APIError)?.status == 400
                && error.localizedDescription == "the link name is 2-40 chars: letters, digits and dashes"
        }
        var backwards = before
        backwards.hours["sun"] = [["17:00", "09:00"]]
        await #expect {
            _ = try await api.saveBooking(backwards)
        } throws: { error in
            (error as? APIError)?.status == 400 && error.localizedDescription.contains("ends before it starts")
        }
        #expect(try await api.booking().settings == before)
    }

    // MARK: Busy feeds

    @Test func anIosTestFeedIsAddedChangedReadAndRemoved() async throws {
        let api = try client()
        let name = Dev.title("feed")
        let before = try await api.busy()
        let added = try await api.addBusy(name: name, url: Self.publicFeed)
        let feed = try #require(added.first { $0.name == name })
        do {
            #expect(feed.url == Self.publicFeed && feed.enabled && feed.showInAgenda)
            let off = try await api.updateBusy(feed.id, ["show_in_agenda": false])
            #expect(off.first { $0.id == feed.id }?.showInAgenda == false)
            let unblocked = try await api.updateBusy(feed.id, ["enabled": false])
            #expect(unblocked.first { $0.id == feed.id }?.enabled == false)
            let read = try await api.refreshBusy()
            let again = try #require(read.first { $0.id == feed.id })
            #expect(H.parseInstant(again.lastFetched) != nil || again.lastFetched == nil, "a time luach wrote reads")
            #expect(try await api.busy().contains { $0.id == feed.id })
        } catch {
            Issue.record(error)
        }
        let left = try await api.removeBusy(feed.id)
        #expect(!left.contains { $0.id == feed.id })
        #expect(try await api.busy().map(\.id) == before.map(\.id), "dev's feeds are as they were")
        // Removing it twice is the server's sentence, not a crash.
        await #expect {
            _ = try await api.removeBusy(feed.id)
        } throws: { error in
            (error as? APIError)?.status == 404 && error.localizedDescription == "that calendar is not yours"
        }
    }

    @Test func aFeedThatIsNotAnAddressIsRefused() async throws {
        let api = try client()
        let before = try await api.busy()
        await #expect {
            _ = try await api.addBusy(name: Dev.title("bad"), url: "not a feed")
        } throws: { error in
            (error as? APIError)?.status == 400 && error.localizedDescription == "that is not a calendar feed address"
        }
        #expect(try await api.busy().map(\.id) == before.map(\.id))
    }
}
