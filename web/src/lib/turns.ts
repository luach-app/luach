import type { HeldItem } from '../components/ApprovalCard'
import type { CompactEvent, StoredTurn, StreamFrame, Widget } from './types'
import { stepResult } from './labels'

/**
 * One step of the work behind an answer: a tool call, or a guide (skill) the
 * model read before acting. Kept for the whole turn, with what each found, so
 * the finished answer can still say how it got there.
 */
export interface Activity {
  /** The tool's name, or the skill's folder name for a guide. */
  tool: string
  args?: Record<string, unknown>
  done: boolean
  error?: string
  /** What it found or did, in a few words ("3 events", "free"). */
  summary?: string
  /** A write the policy held for a person's yes: finished, but not done. */
  held?: boolean
  kind: 'tool' | 'skill'
  startedAt?: number
  endedAt?: number
}

export interface Turn {
  id: string
  role: 'user' | 'assistant'
  text: string
  /** The model's own reasoning, streamed as it comes. Shown folded away. */
  thinking: string
  activity: Activity[]
  held: HeldItem[]
  widgets: Widget[]
  created: CompactEvent[]
  error?: string
  streaming?: boolean
  /** The model that answered, as the router named it — not always the one picked. */
  model?: string
  /** The person pressed Stop before the turn finished. */
  stopped?: boolean
  /** When the first frame arrived and when the turn finished (ms), for "worked for 3.2s". */
  startedAt?: number
  endedAt?: number
}

let counter = 0
export const nextTurnId = () => `t${Date.now().toString(36)}${(counter++).toString(36)}`

export function newTurn(role: Turn['role'], text = '', streaming = false): Turn {
  return { id: nextTurnId(), role, text, thinking: '', activity: [], held: [], widgets: [], created: [], streaming }
}

const WIDGET_KINDS = new Set(['agenda', 'availability', 'event'])
export function isWidget(v: unknown): v is Widget {
  if (!v || typeof v !== 'object') return false
  const w = v as { kind?: unknown; data?: unknown }
  return typeof w.kind === 'string' && WIDGET_KINDS.has(w.kind) && !!w.data && typeof w.data === 'object'
}

function looksLikeEvent(v: unknown): v is CompactEvent {
  return !!v && typeof v === 'object' && 'title' in v && ('start' in v || 'when' in v)
}

/**
 * Finish a turn: nothing in it is still running. Used on `done` and `error`,
 * and by the chat when the stream ends any other way (Stop, a dropped line),
 * so no step is left pulsing and the timer stops where the work did.
 */
export function settle(t: Turn, now = Date.now()): Turn {
  return {
    ...t,
    streaming: false,
    endedAt: t.endedAt ?? now,
    activity: t.activity.map((a) => (a.done ? a : { ...a, done: true, endedAt: a.endedAt ?? now })),
  }
}

/** A `result.error` is a refusal the tool wrote (no such event, whose is it?): a step that did not happen. */
function refusal(result: unknown): string | undefined {
  if (!result || typeof result !== 'object') return undefined
  const e = (result as { error?: unknown }).error
  return typeof e === 'string' && e ? e : undefined
}

/**
 * "Not added yet: whose is it?" is not a failure: luach stopped to ask the person,
 * as it is meant to when a message names someone. It is shown as waiting, like a hold.
 */
const ASKS_THE_PERSON = /^Not added yet: whose is it\?/i

/**
 * Fold one stream frame into the assistant turn it belongs to. Pure but for
 * the clock, which a test can pass in. Careful with `frames.reduce(applyFrame)`:
 * reduce hands over the index third, and it would be taken for the time.
 */
