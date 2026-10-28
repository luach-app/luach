import { useEffect, useState, type FormEvent } from 'react'
import { errorMessage, passkeys as passkeysApi } from '../lib/api'
import type { Passkey } from '../lib/types'
import { guessDeviceName, passkeyErrorMessage, passkeysSupported, registerPasskey } from '../lib/passkeys'
import { formatTimestamp, relativeTime } from '../lib/time'
import { useAction } from '../lib/hooks'
import { Button, Spinner } from './Button'
import { Input, Notice } from './Field'
import { KeyIcon } from './Icons'

/** Settings › Passkeys: list, add (with a short name), remove with confirm. */
export function Passkeys({ tz, locale }: { tz: string; locale: string }) {
  const [list, setList] = useState<Passkey[] | null>(null)
  const [loadError, setLoadError] = useState('')
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState(() => guessDeviceName())
  const [confirm, setConfirm] = useState<string | null>(null)
  const { busy, error, setError, run } = useAction()
  const supported = passkeysSupported()

  useEffect(() => {
    passkeysApi
      .list()
      .then((l) => setList(l.passkeys))
      .catch((e) => setLoadError(errorMessage(e)))
  }, [])

  const add = async (e: FormEvent) => {
    e.preventDefault()
    const l = await run(() => registerPasskey(name), passkeyErrorMessage)
    if (l) {
      setList(l.passkeys)
      setAdding(false)
      setName(guessDeviceName())
    }
  }
  const remove = async (id: string) => {
    const l = await run(() => passkeysApi.remove(id), errorMessage)
    setConfirm(null)
    if (l) setList(l.passkeys)
  }

  return (
    <section className="card flex flex-col gap-3 px-4 py-4" aria-labelledby="passkeys-heading">
      <div>
        <h2 id="passkeys-heading" className="font-semibold">
          Passkeys
        </h2>
        <p className="text-sm text-muted">Face ID, Touch ID or your phone — no password to type.</p>
      </div>
      {loadError ? <Notice kind="error">{loadError}</Notice> : null}
      {list === null && !loadError ? (
        <div className="flex justify-center py-3 text-muted">
          <Spinner />
        </div>
      ) : list && list.length > 0 ? (
        <ul className="flex flex-col divide-y divide-line rounded-xl border border-line">
          {list.map((k) => (
            <li key={k.id} className="flex min-h-12 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
              <KeyIcon width={18} height={18} className="shrink-0 text-muted" />
              <span className="min-w-[10rem] flex-1">
                <span className="block truncate text-[15px]" dir="auto">
                  {k.name || 'Passkey'}
                </span>
                <span className="block text-xs text-muted">
                  Added {formatTimestamp(k.created_at, tz, locale)} · {k.last_used ? `used ${relativeTime(k.last_used, locale)}` : 'never used'}
                </span>
              </span>
              {confirm === k.id ? (
                <span className="ms-auto flex items-center gap-1.5">
                  <Button size="sm" variant="ghost" onClick={() => setConfirm(null)} disabled={busy}>
                    Keep
                  </Button>
                  <Button size="sm" variant="danger" busy={busy} onClick={() => void remove(k.id)}>
                    Remove
                  </Button>
                </span>
              ) : (
                <Button size="sm" variant="ghost" className="ms-auto" disabled={busy} onClick={() => setConfirm(k.id)} aria-label={`Remove passkey ${k.name || ''}`.trim()}>
                  Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
      ) : list ? (
        <p className="rounded-xl border border-dashed border-line-strong px-3 py-4 text-center text-sm text-muted">No passkeys yet.</p>
      ) : null}
      {adding ? (
        <form onSubmit={add} className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <Input label="Name this passkey" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoFocus autoComplete="off" className="flex-1" hint="Something like the device you are on." />
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={() => setAdding(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" busy={busy}>
              Create
            </Button>
          </div>
        </form>
      ) : (
        <Button
          onClick={() => {
            setError('')
            setAdding(true)
          }}
          disabled={!supported || list === null}
          className="self-start"
        >
          <KeyIcon width={16} height={16} /> Add a passkey
        </Button>
      )}
      {!supported ? <p className="text-xs text-muted">This browser cannot create passkeys.</p> : null}
      <Notice kind="error">{error}</Notice>
    </section>
  )
}
