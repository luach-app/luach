import { useState } from 'react'
import type { AgendaWidget, AvailabilityWidget, CompactEvent, EventWidget, Widget } from '../lib/types'
import { addDays, eventStartDay, formatDateShort, formatEventRange, todayISO } from '../lib/time'
import { eventLink, isRecurring } from '../lib/events'
import { OpenLink } from './EventCard'
import { PinIcon, RepeatIcon } from './Icons'
import { personOf, useFamily } from '../lib/family'

/** A row's dot: the colour of the first person it is for, else all-day green or the accent. */
function useDot(ev: CompactEvent): { className: string; style?: { background: string } } {
  const fam = useFamily()
  const who = personOf(fam, ev.leaders?.[0] ?? ev.leader)
  if (who?.hex) return { className: '', style: { background: who.hex } }
  return { className: ev.all_day ? 'bg-success' : 'bg-accent' }
}

interface Ctx {
  tz: string
  locale: string
  /** Opens the shared event sheet; rows are plain text when absent or the row has no id. */
  onOpen?: (ev: CompactEvent) => void
}

export function WidgetCard({ widget, ...ctx }: { widget: Widget } & Ctx) {
  if (widget.kind === 'agenda') return <AgendaCard data={widget.data} {...ctx} />
  if (widget.kind === 'availability') return <AvailabilityCard data={widget.data} {...ctx} />
  return <EventDetailCard data={widget.data} {...ctx} />
}

/* ---- one row, shared by every widget ----------------------------------- */
function EventRow({ event, tz, locale, onOpen, showDay = false }: { event: CompactEvent; showDay?: boolean } & Ctx) {
  const range = formatEventRange(event, tz, locale)
  const time = range === 'All day' ? 'all day' : range || event.when || ''
  const day = showDay && event.start ? formatDateShort(eventStartDay(event, tz), locale) : ''
  const link = eventLink(event)
  const clickable = !!onOpen && !!event.id
  const dot = useDot(event)
  const inner = (
    <>
      <span aria-hidden className={`mt-[7px] h-2 w-2 shrink-0 rounded-full ${dot.className}`} style={dot.style} />
      <span className="w-[5.75rem] shrink-0 pt-px text-[13px] leading-5 text-muted tabular-nums">
        {day ? <span className="block">{day}</span> : null}
        {time}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate font-medium leading-5" dir="auto">
            {event.title || '(untitled)'}
          </span>
          {isRecurring(event) ? <RepeatIcon width={13} height={13} className="shrink-0 text-muted" role="img" aria-label="Recurring" /> : null}
        </span>
        {event.location ? (
          <span className="mt-0.5 flex items-center gap-1 text-[13px] text-muted">
            <PinIcon width={13} height={13} className="shrink-0" />
            <span className="truncate" dir="auto">
              {event.location}
            </span>
          </span>
        ) : null}
      </span>
    </>
  )
  const cls = 'flex min-w-0 flex-1 items-start gap-2.5 px-3 py-2 text-left'
  return (
    <li className={`flex items-start ${clickable ? 'hover:bg-surface-2/70' : ''}`}>
      {clickable ? (
        <button type="button" onClick={() => onOpen(event)} className={`${cls} rounded-xl`} aria-label={`${event.title || 'event'}, ${day ? `${day} ` : ''}${time}`}>
          {inner}
        </button>
      ) : (
        <div className={cls}>{inner}</div>
      )}
      {link ? <OpenLink href={link} className="me-2 mt-1.5" /> : null}
    </li>
  )
}

function dayLabel(day: string, tz: string, locale: string): string {
  const today = todayISO(tz)
  const pretty = formatDateShort(day, locale)
  if (day === today) return `Today · ${pretty}`
  if (day === addDays(today, 1)) return `Tomorrow · ${pretty}`
  return pretty
}

/* ---- agenda ------------------------------------------------------------ */
function AgendaCard({ data, tz, locale, onOpen }: { data: AgendaWidget['data'] } & Ctx) {
  const events = Array.isArray(data.events) ? data.events : []
  const groups = new Map<string, CompactEvent[]>()
  for (const ev of events) {
    const key = eventStartDay(ev, tz)
    groups.set(key, [...(groups.get(key) ?? []), ev])
  }
  const days = [...groups.keys()].sort()
  return (
    <section className="card overflow-hidden" aria-label={data.title || 'Agenda'}>
      <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
        <h3 className="truncate text-sm font-semibold" dir="auto">
          {data.title || 'Agenda'}
        </h3>
        <span className="shrink-0 text-xs text-muted">{events.length ? `${events.length} event${events.length === 1 ? '' : 's'}` : ''}</span>
      </header>
      {events.length === 0 ? (
        <p className="px-4 py-5 text-center text-sm text-muted">Nothing on the calendar for that range.</p>
      ) : (
        days.map((day) => (
          <div key={day || 'undated'} className="border-b border-line last:border-b-0">
            {day ? <div className="px-4 pt-2.5 pb-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted">{dayLabel(day, tz, locale)}</div> : null}
            <ul className="flex flex-col py-1">
              {groups.get(day)!.map((ev, i) => (
                <EventRow key={ev.id ?? `${day}-${i}`} event={ev} tz={tz} locale={locale} onOpen={onOpen} />
              ))}
            </ul>
          </div>
        ))
      )}
      {data.truncated ? <footer className="border-t border-line px-4 py-2 text-xs text-muted">The list was cut short — ask for a narrower range.</footer> : null}
    </section>
  )
}