export function applyFrame(t0: Turn, f: StreamFrame, now = Date.now()): Turn {
  const t = t0.startedAt === undefined && f.type !== 'session' ? { ...t0, startedAt: now } : t0
  switch (f.type) {
    case 'model':
      return { ...t, model: f.name }
    case 'token':
      return { ...t, text: t.text + f.text }
    case 'retract':
      // A model may answer, call a tool, and answer again; the server takes the first
      // back as the second begins, or the answer showed twice while it streamed.
      return { ...t, text: '' }
    case 'thinking':
      return { ...t, thinking: t.thinking + f.text }
    case 'tool_start':
      return { ...t, activity: [...t.activity, { tool: f.tool, args: f.args, done: false, kind: 'tool', startedAt: now }] }
    case 'tool_result': {
      const idx = t.activity.findIndex((a) => a.kind === 'tool' && a.tool === f.tool && !a.done)
      const refused = f.error || refusal(f.result)
      const asking = !f.error && !!refused && ASKS_THE_PERSON.test(refused)
      const error = asking ? undefined : refused
      const held =
        asking || (!!f.result && typeof f.result === 'object' && (f.result as { status?: unknown }).status === 'held_for_approval')
      const summary = asking ? 'asking whose it is' : stepResult(f.tool, f.result, error)
      const finished = { done: true, endedAt: now, error, summary, ...(held ? { held } : {}) }
      const activity = [...t.activity]
      if (idx >= 0) activity[idx] = { ...activity[idx]!, ...finished }
      else activity.push({ tool: f.tool, kind: 'tool', startedAt: now, ...finished })
      return { ...t, activity }
    }
    case 'skill':
      // Reading a guide is instant and finished by the time it is announced.
      return { ...t, activity: [...t.activity, { tool: f.name, done: true, kind: 'skill', startedAt: now, endedAt: now }] }
    case 'widget': {
      // The step that drew it stays: the trace is the record of the work, and
      // a widget is what one step found, not a replacement for it.
      const widget: Widget = { kind: f.kind, data: f.data } as Widget
      return { ...t, widgets: [...t.widgets, widget] }
    }
    case 'held':
      if (t.held.some((h) => h.id === f.id)) return t
      return {
        ...t,
        held: [...t.held, { id: f.id, tool: f.tool, summary: f.summary, reason: f.reason ?? [], reason_text: f.reason_text, status: 'pending' }],
      }
    case 'done':
      return {
        ...settle(t, now),
        // The server's reply wins over what streamed, not the other way round.
        // runtime.py rewrites the answer when a turn called no tool, ran out of
        // steps, or went quiet — and those rewrites were the one thing a person
        // never saw, because any token at all had already filled `t.text`.
        text: f.reply || t.text || '',
        created: Array.isArray(f.created) ? f.created : [],
        widgets: t.widgets.length ? t.widgets : (f.widgets ?? []).filter(isWidget),
        model: f.model || t.model,
      }
    case 'error':
      return { ...settle(t, now), error: f.message || 'Something went wrong.' }
    default:
      return t0
  }
}

/** Rebuild chat turns from `GET /api/threads/{id}`; widgets ride in `events` as `{widget}` entries. */
export function turnsFromThread(stored: StoredTurn[]): Turn[] {
  const out: Turn[] = []
  for (const s of stored) {
    if (s.role !== 'user' && s.role !== 'assistant') continue
    const t = newTurn(s.role, typeof s.content === 'string' ? s.content : '')
    // runtime.py saves a turn the person stopped with this mark on the end.
    if (s.role === 'assistant' && /\(stopped\)$/.test(t.text)) {
      t.text = t.text.replace(/\s*\(stopped\)$/, '')
      t.stopped = true
    }
    for (const e of Array.isArray(s.events) ? s.events : []) {
      const entry = e as { widget?: unknown; created?: unknown }
      if (isWidget(entry?.widget)) t.widgets.push(entry.widget)
      else if (looksLikeEvent(entry?.created)) t.created.push(entry.created)
      else if (looksLikeEvent(e)) t.created.push(e)
    }
    // A turn stopped before it said anything is still a turn: without the
    // mark it has no text, and dropping it made the stop vanish on reload.
    if (t.text || t.widgets.length || t.created.length || t.stopped) out.push(t)
  }
  return out
}
