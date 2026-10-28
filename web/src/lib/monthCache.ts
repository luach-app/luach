import { useEffect, useState } from 'react'
import { calendar, errorMessage, onCalendarWrite } from './api'
import type { CalendarEvent } from './types'
import { addDays, sortEvents } from './time'
import { monthGrid } from './months'

/**
 * Events per visible month grid, keyed "YYYY-MM". Module-level so the cache
 * survives tab switches. It is dropped after any write anywhere in the app (an
 * approve, a deny, an edit: api.onCalendarWrite), and a month on screen is asked
 * again when the tab comes back and every REVALIDATE_MS while it is looked at —
 * a partner's change, or a hold approved on another device, used to appear only
 * after a hard reload.
 */
const cache = new Map<string, CalendarEvent[]>()
/**
 * What the last load returned, kept after the cache is dropped. A month that
 * is refreshing already has something true enough to show, and blanking the
 * grid to skeletons on every refresh made the whole calendar jump each time
 * the assistant finished a sentence.
 */
const shown = new Map<string, CalendarEvent[]>()
/** At most one request per month: who asks while one is out waits for it. */
const inflight = new Map<string, { p: Promise<CalendarEvent[]>; gen: number }>()
/** When each month last came back, so a burst of reasons to ask costs one request. */
const fetchedAt = new Map<string, number>()
const listeners = new Set<() => void>()
/**
 * Bumped by every change. A load started before a change does not fill the cache
 * when it lands (it may predate the change); the month is asked once more after it.
 */
let generation = 0

/** How often a month on screen is asked again while the tab is visible. */
export const REVALIDATE_MS = 90_000
/** A month that came back this recently is not asked again for a revalidation. */
const FRESH_MS = 15_000

/**
 * Drop everything, including what is on screen. Sign-out calls this: the next
 * person to use this browser must not be shown the last one's events while
 * their own month loads.
 */
export function forgetMonths() {
  generation += 1
  cache.clear()
  shown.clear()
  inflight.clear()
  fetchedAt.clear()
  for (const l of listeners) l()
}

export function invalidateMonths() {
  generation += 1
  for (const [ym, events] of cache) shown.set(ym, events)
  cache.clear()
  fetchedAt.clear()
  for (const l of listeners) l()
}

onCalendarWrite(() => invalidateMonths())

function fetchMonth(ym: string, tz: string, fresh = false): Promise<CalendarEvent[]> {
  const hit = cache.get(ym)
  if (hit && !fresh) return Promise.resolve(hit)
  const pending = inflight.get(ym)
  if (pending) {
    if (pending.gen === generation) return pending.p
    // Started before the latest change: let it land, then ask once more — still
    // one request at a time for this month.
    return pending.p.then(
      () => fetchMonth(ym, tz),
      () => fetchMonth(ym, tz),
    )
  }
  const gen = generation
  const grid = monthGrid(ym)
  // `end` is passed as the day after the last cell so an exclusive server bound still covers it.
  const p: Promise<CalendarEvent[]> = calendar
    .list(grid.first, addDays(grid.last, 1))
    .then((r) => {
      const list = sortEvents(r.events, tz)
      if (gen === generation) {
        cache.set(ym, list)
        shown.set(ym, list)
        fetchedAt.set(ym, Date.now())
      }
      return list
    })
    .finally(() => {
      if (inflight.get(ym)?.p === p) inflight.delete(ym)
    })
  inflight.set(ym, { p, gen })
  return p
}

/** Ask a month on screen again, unless it has just come back or is on its way. */
function revalidate(ym: string, tz: string): Promise<CalendarEvent[]> | null {
  if (inflight.has(ym)) return null
  const at = fetchedAt.get(ym)
  if (at !== undefined && Date.now() - at < FRESH_MS) return null
  return fetchMonth(ym, tz, true)
}

/** The same events, in the same order, with the same details: no redraw needed. */
function same(a: CalendarEvent[] | null, b: CalendarEvent[]): boolean {
  return a !== null && a.length === b.length && JSON.stringify(a) === JSON.stringify(b)
}

export interface MonthState {
  events: CalendarEvent[] | null
  error: string
}

/** The events covering the grid of `ym`; `events` is null only until the first
 * load for that month lands — a refresh keeps showing the last ones. */
export function useMonthEvents(ym: string, tz: string): MonthState & { reload: () => void } {
  const [state, setState] = useState<MonthState>(() => ({ events: cache.get(ym) ?? shown.get(ym) ?? null, error: '' }))
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const bump = () => setTick((n) => n + 1)
    listeners.add(bump)
    return () => {
      listeners.delete(bump)
    }
  }, [])

  // A month that failed has nothing to show and no reason to change: without
  // this, a tab left open through a server problem stays empty for ever while
  // the rest of the app carries on polling. Coming back to the tab retries.
  useEffect(() => {
    if (!state.error) return
    const retry = () => {
      if (document.visibilityState === 'visible') setTick((n) => n + 1)
    }
    document.addEventListener('visibilitychange', retry)
    window.addEventListener('online', retry)
    return () => {
      document.removeEventListener('visibilitychange', retry)
      window.removeEventListener('online', retry)
    }
  }, [state.error])

  // What someone else changed: asked again when the tab is looked at, and every
  // REVALIDATE_MS while it is. Nothing is asked while the tab is hidden.
  useEffect(() => {
    let alive = true
    const check = () => {
      if (document.visibilityState !== 'visible') return
      revalidate(ym, tz)?.then(
        (events) => {
          if (alive) setState((s) => (same(s.events, events) && !s.error ? s : { events, error: '' }))
        },
        () => {
          /* a revalidation that fails keeps what is shown; the next one tries again */
        },
      )
    }
    const timer = window.setInterval(check, REVALIDATE_MS)
    document.addEventListener('visibilitychange', check)
    return () => {
      alive = false
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', check)
    }
  }, [ym, tz])

  useEffect(() => {
    let alive = true
    const hit = cache.get(ym) ?? shown.get(ym)
    setState({ events: hit ?? null, error: '' })
    fetchMonth(ym, tz).then(
      (events) => {
        if (alive) setState((s) => (same(s.events, events) && !s.error ? s : { events, error: '' }))
      },
      (e) => {
        if (alive) setState((s) => ({ events: s.events, error: errorMessage(e) || 'Could not load this month.' }))
      },
    )
    return () => {
      alive = false
    }
  }, [ym, tz, tick])

  return {
    ...state,
    reload: () => {
      invalidateMonths()
      setTick((n) => n + 1)
    },
  }
}
