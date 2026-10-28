import { useEffect, useState } from 'react'
import { errorMessage } from '../lib/api'
import { disablePush, enablePush, pushState, type PushState } from '../lib/push'
import { Button } from './Button'
import { Notice } from './Field'

export function PushToggle() {
  const [state, setState] = useState<PushState | 'loading'>('loading')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    pushState()
      .then((s) => alive && setState(s))
      .catch(() => alive && setState('unsupported'))
    return () => {
      alive = false
    }
  }, [])

  const toggle = async () => {
    setBusy(true)
    setError('')
    try {
      if (state === 'on') await disablePush()
      else await enablePush()
      setState(await pushState())
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const copy: Record<PushState | 'loading', string> = {
    loading: 'Checking…',
    unsupported: 'This browser cannot receive push notifications. On iPhone, add luach to the Home Screen first.',
    unconfigured: 'Push is not configured on the server yet.',
    denied: 'Notifications are blocked for this site in your browser settings.',
    off: 'Turn on to get your reminders on this device, and a ping when something needs your approval.',
    on: 'This device gets your reminders, and a ping when something needs your approval.',
  }
  const can = state === 'on' || state === 'off'
  return (
    <section className="card flex flex-col gap-3 px-4 py-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">Notifications</h2>
          <p className="text-sm text-muted">{copy[state]}</p>
        </div>
        {can ? (
          <Button variant={state === 'on' ? 'secondary' : 'primary'} size="sm" busy={busy} onClick={() => void toggle()} aria-pressed={state === 'on'}>
            {state === 'on' ? 'Turn off' : 'Enable'}
          </Button>
        ) : null}
      </div>
      <Notice kind="error">{error}</Notice>
    </section>
  )
}
