import { useState, type FormEvent } from 'react'
import { errorMessage, family as familyApi } from '../lib/api'
import { exampleName, invalidateFamily, useFamily } from '../lib/family'
import { useAction } from '../lib/hooks'
import type { Person } from '../lib/types'
import { Badge } from './Badge'
import { Button } from './Button'
import { Input, Notice } from './Field'

/**
 * The owner's family: who events and tasks belong to. A person here is not an
 * account — the children need none — though one who signs in is linked by the
 * address they share.
 */
export function FamilyEditor() {
  const family = useFamily()
  const [name, setName] = useState('')
  const [kid, setKid] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const add = useAction()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const ok = await add.run(() => familyApi.add({ name: name.trim(), kind: kid ? 'kid' : 'adult' }), errorMessage)
    if (ok) {
      setName('')
      setKid(false)
      invalidateFamily()
    }
  }

  return (
    <section className="mt-5" aria-labelledby="family-heading">
      <h2 id="family-heading" className="px-1 text-lg font-semibold">
        Family
      </h2>
      <p className="px-1 text-sm text-muted">Who events and tasks are for. Each person has their own colour, in luach and in Google Calendar.</p>
      <p className="mt-1 px-1 text-sm text-muted">
        In Google Calendar an event becomes someone’s when you give it their colour, start its title with their name (“{exampleName(family)}: football”), or invite just them.
      </p>
      <ul className="mt-3 flex flex-col gap-2">
        {(family?.people ?? []).map((p) => (
          <li key={p.key}>
            <PersonRow person={p} colors={family?.colors ?? []} open={open === p.key} onToggle={() => setOpen(open === p.key ? null : p.key)} />
          </li>
        ))}
      </ul>
      <form onSubmit={submit} className="card mt-3 flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-end">
        <div className="flex-1">
          <Input label="Add someone" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" required autoComplete="off" dir="auto" />
        </div>
        <label className="flex min-h-9 items-center gap-2 text-sm">
          <input type="checkbox" checked={kid} onChange={(e) => setKid(e.target.checked)} className="h-5 w-5 accent-[var(--accent)]" />
          A child
        </label>
        <Button type="submit" variant="primary" busy={add.busy}>
          Add
        </Button>
      </form>
      <div className="mt-2">
        <Notice kind="error">{add.error}</Notice>
      </div>
    </section>
  )
}

function PersonRow({ person, colors, open, onToggle }: { person: Person; colors: { id: string; name: string; hex: string }[]; open: boolean; onToggle: () => void }) {
  const [email, setEmail] = useState(person.email)
  const [confirm, setConfirm] = useState(false)
  const act = useAction()
  const save = async (fields: Partial<Person>) => {
    const ok = await act.run(() => familyApi.update(person.key, fields), errorMessage)
    if (ok) invalidateFamily()
  }
  const remove = async () => {
    const ok = await act.run(() => familyApi.remove(person.key), errorMessage)
    if (ok) invalidateFamily()
  }
  return (
    <div className="card px-4 py-3">
      <button type="button" onClick={onToggle} className="flex w-full items-center gap-3 text-left" aria-expanded={open}>
        <span aria-hidden className="h-4 w-4 shrink-0 rounded-full" style={{ background: person.hex }} />
        <span className="flex-1 font-medium" dir="auto">
          {person.name}
        </span>
        {person.kind === 'kid' ? <Badge>child</Badge> : null}
        {person.user_id ? <Badge>signs in</Badge> : null}
      </button>
      {open ? (
        <div className="mt-3 flex flex-col gap-3 border-t border-line pt-3">
          <div>
            <div className="mb-2 text-sm font-medium">Colour</div>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={`${person.name}’s colour`}>
              {colors.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  role="radio"
                  aria-checked={c.id === person.color}
                  aria-label={c.name}
                  title={c.name}
                  onClick={() => void save({ color: c.id })}
                  className={`h-8 w-8 rounded-full border-2 ${c.id === person.color ? 'border-text' : 'border-transparent'}`}
                  style={{ background: c.hex }}
                />
              ))}
            </div>
          </div>
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              void save({ email: email.trim() })
            }}
          >
            <div className="flex-1">
              <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} hint="Invited to the events they lead. Optional." autoComplete="off" />
            </div>
            <Button type="submit" variant="ghost" busy={act.busy} disabled={email.trim() === person.email}>
              Save
            </Button>
          </form>
          <label className="flex min-h-9 items-center gap-2 text-sm">
            <input type="checkbox" checked={person.kind === 'kid'} onChange={(e) => void save({ kind: e.target.checked ? 'kid' : 'adult' })} className="h-5 w-5 accent-[var(--accent)]" />
            A child
          </label>
          <div className="flex justify-end gap-2">
            {confirm ? (
              <>
                <Button variant="ghost" onClick={() => setConfirm(false)}>
                  Keep
                </Button>
                <Button variant="danger" onClick={remove} busy={act.busy}>
                  Remove {person.name}
                </Button>
              </>
            ) : (
              <Button variant="ghost" onClick={() => setConfirm(true)}>
                Remove
              </Button>
            )}
          </div>
          <Notice kind="error">{act.error}</Notice>
        </div>
      ) : null}
    </div>
  )
}
