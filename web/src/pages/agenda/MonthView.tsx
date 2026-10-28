import { useEffect, useMemo, useState } from 'react'
import type { CalendarEvent } from '../../lib/types'
import { eventDays, formatDateLong, formatDayName, todayISO } from '../../lib/time'
import { addMonths, formatMonthYear, monthGrid, ymOf } from '../../lib/months'
import { useMonthEvents } from '../../lib/monthCache'
import { useMediaQuery } from '../../lib/hooks'
import { useHousehold } from '../../lib/household'
import { eventColor, personOf, useFamily } from '../../lib/family'
import { Button } from '../../components/Button'
import { EventCard } from '../../components/EventCard'
import { PlusIcon } from '../../components/Icons'
import { CompactGrid, DesktopGrid } from './MonthGrid'
import { MonthPicker } from './MonthPicker'
import type { ViewProps } from './Upcoming'

const isField = (el: EventTarget | null) => el instanceof HTMLElement && /^(input|textarea|select)$/i.test(el.tagName)

export function MonthView({ tz, locale, selected, onSelect, onOpen, onCreate, dayPanel = true }: ViewProps) {
  const today = todayISO(tz)
  const [ym, setYm] = useState(() => ymOf(selected))
  const [picker, setPicker] = useState(false)
  const wide = useMediaQuery('(min-width: 900px)')
  const grid = useMemo(() => monthGrid(ym), [ym])
  const { events, error, reload } = useMonthEvents(ym, tz)
  const { data: household } = useHousehold()
  const family = useFamily()

  // Keep the month in step when the parent moves the selection (e.g. from Upcoming).
  useEffect(() => {
    setYm(ymOf(selected))
  }, [selected])

  const goto = (next: string) => {
    if (next === ym) return
    setYm(next)
    onSelect(next === ymOf(today) ? today : `${next}-01`)
  }
  const goToday = () => {
    setYm(ymOf(today))
    onSelect(today)
  }

  // ←/→ change month, Home = today — unless a field or a dialog has the keyboard.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (isField(e.target) || e.altKey || e.ctrlKey || e.metaKey || document.querySelector('[role="dialog"]')) return
      if (e.key === 'ArrowLeft') goto(addMonths(ym, -1))
      else if (e.key === 'ArrowRight') goto(addMonths(ym, 1))
      else if (e.key === 'Home') goToday()
      else return
      e.preventDefault()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  })

  const byDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>()
    for (const ev of events ?? []) {
      for (const d of eventDays(ev, tz, grid.first, grid.last)) map.set(d, [...(map.get(d) ?? []), ev])
    }
    return map
  }, [events, tz, grid])

  const dayEvents = byDay.get(selected) ?? []
  const loading = events === null && !error
  const GridCmp = wide ? DesktopGrid : CompactGrid

  return (
    <div className="fade-up" aria-label="Month view">
      <div className="mt-1 flex items-center gap-1">
        <Button size="icon" variant="ghost" aria-label="Previous month" onClick={() => goto(addMonths(ym, -1))} className="h-10 w-10">
          ‹
        </Button>
        <button type="button" onClick={() => setPicker(true)} aria-haspopup="dialog" className="min-w-0 flex-1 truncate rounded-xl px-2 py-1.5 text-center text-xl font-semibold hover:bg-surface-2 sm:flex-none sm:text-start" aria-label={`${formatMonthYear(ym, locale)}, choose month`}>
          {formatMonthYear(ym, locale)}
        </button>
        <Button size="icon" variant="ghost" aria-label="Next month" onClick={() => goto(addMonths(ym, 1))} className="h-10 w-10">
          ›
        </Button>
        <Button size="sm" variant="ghost" onClick={goToday} disabled={ym === ymOf(today) && selected === today} className="ms-auto">
          Today
        </Button>
      </div>

      {error ? (
        <div className="mt-2 flex flex-wrap items-center gap-2 px-1" role="alert">
          <p className="text-sm text-danger">{error}</p>
          <Button size="sm" variant="ghost" onClick={reload}>
            Try again
          </Button>
        </div>
      ) : null}

      <div className="mt-3 flex min-h-0 flex-col gap-5">
        <div className="min-w-0 flex-1">
          <GridCmp grid={grid} byDay={byDay} loading={loading} today={today} selected={selected} tz={tz} locale={locale} onSelect={onSelect} onOpen={onOpen} />
        </div>

      {dayPanel ? (
      <section className="w-full" aria-live="polite" aria-label="Selected day">
        <h2 className="px-1 text-sm font-medium text-text/90 xl:text-base">
          {formatDateLong(selected, locale)}
          {selected === today ? ' · today' : ''}
        </h2>
        {loading ? (
          <div className="mt-2 flex flex-col gap-2">
            <div className="card h-16 pulse-dot" />
            <div className="card h-16 pulse-dot" />
          </div>
        ) : dayEvents.length === 0 ? (
          <div className="card mt-2 px-5 py-6 text-center text-muted">
            Nothing on {selected === today ? 'today' : formatDayName(selected, locale, 'long')}.
            <div className="mt-3">
              <Button size="sm" onClick={() => onCreate(selected)}>
                <PlusIcon width={16} height={16} /> Add something
              </Button>
            </div>
          </div>
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {dayEvents.map((ev) => (
              <li key={`${ev.id}-${selected}`}>
                <EventCard event={ev} tz={tz} locale={locale} color={eventColor(family, household, ev)} who={personOf(family, ev.leader)?.name} onClick={() => onOpen(ev)} />
              </li>
            ))}
          </ul>
        )}
      </section>
      ) : null}
      </div>

      {picker ? <MonthPicker ym={ym} todayYm={ymOf(today)} locale={locale} onPick={(next) => { setPicker(false); goto(next) }} onClose={() => setPicker(false)} /> : null}
    </div>
  )
}
