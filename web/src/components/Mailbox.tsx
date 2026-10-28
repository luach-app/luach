import { useCallback, useEffect, useState } from 'react'
import { errorMessage, mail as mailApi } from '../lib/api'
import type { MailStatus } from '../lib/types'
import { useAction } from '../lib/hooks'
import { onConsent, openConsent, resultOf, type MailResult } from '../lib/mailPopup'
import { Button, Spinner } from './Button'
import { Notice } from './Field'

/**
 * Settings › You › Your email. Each person connects their own Gmail, read-only, and
 * the chat searches that mailbox for them and nobody else — ask "when is our flight?"
 * and it looks in yours; your partner asking looks in theirs.
 */
export function Mailbox() {
  const [st, setSt] = useState<MailStatus | null>(null)
  const [off, setOff] = useState('')
  const { busy, error, run } = useAction()
  // Back from Google: say how it went once, then tidy the address bar.
  const [came, setCame] = useState<MailResult | null>(() => resultOf(window.location.search))

  const refresh = useCallback(
    () =>
      mailApi
        .status()
        .then(setSt)
        .catch((e) => setOff(errorMessage(e))),
    [],
  )

  useEffect(() => {
    void refresh()
    // Back from Google in this window: tidy the address bar once.
    if (new URLSearchParams(window.location.search).get('mail')) {
      window.history.replaceState(null, '', window.location.pathname + '?tab=settings')
    }
    // Back from the popup: its result, and the connection as it now is.
    return onConsent((result) => {
      setCame(result)
      void refresh()
    })
  }, [refresh])

  const setScan = async (enabled: boolean) => {
    const next = await run(() => mailApi.scan(enabled), errorMessage)
    if (next) setSt(next)
  }

  // Google's consent is its own page: a popup, or the whole window when popups are blocked.
  const connect = () => {
    setCame(null)
    if (!openConsent()) window.location.assign('/api/mail/connect')
  }

  const disconnect = async () => {
    const done = await run(() => mailApi.disconnect(), errorMessage)
    if (done) setSt(done)
  }

  // With nothing connected, the same call puts the "disconnected" notice away.
  const dismiss = disconnect

  return (
    <section className="card flex flex-col gap-3 px-4 py-4" aria-labelledby="mail-heading">
      <div>
        <h2 id="mail-heading" className="font-semibold">
          Your Gmail
        </h2>
        <p className="text-sm text-muted">
          Connect your Gmail and ask the chat about it — “when is our flight?”, “what did the school send?” — and have it add what it finds. luach only reads, only when you ask, and only
          your own mailbox: nobody else in the family can search it, and you cannot search theirs.
        </p>
      </div>
      {came === 'connected' ? <Notice kind="info">Your email is connected.</Notice> : null}
      {st?.lost && came !== 'connected' ? (
        <div role="alert" className="flex flex-col gap-2 rounded-xl border border-danger/25 bg-danger/10 px-3.5 py-3 text-sm">
          <p className="font-semibold text-danger">Gmail disconnected — reconnect</p>
          <p>
            Google stopped luach reading {st.lost.address ? <span className="font-medium">{st.lost.address}</span> : 'your Gmail'}
            {st.lost.via === 'household' ? ' (the household mailbox the email door reads)' : ''}, so new mail is no longer looked through. Google does this when access is
            revoked, a password changes, or — for a personal Gmail — about once a week while this luach's Google app is in testing.
          </p>
          <div className="flex flex-wrap gap-2">
            {st.can_connect ? (
              <Button variant="primary" onClick={connect}>
                Reconnect Gmail
              </Button>
            ) : null}
            <Button variant="secondary" busy={busy} onClick={() => void dismiss()}>
              Dismiss
            </Button>
          </div>
        </div>
      ) : null}
      {came === 'failed' ? <Notice kind="error">Connecting your email did not work. Try again, or ask whoever set luach up.</Notice> : null}
      {came === 'not-yours' ? (
        <Notice kind="error">
          That Gmail is not one of your addresses here, so it was not connected. Add it under your addresses and confirm it, then connect again — or choose your own account when
          Google asks.
        </Notice>
      ) : null}
      {off ? (
        <Notice kind="info">{off}</Notice>
      ) : st === null ? (
        <Spinner />
      ) : st.connected ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[15px]">
            Connected{st.address ? <> as <span className="font-medium">{st.address}</span></> : null}
            {st.via === 'household' ? <span className="text-sm text-muted"> — the household mailbox, the one you forward things to</span> : null}
          </p>
          {st.via === 'own' ? (
            <Button variant="secondary" busy={busy} onClick={() => void disconnect()}>
              Disconnect
            </Button>
          ) : null}
          {/* The owner reads the household mailbox until they connect their own; once they
              do, theirs is the one every search and the scan use. */}
          {st.via === 'household' && st.can_connect ? (
            <div className="flex w-full flex-col gap-2 rounded-xl border border-line px-3 py-3">
              <p className="text-sm text-muted">
                This is the household's shared connection. Connect your own to have luach read your Gmail through its own access, which you can disconnect here at any time.
              </p>
              <Button variant="secondary" className="self-start" onClick={connect}>
                Connect my own Gmail
              </Button>
            </div>
          ) : null}
        </div>
      ) : st.lost ? null : st.can_connect ? (
        <div>
          <Button variant="primary" onClick={connect}>
            Connect my Gmail
          </Button>
        </div>
      ) : (
        <p className="text-sm text-muted">Connecting email is not set up on this luach yet.</p>
      )}
      {st?.connected && st.scan?.available ? (
        <label className="flex items-start gap-3 rounded-xl border border-line px-3 py-3">
          <input
            type="checkbox"
            checked={st.scan.enabled}
            disabled={busy}
            onChange={(e) => void setScan(e.target.checked)}
            className="mt-0.5 h-5 w-5 shrink-0 accent-[var(--accent)]"
          />
          <span className="flex flex-col gap-0.5">
            <span className="text-[15px] font-medium">Look through new mail for things to add</span>
            <span className="text-sm text-muted">
              Every {st.scan.minutes} minutes luach reads what has arrived — not promotions or social mail — and when it finds an appointment, a booking or a date, it asks
              you under Pending. Nothing is added until you say yes, and only you see what it found.
              {st.scan.enabled && st.scan.since ? ` Reading mail from ${new Date(st.scan.since + (st.scan.since.endsWith('Z') ? '' : 'Z')).toLocaleDateString()} on.` : ''}
            </span>
            {st.scan.enabled && st.scan.read !== undefined ? (
              <span className="mt-1 flex items-center gap-2 text-xs text-muted">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-success" />
                {st.scan.last_read ? `Last read ${new Date(st.scan.last_read).toLocaleString()} · ` : ''}
                {st.scan.read} read · {st.scan.proposed ?? 0} found
              </span>
            ) : null}
          </span>
        </label>
      ) : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
    </section>
  )
}
