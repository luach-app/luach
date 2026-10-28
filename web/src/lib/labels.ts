import type { HoldReason } from './types'

export const REASON_LABELS: Record<string, string> = {
  ambiguous: 'Not sure what you meant',
  past: 'This is in the past',
  'possible-duplicate': 'Looks like a duplicate',
  'mutation-existing': 'Changes an existing event',
  'from-your-email': 'Found in your email',
  'outside-the-house': 'Sends an invitation outside the household',
}

export function reasonLabel(r: HoldReason): string {
  return REASON_LABELS[r] ?? r.replace(/[-_]/g, ' ')
}

/**
 * Friendly wording for a tool name while it runs. Exact names come first: the
 * patterns below are about calendars, and `search_the_web` matching /search/
 * had luach saying "checking the calendar…" three times while it read the web.
 */
const TOOL_PHRASES: Record<string, string> = {
  search_the_web: 'searching the web…',
  just_talking: 'thinking…',
  list_events: 'checking the calendar…',
  find_events: 'searching the calendar…',
  check_availability: 'looking for a free slot…',
  get_event: 'opening the event…',
  create_event: 'adding to the calendar…',
  update_event: 'updating an event…',
  delete_event: 'removing an event…',
  // Tasks are not on the calendar, and add_task matching /add/ had luach say
  // "adding to the calendar…" while it gave Sam a to-do.
  list_tasks: 'checking the tasks…',
  add_task: 'adding a task…',
  complete_task: 'ticking a task off…',
  change_task: 'changing a task…',
  remove_task: 'removing a task…',
  remember: 'remembering…',
  forget: 'forgetting…',
}

export function toolPhrase(tool: string): string {
  const exact = TOOL_PHRASES[tool.toLowerCase()]
  if (exact) return exact
  const t = tool.toLowerCase()
  if (/(list|find|get|read|lookup|query|check)/.test(t)) return 'checking the calendar…'
  if (/(create|add|insert|schedule)/.test(t)) return 'adding to the calendar…'
  if (/(update|edit|move|patch|change|resched)/.test(t)) return 'updating an event…'
  if (/(delete|remove|cancel)/.test(t)) return 'removing an event…'
  if (/(time|now|date|clock)/.test(t)) return 'checking the time…'
  return `${tool.replace(/[_-]/g, ' ')}…`
}

/* ---- the work trace --------------------------------------------------- */

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

interface WallTime {
  y: number
  m: number
  d: number
  /** "16:00", or '' for a bare date. */
  hm: string
}

/**
 * The date and clock time the model wrote, read off the string as written.
 * Deliberately not run through `Date`: the model writes the household's wall
 * time ("2026-10-02T16:00"), and converting it through the browser's zone
 * could show a person a different hour from the one luach is checking.
 */
function wallTime(v: unknown): WallTime | null {
  if (typeof v !== 'string') return null
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(v.trim())
  if (!m) return null
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])]
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null
  return { y, m: mo, d, hm: m[4] ? `${m[4]}:${m[5]}` : '' }
}

const weekday = (w: WallTime) => DAYS[new Date(Date.UTC(w.y, w.m - 1, w.d)).getUTCDay()]
const dayLine = (w: WallTime, month = true) => `${weekday(w)} ${w.d}${month ? ` ${MONTHS[w.m - 1]}` : ''}`
const sameDay = (a: WallTime, b: WallTime) => a.y === b.y && a.m === b.m && a.d === b.d

function clip(s: string, n: number): string {
  const t = s.replace(/\s+/g, ' ').trim()
  return t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t
}

/** "Thu 2 Oct 16:00" — or whatever was written, when it is not a date. */
function when(v: unknown): string {
  const w = wallTime(v)
  if (!w) return typeof v === 'string' ? clip(v, 32) : ''
  return w.hm ? `${dayLine(w)} ${w.hm}` : dayLine(w)
}

/** "Mon 6 – Sun 12 Oct": the month written once when both ends share it. */
function range(a: unknown, b: unknown): string {
  const s = wallTime(a)
  const e = wallTime(b)
  if (!s) return when(a)
  if (!e || sameDay(s, e)) return dayLine(s)
  return `${dayLine(s, !(s.y === e.y && s.m === e.m))} – ${dayLine(e)}`
}

const str = (v: unknown) => (typeof v === 'string' ? v.trim() : '')
const quoted = (v: unknown, n = 40) => `“${clip(str(v), n)}”`

/** A skill's folder name as words: "repeating-events" → "repeating events". */
export const skillName = (slug: string) => slug.replace(/[-_]+/g, ' ').trim()

/**
 * What one step of the work is, in the present tense and with its particulars —
 * "Looking for “dentist”", not "searching the calendar…". The chips said the
 * same few phrases for every question; the arguments are what make a step
 * worth reading, and they were in the frame all along.
 */
