import { useEffect, useState, type FormEvent } from 'react'
import { booking, calendar, errorMessage } from '../lib/api'
import type { BookingSettings, BookingRow } from '../lib/types'
import { formatDateTime } from '../lib/time'
import { useAction } from '../lib/hooks'
import { enabledCalendars, useHousehold } from '../lib/household'
import { Badge } from './Badge'
import { Button, Spinner } from './Button'
import { Input, Notice, Select } from './Field'

const DAYS: { key: string; label: string }[] = [
  { key: 'mon', label: 'Monday' },
  { key: 'tue', label: 'Tuesday' },
  { key: 'wed', label: 'Wednesday' },
  { key: 'thu', label: 'Thursday' },
  { key: 'fri', label: 'Friday' },
  { key: 'sat', label: 'Saturday' },
  { key: 'sun', label: 'Sunday' },
]

const same = (a: BookingSettings, b: BookingSettings) => JSON.stringify(a) === JSON.stringify(b)

/** Settings › Meetings with me: the hours, the caps and the link to share. */
export function Booking({ tz, locale }: { tz: string; locale: string }) {
  const [saved, setSaved] = useState<BookingSettings | null>(null)
  const [form, setForm] = useState<BookingSettings | null>(null)
  const [rows, setRows] = useState<BookingRow[]>([])
  const [loadError, setLoadError] = useState('')
  const [copied, setCopied] = useState(false)
  const [dropping, setDropping] = useState('')
  const [ok, setOk] = useState(false)
  const { busy, error, run } = useAction()
  const { data: household } = useHousehold()
  const calendars = enabledCalendars(household).filter((c) => c.writable)

  useEffect(() => {
    booking
      .mine()
      .then((s) => {
        setSaved(s)
        setForm(s)
      })
      .catch((e) => setLoadError(errorMessage(e)))
    booking.upcoming().then((r) => setRows(r.bookings)).catch(() => setRows([]))
  }, [])

  if (loadError) {
    return (
      <section className="card flex flex-col gap-2 px-4 py-4">
        <h2 className="font-semibold">Meetings with me</h2>
        <Notice kind="error">{loadError}</Notice>
      </section>
    )
  }
  if (!form || !saved) {
    return (
      <section className="card flex justify-center px-4 py-6 text-muted">
        <Spinner />
      </section>
    )
  }

  const set = <K extends keyof BookingSettings>(k: K, v: BookingSettings[K]) => {
    setForm((p) => (p ? { ...p, [k]: v } : p))
    setOk(false)
  }
  const setWindow = (day: string, which: 0 | 1, value: string) => {
    const current = form.hours[day]?.[0] ?? ['09:00', '17:00']
    const next: string[] = which === 0 ? [value, current[1] ?? '17:00'] : [current[0] ?? '09:00', value]
    set('hours', { ...form.hours, [day]: [next] })
  }
  const toggleDay = (day: string, on: boolean) => set('hours', { ...form.hours, [day]: on ? [form.hours[day]?.[0] ?? ['09:00', '17:00']] : [] })

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    // The server owns `link` and `timezone`; send only what it accepts.
    const changes: Partial<BookingSettings> = { ...form }
    delete changes.link
    delete changes.timezone
    delete changes.zoom_ready
    const next = await run(() => booking.update(changes), errorMessage)
    if (next) {
      setSaved(next)
      setForm(next)
      setOk(true)
    }
  }
  /** The host calling one off: removing the event tells the guest, server-side. */
  const drop = async (row: BookingRow) => {
    const done = await run(() => calendar.remove(row.event_id), errorMessage)
    if (done !== null) {
      setRows((all) => all.filter((r) => r.event_id !== row.event_id))
      setDropping('')
    }
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(saved.link)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard refused: the link is on screen anyway */
    }
  }

  return (
    <form onSubmit={submit} className="card flex flex-col gap-4 px-4 py-4">
      <div>
        <h2 className="font-semibold">Meetings with me</h2>
        <p className="text-sm text-muted">Share one link. People see only the times you are free, and can take at most {form.max_per_day} a day. Times are in {saved.timezone}.</p>
      </div>

      {/* The link is the point of this card, so it is the first thing in it —
          and it is shown whether or not it is live, because a person decides
          whether to turn it on by looking at what they would be sharing. */}
      <div className="flex flex-col gap-2 rounded-xl border border-line bg-surface-2/40 px-3 py-3">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium">Your link</span>
          <Badge tone={saved.enabled ? 'success' : 'neutral'}>{saved.enabled ? 'live' : 'not live yet'}</Badge>
        </div>
        <code className="block overflow-x-auto whitespace-nowrap rounded-lg bg-surface px-2.5 py-2 text-sm text-accent-text" dir="ltr">
          {saved.link}
        </code>
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" onClick={() => void copy()}>
            {copied ? 'Copied' : 'Copy link'}
          </Button>
          <a
            href={saved.link}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex min-h-9 items-center rounded-full px-3 text-sm text-muted hover:text-accent-text"
          >
            Open it
          </a>
        </div>
      </div>

      <label className="flex min-h-9 items-center gap-2.5 text-sm">
        <input type="checkbox" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} className="h-5 w-5 shrink-0 accent-[var(--accent)]" />
        The link is live
      </label>

      <Input label="Link name" value={form.slug} onChange={(e) => set('slug', e.target.value)} hint="The last part of the address above." autoComplete="off" />

      <div className="grid grid-cols-2 gap-3">
        <Select label="Meeting length" value={String(form.slot_minutes)} onChange={(e) => set('slot_minutes', Number(e.target.value))}>
          {[15, 20, 30, 45, 60, 90].map((m) => (
            <option key={m} value={m}>
              {m} minutes
            </option>
          ))}
        </Select>
        <Select label="Most per day" value={String(form.max_per_day)} onChange={(e) => set('max_per_day', Number(e.target.value))}>
          {[1, 2, 3, 4, 5].map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </Select>
        <Select label="Gap around meetings" value={String(form.buffer_minutes)} onChange={(e) => set('buffer_minutes', Number(e.target.value))}>
          {[0, 10, 15, 30, 60].map((m) => (
            <option key={m} value={m}>
              {m ? `${m} minutes` : 'none'}
            </option>
          ))}
        </Select>
        <Select label="Notice needed" value={String(form.lead_hours)} onChange={(e) => set('lead_hours', Number(e.target.value))}>
          {[0, 2, 12, 24, 48, 72].map((h) => (
            <option key={h} value={h}>
              {h ? `${h} hours` : 'none'}
            </option>
          ))}
        </Select>
      </div>

      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1 text-sm text-muted">Hours you are bookable</legend>
        {DAYS.map((d) => {
          const win = form.hours[d.key]?.[0]
          return (
            <div key={d.key} className="flex flex-wrap items-center gap-2">
              <label className="flex min-h-9 min-w-[6.5rem] flex-1 items-center gap-2.5 text-sm sm:flex-none">
                <input type="checkbox" checked={!!win} onChange={(e) => toggleDay(d.key, e.target.checked)} className="h-5 w-5 shrink-0 accent-[var(--accent)]" />
                {d.label}
              </label>
              {win ? (
                <span className="flex basis-full items-center gap-1.5 text-sm sm:basis-auto">
                  <input type="time" value={win[0]} onChange={(e) => setWindow(d.key, 0, e.target.value)} aria-label={`${d.label} from`} className="min-w-0 flex-1 rounded-lg border border-line-strong bg-surface-2 px-2 py-1.5 tabular-nums sm:w-[7.5rem] sm:flex-none" />
                  <span className="text-muted">–</span>
                  <input type="time" value={win[1]} onChange={(e) => setWindow(d.key, 1, e.target.value)} aria-label={`${d.label} to`} className="min-w-0 flex-1 rounded-lg border border-line-strong bg-surface-2 px-2 py-1.5 tabular-nums sm:w-[7.5rem] sm:flex-none" />
                </span>
              ) : (
                <span className="text-sm text-muted">not bookable</span>
              )}
            </div>
          )
        })}
      </fieldset>

      {calendars.length > 1 ? (
        <Select label="Meetings land on" value={form.calendar_id} onChange={(e) => set('calendar_id', e.target.value)} hint="Keep work meetings off the family calendar.">
          <option value="">{`The household default${household?.default_calendar ? ` (${calendars.find((c) => c.id === household.default_calendar)?.name ?? household.default_calendar})` : ''}`}</option>
          {calendars.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      ) : null}

      <Select label="Where you meet" value={form.conferencing} onChange={(e) => set('conferencing', e.target.value)} hint={form.zoom_ready === false ? 'Zoom needs credentials on the server before it can be picked.' : 'A Zoom link is created on your account for each booking.'}>
        <option value="none">Wherever I wrote below</option>
        <option value="zoom" disabled={form.zoom_ready === false}>
          A fresh Zoom link per meeting
        </option>
      </Select>

      <label className="flex min-h-9 items-center gap-2.5 text-sm">
        <input type="checkbox" checked={form.notify_host} onChange={(e) => set('notify_host', e.target.checked)} className="h-5 w-5 shrink-0 accent-[var(--accent)]" />
        Email me when someone books
      </label>

      <Input label={form.conferencing === 'zoom' ? 'Where, if Zoom cannot be reached' : 'Where (optional)'} value={form.location} onChange={(e) => set('location', e.target.value)} placeholder="my office, a phone call, …" dir="auto" autoComplete="off" />
      <Input label="A line for the page (optional)" value={form.note} onChange={(e) => set('note', e.target.value)} placeholder="Looking forward to it." dir="auto" autoComplete="off" />

      {rows.length ? (
        <div>
          <h3 className="text-sm font-medium">Booked so far</h3>
          <ul className="mt-1.5 flex flex-col divide-y divide-line rounded-xl border border-line">
            {rows.map((r) => (
              <li key={r.start + r.email} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="text-text">{r.name}</span> · {formatDateTime(r.start, tz, locale)}
                  <span className="block truncate text-muted" dir="ltr">
                    {r.email}
                  </span>
                </span>
                {dropping === r.event_id ? (
                  <span className="ms-auto flex items-center gap-1.5">
                    <Button size="sm" variant="ghost" type="button" onClick={() => setDropping('')} disabled={busy}>
                      Keep
                    </Button>
                    <Button size="sm" variant="danger" type="button" busy={busy} onClick={() => void drop(r)}>
                      Cancel it
                    </Button>
                  </span>
                ) : (
                  <Button size="sm" variant="ghost" type="button" className="ms-auto" onClick={() => setDropping(r.event_id)}>
                    Cancel
                  </Button>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs text-muted">Cancelling tells them by email, takes the Zoom link down, and frees the slot.</p>
        </div>
      ) : null}

      <Notice kind="error">{error}</Notice>
      {ok && same(form, saved) ? <Notice kind="success">Saved.</Notice> : null}
      <Button type="submit" variant="primary" busy={busy} disabled={same(form, saved)} className="self-end">
        Save
      </Button>
    </form>
  )
}
