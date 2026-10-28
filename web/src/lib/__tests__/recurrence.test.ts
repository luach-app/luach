import { describe, expect, it } from 'vitest'
import { describeRepeat, repeatOf, repeatWord } from '../recurrence'

describe('reading a repeat', () => {
  it('recognises the ones the menu can say', () => {
    expect(repeatOf(undefined)).toBe('none')
    expect(repeatOf([])).toBe('none')
    expect(repeatOf(['RRULE:FREQ=DAILY'])).toBe('daily')
    expect(repeatOf(['RRULE:FREQ=WEEKLY;BYDAY=TU'])).toBe('weekly')
    expect(repeatOf(['RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TU'])).toBe('biweekly')
    expect(repeatOf(['RRULE:FREQ=MONTHLY'])).toBe('monthly')
    expect(repeatOf(['RRULE:FREQ=YEARLY'])).toBe('yearly')
  })

  it('calls anything it cannot say custom, so it is left alone', () => {
    expect(repeatOf(['RRULE:FREQ=WEEKLY;COUNT=5'])).toBe('custom')
    expect(repeatOf(['RRULE:FREQ=MONTHLY;BYSETPOS=2;BYDAY=TU'])).toBe('custom')
    expect(repeatOf(['RRULE:FREQ=DAILY;UNTIL=20261231T000000Z'])).toBe('custom')
    expect(repeatOf(['RRULE:FREQ=DAILY;INTERVAL=3'])).toBe('custom')
  })
})

describe('writing a repeat', () => {
  it('sends the menu’s word, for the server to put on the event’s own day', () => {
    // The weekday used to be worked out here from new Date('2026-09-17'), which is UTC
    // midnight: Wednesday evening in New York, so a weekly all-day Thursday repeated on Wednesdays.
    expect(repeatWord('weekly')).toBe('weekly')
    expect(repeatWord('biweekly')).toBe('biweekly')
    expect(repeatWord('daily')).toBe('daily')
  })

  it('has no rule for "does not repeat", and none for one it cannot say', () => {
    expect(repeatWord('none')).toBe('')
    expect(repeatWord('custom')).toBe('')
  })
})

describe('saying a repeat out loud', () => {
  it('reads as English rather than as an RRULE', () => {
    expect(describeRepeat(['RRULE:FREQ=WEEKLY;BYDAY=TH'])).toBe('Every week on Thursday')
    expect(describeRepeat(['RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE'])).toBe('Every 2 weeks on Monday, Wednesday')
    expect(describeRepeat(['RRULE:FREQ=DAILY'])).toBe('Every day')
    expect(describeRepeat(['RRULE:FREQ=MONTHLY'])).toBe('Every month')
    expect(describeRepeat(['RRULE:FREQ=WEEKLY;BYDAY=TU;COUNT=3'])).toContain('3 times')
    expect(describeRepeat(['RRULE:FREQ=DAILY;UNTIL=20261231T000000Z'])).toContain('until 2026-12-31')
  })

  it('says nothing when there is nothing to say', () => {
    expect(describeRepeat(undefined)).toBe('')
    expect(describeRepeat([])).toBe('')
  })
})
