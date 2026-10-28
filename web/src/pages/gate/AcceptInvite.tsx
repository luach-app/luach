import { useEffect, useState, type FormEvent } from 'react'
import { auth, errorMessage } from '../../lib/api'
import { browserTimeZone } from '../../lib/time'
import type { InviteInfo, Member } from '../../lib/types'
import { useAction } from '../../lib/hooks'
import { Button, Spinner } from '../../components/Button'
import { Input, Notice } from '../../components/Field'
import { GateShell } from './GateShell'
import { ZoneField } from './ZoneField'

interface Props {
  token: string
  onSignedIn: (m: Member, fresh?: boolean) => void
  onCancel: () => void
}

export function AcceptInvite({ token, onSignedIn, onCancel }: Props) {
  const [info, setInfo] = useState<InviteInfo | null>(null)
  const [lookupError, setLookupError] = useState('')
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [timezone, setTimezone] = useState(browserTimeZone)
  const { busy, error, run } = useAction()

  useEffect(() => {
    let alive = true
    auth
      .invite(token)
      .then((i) => alive && setInfo(i))
      .catch((e) => alive && setLookupError(errorMessage(e) || 'This invitation is not valid.'))
    return () => {
      alive = false
    }
  }, [token])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const m = await run(
      () => auth.accept({ token, username: username.trim(), password, display_name: displayName.trim() || undefined, timezone }),
      errorMessage,
    )
    if (m) onSignedIn(m, true)
  }

  if (lookupError) {
    return (
      <GateShell title="Invitation not found" subtitle="The link may have expired or already been used.">
        <div className="flex flex-col gap-4">
          <Notice kind="error">{lookupError}</Notice>
          <Button variant="secondary" onClick={onCancel}>
            Go to sign in
          </Button>
        </div>
      </GateShell>
    )
  }
  if (!info) {
    return (
      <GateShell title="Checking your invitation">
        <div className="flex justify-center py-6 text-muted">
          <Spinner />
        </div>
      </GateShell>
    )
  }
  return (
    <GateShell
      title="Join the household"
      subtitle={
        <>
          <span dir="auto">{info.inviter}</span> invited <span className="text-text">{info.email}</span>.
        </>
      }
    >
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Input label="Username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" autoFocus required minLength={2} />
        <Input label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} autoComplete="name" dir="auto" />
        <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" required minLength={8} hint="At least 8 characters." />
        <ZoneField value={timezone} onChange={setTimezone} />
        <Notice kind="error">{error}</Notice>
        <Button type="submit" variant="primary" size="lg" busy={busy}>
          Create my account
        </Button>
        <button type="button" onClick={onCancel} className="self-center text-sm text-muted underline-offset-4 hover:text-accent-text hover:underline">
          I already have an account
        </button>
      </form>
    </GateShell>
  )
}