export function stepLabel(tool: string, args?: Record<string, unknown>, kind: 'tool' | 'skill' = 'tool'): string {
  if (kind === 'skill') return `Following the guide: ${skillName(tool)}`
  const a = args ?? {}
  switch (tool) {
    case 'list_events':
      return a.start_date ? `Reading the calendar · ${range(a.start_date, a.end_date)}` : 'Reading the calendar'
    case 'find_events':
      return str(a.query) ? `Looking for ${quoted(a.query)}` : 'Looking through the calendar'
    case 'check_availability': {
      const s = wallTime(a.start)
      const e = wallTime(a.end)
      if (s?.hm && e?.hm && sameDay(s, e)) return `Checking ${dayLine(s)}, ${s.hm}–${e.hm}`
      if (s?.hm) return `Checking ${dayLine(s)}, ${s.hm}`
      return a.start ? `Checking ${when(a.start)}` : 'Checking for a free slot'
    }
    case 'get_event':
      return 'Opening an event'
    case 'create_event': {
      const what = str(a.title) ? `Adding ${quoted(a.title)}` : 'Adding an event'
      const at = when(a.start)
      return at ? `${what} · ${at}` : what
    }
    case 'update_event':
      return str(a.title) ? `Changing ${quoted(a.title)}` : 'Changing an event'
    case 'delete_event':
      return 'Removing an event'
    case 'search_email':
      return str(a.query) ? `Searching your email for ${quoted(a.query)}` : 'Searching your email'
    case 'read_email':
      return 'Reading an email'
    case 'search_the_web':
      return str(a.query) ? `Searching the web for ${quoted(a.query)}` : 'Searching the web'
    case 'add_task': {
      const what = str(a.title) ? `Adding the task ${quoted(a.title)}` : 'Adding a task'
      return str(a.for_whom) ? `${what} for ${clip(str(a.for_whom), 24)}` : what
    }
    case 'list_tasks':
      return str(a.for_whom) ? `Checking the tasks for ${clip(str(a.for_whom), 24)}` : 'Checking the tasks'
    case 'complete_task':
      return a.undo ? 'Unticking a task' : 'Ticking a task off'
    case 'change_task':
      return 'Changing a task'
    case 'remove_task':
      return 'Removing a task'
    case 'remember':
      // With no fact, `remember` is recall: it reads, it does not write.
      if (str(a.fact)) return `Remembering: ${clip(str(a.fact), 48)}`
      return str(a.topic) ? `Recalling what it knows about ${quoted(a.topic, 32)}` : 'Recalling what it knows'
    case 'forget':
      return str(a.what) ? `Forgetting ${quoted(a.what)}` : 'Forgetting something'
  }
  // A tool this file does not know keeps the old wording, as a sentence.
  const p = toolPhrase(tool).replace(/…$/, '')
  return p.charAt(0).toUpperCase() + p.slice(1)
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/**
 * The first clause of an error, for a person. Tool errors are written for the
 * model ("…; say so", "call create_event with {…}"), and that half is not for
 * the person reading the trace.
 */
function humaneError(e: string): string {
  const cut = e.search(/[;.?!](\s|$)/)
  const first = cut < 0 ? e : e.slice(0, e[cut] === '?' || e[cut] === '!' ? cut + 1 : cut)
  return `couldn't: ${clip(first, 60)}`
}

/** What a step found or did, in a few words; '' when there is nothing worth saying. */
export function stepResult(tool: string, result: unknown, error?: string): string {
  if (error) return humaneError(error)
  if (!result || typeof result !== 'object' || Array.isArray(result)) return ''
  const r = result as Record<string, unknown>
  if (typeof r.error === 'string' && r.error) return humaneError(r.error)
  if (r.status === 'held_for_approval') return 'waiting for your yes'
  const count = typeof r.count === 'number' ? r.count : null
  switch (tool) {
    case 'list_events':
      if (count === null) return ''
      return count === 0 ? 'nothing on' : plural(count, 'event')
    case 'find_events':
      if (count === null) return ''
      return count === 0 ? 'no match' : plural(count, 'match', 'matches')
    case 'check_availability': {
      if (r.free === true) return 'free'
      if (r.free !== false) return ''
      const clashes = Array.isArray(r.clashes) ? (r.clashes as { title?: unknown }[]) : []
      const title = clashes[0]?.title
      if (typeof title !== 'string' || !title) return 'busy'
      const more = clashes.length > 1 ? ` +${clashes.length - 1}` : ''
      return `busy — clashes with ${clip(title, 32)}${more}`
    }
    case 'get_event':
      return typeof r.title === 'string' ? clip(r.title, 40) : ''
    case 'create_event':
      return r.created ? 'added' : ''
    case 'update_event':
      return r.updated ? 'changed' : ''
    case 'delete_event':
      return 'deleted' in r ? 'removed' : ''
    case 'search_email':
      if (count === null) return ''
      return count === 0 ? 'no email matched' : plural(count, 'message')
    case 'read_email': {
      const subject = (r.email as { subject?: unknown } | undefined)?.subject
      return typeof subject === 'string' && subject ? quoted(subject) : ''
    }
    case 'search_the_web':
      if (count === null) return ''
      return count === 0 ? 'nothing came back' : plural(count, 'result')
    case 'add_task':
      if (r.added) return 'added'
      return r.already ? 'already on the list' : ''
    case 'list_tasks':
      if (count === null) return ''
      return count === 0 ? 'nothing to do' : plural(count, 'task')
    case 'complete_task':
      return r.ticked ? 'done' : ''
    case 'change_task':
      return r.changed ? 'changed' : ''
    case 'remove_task':
      return r.removed ? 'removed' : ''
    case 'remember':
      if (r.saved === true) return 'noted'
      if (count === null) return ''
      return count === 0 ? 'nothing remembered' : `${plural(count, 'thing')} remembered`
    case 'forget':
      if (r.forgotten === true) return 'forgotten'
      return r.forgotten === false ? 'nothing like that remembered' : ''
  }
  return ''
}
