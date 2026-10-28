import { useEffect, useState, type FormEvent } from 'react'
import { busy as busyApi, errorMessage } from '../lib/api'
import type { BusySource } from '../lib/types'
import { useAction } from '../lib/hooks'
import { Badge } from './Badge'
import { Button, Spinner } from './Button'
import { Input, Notice } from './Field'
import { CloseIcon } from './Icons'

const when = (iso: string | null) => {
  if (!iso) return 'not read yet'
  const mins = Math.round((Date.now() - new Date(iso + 'Z').getTime()) / 60000)
  if (mins < 2) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  return hours < 24 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`
}

/**
 * Settings › Work calendar: feeds luach reads for busy time only. It never
 * writes to them and never shows what the meetings are — only that the hours
 * are taken, so the booking page cannot offer them away.
 */
export function BusyCalendars() {
  const [sources, setSources] = useState<BusySource[] | null>(null)
  const [loadError, setLoadError] = useState('')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const { busy: working, error, run } = useAction()

  useEffect(() => {
    busyApi
      .list()
      .then((r) => setSources(r.sources))
      .catch((e) => setLoadError(errorMessage(e)))
  }, [])

  const add = async (e: FormEvent) => {
    e.preventDefault()
    const done = await run(() => busyApi.add({ name: name.trim() || 'Work', url: url.trim() }), errorMessage)
    if (done) {
      setSources(done.sources)
      setName('')
      setUrl('')
    }
  }
  const act = async (fn: () => Promise<{ sources: BusySource[] }>) => {
    const done = await run(fn, errorMessage)
    if (done) setSources(done.sources)
  }

  return (
    <section className="card flex flex-col gap-3 px-4 py-4" aria-labelledby="busy-heading">
      <div>
        <h2 id="busy-heading" className="font-semibold">
          Work calendar
        </h2>
        <p className="text-sm text-muted">
          A calendar luach may read but never change, such as the one at your job. It takes the hours, not the meetings: the booking page stops
          offering times you are already in something, and the agenda shows them as “Busy”.
        </p>
      </div>
      {loadError ? <Notice kind="error">{loadError}</Notice> : null}
      {sources === null && !loadError ? (
        <div className="flex justify-center py-3 text-muted">
          <Spinner />
        </div>
      ) : sources && sources.length ? (
        <ul className="flex flex-col divide-y divide-line rounded-xl border border-line">
          {sources.map((s) => (
            <li key={s.id} className="flex flex-col gap-2 px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-[15px]" dir="auto">
                  {s.name}
                </span>
                {s.last_error ? <Badge tone="danger">could not read</Badge> : <Badge>{s.blocks} busy</Badge>}
                <button
                  type="button"
                  disabled={working}
                  onClick={() => void act(() => busyApi.remove(s.id))}
                  aria-label={`Remove ${s.name}`}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-danger disabled:opacity-50"
                >
                  <CloseIcon width={18} height={18} />
                </button>
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
                <label className="flex min-h-9 items-center gap-2.5">
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    disabled={working}
                    onChange={(e) => void act(() => busyApi.update(s.id, { enabled: e.target.checked }))}
                    className="h-5 w-5 shrink-0 accent-[var(--accent)]"
                  />
                  Block bookings
                </label>
                <label className="flex min-h-9 items-center gap-2.5">
                  <input
                    type="checkbox"
                    checked={s.show_in_agenda}
                    disabled={working}
                    onChange={(e) => void act(() => busyApi.update(s.id, { show_in_agenda: e.target.checked }))}
                    className="h-5 w-5 shrink-0 accent-[var(--accent)]"
                  />
                  Show in the agenda
                </label>
                <span>read {when(s.last_fetched)}</span>
              </div>
              {s.last_error ? <div className="text-xs text-danger">{s.last_error}</div> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">No work calendar yet.</p>
      )}

      <form onSubmit={add} className="flex flex-col gap-2">
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Work" className="sm:w-40" autoComplete="off" />
          <Input label="Feed address (ICS)" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://outlook.office365.com/owa/calendar/…/calendar.ics" className="flex-1" autoComplete="off" dir="ltr" />
        </div>
        <p className="text-xs text-muted">
          In Outlook: Settings › Calendar › Shared calendars › Publish a calendar, permission “Can view when I’m busy”, then copy the ICS
          link. Anyone with that link can read it, so treat it like a password.
        </p>
        <Notice kind="error">{error}</Notice>
        <div className="flex flex-wrap justify-end gap-2">
          {sources && sources.length ? (
            <Button variant="ghost" type="button" busy={working} onClick={() => void act(() => busyApi.refresh())}>
              Read them now
            </Button>
          ) : null}
          <Button type="submit" busy={working} disabled={!url.trim()}>
            Add
          </Button>
        </div>
      </form>
    </section>
  )
}
