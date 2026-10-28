import { useEffect, useState, type FormEvent } from 'react'
import { calendar, errorMessage } from '../lib/api'
import { isHtmlNotes, notesAsText, renderNotes } from '../lib/notes'
import type { CalendarEvent, EventInput, EventScope, HouseholdCalendars, Person } from '../lib/types'
import { EVENT_TEXT, type EventText } from '../lib/eventText'
import { joinNames } from '../lib/boardText'
import { useAction } from '../lib/hooks'
import { calendarOf, enabledCalendars, useHousehold } from '../lib/household'
import { useFamily } from '../lib/family'
import { DATE_RE, addDays, addMinutesInput, formatEventRange, nextHourInput, toLocalInput, formatDateLong } from '../lib/time'
import { describeRepeat, repeatOf, repeatWord, type Repeat } from '../lib/recurrence'
import { isOccurrence } from '../lib/events'
import { Button } from './Button'
import { EmailChips } from './EmailChips'
import { Input, Notice, Select, Textarea } from './Field'
import { ExternalIcon, PeopleIcon, PinIcon } from './Icons'
import { Sheet } from './Sheet'

export type SheetState = { mode: 'view'; event: CalendarEvent } | { mode: 'edit'; event: CalendarEvent } | { mode: 'create'; day: string; leader?: string } | null

interface Props {
  state: SheetState
  tz: string
  locale: string
  onClose: () => void
  onChanged: () => void
  onEdit: (ev: CalendarEvent) => void
  /** The member's own "also notify" inboxes, added to a new event's invitees. */
  notifyEmails?: string[]
  /** Where the writes go: the member's calendar API, or the house board's. */
  client?: EventClient
  /** Offer no edit or delete (a screen that only shows the day). */
  readOnly?: boolean
  /**
   * Opened from the house board: its language and direction, its own people and
   * calendars (the member API answers a screen with 401), and nothing that leaves
   * luach or invites anyone — no Invite field, no guest list, no Google link.
   */
  board?: BoardSource
}

export interface BoardSource {
  text: EventText
  dir: 'ltr' | 'rtl'
  lang: string
  people: Person[]
  /** null until the board's calendars have loaded. */
  household: HouseholdCalendars | null
}

/** The family and the calendars: the board's own, or the member's. */
function useSources(board: BoardSource | undefined) {
  const own = useHousehold(!board)
  const fam = useFamily(!board)
  return {
    household: board ? board.household : own.data,
    people: board ? board.people : (fam?.people ?? []),
    t: board?.text ?? EVENT_TEXT.en,
  }
}

export interface EventClient {
  create: (body: EventInput) => Promise<CalendarEvent>
  /** `scope`, on one occurrence of a repeating event: that one, or the whole series. */
  update: (id: string, body: Partial<EventInput>, calendarId?: string, scope?: EventScope) => Promise<CalendarEvent>
  remove: (id: string, calendarId?: string, scope?: EventScope) => Promise<unknown>
}

export function EventSheet({ state, tz, locale, onClose, onChanged, onEdit, notifyEmails = [], client = calendar, readOnly = false, board }: Props) {
  if (!state) return null
  if (state.mode === 'view') {
    return <ViewSheet event={state.event} tz={tz} locale={locale} onClose={onClose} onChanged={onChanged} onEdit={() => onEdit(state.event)} client={client} readOnly={readOnly} board={board} />
  }
  return <FormSheet key={state.mode === 'edit' ? state.event.id : 'new'} state={state} tz={tz} locale={locale} onClose={onClose} onChanged={onChanged} notifyEmails={notifyEmails} client={client} board={board} />
}

