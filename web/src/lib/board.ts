import { serverBuild } from './selfUpdate'
import { addDays, addMinutesInput, toLocalInput, zonedToIso } from './time'
import type { CalendarEvent, EventInput, EventScope, HouseholdCalendars, Task, TaskInput } from './types'

/**
 * The wall screen's own client. It never uses the member API: it holds a board
 * token, not a session, and a 401 means "pair again" rather than "sign in".
 */
const KEY = 'luach.board'
export const BOARD_HEADER = 'x-luach-board'
export const PAIR_HEADER = 'x-luach-pair'

export interface BoardPerson {
  key: string
  name: string
  hex: string
  kind: 'adult' | 'kid'
}

export interface BoardEvent {
  id: string
  title: string
  start: string
  end: string
  all_day: boolean
  location: string
  leader: string
  /** Everyone it is for; an event can be several people's. Older servers send only `leader`. */
  leaders?: string[]
  /** Someone else's invitation, or a calendar luach only reads: it stays where it is. */
  read_only?: boolean
  organizer?: string
  /** One day of a series: moving it to another day is the editor's job. */
  recurring?: boolean
  calendar_id?: string
}

export interface BoardDay {
  /** Whether this viewer may add, change and remove (a member; a screen the owner allowed). */
  can_edit?: boolean
  /** Today, in the household's zone — `day` is the page being looked at. */
  today?: string
  /** The paired screen's name; '' when a member is looking on their own device. */
  board: string
  /** The member looking, when it is not a paired screen. */
  viewer?: string
  /** The language the owner gave this screen: 'auto' (its own browser's), 'en', 'es' or 'he'. */
  language?: string
  timezone: string
  now: string
  day: string
  people: BoardPerson[]
  events: BoardEvent[]
  tomorrow: BoardEvent[]
  tasks: Task[]
}

export class Unpaired extends Error {}

export function storedToken(): string {
  try {
    return localStorage.getItem(KEY) ?? ''
  } catch {
    return ''
  }
}

export function storeToken(token: string) {
  try {
    if (token) localStorage.setItem(KEY, token)
    else localStorage.removeItem(KEY)
  } catch {
    /* a screen that cannot keep it pairs again next time */
  }
}

/** With a board token it is the screen on the wall; with none, the member's own session. */
const who = (token: string): Record<string, string> => (token ? { [BOARD_HEADER]: token } : {})

/**
 * Only a 401 means this screen is no longer a board. A 404 is "no such task" or
 * "no such event" — a child ticking a chore a parent had just deleted wiped the
 * board's token and threw the wall back to its pairing code. `gone` lists what
 * else means "start again" for one call (a pairing code that ran out is a 404).
 */
async function call<T>(path: string, init: RequestInit = {}, session = false, gone: number[] = [401]): Promise<T> {
  const r = await fetch(path, { ...init, credentials: session ? 'same-origin' : 'omit', headers: { 'content-type': 'application/json', ...(init.headers ?? {}) } })
  if (gone.includes(r.status)) throw new Unpaired(String(r.status))
  if (!r.ok) {
    const data = (await r.json().catch(() => ({}))) as { error?: string }
    throw new Error(data.error || `the board could not reach luach (${r.status})`)
  }
  return (await r.json()) as T
}

const enc = encodeURIComponent
const cal = (calendarId: string, scope?: EventScope) => {
  const q = new URLSearchParams()
  if (calendarId) q.set('calendar', calendarId)
  if (scope) q.set('scope', scope)
  return q.size ? `?${q}` : ''
}

/**
 * A change made from the board. Only 401 means the screen was unpaired: a 404
 * here is "no such task", and treating it as unpaired threw the wall back to
 * its pairing code.
 */
