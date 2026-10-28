import { useEffect, useRef, useState, type FormEvent } from 'react'
import { auth, errorMessage } from '../../lib/api'
import type { MailInfo, Member, SsoInfo } from '../../lib/types'
import { cleanQuery } from '../../lib/route'
import { useAction } from '../../lib/hooks'
import { conditionalPasskeySignIn, passkeyErrorMessage, passkeysSupported, signInWithPasskey } from '../../lib/passkeys'
import { Button } from '../../components/Button'
import { Input, Notice } from '../../components/Field'
import { KeyIcon } from '../../components/Icons'
import { GateShell } from './GateShell'

export function Login({
  onSignedIn,
  sso,
  household,
  mail,
}: {
  onSignedIn: (m: Member) => void
  sso?: SsoInfo
  household?: string
  /** What mail can do on this server (`/api/auth/status`); older servers may omit it. */
  mail?: MailInfo
}) {
  const [mode, setMode] = useState<'login' | 'forgot'>('login')
  if (mode === 'forgot') return <Forgot onBack={() => setMode('login')} mail={mail} />
  return <LoginForm onSignedIn={onSignedIn} onForgot={() => setMode('forgot')} sso={sso} household={household} />
}

/** "The Rivera household calendar.", or "The household calendar." for a household with no name set. */
function householdLine(name?: string): string {
  const n = name?.trim()
  return n ? `The ${n} household calendar.` : 'The household calendar.'
}

/** The server sends a failed single sign-on back to `/?sso=failed`, with no detail. */
function readSsoFailed(): boolean {
  return new URLSearchParams(window.location.search).get('sso') === 'failed'
}

function LoginForm({ onSignedIn, onForgot, sso, household }: { onSignedIn: (m: Member) => void; onForgot: () => void; sso?: SsoInfo; household?: string }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const { busy, error, run } = useAction()
  const passkey = useAction()
  const supported = passkeysSupported()
  const conditional = useRef<AbortController | null>(null)
  const [ssoFailed] = useState(readSsoFailed)
  const [ssoLeaving, setSsoLeaving] = useState(false)
  const ssoEnabled = sso?.enabled === true

  useEffect(() => {
    if (ssoFailed) cleanQuery()
  }, [ssoFailed])

  // Coming back from the provider with the Back button restores this page from cache.
  useEffect(() => {
    const reset = () => setSsoLeaving(false)
    window.addEventListener('pageshow', reset)
    return () => window.removeEventListener('pageshow', reset)
  }, [])

  // Let the browser offer a saved passkey inline on the username field; drop it on unmount.
  useEffect(() => {
    if (!supported) return
    const ac = new AbortController()
    conditional.current = ac
    conditionalPasskeySignIn(ac.signal)
      .then((m) => {
        if (m && !ac.signal.aborted) onSignedIn(m)
      })
      .catch(() => {
        /* quiet: the modal button reports errors */
      })
    return () => ac.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supported])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const m = await run(() => auth.login(username.trim(), password), errorMessage)
    if (m) onSignedIn(m)
  }
  const withSso = () => {
    conditional.current?.abort()
    setSsoLeaving(true)
    window.location.assign('/api/auth/oidc/start')
  }
  const withPasskey = async () => {
    conditional.current?.abort() // one WebAuthn request at a time
    const m = await passkey.run(() => signInWithPasskey(), passkeyErrorMessage)
    if (m) onSignedIn(m)
  }

  return (
    <GateShell title="Welcome back" subtitle={householdLine(household)}>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Input label="Username or email" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username webauthn" autoCapitalize="none" autoFocus required />
        <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        <Notice kind="error">{error}</Notice>
        <Button type="submit" variant="primary" size="lg" busy={busy}>
          Sign in
        </Button>
        {supported || ssoEnabled ? (
          <div className="flex items-center gap-3 text-xs uppercase tracking-wider text-muted" aria-hidden>
            <span className="h-px flex-1 bg-line-strong" /> or <span className="h-px flex-1 bg-line-strong" />
          </div>
        ) : null}
        {supported ? (
          <>
            <Button type="button" size="lg" busy={passkey.busy} disabled={busy || ssoLeaving} onClick={() => void withPasskey()}>
              <KeyIcon width={18} height={18} /> Sign in with a passkey
            </Button>
            <Notice kind="error">{passkey.error}</Notice>
          </>
        ) : null}
        {ssoEnabled ? (
          <Button type="button" size="lg" busy={ssoLeaving} disabled={busy || passkey.busy} onClick={withSso}>
            {sso?.label || 'Sign in with single sign-on'}
          </Button>
        ) : null}
        {ssoFailed ? <Notice kind="info">Single sign-on did not complete. Try again, or use another way to sign in.</Notice> : null}
        <button type="button" onClick={onForgot} className="self-center text-sm text-muted underline-offset-4 hover:text-accent-text hover:underline">
          Forgot your password?
        </button>
      </form>
    </GateShell>
  )
}

const OFFLINE_RESET = 'docker compose exec luach python -m luach.passwd <username>'

/** The command whoever runs the server types to set a member's password without mail. */
function OfflineReset({ mail }: { mail?: MailInfo }) {
  return (
    <code className="block select-all break-all rounded-lg bg-surface px-2.5 py-2 text-xs text-text" dir="ltr">
      {mail?.offline_reset || OFFLINE_RESET}
    </code>
  )
}

function Forgot({ onBack, mail }: { onBack: () => void; mail?: MailInfo }) {
  if (mail && !mail.enabled) {
    // A form that promised a link nobody would send was a dead end.
    return (
      <GateShell title="Reset your password" subtitle="This luach does not send email, so a reset link cannot reach you.">
        <div className="flex flex-col gap-4">
          <p className="text-sm text-muted">Ask whoever runs luach to set a new password for you. On the server, they run:</p>
          <OfflineReset mail={mail} />
          <Button variant="secondary" onClick={onBack}>
            Back to sign in
          </Button>
        </div>
      </GateShell>
    )
  }
  return <ForgotByMail onBack={onBack} mail={mail} />
}

function ForgotByMail({ onBack, mail }: { onBack: () => void; mail?: MailInfo }) {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const { busy, error, run } = useAction()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const ok = await run(() => auth.forgot(email.trim()), errorMessage)
    if (ok) setSent(true)
  }

  return (
    <GateShell title="Reset your password" subtitle="We will email you a reset link if that address belongs to a member. It expires in 30 minutes.">
      {sent ? (
        <div className="flex flex-col gap-4">
          <Notice kind="success">If that address is a member, a reset link is on its way by email. It expires in 30 minutes.</Notice>
          {mail?.limitation ? <Notice kind="info">{mail.limitation}</Notice> : null}
          <Button variant="secondary" onClick={onBack}>
            Back to sign in
          </Button>
        </div>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoFocus required />
          {mail?.limitation ? <Notice kind="info">{mail.limitation}</Notice> : null}
          <Notice kind="error">{error}</Notice>
          <Button type="submit" variant="primary" size="lg" busy={busy}>
            Send the link
          </Button>
          <button type="button" onClick={onBack} className="self-center text-sm text-muted underline-offset-4 hover:text-accent-text hover:underline">
            Back to sign in
          </button>
        </form>
      )}
    </GateShell>
  )
}