function ViewSheet({ event, tz, locale, onClose, onChanged, onEdit, client, readOnly, board }: { event: CalendarEvent; tz: string; locale: string; onClose: () => void; onChanged: () => void; onEdit: () => void; client: EventClient; readOnly: boolean; board?: BoardSource }) {
  const [confirm, setConfirm] = useState(false)
  const { busy, error, run } = useAction()
  const { household, people, t } = useSources(board)
  const cal = calendarOf(household, event.calendar_id)
  const several = enabledCalendars(household).length > 1
  const leaders = (event.leaders?.length ? event.leaders : event.leader ? [event.leader] : [])
    .map((k) => people.find((p) => p.key === k))
    .filter((p): p is Person => !!p)
  // One occurrence of a repeating event: delete that one, or every one.
  const occurrence = isOccurrence(event)
  const [going, setGoing] = useState<EventScope | null>(null)
  const remove = async (scope?: EventScope) => {
    setGoing(scope ?? null)
    const ok = await run(() => client.remove(event.id, event.calendar_id, scope), errorMessage)
    if (ok) {
      onChanged()
      onClose()
    }
  }
  return (
    <Sheet
      open
      title={t.event}
      onClose={onClose}
      dir={board?.dir}
      lang={board?.lang}
      closeLabel={t.close}
      footer={
        event.read_only || readOnly ? null : confirm && occurrence ? (
          <>
            <Button variant="ghost" onClick={() => setConfirm(false)} disabled={busy}>
              {t.keepIt}
            </Button>
            <Button variant="danger" onClick={() => remove('this')} busy={busy && going === 'this'} disabled={busy}>
              {t.thisEvent}
            </Button>
            <Button variant="danger" onClick={() => remove('series')} busy={busy && going === 'series'} disabled={busy}>
              {t.allEvents}
            </Button>
          </>
        ) : confirm ? (
          <>
            <Button variant="ghost" onClick={() => setConfirm(false)} disabled={busy}>
              {t.keepIt}
            </Button>
            <Button variant="danger" onClick={() => remove()} busy={busy}>
              {t.deleteForReal}
            </Button>
          </>
        ) : (
          <>
            <Button variant="danger" onClick={() => setConfirm(true)}>
              {t.delete}
            </Button>
            <Button variant="primary" onClick={onEdit}>
              {t.edit}
            </Button>
          </>
        )
      }
    >
      <h3 className="text-2xl font-semibold leading-tight" dir="auto">
        {event.title || t.untitled}
      </h3>
      {event.read_only ? (
        <p className="mt-1 text-sm text-muted" dir="auto">
          {event.organizer ? t.invitationFrom(event.organizer) : t.readOnlyCalendar}
        </p>
      ) : null}
      <div className="mt-1 text-muted">{formatEventRange(event, tz, locale)}</div>
      {leaders.length ? (
        <div className="mt-2 flex items-center gap-2 text-sm font-medium">
          {leaders.map((p) => (
            <span key={p.key} aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: p.hex }} />
          ))}
          <span dir="auto">{t.forNames(names(leaders, board ? locale : 'en'))}</span>
        </div>
      ) : null}
      {cal && several ? (
        <div className="mt-2 flex items-center gap-2 text-sm text-muted">
          <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: cal.color || 'var(--accent)' }} />
          <span dir="auto">{cal.name}</span>
        </div>
      ) : null}
      {event.location ? (
        <div className="mt-3 flex items-center gap-2 text-sm">
          <PinIcon width={16} height={16} className="text-muted" />
          <span dir="auto">{event.location}</span>
        </div>
      ) : null}
      {event.description ? (
        <div className={`mt-3 text-sm leading-relaxed text-text/90 ${isHtmlNotes(event.description) ? '' : 'whitespace-pre-wrap'}`} dir="auto">
          {renderNotes(event.description)}
        </div>
      ) : null}
      {event.attendees?.length && !board ? (
        <div className="mt-3 flex items-start gap-2 text-sm">
          <PeopleIcon width={16} height={16} className="mt-0.5 shrink-0 text-muted" />
          <span className="min-w-0 break-words text-text/90" dir="ltr">
            {event.attendees.join(', ')}
          </span>
        </div>
      ) : null}
      {event.invite_error ? (
        <div className="mt-3">
          <Notice kind="info">{event.invite_error}</Notice>
        </div>
      ) : null}
      {event.recurrence?.length ? <div className="mt-3 text-xs text-muted">{describeRepeat(event.recurrence, locale)}</div> : null}
      {confirm && occurrence ? (
        <div className="mt-3">
          <Notice kind="info">{t.deleteWhich}</Notice>
        </div>
      ) : null}
      {event.html_link && !board ? (
        <a href={event.html_link} target="_blank" rel="noreferrer noopener" className="mt-4 inline-flex items-center gap-1.5 text-sm text-accent-text hover:underline">
          <ExternalIcon width={16} height={16} /> {t.openInGoogle}
        </a>
      ) : null}
      {error ? (
        <div className="mt-3">
          <Notice kind="error">{error}</Notice>
        </div>
      ) : null}
    </Sheet>
  )
}

