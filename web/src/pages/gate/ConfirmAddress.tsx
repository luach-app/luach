import { useEffect, useRef, useState } from 'react'
import { emails as emailsApi, errorMessage } from '../../lib/api'
import { Button, Spinner } from '../../components/Button'
import { Notice } from '../../components/Field'
import { GateShell } from './GateShell'

/** Landing on the link mailed to an address, signed in or not. */
export function ConfirmAddress({ token, onDone }: { token: string; onDone: () => void }) {
  const [state, setState] = useState<{ email: string; kind: string } | null>(null)
  const [error, setError] = useState('')
  const asked = useRef(false)

  useEffect(() => {
    if (asked.current) return // StrictMode mounts twice; the token is one use
    asked.current = true
    emailsApi
      .verify(token)
      .then(setState)
      .catch((e) => setError(errorMessage(e) || 'This link is no longer valid.'))
  }, [token])

  if (error) {
    return (
      <GateShell title="That link has expired" subtitle="Ask for a new one from Settings › Emails.">
        <Notice kind="error">{error}</Notice>
        <Button variant="primary" onClick={onDone} className="mt-4 w-full">
          Continue to luach
        </Button>
      </GateShell>
    )
  }
  if (!state) {
    return (
      <GateShell title="Confirming your address">
        <div className="flex justify-center py-4 text-muted">
          <Spinner />
        </div>
      </GateShell>
    )
  }
  return (
    <GateShell title="Address confirmed" subtitle={state.email}>
      <p className="text-sm text-muted">
        {state.kind === 'alias'
          ? 'You can sign in with this address now, and mail you send from it is yours.'
          : 'Every event you add from now on also invites this address.'}
      </p>
      <Button variant="primary" onClick={onDone} className="mt-5 w-full">
        Continue to luach
      </Button>
    </GateShell>
  )
}