async function write<T>(token: string, path: string, method = 'GET', body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    credentials: token ? 'omit' : 'same-origin',
    headers: { 'content-type': 'application/json', ...who(token) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  if (r.status === 401) throw new Unpaired('401')
  const data = (await r.json().catch(() => ({}))) as { error?: string }
  if (!r.ok) throw new Error(data.error || `luach said no (${r.status})`)
  return data as T
}

export const boardApi = {
  pair: () => call<{ code: string; secret: string; expires_at: string }>('/api/board/pair', { method: 'POST', body: '{}' }),
  collect: (code: string, secret: string) => call<{ token?: string; waiting?: boolean }>(`/api/board/pair/${code}`, { headers: { [PAIR_HEADER]: secret } }, false, [401, 404]),
  today: (token: string, day = '') => call<BoardDay>(`/api/board/today${day ? `?day=${day}` : ''}`, { headers: who(token) }, !token),
  tick: (token: string, id: number, done: boolean, day = '') =>
    call<Task>(`/api/board/tasks/${id}/done`, { method: 'POST', body: JSON.stringify({ done, ...(day ? { day } : {}) }), headers: who(token) }, !token),
  /** The calendars the household uses, for the board's own event form (the member API is closed to a screen). */
  calendars: (token: string) => write<HouseholdCalendars>(token, '/api/board/calendars'),
  /** Changing things from the board — a member's session, or a screen the owner let edit. */
  events: (token: string) => ({
    get: (id: string, calendarId = '') => write<CalendarEvent>(token, `/api/board/events/${enc(id)}${cal(calendarId)}`),
    create: (body: EventInput) => write<CalendarEvent>(token, '/api/board/events', 'POST', body),
    update: (id: string, body: Partial<EventInput>, calendarId = '', scope?: EventScope) =>
      write<CalendarEvent>(token, `/api/board/events/${enc(id)}${cal(calendarId, scope)}`, 'PATCH', body),
    remove: (id: string, calendarId = '', scope?: EventScope) => write<{ ok: boolean }>(token, `/api/board/events/${enc(id)}${cal(calendarId, scope)}`, 'DELETE'),
  }),
  tasks: (token: string) => ({
    add: (body: TaskInput) => write<Task>(token, '/api/board/tasks', 'POST', body),
    update: (id: number, body: Partial<TaskInput>) => write<Task>(token, `/api/board/tasks/${id}`, 'PATCH', body),
    remove: (id: number) => write<{ ok: boolean }>(token, `/api/board/tasks/${id}`, 'DELETE'),
  }),
  /** Which build of the web app the server hands out now; '' when it cannot say. */
  build: serverBuild,
  /** Whether this browser is signed in, so /board can show the day without pairing. */
  signedIn: async (): Promise<boolean> => {
    try {
      const r = await fetch('/api/auth/status', { credentials: 'same-origin' })
      return r.ok && Boolean(((await r.json()) as { authenticated?: boolean }).authenticated)
    } catch {
      return false
    }
  },
}

export interface BoardColumn {
  key: string
  name: string
  hex: string
  events: BoardEvent[]
  tasks: Task[]
}

export const leadersOf = (e: BoardEvent): string[] => (e.leaders?.length ? e.leaders : e.leader ? [e.leader] : [])

/** One column per person, then the family's shared things. Each person's column
 * holds what is theirs — an event for Noa and Sam is in both. An empty shared
 * column is left out of a board that only shows, but kept where the viewer can
 * edit: its + is the only way to add something for the whole family. */
export function columnsOf(day: BoardDay, withFamily = false): BoardColumn[] {
  const known = new Set(day.people.map((p) => p.key))
  const cols: BoardColumn[] = day.people.map((p) => ({
    key: p.key,
    name: p.name,
    hex: p.hex,
    events: day.events.filter((e) => leadersOf(e).includes(p.key)),
    tasks: day.tasks.filter((t) => t.person === p.key),
  }))
  const shared: BoardColumn = {
    key: '',
    name: 'Family',
    hex: '',
    events: day.events.filter((e) => !leadersOf(e).some((k) => known.has(k))),
    tasks: day.tasks.filter((t) => !t.person || !known.has(t.person)),
  }
  if (withFamily || shared.events.length || shared.tasks.length) cols.push(shared)
  return cols
}

/**
 * Black or white, whichever reads better on a person's colour. White on every
 * colour left the + and a chosen name unreadable on yellow or light green; this
 * is the WCAG relative luminance, and the side of it with the higher contrast.
 * Anything that is not a #rgb or #rrggbb colour gets white.
 */
export function inkOn(hex: string): '#000000' | '#ffffff' {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim())
  if (!m?.[1]) return '#ffffff'
  const full = m[1].length === 3 ? m[1].replace(/./g, (c) => c + c) : m[1]
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(full.slice(i, i + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }) as [number, number, number]
  const l = 0.2126 * r + 0.7152 * g + 0.0722 * b
  // Contrast with black is (l + 0.05) / 0.05, with white 1.05 / (l + 0.05).
  return (l + 0.05) / 0.05 > 1.05 / (l + 0.05) ? '#000000' : '#ffffff'
}

// -- moving things by hand ------------------------------------------------------

/** What a finger picked up, and the column it came from ('' is the family's). */
export type DragItem = { kind: 'task'; task: Task; from: string } | { kind: 'event'; event: BoardEvent; from: string }

/** Where it can be put down: someone's column (or the family's, key ''), or a day chip. */
export type DropTarget = { kind: 'person'; key: string } | { kind: 'day'; iso: string }

