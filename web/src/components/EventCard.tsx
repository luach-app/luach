import type { CompactEvent } from '../lib/types'
import { eventLink, isRecurring } from '../lib/events'
import { formatEventRange } from '../lib/time'
import { ExternalIcon, PinIcon, RepeatIcon } from './Icons'

interface Props {
  event: CompactEvent
  tz: string
  locale: string
  onClick?: () => void
  compact?: boolean
  /** The calendar's colour for the dot; the accent when absent. */
  color?: string
  /** Whose event it is, shown next to the time. */
  who?: string
}

/** Link-out icon shared by the agenda cards and the chat widgets. */
export function OpenLink({ href, className = '' }: { href: string; className?: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      aria-label="Open in Google Calendar"
      className={`rounded-full p-1 text-muted hover:text-accent-text ${className}`}
      onClick={(e) => e.stopPropagation()}
    >
      <ExternalIcon width={18} height={18} />
    </a>
  )
}

export function EventCard({ event, tz, locale, onClick, compact = false, color, who }: Props) {
  const range = formatEventRange(event, tz, locale) || event.when || ''
  const link = eventLink(event)
  const body = (
    <div className="flex items-start gap-3">
      <span aria-hidden className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${event.all_day ? 'bg-success' : color ? '' : 'bg-accent'}`} style={!event.all_day && color ? { background: color } : undefined} />
      <div className="min-w-0 flex-1">
        <div className={`flex gap-1.5 ${compact ? 'items-center' : 'items-start'}`}>
          <span className={`${compact ? 'truncate' : 'break-words'} min-w-0 font-medium`} dir="auto">
            {event.title || '(untitled)'}
          </span>
          {isRecurring(event) ? <RepeatIcon width={14} height={14} className={`shrink-0 text-muted ${compact ? '' : 'mt-1'}`} aria-label="Recurring" role="img" /> : null}
        </div>
        <div className="text-sm text-muted">
          {range}
          {who ? (
            <span className="font-medium" style={color ? { color } : undefined}>
              {' · '}
              {who}
            </span>
          ) : null}
        </div>
        {event.location && !compact ? (
          <div className="mt-0.5 flex items-start gap-1 text-sm text-muted">
            <PinIcon width={14} height={14} className="mt-0.5 shrink-0" />
            <span className="min-w-0 break-words" dir="auto">
              {event.location}
            </span>
          </div>
        ) : null}
      </div>
      {compact && link ? <OpenLink href={link} className="-m-1" /> : null}
    </div>
  )
  const cls = `card w-full text-left px-4 py-3 transition-colors ${onClick ? 'hover:border-line-strong active:bg-surface-2 cursor-pointer' : ''}`
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={cls} aria-label={`${event.title ?? 'event'}, ${range}`}>
        {body}
      </button>
    )
  }
  return <div className={cls}>{body}</div>
}
