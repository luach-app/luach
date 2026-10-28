import { useEffect, useId, useRef, useState } from 'react'
import { stepLabel } from '../lib/labels'
import type { Activity, Turn } from '../lib/turns'
import { BookIcon, CheckIcon, ChevronDownIcon, CloseIcon, ListCheckIcon } from './Icons'

/** "2.4s" — tenths, because the steps that matter take one or two seconds. */
const secs = (ms: number) => `${(Math.max(0, ms) / 1000).toFixed(1)}s`
const steps = (n: number) => `${n} ${n === 1 ? 'step' : 'steps'}`

/**
 * The clock, ticking only while the turn is live. A finished turn renders from
 * its own `startedAt`/`endedAt` and never re-renders on a timer — a long
 * thread is dozens of these.
 */
function useNow(live: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!live) return
    const id = setInterval(() => setNow(Date.now()), 200)
    return () => clearInterval(id)
  }, [live])
  return now
}

function StepIcon({ a }: { a: Activity }) {
  // A fixed box, so labels line up whichever icon a row has.
  const box = 'mt-[3px] flex h-3.5 w-3.5 shrink-0 items-center justify-center'
  const [icon, said] = !a.done
    ? [<span key="i" className="h-2 w-2 rounded-full bg-accent pulse-dot" />, 'running:']
    : a.error
      ? [<CloseIcon key="i" width={14} height={14} strokeWidth={2.2} className="text-danger" />, 'failed:']
      : a.held
        ? // A ring, not a tick: the write has not happened yet, it is waiting on a person.
          [<span key="i" className="h-2.5 w-2.5 rounded-full border-2 border-accent" />, 'waiting:']
        : a.kind === 'skill'
          ? [<BookIcon key="i" width={14} height={14} className="text-accent-text" />, '']
          : [<CheckIcon key="i" width={14} height={14} strokeWidth={2.2} className="text-success" />, 'done:']
  return (
    <span className={box}>
      {icon}
      {/* The colour says it at a glance; a screen reader hears it instead. */}
      {said ? <span className="sr-only">{said}</span> : null}
    </span>
  )
}

function Step({ a }: { a: Activity }) {
  const took = a.kind === 'tool' && a.done && a.startedAt !== undefined && a.endedAt !== undefined ? secs(a.endedAt - a.startedAt) : ''
  return (
    <li className="step-in flex items-start gap-2 text-[13px] leading-snug" title={a.error || undefined}>
      <StepIcon a={a} />
      {/* Label and outcome wrap onto two lines on a phone rather than scroll. */}
      <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className={`min-w-0 break-words ${a.done ? 'text-text/85' : 'text-text'}`} dir="auto">
          {stepLabel(a.tool, a.args, a.kind)}
        </span>
        {a.summary ? (
          <span className={`min-w-0 break-words text-xs ${a.error ? 'text-danger' : a.held ? 'text-accent-text' : 'text-muted'}`} data-testid="step-result" dir="auto">
            {a.summary}
          </span>
        ) : null}
      </span>
      {took ? <span className="shrink-0 text-[11px] tabular-nums text-muted/70">{took}</span> : null}
    </li>
  )
}

/**
 * What luach did to get to its answer, as it does it: each tool with what it
 * was asked ("Reading the calendar · Mon 6 – Sun 12 Oct"), what it found
 * ("4 events"), and how long the whole thing has taken. Open while it is the
 * only thing happening; folded to one line once the answer starts, because
 * from then on the answer is what a person is reading — but kept, so "how did
 * it know that?" has an answer a click away.
 */
export function WorkTrace({ turn }: { turn: Turn }) {
  const live = !!turn.streaming
  const now = useNow(live)
  // null: follow the turn (open while working, folded once it answers). A click
  // takes over from there and is not overruled by the next frame.
  const [pinned, setPinned] = useState<boolean | null>(null)
  const open = pinned ?? (live && !turn.text)
  const listId = useId()
  const thinkingRef = useRef<HTMLParagraphElement>(null)

  // Reasoning arrives at the bottom: keep the newest line in view while it does.
  useEffect(() => {
    const el = thinkingRef.current
    if (el && live) el.scrollTop = el.scrollHeight
  }, [turn.thinking, live])

  const n = turn.activity.length
  const started = turn.startedAt
  const elapsed = started === undefined ? '' : secs((live ? now : (turn.endedAt ?? now)) - started)
  let headline: string
  if (live) headline = open ? 'Working…' : `Working…${n ? ` · ${steps(n)}` : ''}`
  else if (n === 0) headline = elapsed ? `Thought for ${elapsed}` : 'How it got there'
  else headline = `${elapsed ? `${turn.stopped ? 'Stopped after' : 'Worked for'} ${elapsed} · ` : ''}${steps(n)}`

  return (
    <div
      data-testid="work-trace"
      className={`rounded-2xl border border-line bg-surface-2/40 text-muted ${open ? 'w-full px-3 py-2' : 'self-start px-2.5 py-1'}`}
    >
      <button
        type="button"
        onClick={() => setPinned(!open)}
        aria-expanded={open}
        aria-controls={listId}
        className="flex w-full min-w-0 items-center gap-2 rounded-lg text-start text-xs hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {live ? (
          <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent pulse-dot" />
        ) : (
          <ListCheckIcon width={14} height={14} className="shrink-0" />
        )}
        <span className={`min-w-0 truncate ${live ? 'font-medium text-text/85' : ''}`}>{headline}</span>
        {live && elapsed ? (
          <span className="shrink-0 tabular-nums text-muted" data-testid="trace-timer">
            {open || n === 0 ? elapsed : `· ${elapsed}`}
          </span>
        ) : null}
        <ChevronDownIcon
          width={14}
          height={14}
          className={`shrink-0 transition-transform motion-reduce:transition-none ${open ? 'rotate-180' : ''} ${open ? 'ms-auto' : ''}`}
        />
      </button>
      {open ? (
        <div id={listId}>
          {turn.thinking ? (
            <div className="mt-2">
              <div className="text-[10px] font-medium uppercase tracking-wider text-muted/80">Thinking</div>
              <p
                ref={thinkingRef}
                className="mt-0.5 max-h-20 overflow-y-auto whitespace-pre-wrap break-words text-xs italic leading-relaxed text-muted"
                dir="auto"
              >
                {turn.thinking}
              </p>
            </div>
          ) : null}
          {n > 0 ? (
            <ol className="mt-2 flex flex-col gap-1.5" aria-label="Steps">
              {turn.activity.map((a, i) => (
                <Step key={`${a.kind}-${a.tool}-${i}`} a={a} />
              ))}
            </ol>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