/** A change one drop makes, and the change that takes it back. */
export type BoardMove =
  | { kind: 'task'; task: Task; to: DropTarget; body: Partial<TaskInput>; undo: Partial<TaskInput> }
  | { kind: 'event'; event: BoardEvent; to: DropTarget; body: Partial<EventInput>; undo: Partial<EventInput> }

export const dropAttr = (t: DropTarget): string => (t.kind === 'person' ? `person:${t.key}` : `day:${t.iso}`)

/** The drop target an element is part of, read from its `data-drop`. Hit-testing the
 * element under the finger, not coordinates, is what keeps a right-to-left board right. */
export function dropTargetOf(el: Element | null | undefined): DropTarget | null {
  const value = el?.closest?.('[data-drop]')?.getAttribute('data-drop') ?? ''
  if (value.startsWith('person:')) return { kind: 'person', key: value.slice(7) }
  if (/^day:\d{4}-\d{2}-\d{2}$/.test(value)) return { kind: 'day', iso: value.slice(4) }
  return null
}

const daysBetween = (from: string, to: string): number => Math.round((Date.parse(`${to}T12:00:00Z`) - Date.parse(`${from}T12:00:00Z`)) / 86_400_000)

/** The same event `days` later (or earlier), at the same time of day in `tz`. */
export function shiftEvent(ev: BoardEvent, days: number, tz: string): { start: string; end?: string } {
  if (ev.all_day || ev.start.length <= 10) {
    const start = addDays(ev.start.slice(0, 10), days)
    return { start, end: ev.end ? addDays(ev.end.slice(0, 10), days) : addDays(start, 1) }
  }
  const move = (iso: string) => zonedToIso(addMinutesInput(toLocalInput(iso, tz), days * 1440), tz)
  return ev.end ? { start: move(ev.start), end: move(ev.end) } : { start: move(ev.start) }
}

/** An event's people after it is carried from one column to another: the one it was
 * taken from gives it to the one it is put on. The family column is nobody's. */
function handOver(leaders: string[], from: string, to: string): string[] {
  if (!to) return []
  if (!from) return [to]
  const out: string[] = []
  for (const k of leaders.map((k) => (k === from ? to : k))) if (!out.includes(k)) out.push(k)
  if (!out.includes(to)) out.push(to)
  return out
}

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((k) => b.includes(k))

/**
 * What putting `item` down on `to` means, on the page showing `shown`: a move,
 * `'repeats'` when it is one day of something that repeats (that is changed in the
 * editor), or null when it changes nothing — dropped where it was, or nowhere.
 */
export function planMove(item: DragItem, to: DropTarget | null, shown: string, tz: string): BoardMove | 'repeats' | null {
  if (!to) return null
  if (to.kind === 'day' && to.iso === shown) return null
  if (to.kind === 'person' && to.key === item.from) return null
  if (item.kind === 'task') {
    const t = item.task
    if (to.kind === 'person') return { kind: 'task', task: t, to, body: { person: to.key }, undo: { person: t.person } }
    if (t.chore) return 'repeats'
    return { kind: 'task', task: t, to, body: { due: to.iso }, undo: { due: t.due } }
  }
  const ev = item.event
  if (to.kind === 'person') {
    const had = leadersOf(ev)
    const next = handOver(had, item.from, to.key)
    if (sameSet(had, next)) return null
    return { kind: 'event', event: ev, to, body: { leaders: next }, undo: { leaders: had } }
  }
  if (ev.recurring) return 'repeats'
  const undo: Partial<EventInput> = ev.end ? { start: ev.start, end: ev.end } : { start: ev.start }
  return { kind: 'event', event: ev, to, body: shiftEvent(ev, daysBetween(shown, to.iso), tz), undo }
}

/** The page as it will look once the move is saved, shown before it is. */
export function applyMove(day: BoardDay, m: BoardMove): BoardDay {
  if (m.kind === 'task') {
    const { to, task } = m
    if (to.kind === 'day' && to.iso > day.day) return { ...day, tasks: day.tasks.filter((t) => t.id !== task.id) }
    return { ...day, tasks: day.tasks.map((t) => (t.id === task.id ? { ...t, ...(to.kind === 'person' ? { person: to.key } : { due: to.iso, overdue: false }) } : t)) }
  }
  if (m.to.kind === 'day') return { ...day, events: day.events.filter((e) => e.id !== m.event.id) }
  const leaders = m.body.leaders ?? []
  return { ...day, events: day.events.map((e) => (e.id === m.event.id ? { ...e, leaders, leader: leaders[0] ?? '' } : e)) }
}
