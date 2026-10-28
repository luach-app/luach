import type { CalendarEvent } from '../../lib/types'
import { DATE_RE, formatDayNumber, formatTime } from '../../lib/time'
import { weekdayNames } from '../../lib/months'
import type { MonthGrid as Grid } from '../../lib/months'
import { useMediaQuery } from '../../lib/hooks'
import { useHousehold } from '../../lib/household'
import { eventColor, useFamily } from '../../lib/family'

export interface GridProps {
  grid: Grid
  byDay: Map<string, CalendarEvent[]>
  loading: boolean
  today: string
  selected: string
  tz: string
  locale: string
  onSelect: (day: string) => void
  onOpen: (ev: CalendarEvent) => void
}

/** Rows per cell before "+N more": three on a laptop, five on a wide screen. */
const MAX_PER_CELL = 3
const MAX_PER_CELL_WIDE = 5
const isAllDay = (ev: CalendarEvent) => ev.all_day || DATE_RE.test(ev.start)

function Weekdays({ locale, narrow }: { locale: string; narrow: boolean }) {
  return (
    <div className="grid grid-cols-7 text-center text-xs font-semibold uppercase tracking-wider text-muted" aria-hidden>
      {weekdayNames(locale, narrow ? 'narrow' : 'short').map((n, i) => (
        <div key={i} className="py-2">
          {n}
        </div>
      ))}
    </div>
  )
}

/**
 * ≥900px: seven columns. Each cell lists a few events as readable rows — the
 * time on a thin line of its own, the title wrapping to three or four — and a "+N more" past that.
 */
export function DesktopGrid({ grid, byDay, loading, today, selected, tz, locale, onSelect, onOpen }: GridProps) {
  const wide = useMediaQuery('(min-width: 1280px)')
  const max = wide ? MAX_PER_CELL_WIDE : MAX_PER_CELL
  const { data: household } = useHousehold()
  const family = useFamily()
  return (
    <div className="card overflow-hidden">
      <Weekdays locale={locale} narrow={false} />
      <div role="grid" aria-label="Month" className="grid grid-cols-7 border-t border-line">
        {grid.weeks.flat().map((day) => {
          const inMonth = day.startsWith(grid.ym)
          const list = byDay.get(day) ?? []
          const extra = list.length - max
          const on = day === selected
          return (
            <div
              key={day}
              role="gridcell"
              aria-selected={on}
              onClick={() => onSelect(day)}
              className={`min-h-[9rem] min-w-0 border-b border-e border-line p-1.5 text-sm 2xl:min-h-[12rem] transition-colors xl:min-h-[10.5rem] [&:nth-child(7n)]:border-e-0 ${inMonth ? '' : 'bg-surface-2/40 text-muted/70'} ${on ? 'bg-accent/8' : 'hover:bg-surface-2/60'}`}
            >
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onSelect(day)
                }}
                aria-label={day}
                aria-pressed={on}
                className={`mb-1.5 flex h-8 w-8 items-center justify-center rounded-full text-[15px] font-medium ${day === today ? 'ring-2 ring-accent' : ''} ${on ? 'bg-accent text-accent-on' : ''}`}
              >
                {formatDayNumber(day)}
              </button>
              {loading ? (
                <div className="flex flex-col gap-1.5">
                  <span className="h-9 w-4/5 rounded-lg bg-surface-2 pulse-dot" />
                  <span className="h-9 w-3/5 rounded-lg bg-surface-2 pulse-dot" />
                </div>
              ) : (
                <ul className="flex flex-col gap-1">
                  {list.slice(0, max).map((ev) => {
                    const allDay = isAllDay(ev)
                    const color = eventColor(family, household, ev)
                    return (
                      <li key={ev.id}>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            onOpen(ev)
                          }}
                          style={{ borderInlineStartColor: color }}
                          className={`block w-full min-w-0 rounded-md border-s-[3px] px-1.5 py-1 text-left text-[13px] leading-tight transition-colors ${allDay ? 'bg-success/12 text-success hover:bg-success/20' : 'bg-surface-2/70 hover:bg-surface-2'}`}
                          title={allDay ? ev.title : `${formatTime(ev.start, tz, locale)} ${ev.title}`}
                        >
                          {!allDay ? <span className="block text-[11px] leading-tight text-muted tabular-nums">{formatTime(ev.start, tz, locale)}</span> : null}
                          <span className="line-clamp-3 break-normal font-medium xl:line-clamp-4" dir="auto">
                            {ev.title || '(untitled)'}
                          </span>
                        </button>
                      </li>
                    )
                  })}
                  {extra > 0 ? (
                    <li>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          onSelect(day)
                        }}
                        className="px-2 py-0.5 text-xs font-medium text-muted hover:text-accent-text"
                      >
                        +{extra} more
                      </button>
                    </li>
                  ) : null}
                </ul>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** Phones: a compact grid of day numbers with event dots. */
export function CompactGrid({ grid, byDay, loading, today, selected, locale, onSelect }: GridProps) {
  const { data: household } = useHousehold()
  const family = useFamily()
  return (
    <div className="card px-2 pt-1 pb-2">
      <Weekdays locale={locale} narrow />
      <div role="grid" aria-label="Month" className="grid grid-cols-7 gap-y-1">
        {grid.weeks.flat().map((day) => {
          const inMonth = day.startsWith(grid.ym)
          const list = byDay.get(day) ?? []
          const n = list.length
          const on = day === selected
          return (
            <button
              key={day}
              type="button"
              role="gridcell"
              aria-selected={on}
              aria-label={`${day}${n ? `, ${n} events` : ''}`}
              onClick={() => onSelect(day)}
              className={`mx-auto flex h-11 w-11 flex-col items-center justify-center rounded-full text-[15px] transition-colors ${on ? 'bg-accent font-semibold text-accent-on' : day === today ? 'ring-2 ring-accent' : ''} ${inMonth ? '' : 'text-muted/50'} ${!on ? 'hover:bg-surface-2' : ''}`}
            >
              <span className="leading-none">{formatDayNumber(day)}</span>
              <span className="mt-1 flex h-1.5 gap-0.5">
                {loading ? (
                  <span className="h-1.5 w-1.5 rounded-full bg-surface-2 pulse-dot" />
                ) : (
                  list.slice(0, 3).map((ev, i) => <span key={i} className={`h-1.5 w-1.5 rounded-full ${on ? 'bg-accent-on/70' : ''}`} style={on ? undefined : { background: eventColor(family, household, ev) }} />)
                )}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
