import { useEffect, useState } from 'react'
import { calendarFeed, errorMessage } from '../lib/api'
import type { FeedLink, FeedScope, FeedStatus } from '../lib/types'
import { useAction } from '../lib/hooks'
import { lastRead } from '../lib/feed'
import { Badge } from './Badge'
import { Button, Spinner } from './Button'
import { Notice } from './Field'

const SCOPES: { value: FeedScope; label: string; hint: string }[] = [
  { value: 'household', label: 'The whole household', hint: 'Every event, with whom each one is for.' },
  { value: 'mine', label: 'Only mine', hint: 'The events that are yours, and the ones that are everyone’s.' },
]

/**
 * Settings › Calendar feed: luach's events in the phone's own calendar app, read-only.
 * The server keeps only a fingerprint of the link, so it is shown once, when it is made;
 * a lost (or leaked) link is reset, which makes a new one and kills the old.
 */
export function CalendarFeed() {
  const [status, setStatus] = useState<FeedStatus | null>(null)
  const [link, setLink] = useState<FeedLink | null>(null)
  const [scope, setScope] = useState<FeedScope>('household')
  const [confirming, setConfirming] = useState<'' | 'reset' | 'off'>('')
  const [copied, setCopied] = useState(false)
  const [loadError, setLoadError] = useState('')
  const { busy, error, run } = useAction()

  useEffect(() => {
    calendarFeed
      .status()
      .then((s) => {
        setStatus(s)
        setScope(s.scope)
      })
      .catch((e) => setLoadError(errorMessage(e)))
  }, [])

  const made = (got: FeedLink | undefined) => {
    if (!got) return
    setLink(got)
    setStatus(got)
    setScope(got.scope)
    setConfirming('')
  }
  const turnOn = async () => made(await run(() => calendarFeed.turnOn(scope), errorMessage))
  const reset = async () => made(await run(() => calendarFeed.reset(), errorMessage))
  const turnOff = async () => {
    const got = await run(() => calendarFeed.turnOff(), errorMessage)
    if (got) {
      setStatus(got)
      setLink(null)
      setConfirming('')
    }
  }
  const choose = async (next: FeedScope) => {
    setScope(next)
    if (!status?.enabled) return
    const got = await run(() => calendarFeed.change(next), errorMessage)
    if (got) {
      setStatus(got)
      if (link) setLink({ ...link, scope: got.scope })
    } else setScope(status.scope)
  }
  const copy = async () => {
    if (!link) return
    try {
      await navigator.clipboard.writeText(link.url)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard refused: the link is on screen to copy by hand */
    }
  }

  return (
    <section className="card flex flex-col gap-3 px-4 py-4" aria-labelledby="feed-heading">
      <div>
        <div className="flex items-center justify-between gap-2">
          <h2 id="feed-heading" className="font-semibold">
            Calendar feed
          </h2>
          {status ? <Badge tone={status.enabled ? 'success' : 'neutral'}>{status.enabled ? 'on' : 'off'}</Badge> : null}
        </div>
        <p className="text-sm text-muted">
          Show luach’s events in your phone’s own calendar (iPhone, Mac, Google Calendar, Outlook), read-only. It holds a month back and a year
          ahead: titles, places, notes and whom each event is for. Never who is invited, nothing waiting for approval, and not your work
          calendar.
        </p>
      </div>
      {loadError ? <Notice kind="error">{loadError}</Notice> : null}
      {status === null && !loadError ? (
        <div className="flex justify-center py-3 text-muted">
          <Spinner />
        </div>
      ) : null}

      {status ? (
        <fieldset className="flex flex-col gap-1" disabled={busy}>
          <legend className="mb-1 text-sm font-medium">What it shows</legend>
          {SCOPES.map((s) => (
            <label key={s.value} className="flex min-h-11 items-start gap-2.5 py-1">
              <input
                type="radio"
                name="feed-scope"
                value={s.value}
                checked={scope === s.value}
                onChange={() => void choose(s.value)}
                className="mt-0.5 h-5 w-5 shrink-0 accent-[var(--accent)]"
              />
              <span className="flex flex-col">
                <span className="text-[15px]">{s.label}</span>
                <span className="text-xs text-muted">{s.hint}</span>
              </span>
            </label>
          ))}
        </fieldset>
      ) : null}

      {link ? (
        <div className="flex flex-col gap-2 rounded-xl border border-line bg-surface-2/40 px-3 py-3">
          <span className="text-sm font-medium">Your link</span>
          <code className="block overflow-x-auto whitespace-nowrap rounded-lg bg-surface px-2.5 py-2 text-sm text-accent-text" dir="ltr">
            {link.url}
          </code>
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" onClick={() => void copy()}>
              {copied ? 'Copied' : 'Copy link'}
            </Button>
            <a
              href={link.webcal}
              className="inline-flex h-9 items-center rounded-xl bg-accent px-3 text-sm font-medium text-accent-on hover:brightness-105"
            >
              Subscribe
            </a>
          </div>
          <p className="text-xs text-muted">
            Subscribe opens your calendar app on this device. In Google Calendar on the web: Other calendars › + › From URL, and paste the
            link. luach keeps only a fingerprint of it, so this is the one time it is shown: copy it now.
          </p>
        </div>
      ) : status?.enabled ? (
        <p className="text-sm text-muted">
          On, {lastRead(status.last_read)}. The link was shown once, when it was made; to add it somewhere new, reset it.
        </p>
      ) : null}

      {status ? (
        <p className="text-xs text-muted">
          Anyone with the link can read the calendar, so keep it like a password. Reset link makes a new one and the old one stops working at
          once.
        </p>
      ) : null}

      <Notice kind="error">{error}</Notice>

      {confirming ? (
        <div className="flex flex-col gap-2 rounded-xl border border-danger/30 bg-danger/5 px-3 py-3" role="group" aria-label="Confirm">
          <p className="text-sm">
            {confirming === 'reset'
              ? 'Make a new link? Calendars subscribed to the old one stop updating; add the new one to them.'
              : 'Turn the feed off? Calendars subscribed to it stop updating, and the link stops working.'}
          </p>
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" size="sm" variant="ghost" onClick={() => setConfirming('')}>
              Keep it
            </Button>
            <Button type="button" size="sm" variant="danger" busy={busy} onClick={() => void (confirming === 'reset' ? reset() : turnOff())}>
              {confirming === 'reset' ? 'Reset link' : 'Turn off'}
            </Button>
          </div>
        </div>
      ) : status?.enabled ? (
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="ghost" disabled={busy} onClick={() => setConfirming('off')}>
            Turn off
          </Button>
          <Button type="button" disabled={busy} onClick={() => setConfirming('reset')}>
            Reset link
          </Button>
        </div>
      ) : status ? (
        <div className="flex justify-end">
          <Button type="button" variant="primary" busy={busy} onClick={() => void turnOn()}>
            Turn on
          </Button>
        </div>
      ) : null}
    </section>
  )
}
