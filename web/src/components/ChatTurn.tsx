import { useEffect, useState } from 'react'
import type { CompactEvent, PendingRow } from '../lib/types'
import { renderMarkdown } from '../lib/markdown'
import type { Turn } from '../lib/turns'
import { ApprovalCard } from './ApprovalCard'
import { EventCard } from './EventCard'
import { Notice } from './Field'
import { CheckIcon, CopyIcon, SparkIcon } from './Icons'
import { WidgetCard } from './Widgets'
import { WorkTrace } from './WorkTrace'

export type { Activity, Turn } from '../lib/turns'

interface Props {
  turn: Turn
  tz: string
  locale: string
  onDecided: (turnId: string, row: PendingRow) => void
  onOpenEvent?: (ev: CompactEvent) => void
  /** The language luach answers this member in ('' when it follows the browser). */
  lang?: string
}

/**
 * Under a finished answer: which model gave it, and a way to take the words
 * elsewhere. The model is named because a person who picked one should see
 * when the router let another answer.
 */
function Footer({ text, model, stopped }: { text: string; model?: string; stopped?: boolean }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 1600)
    return () => clearTimeout(t)
  }, [copied])
  const canCopy = !!text && typeof navigator !== 'undefined' && !!navigator.clipboard
  if (!canCopy && !model && !stopped) return null
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted">
      {stopped ? <span>stopped</span> : null}
      {model ? (
        <span className="truncate font-mono opacity-80" data-testid="turn-model" title="The model that answered">
          {model}
        </span>
      ) : null}
      {canCopy ? (
        <button
          type="button"
          onClick={() => {
            navigator.clipboard.writeText(text).then(
              () => setCopied(true),
              () => setCopied(false),
            )
          }}
          aria-label={copied ? 'Copied' : 'Copy the answer'}
          className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 hover:bg-surface-2 hover:text-text"
        >
          {copied ? <CheckIcon width={13} height={13} /> : <CopyIcon width={13} height={13} />}
          {copied ? 'copied' : 'copy'}
        </button>
      ) : null}
    </div>
  )
}

export function ChatTurn({ turn, tz, locale, onDecided, onOpenEvent, lang }: Props) {
  if (turn.role === 'user') {
    return (
      <div className="fade-up flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-3xl rounded-br-md bg-accent px-4 py-2.5 text-[15px] text-accent-on" dir="auto">
          {turn.text}
        </div>
      </div>
    )
  }
  const quiet = !turn.text && !turn.thinking && turn.activity.length === 0 && turn.held.length === 0 && turn.widgets.length === 0 && !turn.error
  return (
    <div className="fade-up flex gap-2.5">
      <span aria-hidden className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-2 text-accent-text">
        <SparkIcon width={16} height={16} />
      </span>
      <div className="flex min-w-0 max-w-[88%] flex-1 flex-col gap-2.5 md:max-w-[80%]">
        {/* Steps and reasoning, as they happen; until there are any, the dots below. */}
        {turn.thinking || turn.activity.length > 0 ? <WorkTrace turn={turn} /> : null}
        {turn.widgets.map((w, i) => (
          <WidgetCard key={`${w.kind}-${i}`} widget={w} tz={tz} locale={locale} onOpen={onOpenEvent} />
        ))}
        {turn.text ? (
          <div className="text-[15px] leading-relaxed" dir="auto" lang={lang || undefined}>
            {renderMarkdown(turn.text)}
            {turn.streaming ? <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 bg-accent pulse-dot" /> : null}
          </div>
        ) : turn.streaming && quiet ? (
          <div className="flex gap-1 py-2" aria-label="Thinking">
            <span className="h-2 w-2 rounded-full bg-muted pulse-dot" />
            <span className="h-2 w-2 rounded-full bg-muted pulse-dot [animation-delay:150ms]" />
            <span className="h-2 w-2 rounded-full bg-muted pulse-dot [animation-delay:300ms]" />
          </div>
        ) : null}
        {turn.held.map((h) => (
          <ApprovalCard key={h.id} item={h} tz={tz} locale={locale} onDecided={(row) => onDecided(turn.id, row)} />
        ))}
        {turn.created.length > 0 ? (
          <div className="flex flex-col gap-2">
            {turn.created.map((ev, i) => (
              <EventCard key={ev.id ?? i} event={ev} tz={tz} locale={locale} compact onClick={onOpenEvent && ev.id ? () => onOpenEvent(ev) : undefined} />
            ))}
          </div>
        ) : null}
        {turn.error ? <Notice kind="error">{turn.error}</Notice> : null}
        {!turn.streaming ? <Footer text={turn.text} model={turn.model} stopped={turn.stopped} /> : null}
      </div>
    </div>
  )
}
