import { useState, type FormEvent } from 'react'
import { auth, errorMessage } from '../../lib/api'
import type { Member } from '../../lib/types'
import { useAction } from '../../lib/hooks'
import { Button } from '../../components/Button'
import { Input, Notice } from '../../components/Field'
import { GateShell } from './GateShell'

interface Props {
  token: string
  onSignedIn: (m: Member) => void
  onCancel: () => void
}

export function Reset({ token, onSignedIn, onCancel }: Props) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const { busy, error, setError, run } = useAction()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (password !== confirm) {
      setError('The two passwords do not match.')
      return
    }
    const m = await run(() => auth.reset(token, password), errorMessage)
    if (m) onSignedIn(m)
  }

  return (
    <GateShell title="Choose a new password">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Input label="New password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" autoFocus required minLength={8} hint="At least 8 characters." />
        <Input label="Repeat it" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
        <Notice kind="error">{error}</Notice>
        <Button type="submit" variant="primary" size="lg" busy={busy}>
          Save and sign in
        </Button>
        <button type="button" onClick={onCancel} className="self-center text-sm text-muted underline-offset-4 hover:text-accent-text hover:underline">
          Back to sign in
        </button>
      </form>
    </GateShell>
  )
}