/* ---- availability ------------------------------------------------------ */
function AvailabilityCard({ data, tz, locale, onOpen }: { data: AvailabilityWidget['data'] } & Ctx) {
  const clashes = Array.isArray(data.clashes) ? data.clashes : []
  const free = !!data.free && clashes.length === 0
  const range = { start: data.start, end: data.end }
  const day = data.start ? dayLabel(eventStartDay(range, tz), tz, locale) : ''
  const time = formatEventRange(range, tz, locale)
  const tone = free ? 'border-success/30 bg-[color-mix(in_srgb,var(--success)_7%,var(--surface))]' : 'border-danger/30 bg-[color-mix(in_srgb,var(--danger)_7%,var(--surface))]'
  return (
    <section className={`card overflow-hidden ${tone}`} aria-label={free ? 'Free' : 'Busy'}>
      <div className="flex items-center gap-3 px-4 py-3">
        <span aria-hidden className={`h-2.5 w-2.5 shrink-0 rounded-full ${free ? 'bg-success' : 'bg-danger'}`} />
        <div className="min-w-0 flex-1">
          <div className={`font-semibold ${free ? 'text-success' : 'text-danger'}`}>{free ? 'Free' : 'Busy'}</div>
          <div className="truncate text-sm text-muted">{[day, time].filter(Boolean).join(' · ')}</div>
        </div>
      </div>
      {clashes.length ? (
        <ul className="flex flex-col border-t border-line py-1">
          {clashes.map((ev, i) => (
            <EventRow key={ev.id ?? i} event={ev} tz={tz} locale={locale} onOpen={onOpen} showDay={eventStartDay(ev, tz) !== eventStartDay(range, tz)} />
          ))}
        </ul>
      ) : null}
    </section>
  )
}

/* ---- single event ------------------------------------------------------ */
function EventDetailCard({ data, tz, locale, onOpen }: { data: EventWidget['data'] } & Ctx) {
  const ev = data.event ?? {}
  const [expanded, setExpanded] = useState(false)
  const desc = (ev.description ?? '').trim()
  const long = desc.length > 180 || desc.split('\n').length > 3
  const when = formatEventRange(ev, tz, locale)
  const day = ev.start ? dayLabel(eventStartDay(ev, tz), tz, locale) : ''
  const link = eventLink(ev)
  const clickable = !!onOpen && !!ev.id
  const dot = useDot(ev)
  return (
    <section className="card px-4 py-3" aria-label={ev.title || 'Event'}>
      <div className="flex items-start gap-3">
        <span aria-hidden className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${dot.className}`} style={dot.style} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {clickable ? (
              <button type="button" onClick={() => onOpen(ev)} className="truncate text-left font-semibold hover:text-accent-text" dir="auto">
                {ev.title || '(untitled)'}
              </button>
            ) : (
              <span className="truncate font-semibold" dir="auto">
                {ev.title || '(untitled)'}
              </span>
            )}
            {isRecurring(ev) ? <RepeatIcon width={14} height={14} className="shrink-0 text-muted" role="img" aria-label="Recurring" /> : null}
          </div>
          <div className="text-sm text-muted">{[day, when].filter(Boolean).join(' · ') || ev.when}</div>
          {ev.location ? (
            <div className="mt-1 flex items-center gap-1 text-sm text-muted">
              <PinIcon width={14} height={14} className="shrink-0" />
              <span className="truncate" dir="auto">
                {ev.location}
              </span>
            </div>
          ) : null}
          {desc ? (
            <div className="mt-2">
              <p className={`whitespace-pre-wrap text-sm text-text/90 ${expanded ? '' : 'line-clamp-3'}`} dir="auto">
                {desc}
              </p>
              {long ? (
                <button type="button" onClick={() => setExpanded((v) => !v)} className="mt-1 text-xs font-medium text-accent-text hover:underline" aria-expanded={expanded}>
                  {expanded ? 'less' : 'more'}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
        {link ? <OpenLink href={link} className="-m-1" /> : null}
      </div>
    </section>
  )
}
