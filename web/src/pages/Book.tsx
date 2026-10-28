import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { booking, errorMessage } from '../lib/api'
import type { BookingManage, BookingPage, BookingTaken } from '../lib/types'
import { formatDateLong, formatDayName } from '../lib/time'
import { useAction } from '../lib/hooks'
import { Button, Spinner } from '../components/Button'
import { Input, Notice, Textarea } from '../components/Field'
import { Logo } from '../components/Logo'

const time = (iso: string, tz: string) =>
  new Date(iso).toLocaleTimeString('en', { hour: 'numeric', minute: '2-digit', timeZone: tz })

/** Whatever zone this browser is in; slots are shown there, not in the host's. */
const hereZone = (): string => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

/** The one page a stranger can open: pick a free slot, leave a name, done —
 *  or, with the token from their confirmation mail, move or cancel what they took. */
export function Book({ slug, manage }: { slug: string; manage?: string }) {
  if (manage) return <Manage slug={slug} token={manage} />
  return <Take slug={slug} />
}

function Take({ slug }: { slug: string }) {
  const [page, setPage] = useState<BookingPage | null>(null)
  const [loadError, setLoadError] = useState('')
  const [day, setDay] = useState('')
  const [slot, setSlot] = useState('')
  const [done, setDone] = useState<BookingTaken | null>(null)

  const load = () =>
    booking
      .page(slug)
      .then((p) => {
        setPage(p)
        setDay((d) => (p.days.some((x) => x.day === d) ? d : (p.days[0]?.day ?? '')))
      })
      .catch((e) => setLoadError(errorMessage(e)))

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  const slots = useMemo(() => page?.days.find((d) => d.day === day)?.slots ?? [], [page, day])
  const zone = hereZone()
  const elsewhere = !!page && zone !== page.timezone

  if (loadError) {
    return (
      <Shell>
        <Notice kind="error">{loadError}</Notice>
      </Shell>
    )
  }
  if (!page) {
    return (
      <Shell>
        <div className="flex justify-center py-8 text-muted">
          <Spinner />
        </div>
      </Shell>
    )
  }
  if (done) {
    return (
      <Shell subtitle={`with ${page.host}`}>
        <h1 className="text-xl font-semibold">You are booked in.</h1>
        <p className="mt-2 text-muted">
          {time(done.start, zone)} on {formatDateLong(done.start.slice(0, 10), 'en')} ({zone})
          {elsewhere ? ` — ${time(done.start, page.timezone)} for ${page.host}` : ''}. A calendar
          invitation is on its way to your inbox
          {page.location ? `, and you are meeting at ${page.location}` : ''}.
        </p>
        {done.manage ? (
          <p className="mt-3 text-sm text-muted">
            Need to change it?{' '}
            <a href={done.manage} className="text-accent-text hover:underline">
              Move or cancel it here
            </a>
            . The link is in your confirmation email too.
          </p>
        ) : null}
        {done.confirmation_sent === false ? (
          <div className="mt-3">
            <Notice kind="info">The slot is yours, but the confirmation email could not be sent. Keep this page, or write the time down.</Notice>
          </div>
        ) : null}
      </Shell>
    )
  }

  return (
    <Shell subtitle={`${page.slot_minutes} minutes with ${page.host} · times in ${zone}`}>
      <h1 className="text-xl font-semibold">Book time with {page.host}</h1>
      {page.note ? (
        <p className="mt-2 whitespace-pre-wrap text-sm text-muted" dir="auto">
          {page.note}
        </p>
      ) : null}
      {page.days.length === 0 ? (
        <Notice kind="info">No free slots in the coming weeks. Try again in a few days.</Notice>
      ) : (
        <>
          <div role="tablist" aria-label="Day" className="no-scrollbar mt-5 -mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
            {page.days.map((d) => (
              <button
                key={d.day}
                role="tab"
                aria-selected={d.day === day}
                onClick={() => {
                  setDay(d.day)
                  setSlot('')
                }}
                className={`flex min-w-[4.5rem] shrink-0 flex-col items-center rounded-xl border px-3 py-2 text-sm transition-colors ${d.day === day ? 'border-accent bg-accent/15 text-accent-text' : 'border-line hover:bg-surface-2'}`}
              >
                <span className="text-xs uppercase tracking-wide">{formatDayName(d.day, 'en', 'short')}</span>
                <span className="text-base font-semibold tabular-nums">{Number(d.day.slice(8))}</span>
                <span className="text-[11px] text-muted">{d.slots.length} free</span>
              </button>
            ))}
          </div>
          <h2 className="mt-4 text-sm font-medium">{day ? formatDateLong(day, 'en') : ''}</h2>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {slots.map((s) => (
              <button
                key={s.start}
                onClick={() => setSlot(s.start)}
                aria-pressed={slot === s.start}
                className={`rounded-xl border px-3 py-2 text-sm tabular-nums transition-colors ${slot === s.start ? 'border-accent bg-accent text-accent-on' : 'border-line hover:bg-surface-2'}`}
              >
                {time(s.start, zone)}
              </button>
            ))}
          </div>
          {elsewhere ? (
            <p className="mt-3 text-xs text-muted">
              Shown in your timezone ({zone}). {page.host} is in {page.timezone}.
            </p>
          ) : null}
          {slot ? <TakeForm slug={slug} slot={slot} tz={zone} onDone={setDone} onStale={() => void load()} /> : null}
        </>
      )}
    </Shell>
  )
}

