import { useState, type FormEvent } from 'react'
import type { Member } from '../../lib/types'
import { dismissPasskeyOffer, guessDeviceName, passkeyErrorMessage, registerPasskey } from '../../lib/passkeys'
import { useAction } from '../../lib/hooks'
import { Button } from '../../components/Button'
import { Input, Notice } from '../../components/Field'
import { KeyIcon } from '../../components/Icons'
import { GateShell } from './GateShell'

export function PasskeyOffer({ member, onDone }: { member: Member; onDone: () => void }) {
  const [name, setName] = useState(() => guessDeviceName())
  const { busy, error, run } = useAction()

  const notNow = () => {
    dismissPasskeyOffer()
    onDone()
  }
  const add = async (e: FormEvent) => {
    e.preventDefault()
    const l = await run(() => registerPasskey(name), passkeyErrorMessage)
    if (l) onDone()
  }

  return (
    <GateShell title="Add a passkey to this device?" subtitle={<>Next time, <span className="text-text" dir="auto">{member.display_name || member.username}</span> can sign in with Face ID, Touch ID or a phone — no password to type.</>}>
      <form onSubmit={add} className="flex flex-col gap-4">
        <Input label="Name this passkey" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoComplete="off" />
        <Notice kind="error">{error}</Notice>
        <Button type="submit" variant="primary" size="lg" busy={busy}>
          <KeyIcon width={18} height={18} /> Add a passkey
        </Button>
        <Button type="button" variant="ghost" onClick={notNow} disabled={busy}>
          Not now
        </Button>
      </form>
    </GateShell>
  )
}
