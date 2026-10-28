import type { CalendarEvent, CompactEvent } from './types'

export const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

export function resolveLocale(language: string | undefined): string {
  if (language === 'en' || language === 'es' || language === 'he') return language
  return typeof navigator !== 'undefined' ? navigator.language : 'en'
}

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

export function timeZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] }
  try {
    const list = intl.supportedValuesOf?.('timeZone') ?? []
    return list.length ? list : ['UTC']
  } catch {
    return ['UTC']
  }
}

function parts(date: Date, tz: string, opts: Intl.DateTimeFormatOptions): Record<string, string> {
  const out: Record<string, string> = {}
  for (const p of new Intl.DateTimeFormat('en-CA', { timeZone: tz, ...opts }).formatToParts(date)) {
    out[p.type] = p.value
  }
  return out
}

/** YYYY-MM-DD of `date` as seen in `tz`. */
export function dateInZone(date: Date, tz: string): string {
  const p = parts(date, tz, { year: 'numeric', month: '2-digit', day: '2-digit' })
  return `${p.year}-${p.month}-${p.day}`
}

export function todayISO(tz: string): string {
  return dateInZone(new Date(), tz)
}

/** Add days to a YYYY-MM-DD string (pure calendar arithmetic). */
export function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  const t = Date.UTC(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + n)
  return new Date(t).toISOString().slice(0, 10)
}

/** A Date pinned to noon UTC of that calendar day, safe for weekday/month formatting in UTC. */
function noonUTC(iso: string): Date {
  return new Date(`${iso}T12:00:00Z`)
}

export function formatDayName(iso: string, locale: string, style: 'short' | 'long' = 'short'): string {
  return new Intl.DateTimeFormat(locale, { timeZone: 'UTC', weekday: style }).format(noonUTC(iso))
}

export function formatDayNumber(iso: string): string {
  return String(Number(iso.slice(8, 10)))
}

export function formatDateLong(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    timeZone: 'UTC',
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  }).format(noonUTC(iso))
}

export function formatDateShort(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' }).format(
    noonUTC(iso),
  )
}

export function formatTime(isoDateTime: string, tz: string, locale: string): string {
  const d = new Date(isoDateTime)
  if (Number.isNaN(d.getTime())) return isoDateTime
  return new Intl.DateTimeFormat(locale, { timeZone: tz, hour: 'numeric', minute: '2-digit' }).format(d)
}

export function formatDateTime(isoDateTime: string, tz: string, locale: string): string {
  const d = new Date(isoDateTime)
  if (Number.isNaN(d.getTime())) return isoDateTime
  return new Intl.DateTimeFormat(locale, {
    timeZone: tz,
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  }).format(d)
}

/** "3:00 – 3:45 PM", "All day", or "Tue 16 Sep, 3:00 PM" when it spans days. */
export function formatEventRange(ev: CompactEvent, tz: string, locale: string): string {
  if (!ev.start) return ''
  if (ev.all_day || DATE_RE.test(ev.start)) {
    const endInc = ev.end && DATE_RE.test(ev.end) ? addDays(ev.end, -1) : ev.start
    if (endInc && endInc !== ev.start) {
      return `${formatDateShort(ev.start, locale)} – ${formatDateShort(endInc, locale)}`
    }
    return 'All day'
  }
  const startDay = dateInZone(new Date(ev.start), tz)
  const endDay = ev.end ? dateInZone(new Date(ev.end), tz) : startDay
  if (endDay !== startDay && ev.end) {
    return `${formatDateTime(ev.start, tz, locale)} – ${formatDateTime(ev.end, tz, locale)}`
  }
  const s = formatTime(ev.start, tz, locale)
  return ev.end ? `${s} – ${formatTime(ev.end, tz, locale)}` : s
}

/** The day (YYYY-MM-DD in tz) an event starts. */
export function eventStartDay(ev: CompactEvent, tz: string): string {
  if (!ev.start) return ''
  if (ev.all_day || DATE_RE.test(ev.start)) return ev.start.slice(0, 10)
  return dateInZone(new Date(ev.start), tz)
}

/** Every day the event touches, clipped to [from, to] inclusive. */
export function eventDays(ev: CalendarEvent, tz: string, from: string, to: string): string[] {
  const first = eventStartDay(ev, tz)
  let last = first
  if (ev.all_day || DATE_RE.test(ev.start)) {
    if (ev.end && DATE_RE.test(ev.end)) last = addDays(ev.end, -1)
  } else if (ev.end) {
    last = dateInZone(new Date(ev.end), tz)
  }
  if (last < first) last = first
  const days: string[] = []
  for (let d = first < from ? from : first; d <= last && d <= to; d = addDays(d, 1)) days.push(d)
  return days
}

export function sortEvents(list: CalendarEvent[], tz: string): CalendarEvent[] {
  const key = (e: CalendarEvent) => {
    if (e.all_day || DATE_RE.test(e.start)) return `${e.start}T00:00`
    return `${dateInZone(new Date(e.start), tz)}T${new Date(e.start).toISOString()}`
  }
  return [...list].sort((a, b) => {
    const ka = key(a)
    const kb = key(b)
    return ka < kb ? -1 : ka > kb ? 1 : 0
  })
}

/** ISO-with-offset → `YYYY-MM-DDTHH:MM` in `tz` (the shape the write API takes). */
export function toLocalInput(isoDateTime: string, tz: string): string {
  const d = new Date(isoDateTime)
  if (Number.isNaN(d.getTime())) return ''
  const p = parts(d, tz, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
}

export function nextHourInput(tz: string): string {
  const d = new Date(Date.now() + 60 * 60 * 1000)
  const p = parts(d, tz, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    hourCycle: 'h23',
  })
  return `${p.year}-${p.month}-${p.day}T${p.hour}:00`
}

/** Add minutes to a `YYYY-MM-DDTHH:MM` string treating it as wall-clock time. */
export function addMinutesInput(local: string, minutes: number): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(local)
  if (!m) return local
  const t = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]) + minutes)
  return new Date(t).toISOString().slice(0, 16)
}

/**
 * A wall clock in `tz` (`YYYY-MM-DDTHH:MM`) → that instant, as ISO in UTC. The
 * write API reads a bare wall clock in the *viewer's* zone, which on a member's
 * phone abroad is not the household's; an instant means the same everywhere.
 */
export function zonedToIso(local: string, tz: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(local)
  if (!m) return local
  const wall = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]))
  // How far the zone's clock is ahead of UTC at instant t.
  const ahead = (t: number) => {
    const p = parts(new Date(t), tz, { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' })
    return Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour), Number(p.minute), Number(p.second)) - t
  }
  // Twice, so a guess on the far side of a clock change settles on the right offset.
  const first = wall - ahead(wall)
  return new Date(wall - ahead(first)).toISOString()
}

export function relativeTime(iso: string | null | undefined, locale: string): string {
  if (!iso) return 'never'
  const d = new Date(iso.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return iso
  const diff = (d.getTime() - Date.now()) / 1000
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  const abs = Math.abs(diff)
  if (abs < 60) return rtf.format(Math.round(diff), 'second')
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  return rtf.format(Math.round(diff / 86400), 'day')
}

export function formatTimestamp(iso: string, tz: string, locale: string): string {
  const d = new Date(iso.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat(locale, {
    timeZone: tz,
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  }).format(d)
}
