import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { calendar, errorMessage } from '../../lib/api'
import type { CalendarEvent } from '../../lib/types'
import { addDays, eventDays, formatDateLong, formatDayName, formatDayNumber, sortEvents, todayISO } from '../../lib/time'
import { useVisiblePoll } from '../../lib/hooks'
import { Button, Spinner } from '../../components/Button'
import { EventCard } from '../../components/EventCard'
import { Notice } from '../../components/Field'
import { PlusIcon } from '../../components/Icons'

const STRIP_DAYS = 14
const COMING_UP_DAYS = 7

export interface ViewProps {
  tz: string
  locale: string
  /** Bumped by the parent after any create/edit/delete. */
  version: number
  selected: string
  onSelect: (day: string) => void
  onOpen: (ev: CalendarEvent) => void
  onCreate: (day: string) => void
  /** False when a rail beside the calendar is already showing the day. */
  dayPanel?: boolean
}

/** The original two-week strip + "coming up" list. */
export function Upcoming({ tz, locale, version, selected, onSelect, onOpen, onCreate }: ViewProps) {
  const today = todayISO(tz)
  const days = useMemo(() => Array.from({ length: STRIP_DAYS }, (_, i) => addDays(today, i)), [today])
  const [events, setEvents] = useState<CalendarEvent[] | null>(null)
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const inStrip = selected >= today && selected < addDays(today, STRIP_DAYS)
  const day = inStrip ? selected : today

  const load = useCallback(async () => {
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    try {
      const res = await calendar.list(today, addDays(today, STRIP_DAYS), ac.signal)
      if (!ac.signal.aborted) {
        setEvents(sortEvents(res.events, tz))
        setError('')
      }
    } catch (e) {
      if (!ac.signal.aborted) setError(errorMessage(e))
    }
  }, [today, tz])

  useVisiblePoll(load, 120_000)
  useEffect(() => {
    if (version > 0) void load()
  }, [version, load])
  useEffect(() => () => abortRef.current?.abort(), [])

  const byDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>()
    const last = addDays(today, STRIP_DAYS)
    for (const ev of events ?? []) {
      for (const d of eventDays(ev, tz, today, last)) map.set(d, [...(map.get(d) ?? []), ev])
    }
    return map
  }, [events, today, tz])

  const selectedEvents = byDay.get(day) ?? []
  const comingUp = useMemo(
    () => Array.from({ length: COMING_UP_DAYS }, (_, i) => addDays(today, i + 1)).map((d) => ({ day: d, events: byDay.get(d) ?? [] })).filter((g) => g.events.length > 0),
    [byDay, today],
  )

  return (
    <div className="fade-up">
      <p className="px-1 text-sm text-muted">
        {formatDateLong(day, locale)}
        {day === today ? ' · today' : ''}
      </p>
      <div role="tablist" aria-label="Next two weeks" className="no-scrollbar -mx-4 mt-3 flex gap-2 overflow-x-auto px-4 pb-1 snap-x">
        {days.map((d) => {
          const on = d === day
          const n = byDay.get(d)?.length ?? 0
          return (
            <button
              key={d}
              role="tab"
              aria-selected={on}
              aria-label={`${formatDayName(d, locale, 'long')} ${formatDayNumber(d)}${n ? `, ${n} events` : ''}`}
              onClick={() => onSelect(d)}
              className={`flex w-14 shrink-0 snap-start flex-col items-center rounded-2xl border py-2.5 transition-colors ${on ? 'border-accent bg-accent text-accent-on' : d === today ? 'border-accent/50 bg-surface text-text' : 'border-line bg-surface text-muted hover:text-text'}`}
            >
              <span className="text-[11px] uppercase tracking-wide">{formatDayName(d, locale)}</span>
              <span className="text-xl font-semibold leading-tight">{formatDayNumber(d)}</span>
              <span className={`mt-1 h-1.5 w-1.5 rounded-full ${n ? (on ? 'bg-accent-on/70' : 'bg-accent') : 'bg-transparent'}`} />
            </button>
          )
        })}
      </div>

      {error ? (
        <div className="mt-4">
          <Notice kind="error">{error}</Notice>
        </div>
      ) : null}

      <section className="mt-5" aria-live="polite">
        {events === null && !error ? (
          <div className="flex justify-center py-10 text-muted">
            <Spinner />
          </div>
        ) : selectedEvents.length === 0 ? (
          <div className="card px-5 py-8 text-center text-muted">
            Nothing on {day === today ? 'today' : formatDayName(day, locale, 'long')}.
            <div className="mt-3">
              <Button size="sm" onClick={() => onCreate(day)}>
                <PlusIcon width={16} height={16} /> Add something
              </Button>
            </div>
          </div>
        ) : (
          <ul className="flex flex-col gap-2">
            {selectedEvents.map((ev) => (
              <li key={`${ev.id}-${day}`}>
                <EventCard event={ev} tz={tz} locale={locale} onClick={() => onOpen(ev)} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {events !== null ? (
        <section className="mt-8">
          <h2 className="px-1 text-xs font-semibold uppercase tracking-wider text-muted">Coming up</h2>
          {comingUp.length === 0 ? (
            <p className="mt-2 px-1 text-sm text-muted">A quiet week ahead.</p>
          ) : (
            <div className="mt-2 flex flex-col gap-5">
              {comingUp.map((g) => (
                <div key={g.day}>
                  <button onClick={() => onSelect(g.day)} className="mb-1.5 px-1 text-sm font-medium text-text/90 hover:text-accent-text">
                    {formatDateLong(g.day, locale)}
                  </button>
                  <ul className="flex flex-col gap-2">
                    {g.events.map((ev) => (
                      <li key={`${ev.id}-${g.day}`}>
                        <EventCard event={ev} tz={tz} locale={locale} onClick={() => onOpen(ev)} />
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </div>
  )
}
