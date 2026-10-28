import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { errorMessage, members as membersApi } from '../lib/api'
import type { InviteResult, Member, MembersResponse } from '../lib/types'
import { relativeTime, resolveLocale } from '../lib/time'
import { useAction } from '../lib/hooks'
import { Badge } from '../components/Badge'
import { Button, Spinner } from '../components/Button'
import { Input, Notice } from '../components/Field'
import { CopyIcon } from '../components/Icons'
import { FamilyEditor } from '../components/FamilyEditor'
import { Boards } from '../components/Boards'

/** Every address, primary first; older servers only send `email`. */
const memberEmails = (m: Member): string[] => (m.emails?.length ? m.emails : [m.email])

export function Members({ member }: { member: Member }) {
  const locale = resolveLocale(member.language)
  const [data, setData] = useState<MembersResponse | null>(null)
  const [error, setError] = useState('')
  const [email, setEmail] = useState('')
  const [result, setResult] = useState<InviteResult | null>(null)
  const [copied, setCopied] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState<number | null>(null)
  const invite = useAction()
  const act = useAction()

  const load = useCallback(async () => {
    try {
      setData(await membersApi.list())
      setError('')
    } catch (e) {
      setError(errorMessage(e))
    }
  }, [])
  useEffect(() => {
    void load()
  }, [load])

  const sendInvite = async (e: FormEvent) => {
    e.preventDefault()
    setResult(null)
    setCopied(false)
    const r = await invite.run(() => membersApi.invite(email.trim()), errorMessage)
    if (r) {
      setResult(r)
      setEmail('')
      void load()
    }
  }

  const copy = async (link: string) => {
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  const remove = async (id: number) => {
    const ok = await act.run(() => membersApi.remove(id), errorMessage)
    setConfirmRemove(null)
    if (ok) void load()
  }
  const revoke = async (mail: string) => {
    const ok = await act.run(() => membersApi.revoke(mail), errorMessage)
    if (ok) void load()
  }

  return (
    <div className="fade-up">
      <header className="px-1">
        <h1 className="text-2xl font-semibold">Members</h1>
        <p className="text-sm text-muted">Who shares the household calendar.</p>
      </header>

      <FamilyEditor />
      <Boards locale={locale} />

      <form onSubmit={sendInvite} className="card mt-5 flex flex-col gap-3 px-4 py-4">
        <Input label="Invite by email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" required autoComplete="off" />
        <Notice kind="error">{invite.error}</Notice>
        {result ? (
          result.link ? (
            <div className="rounded-xl border border-line-strong bg-surface-2 p-3 text-sm">
              <div className="text-muted">
                {result.mail === 'failed'
                  ? 'The invitation could not be emailed (the server’s log says why). Share this link yourself:'
                  : 'This luach does not send email. Share this link yourself:'}
              </div>
              <div className="mt-1 flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate text-xs">{result.link}</code>
                <Button size="sm" variant="secondary" onClick={() => void copy(result.link!)} aria-label="Copy invitation link">
                  <CopyIcon width={16} height={16} /> {copied ? 'Copied' : 'Copy'}
                </Button>
              </div>
              {result.warning ? (
                <div className="mt-2">
                  <Notice kind="info">{result.warning}</Notice>
                </div>
              ) : null}
            </div>
          ) : (
            <Notice kind="success">Invitation sent.</Notice>
          )
        ) : null}
        <Button type="submit" variant="primary" busy={invite.busy} className="self-end">
          Send invitation
        </Button>
      </form>

      {error ? (
        <div className="mt-4">
          <Notice kind="error">{error}</Notice>
        </div>
      ) : null}
      {act.error ? (
        <div className="mt-4">
          <Notice kind="error">{act.error}</Notice>
        </div>
      ) : null}

      {data === null && !error ? (
        <div className="flex justify-center py-10 text-muted">
          <Spinner />
        </div>
      ) : data ? (
        <>
          <h2 className="mt-7 px-1 text-xs font-semibold uppercase tracking-wider text-muted">Household</h2>
          <ul className="mt-2 flex flex-col gap-2">
            {data.members.map((m) => (
              <li key={m.id} className="card flex items-center gap-3 px-4 py-3">
                <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent-text font-semibold" dir="auto">
                  {(m.display_name || m.username).slice(0, 1).toUpperCase()}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium" dir="auto">
                      {m.display_name || m.username}
                    </span>
                    {m.is_owner ? <Badge tone="accent">owner</Badge> : null}
                  </div>
                  <div className="flex flex-wrap gap-x-2 text-sm text-muted">
                    <span>@{m.username}</span>
                    {memberEmails(m).map((e, i) => (
                      <span key={e} dir="ltr" className={`truncate ${i === 0 ? 'font-semibold text-text/85' : ''}`}>
                        {e}
                      </span>
                    ))}
                  </div>
                  <div className="text-xs text-muted">Last seen {relativeTime(m.last_seen, locale)}</div>
                </div>
                {!m.is_owner ? (
                  confirmRemove === m.id ? (
                    <div className="flex gap-1.5">
                      <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(null)}>
                        Keep
                      </Button>
                      <Button size="sm" variant="danger" busy={act.busy} onClick={() => void remove(m.id)}>
                        Remove
                      </Button>
                    </div>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(m.id)} aria-label={`Remove ${m.display_name || m.username}`}>
                      Remove
                    </Button>
                  )
                ) : null}
              </li>
            ))}
          </ul>

          {data.invites.length > 0 ? (
            <>
              <h2 className="mt-7 px-1 text-xs font-semibold uppercase tracking-wider text-muted">Invitations</h2>
              <ul className="mt-2 flex flex-col gap-2">
                {data.invites.map((i) => (
                  <li key={`${i.email}-${i.created_at}`} className="card flex items-center gap-3 px-4 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{i.email}</div>
                      <div className="text-xs text-muted">
                        {i.expired ? 'Expired' : `Expires ${relativeTime(i.expires_at, locale)}`} · sent {relativeTime(i.created_at, locale)}
                      </div>
                    </div>
                    {i.expired ? <Badge tone="danger">expired</Badge> : <Badge tone="accent">pending</Badge>}
                    <Button size="sm" variant="ghost" busy={act.busy} onClick={() => void revoke(i.email)} aria-label={`Revoke invitation for ${i.email}`}>
                      Revoke
                    </Button>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
