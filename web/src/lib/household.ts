import { useEffect, useState } from 'react'
import { errorMessage, household as householdApi } from './api'
import type { CalendarInfo, HouseholdCalendars } from './types'

/**
 * The household's calendars and defaults, fetched once per session and shared
 * by the agenda, the event sheet and Settings. `invalidateHousehold()` after a
 * change refetches for every mounted consumer.
 */
let cache: HouseholdCalendars | null = null
let inflight: Promise<HouseholdCalendars> | null = null
const listeners = new Set<() => void>()

export function invalidateHousehold() {
  cache = null
  inflight = null
  for (const l of listeners) l()
}

/** Google's calendar list is a network hop away; past this we say so instead
 *  of spinning. */
const LOAD_TIMEOUT_MS = 20_000

function load(): Promise<HouseholdCalendars> {
  if (cache) return Promise.resolve(cache)
  if (inflight) return inflight
  inflight = householdApi
    .calendars(AbortSignal.timeout(LOAD_TIMEOUT_MS))
    .then((h) => {
      cache = h
      return h
    })
    .finally(() => {
      inflight = null
    })
  return inflight
}

export interface HouseholdState {
  data: HouseholdCalendars | null
  error: string
}

/** `enabled` false: asks nothing (the house board brings its own calendars). */
export function useHousehold(enabled = true): HouseholdState & { reload: () => void } {
  const [state, setState] = useState<HouseholdState>({ data: cache, error: '' })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const bump = () => setTick((n) => n + 1)
    listeners.add(bump)
    return () => {
      listeners.delete(bump)
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    let alive = true
    load().then(
      (data) => {
        if (alive) setState({ data, error: '' })
      },
      (e) => {
        if (alive) setState((s) => ({ data: s.data, error: errorMessage(e) }))
      },
    )
    return () => {
      alive = false
    }
  }, [tick, enabled])

  return { ...state, reload: invalidateHousehold }
}

/** The calendars the household actually uses, default first. */
export function enabledCalendars(h: HouseholdCalendars | null): CalendarInfo[] {
  if (!h) return []
  const list = h.available.filter((c) => c.enabled)
  return list.sort((a, b) => Number(b.default) - Number(a.default) || a.name.localeCompare(b.name))
}

export function calendarOf(h: HouseholdCalendars | null, id: string | undefined): CalendarInfo | undefined {
  return id ? h?.available.find((c) => c.id === id) : undefined
}

/** The colour a calendar paints its events with; the accent when unknown. */
export function calendarColor(h: HouseholdCalendars | null, id: string | undefined): string {
  return calendarOf(h, id)?.color || 'var(--accent)'
}