function initialForm(state: Exclude<SheetState, null>, tz: string) {
  if (state.mode === 'create') {
    const start = nextHourInput(tz)
    const startOnDay = `${state.day}T${start.slice(11)}`
    return { title: '', allDay: false, start: startOnDay, end: addMinutesInput(startOnDay, 60), startDay: state.day, endDay: state.day, location: '', description: '', calendarId: '', attendees: [] as string[], repeat: 'none' as Repeat, keptRule: '', leader: state.leader ?? '' }
  }
  const ev = state.mode === 'edit' ? state.event : null
  const allDay = !!ev && (ev.all_day || DATE_RE.test(ev.start))
  const start = ev && !allDay ? toLocalInput(ev.start, tz) : nextHourInput(tz)
  return {
    title: ev?.title ?? '',
    allDay,
    start,
    end: ev && !allDay && ev.end ? toLocalInput(ev.end, tz) : addMinutesInput(start, 60),
    startDay: allDay && ev ? ev.start.slice(0, 10) : start.slice(0, 10),
    endDay: allDay && ev && ev.end ? addDays(ev.end.slice(0, 10), -1) : start.slice(0, 10),
    location: ev?.location ?? '',
    description: notesAsText(ev?.description ?? ''),
    calendarId: ev?.calendar_id ?? '',
    attendees: ev?.attendees ?? ([] as string[]),
    repeat: repeatOf(ev?.recurrence),
    keptRule: (ev?.recurrence ?? []).join(' '),
    // A comma list of family keys: an event can be several people's.
    leader: ev?.leaders?.length ? ev.leaders.join(',') : (ev?.leader ?? ''),
  }
}

