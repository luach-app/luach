import { useState } from 'react'
import { control, errorMessage } from '../lib/api'
import type { CompactEvent, HeldSource, PendingRow } from '../lib/types'
import { Button } from './Button'
import { ReasonBadges, StatusBadge } from './Badge'
import { EventCard } from './EventCard'
import { Notice } from './Field'
import { CheckIcon, CloseIcon } from './Icons'

export interface HeldItem {
  id: string
  tool: string
  summary: string
  reason: string[]
  reason_text?: string
  status: 'pending' | 'running' | 'approved' | 'failed' | 'denied' | string
  result?: unknown
  principal?: string
  door?: string
  source?: HeldSource | null
}

interface Props {
  item: HeldItem
  tz: string
  locale: string
  onDecided?: (row: PendingRow) => void
  meta?: string
}

function looksLikeEvent(v: unknown): v is CompactEvent {
  return !!v && typeof v === 'object' && 'title' in v && 'start' in v
}

/**
 * What came of a decision, in words or as the event itself — never the tool's raw
 * JSON. An approved add arrives as {created: event}, a change as {updated: event},
 * a removal as {deleted, title}; a failure as {error: "<HttpError 400 …>"}. All of
 * those were once printed as JSON, which read as gibberish.
 */
type Outcome = { event: CompactEvent } | { text: string; bad?: boolean } | null

function outcomeOf(v: unknown): Outcome {
  if (!v || typeof v !== 'object') return typeof v === 'string' && v ? { text: v } : null
  const r = v as Record<string, unknown>
  if (looksLikeEvent(r)) return { event: r }
  for (const key of ['created', 'updated', 'event']) if (looksLikeEvent(r[key])) return { event: r[key] as CompactEvent }
  if (typeof r.error === 'string' && r.error) {
    const why = /HttpError 403/.test(r.error)
      ? 'Google would not allow it: only the event’s organizer can change it.'
      : /HttpError/.test(r.error)
        ? 'Google refused that change, so nothing was done.'
        : r.error.split(/[;—]/)[0]!.trim()
    return { text: why, bad: true }
  }
  if (r.deleted !== undefined) return { text: typeof r.title === 'string' && r.title ? `Removed “${r.title}”.` : 'Removed.' }
  if (typeof r.ticked === 'string') return { text: `Ticked off ${r.ticked}.` }
  if (typeof r.removed === 'string') return { text: `Removed ${r.removed}.` }
  // A task proposed from an email: {added: line} for one person, {added: [line…]} for several.
  const lines = (v: unknown) => (Array.isArray(v) ? v : v ? [v] : []) as { task?: string; for?: string }[]
  const added = lines(r.added).filter((t) => t.task)
  const already = lines(r.already).filter((t) => t.task)
  if (added.length) return { text: `Added the task “${added[0]!.task}” for ${added.map((t) => t.for ?? 'anyone').join(', ')}.` }
  if (already.length) return { text: `“${already[0]!.task}” was already on the list.` }
  return null
}

/** Older holds were written as "Change event <id>: {'start': …}": say it in words. */
function readable(summary: string): string {
  return summary
    .replace(/^Change event [\w-]+: \{.*$/s, 'Change an event')
    .replace(/^Delete event [\w-]+$/, 'Delete an event')
    .replace(/^(Change the task .+?): \{.*$/s, '$1')
}

/**
 * The email a proposal was found in, so the decision is made with it in view:
 * who sent it, what it was called, and a way to open it in Gmail.
 */
function FromEmail({ source }: { source: HeldSource }) {
  // Gmail opens a message by its id under #all, whichever label it sits in.
  const href = `https://mail.google.com/mail/u/0/#all/${encodeURIComponent(source.id)}`
  return (
    <div className="mt-2 rounded-xl border border-line bg-surface-2/60 px-3 py-2 text-sm">
      <div className="text-xs text-muted">From your email{source.when ? ` · ${source.when}` : ''}</div>
      <div className="truncate font-medium" dir="auto">
        {source.subject || '(no subject)'}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-3">
        <span className="min-w-0 truncate text-muted" dir="auto">
          {source.from}
        </span>
        <a href={href} target="_blank" rel="noreferrer" className="shrink-0 underline underline-offset-2">
          Open in Gmail
        </a>
      </div>
    </div>
  )
}

export function ApprovalCard({ item, tz, locale, onDecided, meta }: Props) {
  const [busy, setBusy] = useState<'approve' | 'deny' | null>(null)
  const [error, setError] = useState('')

  const decide = async (kind: 'approve' | 'deny') => {
    setBusy(kind)
    setError('')
    try {
      const row = kind === 'approve' ? await control.approve(item.id) : await control.deny(item.id)
      onDecided?.(row)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }

  const pending = item.status === 'pending'
  return (
    <div className="fade-up card border-accent/30 bg-[color-mix(in_srgb,var(--accent)_6%,var(--surface))] px-4 py-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wider text-accent-text">Needs your approval</div>
          <div className="mt-1 font-medium" dir="auto">
            {readable(item.summary || item.tool)}
          </div>
          {meta ? <div className="mt-0.5 text-xs text-muted">{meta}</div> : null}
          {item.source?.kind === 'email' ? <FromEmail source={item.source} /> : null}
        </div>
        <StatusBadge status={item.status} />
      </div>
      {item.reason?.length ? (
        <div className="mt-2.5">
          <ReasonBadges reasons={item.reason} />
        </div>
      ) : null}
      {item.reason_text ? (
        <p className="mt-2 text-sm text-muted" dir="auto">
          {item.reason_text}
        </p>
      ) : null}
      {error ? (
        <div className="mt-2">
          <Notice kind="error">{error}</Notice>
        </div>
      ) : null}
      {pending ? (
        <div className="mt-3 flex gap-2">
          <Button variant="success" size="sm" busy={busy === 'approve'} disabled={busy !== null} onClick={() => decide('approve')} aria-label="Approve">
            <CheckIcon width={16} height={16} /> Approve
          </Button>
          <Button variant="danger" size="sm" busy={busy === 'deny'} disabled={busy !== null} onClick={() => decide('deny')} aria-label="Deny">
            <CloseIcon width={16} height={16} /> Deny
          </Button>
        </div>
      ) : (() => {
          const out = item.status === 'approved' || item.status === 'failed' ? outcomeOf(item.result) : null
          if (!out) return null
          return (
            <div className="mt-3">
              {'event' in out ? (
                <EventCard event={out.event} tz={tz} locale={locale} compact />
              ) : (
                <p className={`text-sm ${out.bad ? 'text-danger' : 'text-muted'}`} dir="auto">
                  {out.text}
                </p>
              )}
            </div>
          )
        })()}
    </div>
  )
}
