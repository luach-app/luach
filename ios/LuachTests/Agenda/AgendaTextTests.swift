import Foundation
import SwiftUI
import Testing
@testable import Luach

/// Repeats as a person says them and as Google needs them (web `lib/recurrence.ts`).
@Suite(.timeLimit(.minutes(1)))
struct AgendaRepeatTests {
    @Test(arguments: [
        ([], AgendaRepeat.none),
        (["EXDATE:20261110T150000"], .none),
        (["RRULE:FREQ=DAILY"], .daily),
        (["FREQ=DAILY"], .daily),
        (["rrule:freq=daily"], .daily),
        (["RRULE:FREQ=DAILY;INTERVAL=1"], .custom),
        (["RRULE:FREQ=WEEKLY;BYDAY=TU"], .weekly),
        (["RRULE:FREQ=WEEKLY;INTERVAL=1;BYDAY=TU"], .weekly),
        (["RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TU"], .biweekly),
        (["RRULE:FREQ=WEEKLY;INTERVAL=3;BYDAY=TU"], .custom),
        (["RRULE:FREQ=MONTHLY"], .monthly),
        (["RRULE:FREQ=MONTHLY;BYMONTHDAY=15"], .custom),
        (["RRULE:FREQ=MONTHLY;BYDAY=TU;BYSETPOS=2"], .custom),
        (["RRULE:FREQ=YEARLY"], .yearly),
        (["RRULE:FREQ=YEARLY;INTERVAL=2"], .custom),
        (["RRULE:FREQ=WEEKLY;COUNT=3;BYDAY=TU"], .custom),
        (["RRULE:FREQ=WEEKLY;UNTIL=20261231T000000Z;BYDAY=TU"], .custom),
        (["RRULE:FREQ=HOURLY"], .custom),
        (["EXDATE:20261110T150000", "RRULE:FREQ=WEEKLY;BYDAY=TU"], .weekly),
    ] as [([String], AgendaRepeat)])
    func anEventsRuleIsOneOfTheMenusOrKept(rules: [String], expected: AgendaRepeat) {
        #expect(AgendaRepeat.of(rules) == expected)
    }

    @Test func eachChoiceIsSentAsTheMenusWordForTheServerToAnchor() {
        // The server puts it on the event's own day in the member's zone (docs/API.md).
        #expect(AgendaRepeat.none.word == "")
        #expect(AgendaRepeat.custom.word == "", "a kept rule is never sent")
        #expect(AgendaRepeat.daily.word == "daily")
        #expect(AgendaRepeat.weekly.word == "weekly")
        #expect(AgendaRepeat.biweekly.word == "biweekly")
        #expect(AgendaRepeat.monthly.word == "monthly")
        #expect(AgendaRepeat.yearly.word == "yearly")
    }

    @Test func everyOfferedChoiceIsAWordTheServerKnows() {
        for choice in AgendaRepeat.offered where choice != .none {
            #expect(AgendaRepeat(rawValue: choice.word) == choice)
        }
        #expect(!AgendaRepeat.offered.contains(.custom))
        #expect(AgendaRepeat.allCases.count == 7)
    }

    @Test func eachChoiceHasWords() {
        let labels = AgendaRepeat.allCases.map(\.label)
        #expect(labels == ["Does not repeat", "Every day", "Every week", "Every two weeks", "Every month", "Every year", "Custom"])
        #expect(AgendaRepeat.allCases.map(\.id) == AgendaRepeat.allCases.map(\.rawValue))
    }

    @Test(arguments: [
        ([], ""),
        (["RRULE:FREQ=DAILY"], "Every day"),
        (["RRULE:FREQ=WEEKLY;BYDAY=TU"], "Every week on Tuesday"),
        (["FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,WE"], "Every week on Monday, Wednesday"),
        (["RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"], "Every 2 weeks on Friday"),
        (["RRULE:FREQ=MONTHLY;BYDAY=1MO"], "Every month on Monday"),
        (["RRULE:FREQ=MONTHLY;BYDAY=XX"], "Every month on XX"),
        (["RRULE:FREQ=YEARLY;COUNT=5"], "Every year, 5 times"),
        (["RRULE:FREQ=WEEKLY;BYDAY=TU;UNTIL=20261231T045959Z"], "Every week on Tuesday, until 2026-12-31"),
        (["RRULE:FREQ=DAILY;UNTIL=2026"], "Every day"),
        (["RRULE:FREQ=HOURLY;INTERVAL=4"], "FREQ=HOURLY;INTERVAL=4"),
        (["rrule:freq=weekly;byday=su"], "Every week on Sunday"),
    ] as [([String], String)])
    func aRuleIsDescribedInWords(rules: [String], words: String) {
        #expect(AgendaRepeat.describe(rules, locale: Locale(identifier: "en_US")) == words)
    }

    @Test func weekdaysAreNamedInTheMembersLanguage() {
        let es = AgendaRepeat.describe(["RRULE:FREQ=WEEKLY;BYDAY=TU"], locale: Locale(identifier: "es"))
        #expect(es == "Every week on martes")
    }
}

/// Notes as a person reads them (web `lib/notes.tsx`).
@Suite(.timeLimit(.minutes(1)))
struct AgendaNotesTests {
    @Test func plainTextIsLeftAlone() {
        let text = "Bring the forms.\n\n  Ask about x < y & z > w.  "
        #expect(!AgendaNotes.isHTML(text))
        #expect(AgendaNotes.asText(text) == text)
        #expect(!AgendaNotes.isHTML("a <notatag> b"))
    }

