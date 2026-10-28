import { useEffect, useState, type FormEvent } from 'react'
import { emails as emailsApi, errorMessage } from '../lib/api'
import type { EmailListing, Member } from '../lib/types'
import { useAction } from '../lib/hooks'
import { Badge } from './Badge'
import { Button, Spinner } from './Button'
import { Input, Notice } from './Field'
import { CloseIcon } from './Icons'

interface Props {
  member: Member
  onMember: (m: Member) => void
}

/** Settings › Emails: the primary address plus any extras; every call answers with the full listing. */
export function Emails({ member, onMember }: Props) {
  const [listing, setListing] = useState<EmailListing | null>(null)
  const [loadError, setLoadError] = useState('')
  const [draft, setDraft] = useState('')
  const [confirm, setConfirm] = useState<string | null>(null)
  const [sentTo, setSentTo] = useState('')
  const { busy, error, setError, run } = useAction()

  useEffect(() => {
    emailsApi
      .list()
      .then((l) => setListing(l))
      .catch((e) => setLoadError(errorMessage(e)))
  }, [])

  const adopt = (l: EmailListing) => {
    setListing(l)
    setConfirm(null)
    const all = [l.primary, ...l.emails.map((r) => r.email).filter((e) => e !== l.primary)]
    onMember({ ...member, email: l.primary, emails: all })
  }

  const add = async (e: FormEvent) => {
    e.preventDefault()
    const value = draft.trim()
    if (!value) return
    const l = await run(() => emailsApi.add(value), errorMessage)
    if (l) {
      adopt(l)
      setDraft('')
    }
  }
  const remove = async (email: string) => {
    const l = await run(() => emailsApi.remove(email), errorMessage)
    if (l) adopt(l)
    else setConfirm(null)
  }
  const makePrimary = async (email: string) => {
    const l = await run(() => emailsApi.primary(email), errorMessage)
    if (l) adopt(l)
  }

  const rows = listing
    ? [
        { email: listing.primary, verified: true },
        ...listing.emails.filter((r) => r.email !== listing.primary).map((r) => ({ email: r.email, verified: r.verified !== false })),
      ]
    : []

  const resend = async (email: string) => {
    const done = await run(() => emailsApi.resend(email), errorMessage)
    if (done) setSentTo(email)
  }

  return (
    <section className="card flex flex-col gap-3 px-4 py-4" aria-labelledby="emails-heading">
      <div>
        <h2 id="emails-heading" className="font-semibold">
          Addresses you sign in with
        </h2>
        <p className="text-sm text-muted">You can sign in with any of these once confirmed. Mail you send from them is yours.</p>
      </div>
      {loadError ? <Notice kind="error">{loadError}</Notice> : null}
      {listing === null && !loadError ? (
        <div className="flex justify-center py-3 text-muted">
          <Spinner />
        </div>
      ) : (
        <ul className="flex flex-col divide-y divide-line rounded-xl border border-line">
          {rows.map(({ email, verified }, i) => {
            const primary = i === 0
            const confirming = confirm === email
            return (
              <li key={email} className="flex min-h-12 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                <span className="min-w-[11rem] flex-1 truncate text-[15px]" dir="ltr">
                  {email}
                </span>
                {!verified ? (
                  <span className="ms-auto flex items-center gap-1.5">
                    <Badge>unconfirmed</Badge>
                    <Button size="sm" variant="ghost" busy={busy} onClick={() => void resend(email)}>
                      {sentTo === email ? 'Sent' : 'Resend'}
                    </Button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setError('')
                        setConfirm(email)
                      }}
                      aria-label={`Remove ${email}`}
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-danger disabled:opacity-50"
                    >
                      <CloseIcon width={18} height={18} />
                    </button>
                  </span>
                ) : primary ? (
                  <Badge tone="accent" className="ms-auto">
                    primary
                  </Badge>
                ) : confirming ? (
                  <span className="ms-auto flex items-center gap-1.5">
                    <Button size="sm" variant="ghost" onClick={() => setConfirm(null)} disabled={busy}>
                      Keep
                    </Button>
                    <Button size="sm" variant="danger" busy={busy} onClick={() => void remove(email)}>
                      Remove
                    </Button>
                  </span>
                ) : (
                  <span className="ms-auto flex items-center gap-1">
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => void makePrimary(email)} aria-label={`Make ${email} primary`}>
                      Make primary
                    </Button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setError('')
                        setConfirm(email)
                      }}
                      aria-label={`Remove ${email}`}
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-danger disabled:opacity-50"
                    >
                      <CloseIcon width={18} height={18} />
                    </button>
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      )}
      <form onSubmit={add} className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <Input label="Add an address" type="email" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="name@example.com" autoComplete="email" required className="flex-1" />
        <Button type="submit" busy={busy} disabled={!draft.trim()} className="sm:shrink-0">
          Add
        </Button>
      </form>
      <p className="text-xs text-muted">A new address gets a confirmation link and does nothing until you follow it.</p>
      <Notice kind="error">{error}</Notice>
    </section>
  )
}