function FormSheet({ state, tz, locale, onClose, onChanged, notifyEmails, client, board }: { state: { mode: 'edit'; event: CalendarEvent } | { mode: 'create'; day: string; leader?: string }; tz: string; locale: string; onClose: () => void; onChanged: () => void; notifyEmails: string[]; client: EventClient; board?: BoardSource }) {
  const [f, setF] = useState(() => initialForm(state, tz))
  // How it repeated when the form opened: the rule is sent only when this changes.
  const [repeatAtFirst] = useState(f.repeat)
  // One occurrence of a repeating event: the body waiting on "this event or all events?".
  const [asking, setAsking] = useState<EventInput | null>(null)
  const occurrence = state.mode === 'edit' && isOccurrence(state.event)
  const { busy, error, setError, run } = useAction()
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }))
  const { household, people, t } = useSources(board)
  const calendars = enabledCalendars(household).filter((c) => c.writable)
  // A new event starts on the default calendar with the household's usual invitees and the member's own.
  const [seeded, setSeeded] = useState(state.mode === 'edit')
  useEffect(() => {
    if (seeded || !household) return
    // The board invites nobody: its form has no Invite field to show who would be.
    const attendees = board ? [] : [...new Set([...household.default_attendees, ...notifyEmails])]
    setF((p) => ({ ...p, calendarId: household.default_calendar || calendars[0]?.id || '', attendees }))
    setSeeded(true)
  }, [household, seeded, calendars, notifyEmails, board])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const body: EventInput = {
      title: f.title.trim(),
      start: f.allDay ? f.startDay : f.start,
      end: f.allDay ? addDays(f.endDay < f.startDay ? f.startDay : f.endDay, 1) : f.end,
      location: f.location.trim(),
      description: f.description.trim(),
      // Sent only from the member's own form; the board's leaves guests as they are.
      ...(board ? {} : { attendees: f.attendees }),
    }
    // Only when the person changed it: an occurrence opened as "Does not repeat" sent
    // that back and stopped the series. A word, which the server puts on the event's
    // own day; a repeat luach's menu cannot say is never sent, so it stays as it was.
    const repeatChanged = f.repeat !== repeatAtFirst && f.repeat !== 'custom'
    if (repeatChanged) body.recurrence = repeatWord(f.repeat)
    if (state.mode === 'create' && f.calendarId) body.calendar_id = f.calendarId
    // Sent only when it says something: a new event someone leads, or a change of hands.
    const had = state.mode === 'create' ? '' : state.event.leaders?.length ? state.event.leaders.join(',') : (state.event.leader ?? '')
    if (f.leader !== had) body.leader = f.leader
    if (!body.title) {
      setError(t.giveTitle)
      return
    }
    if (!f.allDay && body.end && body.end < body.start) {
      setError(t.endBeforeStart)
      return
    }
    if (occurrence && !repeatChanged) {
      setAsking(body)
      return
    }
    // How it repeats is the series': a new repeat from one occurrence is every one's.
    await save(body, occurrence ? 'series' : undefined)
  }

  const save = async (body: EventInput, scope?: EventScope) => {
    const ok = await run(
      () => (state.mode === 'edit' ? client.update(state.event.id, body, state.event.calendar_id, scope) : client.create(body)),
      errorMessage,
    )
    if (ok) {
      onChanged()
      onClose()
    } else {
      setAsking(null)
    }
  }

  return (
    <Sheet
      open
      title={state.mode === 'edit' ? t.editEvent : t.newEvent}
      onClose={onClose}
      dir={board?.dir}
      lang={board?.lang}
      closeLabel={t.close}
      footer={
        asking ? (
          <>
            <Button variant="ghost" onClick={() => setAsking(null)} disabled={busy}>
              {t.back}
            </Button>
            <Button variant="secondary" onClick={() => save(asking, 'this')} disabled={busy}>
              {t.thisEvent}
            </Button>
            <Button variant="primary" onClick={() => save(asking, 'series')} disabled={busy}>
              {t.allEvents}
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              {t.cancel}
            </Button>
            <Button variant="primary" type="submit" form="event-form" busy={busy}>
              {state.mode === 'edit' ? t.save : t.add}
            </Button>
          </>
        )
      }
    >
      <form id="event-form" onSubmit={submit} className="flex flex-col gap-4">
        {/* Held while "this event or all events?" is asked: a change made now would not be in what is saved. */}
        <fieldset disabled={!!asking} className="contents">
        <Input label={t.title} value={f.title} onChange={(e) => set('title', e.target.value)} dir="auto" required autoComplete="off" />
        {people.length ? <LeaderPicker people={people} value={f.leader} onChange={(v) => set('leader', v)} disabled={busy} t={t} locale={board ? locale : 'en'} /> : null}
        <label className="flex min-h-9 items-center gap-2.5 text-sm">
          <input type="checkbox" checked={f.allDay} onChange={(e) => set('allDay', e.target.checked)} className="h-5 w-5 shrink-0 accent-[var(--accent)]" />
          {t.allDay}
        </label>
        {f.allDay ? (
          <div className="grid grid-cols-2 gap-3">
            <Input label={t.from} type="date" value={f.startDay} onChange={(e) => set('startDay', e.target.value)} required />
            <Input label={t.to} type="date" value={f.endDay} min={f.startDay} onChange={(e) => set('endDay', e.target.value)} required hint={f.endDay !== f.startDay ? formatDateLong(f.endDay, locale) : undefined} />
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Input
              label={t.starts}
              type="datetime-local"
              value={f.start}
              onChange={(e) => {
                const v = e.target.value
                const delta = f.end && f.start ? minutesBetween(f.start, f.end) : 60
                setF((p) => ({ ...p, start: v, end: addMinutesInput(v, delta) }))
              }}
              required
            />
            <Input label={t.ends} type="datetime-local" value={f.end} min={f.start} onChange={(e) => set('end', e.target.value)} required />
          </div>
        )}
        <Select label={t.repeats} value={f.repeat} onChange={(e) => set('repeat', e.target.value as Repeat)}>
          <option value="none">{t.repeat.none}</option>
          <option value="daily">{t.repeat.daily}</option>
          <option value="weekly">{t.repeat.weekly}</option>
          <option value="biweekly">{t.repeat.biweekly}</option>
          <option value="monthly">{t.repeat.monthly}</option>
          <option value="yearly">{t.repeat.yearly}</option>
          {f.repeat === 'custom' ? <option value="custom">{`${describeRepeat(f.keptRule.split(' '), locale)} ${t.kept}`}</option> : null}
        </Select>
        {state.mode === 'edit' && (f.repeat !== 'none' || occurrence) ? (
          <p className="-mt-2 text-xs text-muted">{t.changesEvery}</p>
        ) : null}
        <Input label={t.location} value={f.location} onChange={(e) => set('location', e.target.value)} dir="auto" autoComplete="off" />
        {state.mode === 'create' && calendars.length > 1 ? (
          <Select label={t.calendar} value={f.calendarId} onChange={(e) => set('calendarId', e.target.value)}>
            {calendars.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        ) : null}
        {board ? null : (
          <EmailChips label={t.invite} value={f.attendees} onChange={(v) => set('attendees', v)} hint={state.mode === 'create' ? t.inviteHintNew : t.inviteHintEdit} disabled={busy} />
        )}
        <Textarea label={t.notes} value={f.description} onChange={(e) => set('description', e.target.value)} dir="auto" />
        <div className="text-xs text-muted">{t.timesIn(tz)}</div>
        </fieldset>
        {asking ? <Notice kind="info">{t.saveWhich}</Notice> : null}
        <Notice kind="error">{error}</Notice>
      </form>
    </Sheet>
  )
}

