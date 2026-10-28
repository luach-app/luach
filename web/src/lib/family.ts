import { useEffect, useState } from 'react'
import { family as familyApi } from './api'
import { calendarColor } from './household'
import type { CalendarEvent, Family, HouseholdCalendars, Person } from './types'

/**
 * The family, fetched once per session and shared by the agenda, the event
 * sheet and the owner's editor. `invalidateFamily()` after a change refetches
 * for every mounted consumer.
 */
let cache: Family | null = null
let inflight: Promise<Family> | null = null
const listeners = new Set<() => void>()

export function invalidateFamily() {
  cache = null
  inflight = null
  for (const l of listeners) l()
}

function load(): Promise<Family> {
  if (cache) return Promise.resolve(cache)
  if (!inflight) {
    inflight = familyApi
      .get()
      .then((f) => {
        cache = f
        return f
      })
      .finally(() => {
        inflight = null
      })
  }
  return inflight
}

/** `enabled` false: asks nothing (the house board brings its own people). */
export function useFamily(enabled = true): Family | null {
  const [data, setData] = useState<Family | null>(cache)
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
    // A family that will not load is not worth an error on the agenda: events
    // simply keep their calendar's colour.
    load().then(
      (f) => alive && setData(f),
      () => undefined,
    )
    return () => {
      alive = false
    }
  }, [tick, enabled])
  return data
}

/** A name for an example sentence: one of the household's own children, else anyone. */
export function exampleName(f: Family | null): string {
  const people = f?.people ?? []
  return (people.find((p) => p.kind === 'kid') ?? people[0])?.name ?? 'someone'
}

export function personOf(f: Family | null, key: string | undefined): Person | undefined {
  return key ? f?.people.find((p) => p.key === key) : undefined
}

/** An event is painted in its leader's colour; otherwise its calendar's. */
export function eventColor(f: Family | null, h: HouseholdCalendars | null, ev: Pick<CalendarEvent, 'leader' | 'calendar_id'>): string {
  return personOf(f, ev.leader)?.hex || calendarColor(h, ev.calendar_id)
}