function TakeForm({ slug, slot, tz, onDone, onStale }: { slug: string; slot: string; tz: string; onDone: (t: BookingTaken) => void; onStale: () => void }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [note, setNote] = useState('')
  const { busy, error, run } = useAction()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    // Their own zone rides along, so what luach mails them reads in their hours.
    const taken = await run(() => booking.take(slug, { start: slot, name, email, note, timezone: tz }), errorMessage)
    if (taken) onDone(taken)
    else onStale()
  }

  return (
    <form onSubmit={submit} className="mt-5 flex flex-col gap-4 border-t border-line pt-5">
      <p className="text-sm">
        Taking <b className="tabular-nums">{time(slot, tz)}</b> on{' '}
        {new Date(slot).toLocaleDateString('en', { weekday: 'long', day: 'numeric', month: 'long', timeZone: tz })}.
      </p>
      <Input label="Your name" value={name} onChange={(e) => setName(e.target.value)} required dir="auto" autoComplete="name" />
      <Input label="Your email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" hint="The calendar invitation goes here." />
      <Textarea label="What is it about? (optional)" value={note} onChange={(e) => setNote(e.target.value)} dir="auto" />
      <Notice kind="error">{error}</Notice>
      <Button type="submit" variant="primary" busy={busy} disabled={!name.trim() || !email.trim()}>
        Book it
      </Button>
    </form>
  )
}


