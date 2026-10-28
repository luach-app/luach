import { useEffect, useState, type FormEvent } from 'react'
import { reminders as remindersApi, errorMessage } from '../lib/api'
import type { ReminderSettings } from '../lib/types'
import { useAction } from '../lib/hooks'
import { Button, Spinner } from './Button'
import { Notice, Select } from './Field'

const LEADS = [
  { value: 0, label: 'Never' },
  { value: 15, label: '15 minutes before' },
  { value: 30, label: '30 minutes before' },
  { value: 60, label: 'An hour before' },
  { value: 120, label: 'Two hours before' },
  { value: 1440, label: 'A day before' },
]

const WEEKDAYS = [
  { value: -1, label: 'Never' },
  ...['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map((d, i) => ({ value: i, label: d })),
]

const HOURS = [
  { value: -1, label: 'Never' },
  ...[17, 18, 19, 20, 21, 22].map((h) => ({ value: h, label: `${h}:00` })),
]

/** Settings › Reminders: a nudge before a thing, and the evening-before list. */
export function Reminders({ tz }: { tz: string }) {
  const [saved, setSaved] = useState<ReminderSettings | null>(null)
  const [form, setForm] = useState<ReminderSettings | null>(null)
  const [done, setDone] = useState(false)
  const [loadError, setLoadError] = useState('')
  const { busy, error, run } = useAction()

  useEffect(() => {
    remindersApi
      .get()
      .then((r) => {
        setSaved(r)
        setForm(r)
      })
      .catch((e) => setLoadError(errorMessage(e)))
  }, [])

  if (loadError) {
    return (
      <section className="card flex flex-col gap-2 px-4 py-4">
        <h2 className="font-semibold">Reminders</h2>
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

  const dirty = JSON.stringify(form) !== JSON.stringify(saved)
  const set = <K extends keyof ReminderSettings>(k: K, v: ReminderSettings[K]) => {
    setForm((p) => (p ? { ...p, [k]: v } : p))
    setDone(false)
  }
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const next = await run(() => remindersApi.update(form), errorMessage)
    if (next) {
      setSaved(next)
      setForm(next)
      setDone(true)
    }
  }

  return (
    <form onSubmit={submit} className="card flex flex-col gap-4 px-4 py-4">
      <div>
        <h2 className="font-semibold">Reminders</h2>
        <p className="text-sm text-muted">Sent to each device where notifications (above) are on, in {tz}. Only you get yours.</p>
      </div>
      <Select label="Before something starts" value={String(form.lead_minutes)} onChange={(e) => set('lead_minutes', Number(e.target.value))}>
        {LEADS.map((l) => (
          <option key={l.value} value={l.value}>
            {l.label}
          </option>
        ))}
      </Select>
      <Select label="The evening before, a list of tomorrow" value={String(form.evening_hour)} onChange={(e) => set('evening_hour', Number(e.target.value))}>
        {HOURS.map((h) => (
          <option key={h.value} value={h.value}>
            {h.label}
          </option>
        ))}
      </Select>
      <div className="grid grid-cols-2 gap-3">
        <Select label="The week ahead, on" value={String(form.weekly_day)} onChange={(e) => set('weekly_day', Number(e.target.value))}>
          {WEEKDAYS.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </Select>
        <Select label="at" value={String(form.weekly_hour)} onChange={(e) => set('weekly_hour', Number(e.target.value))} disabled={form.weekly_day < 0}>
          {Array.from({ length: 24 }, (_, h) => (
            <option key={h} value={h}>
              {String(h).padStart(2, '0')}:00
            </option>
          ))}
        </Select>
      </div>
      <p className="-mt-2 text-xs text-muted">The week ahead is emailed as well as pushed — a list is easier to read in an inbox.</p>

      <label className="flex min-h-9 items-center gap-2.5 text-sm">
        <input type="checkbox" checked={form.by_email} onChange={(e) => set('by_email', e.target.checked)} className="h-5 w-5 shrink-0 accent-[var(--accent)]" />
        Email them to me as well
      </label>
      <Notice kind="error">{error}</Notice>
      {done && !dirty ? <Notice kind="success">Saved.</Notice> : null}
      <Button type="submit" variant="primary" busy={busy} disabled={!dirty} className="self-end">
        Save
      </Button>
    </form>
  )
}