    @Test func htmlIsSpotted() {
        #expect(AgendaNotes.isHTML("<b>Join</b>"))
        #expect(AgendaNotes.isHTML("line<BR/>line"))
        #expect(AgendaNotes.isHTML(#"<a href="https://example.com">x</a>"#))
        #expect(AgendaNotes.isHTML("<h2>Agenda</h2>"))
    }

    @Test func aGoogleInvitationReadsAsText() {
        let html = """
        <b>Join Google Meet:</b> <a href="https://meet.google.com/abc-defg-hij">meet.google.com/abc-defg-hij</a><br/>\
        <p>Agenda:</p><ul><li>Budget</li><li>Trip &amp; dates</li></ul>\
        <div>Questions? <a href="mailto:host@example.com">Write to me</a></div>
        """
        #expect(AgendaNotes.asText(html) == """
        Join Google Meet: meet.google.com/abc-defg-hij (https://meet.google.com/abc-defg-hij)
        Agenda:

        • Budget
        • Trip & dates
        Questions? Write to me (mailto:host@example.com)
        """)
    }

    @Test func aLinkThatIsItsOwnAddressIsWrittenOnce() {
        #expect(AgendaNotes.asText(#"<a href="https://example.com/x">https://example.com/x</a>"#) == "https://example.com/x")
        // The address as written in the attribute, ampersand and all.
        #expect(AgendaNotes.asText(#"<a href="https://example.com/?a=1&amp;b=2">https://example.com/?a=1&amp;b=2</a>"#)
                == "https://example.com/?a=1&b=2")
    }

    @Test func onlyWebAndMailLinksKeepTheirAddress() {
        #expect(AgendaNotes.asText(#"<a href="javascript:alert(1)">click</a>"#) == "click")
        #expect(AgendaNotes.asText(#"<a href='tel:+15550100'>call</a>"#) == "call")
        #expect(AgendaNotes.asText(#"<A HREF="HTTPS://EXAMPLE.COM">Shout</A>"#) == "Shout (HTTPS://EXAMPLE.COM)")
    }

    @Test func scriptsAndStylesAreDropped() {
        #expect(AgendaNotes.asText("<p>Hi</p><script>alert('x')</script><style>p{color:red}</style>") == "Hi")
    }

    @Test func entitiesAreDecodedOnce() {
        #expect(AgendaNotes.asText("<p>a&nbsp;b &lt;c&gt; &quot;d&quot; &#39;e&#39; &apos;f&apos; &#8217; &amp;lt;</p>")
                == "a b <c> \"d\" 'e' 'f' \u{2019} &lt;")
        // An escaped address inside a link's words is text, not a tag to strip.
        #expect(AgendaNotes.asText(#"<a href="mailto:ana@example.com">Ana &lt;ana@example.com&gt;</a>"#)
                == "Ana <ana@example.com> (mailto:ana@example.com)")
    }

    @Test func blankLinesAreSqueezed() {
        #expect(AgendaNotes.asText("<p>one</p>\n\n\n<p>two</p>   \n<br><br><br>three") == "one\n\ntwo\n\nthree")
    }

    @Test func linksAreTappable() throws {
        let text = AgendaNotes.attributed(#"<p>See <a href="https://example.com/x">the page</a> or write to ana@example.com</p>"#)
        #expect(String(text.characters) == "See the page (https://example.com/x) or write to ana@example.com")
        let links = text.runs.compactMap(\.link)
        #expect(links.contains(URL(string: "https://example.com/x")!))
        #expect(links.contains { $0.scheme == "mailto" && $0.absoluteString.hasSuffix("ana@example.com") })
        #expect(AgendaNotes.attributed("nothing to tap").runs.allSatisfy { $0.link == nil })
    }
}

@Suite(.timeLimit(.minutes(1)))
struct AgendaWordsTests {
    @Test func namesAreListedAsAPersonSaysThem() {
        #expect(AgendaWords.names([]) == "")
        #expect(AgendaWords.names(["Noa"]) == "Noa")
        #expect(AgendaWords.names(["Noa", "Sam"]) == "Noa and Sam")
        #expect(AgendaWords.names(["Noa", "Sam", "Ari"]) == "Noa, Sam and Ari")
    }

    @Test func anEmailAddressHasOneAtAndADot() {
        for good in ["ana@example.com", "a.b+c@mail.example.co"] {
            #expect(good.wholeMatch(of: AgendaWords.emailPattern) != nil, "\(good)")
        }
        for bad in ["ana", "ana@example", "ana@@example.com", "an a@example.com", "@example.com", ""] {
            #expect(bad.wholeMatch(of: AgendaWords.emailPattern) == nil, "\(bad)")
        }
    }

    @Test func coloursAreReadFromHex() {
        #expect(AgendaPalette.color("#039be5") == Color(red: 3 / 255, green: 155 / 255, blue: 229 / 255))
        #expect(AgendaPalette.color(" 33B679 ") == Color(red: 51 / 255, green: 182 / 255, blue: 121 / 255))
        #expect(AgendaPalette.color("") == nil)
        #expect(AgendaPalette.color("#fff") == nil)
        #expect(AgendaPalette.color("#zzzzzz") == nil)
        #expect(AgendaPalette.color("7") == nil, "a Google colour id is not a colour")
    }
}
