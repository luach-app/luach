import { useState, type FormEvent } from 'react'
import { auth, errorMessage } from '../../lib/api'
import { browserTimeZone } from '../../lib/time'
import type { Member } from '../../lib/types'
import { useAction } from '../../lib/hooks'
import { Button } from '../../components/Button'
import { Input, Notice } from '../../components/Field'
import { GateShell } from './GateShell'
import { ZoneField } from './ZoneField'

/** Where the person setting luach up finds the code: the server's own log. */
function SetupCodeHint() {
  return (
    <>
      luach printed it to its log when it started. On the server, run{' '}
      <code className="rounded bg-surface px-1 py-0.5 text-xs text-text" dir="ltr">
        docker compose logs luach
      </code>{' '}
      and look for “setup code”.
    </>
  )
}

export function Bootstrap({ onSignedIn }: { onSignedIn: (m: Member, fresh?: boolean) => void }) {
  const [setupCode, setSetupCode] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [timezone, setTimezone] = useState(browserTimeZone)
  const { busy, error, run } = useAction()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const m = await run(
      () =>
        auth.register({
          username: username.trim(),
          email: email.trim(),
          password,
          display_name: displayName.trim() || undefined,
          setup_code: setupCode.trim(),
          timezone,
        }),
      errorMessage,
    )
    if (m) onSignedIn(m, true)
  }

  return (
    <GateShell title="Set up the household" subtitle="No accounts yet. The first one becomes the owner.">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Input
          label="Setup code"
          value={setupCode}
          onChange={(e) => setSetupCode(e.target.value)}
          autoComplete="one-time-code"
          autoCapitalize="characters"
          spellCheck={false}
          dir="ltr"
          placeholder="XXXX-XXXX-XXXX"
          required
          hint={<SetupCodeHint />}
        />
        <Input label="Username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" required minLength={2} />
        <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
        <Input label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} autoComplete="name" dir="auto" />
        <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" required minLength={8} hint="At least 8 characters." />
        <ZoneField value={timezone} onChange={setTimezone} />
        <Notice kind="error">{error}</Notice>
        <Button type="submit" variant="primary" size="lg" busy={busy}>
          Create owner account
        </Button>
      </form>
    </GateShell>
  )
}
