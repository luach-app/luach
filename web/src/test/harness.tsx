import { vi } from 'vitest'
import type { Member } from '../lib/types'

export const member: Member = {
  id: 1,
  username: 'robin',
  email: 'robin@example.com',
  display_name: 'Robin',
  timezone: 'America/New_York',
  language: 'en',
  is_owner: true,
  last_seen: null,
  emails: ['robin@example.com'],
  notify_emails: [],
  notify_pending: [],
}

/** jsdom answers every media query false; this makes one of them true. */
export function screenWidth(matching: (query: string) => boolean) {
  window.matchMedia = ((query: string) => ({
    matches: matching(query),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

export const wideScreen = () => screenWidth(() => true)
export const phoneScreen = () => screenWidth(() => false)

export const event = (over: Record<string, unknown> = {}) => ({
  id: 'e1',
  title: 'Dentist',
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

/** Freeze "now" so a month grid is the same one every run. */
export function freezeTime(iso = '2026-09-17T18:00:00Z') {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(iso))
}
