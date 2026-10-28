import { describe, expect, it } from 'vitest'
import {
  addDays,
  addMinutesInput,
  dateInZone,
  eventDays,
  eventStartDay,
  formatDateLong,
  formatEventRange,
  formatTime,
  resolveLocale,
  sortEvents,
  todayISO,
  toLocalInput,
} from '../time'
import type { CalendarEvent } from '../types'

const ev = (over: Partial<CalendarEvent>): CalendarEvent => ({
  id: 'e1',
  title: 'Thing',
  start: '2026-09-17T15:00:00-04:00',
  end: '2026-09-17T16:00:00-04:00',
  all_day: false,
  location: '',
  description: '',
  recurrence: [],
  recurring_event_id: '',
  html_link: '',
  creator: '',
  updated: '',
  calendar_id: 'home',
  attendees: [],
  invite_error: '',
  ...over,
})

describe('days and zones', () => {
  it('walks dates without tripping over month ends or leap years', () => {
    expect(addDays('2026-09-30', 1)).toBe('2026-10-01')
    expect(addDays('2026-01-01', -1)).toBe('2025-12-31')
    expect(addDays('2024-02-28', 1)).toBe('2024-02-29')
    expect(addDays('2026-02-28', 1)).toBe('2026-03-01')
  })

  it('reads the same moment as a different day in different zones', () => {
    const midnightUTC = new Date('2026-09-18T03:00:00Z')
    expect(dateInZone(midnightUTC, 'America/New_York')).toBe('2026-09-17')
    expect(dateInZone(midnightUTC, 'Europe/Madrid')).toBe('2026-09-18')
  })

  it('knows today in the zone it was asked about', () => {
    expect(todayISO('America/New_York')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('falls back to a sane locale', () => {
    expect(resolveLocale('auto')).toBeTruthy()
    expect(resolveLocale('he')).toBe('he')
    expect(resolveLocale(undefined)).toBeTruthy()
  })
})

describe('reading an event', () => {
  it('shows the time in the reader’s zone, not the event’s', () => {
    expect(formatTime('2026-09-17T15:00:00-04:00', 'America/New_York', 'en')).toMatch(/3:00/)
    expect(formatTime('2026-09-17T15:00:00-04:00', 'Europe/Madrid', 'en')).toMatch(/9:00/)
  })

  it('names the day an event starts on', () => {
    expect(eventStartDay(ev({}), 'America/New_York')).toBe('2026-09-17')
    expect(eventStartDay(ev({ start: '2026-09-20' }), 'America/New_York')).toBe('2026-09-20')
  })

  it('spreads a multi-day event across the days it covers, clipped to the window', () => {
    const trip = ev({ start: '2026-09-18', end: '2026-09-21', all_day: true })
    expect(eventDays(trip, 'America/New_York', '2026-09-01', '2026-09-30')).toEqual([
      '2026-09-18',
      '2026-09-19',
      '2026-09-20',
    ])
    expect(eventDays(trip, 'America/New_York', '2026-09-19', '2026-09-19')).toEqual(['2026-09-19'])
  })

  it('sorts all-day first, then by the clock', () => {
    const list = [
      ev({ id: 'late', start: '2026-09-17T18:00:00-04:00' }),
      ev({ id: 'allday', start: '2026-09-17', all_day: true }),
      ev({ id: 'early', start: '2026-09-17T09:00:00-04:00' }),
    ]
    expect(sortEvents(list, 'America/New_York').map((e) => e.id)).toEqual(['allday', 'early', 'late'])
  })

  it('writes a range a person can read', () => {
    expect(formatEventRange(ev({}), 'America/New_York', 'en')).toMatch(/3:00/)
    expect(formatDateLong('2026-09-17', 'en')).toMatch(/September/)
  })
})

describe('the form’s own clock', () => {
  it('round-trips an ISO instant into a datetime-local value', () => {
    expect(toLocalInput('2026-09-17T15:00:00-04:00', 'America/New_York')).toBe('2026-09-17T15:00')
  })

  it('adds minutes across an hour and a day boundary', () => {
    expect(addMinutesInput('2026-09-17T15:00', 30)).toBe('2026-09-17T15:30')
    expect(addMinutesInput('2026-09-17T23:45', 30)).toBe('2026-09-18T00:15')
  })
})
