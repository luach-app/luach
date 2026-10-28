import { useEffect, useState, type FormEvent } from 'react'
import { errorMessage, memory as memoryApi } from '../lib/api'
import type { MemoryFact } from '../lib/types'
import { useAction } from '../lib/hooks'
import { exampleName, useFamily } from '../lib/family'
import { Button, Spinner } from './Button'
import { Input, Notice } from './Field'
import { CloseIcon } from './Icons'

/**
 * Settings › You › What luach remembers. The facts the chat keeps about you —
 * "I only book mornings" — which it reads at the start of every conversation.
 * Yours to see, add to and take away; nobody else's list shows here.
 */
export function Memory() {
  const fam = useFamily()
  const [facts, setFacts] = useState<MemoryFact[] | null>(null)
  const [off, setOff] = useState('')
  const [draft, setDraft] = useState('')
  const { busy, error, run } = useAction()

  useEffect(() => {
    memoryApi
      .list()
      .then((r) => setFacts(r.facts))
      .catch((e) => setOff(errorMessage(e)))
  }, [])

  const add = async (e: FormEvent) => {
    e.preventDefault()
    const fact = draft.trim()
    if (!fact) return
    const done = await run(() => memoryApi.add(fact), errorMessage)
    if (done) {
      setFacts(done.facts)
      setDraft('')
    }
  }
  const remove = async (key: string) => {
    const done = await run(() => memoryApi.remove(key), errorMessage)
    if (done) setFacts(done.facts)
  }

  return (
    <section className="card flex flex-col gap-3 px-4 py-4" aria-labelledby="memory-heading">
      <div>
        <h2 id="memory-heading" className="font-semibold">
          What luach remembers
        </h2>
        <p className="text-sm text-muted">
          Things you told the chat that hold from now on — “I only book mornings”, “{exampleName(fam)} finishes school at 3:30”. It reads them at the start of every
          conversation. Take away anything that is no longer true, or tell the chat “forget that”.
        </p>
      </div>
      {off ? (
        <Notice kind="info">{off}</Notice>
      ) : facts === null ? (
        <Spinner />
      ) : facts.length === 0 ? (
        <p className="text-sm text-muted">Nothing yet.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {facts.map((f) => (
            <li key={f.key} className="flex items-start gap-3 py-2">
              <span className="min-w-0 flex-1 text-[15px]" dir="auto">
                {f.fact}
                {f.topic ? <span className="ms-2 text-xs text-muted">{f.topic}</span> : null}
              </span>
              <button
                type="button"
                onClick={() => void remove(f.key)}
                aria-label={`Forget: ${f.fact}`}
                disabled={busy}
                className="rounded-full p-1.5 text-muted hover:bg-surface-2 hover:text-danger"
              >
                <CloseIcon width={16} height={16} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {off ? null : (
        <form onSubmit={add} className="flex items-end gap-2">
          <div className="min-w-0 flex-1">
            <Input label="Tell luach something to keep" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="We keep Friday nights clear" dir="auto" maxLength={500} />
          </div>
          <Button type="submit" busy={busy} disabled={!draft.trim()}>
            Keep
          </Button>
        </form>
      )}
      {error ? <Notice kind="error">{error}</Notice> : null}
    </section>
  )
}