/** Whose event it is: one of the family, or everyone's. */
/** Everyone, or any of the family — tap several for "Noa and Sam". */
function LeaderPicker({ people, value, onChange, disabled, t, locale }: { people: Person[]; value: string; onChange: (v: string) => void; disabled?: boolean; t: EventText; locale: string }) {
  const keys = value.split(',').filter(Boolean)
  const chosen = people.filter((p) => keys.includes(p.key))
  const toggle = (key: string) => {
    if (!key) return onChange('')
    const next = keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key]
    onChange(people.filter((p) => next.includes(p.key)).map((p) => p.key).join(','))
  }
  return (
    <fieldset className="flex flex-col gap-2" disabled={disabled}>
      <legend className="mb-2 text-sm font-medium">{t.who}</legend>
      <div className="flex flex-wrap gap-2" role="group" aria-label={t.who}>
        {[{ key: '', name: t.everyone, hex: '' }, ...people].map((p) => {
          const on = p.key ? keys.includes(p.key) : keys.length === 0
          return (
            <button
              key={p.key || 'everyone'}
              type="button"
              aria-pressed={on}
              onClick={() => toggle(p.key)}
              className={`inline-flex min-h-9 items-center gap-2 rounded-full border px-3 text-sm transition-colors ${on ? 'border-transparent font-medium text-white' : 'border-line hover:border-line-strong'}`}
              style={on ? { background: p.hex || 'var(--accent)' } : undefined}
            >
              {p.hex && !on ? <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: p.hex }} /> : null}
              <span dir="auto">{p.name}</span>
            </button>
          )
        })}
      </div>
      {chosen.length ? (
        <p className="text-xs text-muted">
          {t.onBoard(names(chosen, locale), chosen[0]!.name)}
          {chosen.some((c) => c.email) ? ` ${t.invited(names(chosen.filter((c) => c.email), locale), chosen.filter((c) => c.email).length > 1)}` : ''}
        </p>
      ) : null}
    </fieldset>
  )
}

/** "Noa and Sam", "Noa y Sam", "Noa ו-Sam": in the sheet's own language. */
const names = (people: { name: string }[], locale: string) => joinNames(people.map((p) => p.name), locale)

function minutesBetween(a: string, b: string): number {
  const ta = Date.parse(`${a}:00Z`)
  const tb = Date.parse(`${b}:00Z`)
  if (Number.isNaN(ta) || Number.isNaN(tb) || tb <= ta) return 60
  return Math.round((tb - ta) / 60000)
}
