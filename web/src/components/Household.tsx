import { useEffect, useState } from 'react'
import { errorMessage, household as householdApi } from '../lib/api'
import { enabledCalendars, invalidateHousehold, useHousehold } from '../lib/household'
import { useAction } from '../lib/hooks'
import { Button, Spinner } from './Button'
import { EmailChips } from './EmailChips'
import { Notice } from './Field'

/** Settings › Household (owner only): which calendars luach uses, where new things go, who is always invited. */
export function Household() {
  const { data, error: loadError } = useHousehold()
  const [enabled, setEnabled] = useState<string[]>([])
  const [def, setDef] = useState('')
  const [attendees, setAttendees] = useState<string[]>([])
  const [draft, setDraft] = useState('')
  const [saved, setSaved] = useState(false)
  const { busy, error, setError, run } = useAction()

  useEffect(() => {
    if (!data) return
    setEnabled(data.calendars)
    setDef(data.default_calendar)
    setAttendees(data.default_attendees)
  }, [data])

  if (loadError) {
    return (
      <section className="card flex flex-col gap-3 px-4 py-4">
        <h2 className="font-semibold">Household</h2>
        <Notice kind="error">{loadError}</Notice>
        <Button variant="ghost" onClick={() => invalidateHousehold()} className="self-start">
          Try again
        </Button>
      </section>
    )
  }
  if (!data) {
    return (
      <div className="card flex justify-center px-4 py-6 text-muted">
        <Spinner />
      </div>
    )
  }

  const same = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i])
  const dirty = !same(enabled, data.calendars) || def !== data.default_calendar || !same(attendees, data.default_attendees) || !!draft

  const toggle = (id: string) => {
    setSaved(false)
    setEnabled((cur) => {
      const next = cur.includes(id) ? cur.filter((c) => c !== id) : [...cur, id]
      if (!next.includes(def) && next.length) setDef(next[0] ?? '')
      return next
    })
  }
  const save = async () => {
    setSaved(false)
    if (!enabled.length) {
      setError('Keep at least one calendar.')
      return
    }
    const ok = await run(() => householdApi.update({ calendars: enabled, default_calendar: def || enabled[0], default_attendees: draft && !attendees.includes(draft) ? [...attendees, draft] : attendees }), errorMessage)
    if (ok) {
      invalidateHousehold()
      setSaved(true)
    }
  }

  const listed = data.available.length ? data.available : enabledCalendars(data)
  return (
    <section className="card flex flex-col gap-4 px-4 py-4" aria-labelledby="household-heading">
      <div>
        <h2 id="household-heading" className="font-semibold">
          Household
        </h2>
        <p className="text-sm text-muted">The calendars luach reads, where new things go, and who is invited to everything.</p>
      </div>

      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1.5 text-sm text-muted">Calendars · tick the ones luach should see; the dot marks where new events go</legend>
        <ul className="flex flex-col divide-y divide-line rounded-xl border border-line">
          {listed.map((c) => {
            const on = enabled.includes(c.id)
            return (
              <li key={c.id} className="flex min-h-12 items-center gap-3 px-3 py-2">
                <input type="checkbox" checked={on} onChange={() => toggle(c.id)} aria-label={`Use ${c.name}`} className="h-5 w-5 shrink-0 accent-[var(--accent)]" />
                <span aria-hidden className="h-3 w-3 shrink-0 rounded-full" style={{ background: c.color || 'var(--accent)' }} />
                <span className="min-w-0 flex-1 truncate text-[15px]" dir="auto">
                  {c.name}
                  {!c.writable ? <span className="ms-2 text-xs text-muted">read only</span> : null}
                </span>
                <label className={`flex items-center gap-1.5 text-xs ${on && c.writable ? 'text-muted' : 'text-muted/40'}`}>
                  <input
                    type="radio"
                    name="default-calendar"
                    checked={def === c.id}
                    disabled={!on || !c.writable}
                    onChange={() => {
                      setSaved(false)
                      setDef(c.id)
                    }}
                    aria-label={`New events go to ${c.name}`}
                    className="h-5 w-5 shrink-0 accent-[var(--accent)]"
                  />
                  default
                </label>
              </li>
            )
          })}
        </ul>
      </fieldset>

      <EmailChips
        label="Always invite"
        value={attendees}
        onChange={(v) => {
          setSaved(false)
          setAttendees(v)
        }}
        onDraft={setDraft}
        hint="Every new event sends these people a Google Calendar invitation unless someone says otherwise."
        disabled={busy}
      />

      <Notice kind="error">{error}</Notice>
      {saved && !dirty ? <Notice kind="success">Saved.</Notice> : null}
      <Button variant="primary" busy={busy} disabled={!dirty} onClick={() => void save()} className="self-end">
        Save
      </Button>
    </section>
  )
}