/** Their own meeting: what it is, and the two things they may do to it. */
function Manage({ slug, token }: { slug: string; token: string }) {
  const [state, setState] = useState<BookingManage | null>(null)
  const [loadError, setLoadError] = useState('')
  const [day, setDay] = useState('')
  const [moving, setMoving] = useState(false)
  const [outcome, setOutcome] = useState<'moved' | 'cancelled' | null>(null)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const { busy, error, run } = useAction()
  const zone = hereZone()

  const load = () =>
    booking
      .manage(slug, token)
      .then((m) => {
        setState(m)
        setDay((d) => (m.days.some((x) => x.day === d) ? d : (m.days[0]?.day ?? '')))
      })
      .catch((e) => setLoadError(errorMessage(e) || 'That link does not match a meeting.'))

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, token])

  const slots = useMemo(() => state?.days.find((d) => d.day === day)?.slots ?? [], [state, day])

  if (loadError) {
    return (
      <Shell>
        <Notice kind="error">{loadError}</Notice>
      </Shell>
    )
  }
  if (!state) {
    return (
      <Shell>
        <div className="flex justify-center py-8 text-muted">
          <Spinner />
        </div>
      </Shell>
    )
  }
  if (outcome === 'cancelled' || state.cancelled) {
    return (
      <Shell subtitle={`with ${state.host}`}>
        <h1 className="text-xl font-semibold">That meeting is cancelled.</h1>
        <p className="mt-2 text-muted">Nothing else is needed. If you still want to meet, book another time at the same link.</p>
        <a href={`/book/${slug}`} className="mt-4 inline-block text-sm text-accent-text hover:underline">
          Book another time
        </a>
      </Shell>
    )
  }

  const cancel = async () => {
    const done = await run(() => booking.cancel(slug, token), errorMessage)
    if (done) setOutcome('cancelled')
  }
  const moveTo = async (start: string) => {
    const done = await run(() => booking.move(slug, token, start), errorMessage)
    if (done) {
      setOutcome('moved')
      setMoving(false)
      await load()
    }
  }

  return (
    <Shell subtitle={`${state.slot_minutes} minutes with ${state.host} · times in ${zone}`}>
      <h1 className="text-xl font-semibold">Your meeting with {state.host}</h1>
      <p className="mt-1 text-muted">
        {time(state.start, zone)} on {new Date(state.start).toLocaleDateString('en', { weekday: 'long', day: 'numeric', month: 'long', timeZone: zone })}
      </p>
      {outcome === 'moved' ? (
        <div className="mt-3">
          <Notice kind="success">Moved. A new invitation is on its way.</Notice>
        </div>
      ) : null}
      {state.past ? (
        <div className="mt-3">
          <Notice kind="info">This meeting has already happened.</Notice>
        </div>
      ) : null}

      {!state.past && !moving ? (
        <div className="mt-5 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => setMoving(true)}>
            Move it
          </Button>
          {confirmCancel ? (
            <>
              <Button variant="ghost" onClick={() => setConfirmCancel(false)} disabled={busy}>
                Keep it
              </Button>
              <Button variant="danger" busy={busy} onClick={() => void cancel()}>
                Cancel for real
              </Button>
            </>
          ) : (
            <Button variant="danger" onClick={() => setConfirmCancel(true)}>
              Cancel it
            </Button>
          )}
        </div>
      ) : null}

      {moving ? (
        <>
          <h2 className="mt-5 text-sm font-medium">Move it to</h2>
          {state.days.length === 0 ? (
            <Notice kind="info">No other free times in the coming weeks.</Notice>
          ) : (
            <>
              <div role="tablist" aria-label="Day" className="no-scrollbar mt-2 -mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
                {state.days.map((d) => (
                  <button
                    key={d.day}
                    role="tab"
                    aria-selected={d.day === day}
                    onClick={() => setDay(d.day)}
                    className={`flex min-w-[4.5rem] shrink-0 flex-col items-center rounded-xl border px-3 py-2 text-sm transition-colors ${d.day === day ? 'border-accent bg-accent/15 text-accent-text' : 'border-line hover:bg-surface-2'}`}
                  >
                    <span className="text-xs uppercase tracking-wide">{formatDayName(d.day, 'en', 'short')}</span>
                    <span className="text-base font-semibold tabular-nums">{Number(d.day.slice(8))}</span>
                    <span className="text-[11px] text-muted">{d.slots.length} free</span>
                  </button>
                ))}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                {slots.map((s) => (
                  <button
                    key={s.start}
                    disabled={busy}
                    onClick={() => void moveTo(s.start)}
                    className="rounded-xl border border-line px-3 py-2 text-sm tabular-nums transition-colors hover:bg-surface-2 disabled:opacity-50"
                  >
                    {time(s.start, zone)}
                  </button>
                ))}
              </div>
            </>
          )}
          <Button variant="ghost" onClick={() => setMoving(false)} className="mt-3">
            Keep the time I have
          </Button>
        </>
      ) : null}
      <Notice kind="error">{error}</Notice>
    </Shell>
  )
}

function Shell({ children, subtitle }: { children: React.ReactNode; subtitle?: string }) {
  return (
    <main className="safe-top safe-bottom safe-x mx-auto flex min-h-dvh w-full max-w-xl flex-col justify-center px-5 py-10">
      <div className="fade-up w-full">
        <Logo size="lg" className="mb-6 justify-center" />
        <div className="card px-5 py-6 shadow-[var(--shadow)]">
          {subtitle ? <p className="mb-2 text-xs uppercase tracking-wide text-muted">{subtitle}</p> : null}
          {children}
        </div>
      </div>
    </main>
  )
}
