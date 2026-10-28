---
name: forwarded-mail
description: Use when the message is a forwarded email or a pasted confirmation, booking, ticket or notice — "Fwd:", "Your appointment is confirmed", a flight itinerary, a school letter, a delivery window, a reservation.
allowed-tools: create_event find_events
---
# Forwarded mail

- Find the real appointment: who, what, the date, the time, the place. Ignore
  signatures, footers, unsubscribe lines, marketing and legal text.
- Title it the way the family would say it: "Dentist — Dr. Stein", "Flight to Madrid",
  "Parent–teacher meeting", "IKEA delivery".
- The street address goes in `location`; the confirmation number and anything useful
  from the mail in `description`; the mail's own words in `source_text`.
- A date without a year is the next one to come. A time given as a window
  ("between 9 and 12") is that span. A flight is its departure, in the departure
  airport's local time as written.
- If the mail names someone in the family it is for, that is `for_whom`.
- Look first with `find_events`: a confirmation often repeats something already on
  the calendar. If it is there, say so instead of adding it twice.
