import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage, models as modelsApi } from '../lib/api'
import { useAction, useVisiblePoll } from '../lib/hooks'
import {
  answering,
  contextLabel,
  moved,
  priceLabel,
  verdictLabel,
  type CatalogueAnswer,
  type CatalogueEntry,
  type ManagedModel,
  type ModelsSnapshot,
  type ModelTrial,
} from '../lib/models'
import { Badge } from './Badge'
import { Button, Spinner } from './Button'
import { Input, Notice } from './Field'

/**
 * Settings › Household › Models (owner only): which models members may choose,
 * which one answers by default, each one tried before it joins, and the ones
 * that stopped answering. Every change is the server's to accept; this shows
 * what it answers.
 */
export function Models() {
  const [snap, setSnap] = useState<ModelsSnapshot | null>(null)
  const [loadError, setLoadError] = useState('')
  const [note, setNote] = useState('')
  const { busy, error, setError, run } = useAction()

  const load = useCallback(async () => {
    try {
      setSnap(await modelsApi.manage())
      setLoadError('')
    } catch (e) {
      setLoadError(errorMessage(e))
    }
  }, [])
  useEffect(() => {
    void load()
  }, [load])

  const running = snap?.trial?.status === 'running'
  // While a trial runs, its progress; when it ends, the list again (scores, health).
  useVisiblePoll(
    async () => {
      try {
        const r = await modelsApi.trial()
        if (r.trial?.status !== 'running') await load()
        else setSnap((s) => (s ? { ...s, trial: r.trial, trials_left_today: r.trials_left_today } : s))
      } catch {
        /* the next tick tries again */
      }
    },
    2000,
    running,
  )

  const change = async (task: () => Promise<ModelsSnapshot | void>) => {
    setNote('')
    const next = await run(task, errorMessage)
    if (next) setSnap(next)
  }

  if (loadError && !snap) {
    return (
      <section className="card flex flex-col gap-3 px-4 py-4">
        <h2 className="font-semibold">Models</h2>
        <Notice kind="error">{loadError}</Notice>
        <Button variant="ghost" onClick={() => void load()} className="self-start">
          Try again
        </Button>
      </section>
    )
  }
  if (!snap) {
    return (
      <div className="card flex justify-center px-4 py-6 text-muted">
        <Spinner />
      </div>
    )
  }

  const ids = snap.models.map((m) => m.id)
  const nameOf = (id: string) => snap.models.find((m) => m.id === id)?.name ?? id
  const tryIt = async (id: string) => {
    setNote('')
    const r = await run(() => modelsApi.tryIt(id), errorMessage)
    if (r) setSnap({ ...snap, trial: r.trial, trials_left_today: r.trials_left_today })
  }
  const check = async (id: string) => {
    setNote('')
    const r = await run(() => modelsApi.check(id), errorMessage)
    if (r) {
      setSnap({ ...snap, models: r.models })
      setNote(r.ok ? `${nameOf(id)} answered.` : `${nameOf(id)} did not answer: ${r.reason}`)
    }
  }

  return (
    <section className="card flex flex-col gap-4 px-4 py-4" aria-labelledby="models-heading">
      <div>
        <h2 id="models-heading" className="font-semibold">
          Models
        </h2>
        <p className="text-sm text-muted">
          The AI models members can choose to answer them, and the one that answers when they have not chosen. A new model joins
          the menu when you turn it on; try it first.
        </p>
      </div>
      {!snap.configured ? (
        <Notice kind="error">
          No model is set up yet, so the assistant cannot answer. Add one below and make it the default (the server needs
          OPENAI_BASE_URL too).
        </Notice>
      ) : null}

      <ul className="flex flex-col divide-y divide-line rounded-xl border border-line" aria-label="Models on the list">
        {snap.models.map((m, i) => (
          <ModelRow
            key={m.id}
            model={m}
            first={i === 0}
            last={i === snap.models.length - 1}
            busy={busy}
            trialRunning={running}
            onToggle={(enabled) => void change(() => modelsApi.edit({ id: m.id, enabled }))}
            onDefault={() => void change(() => modelsApi.setDefault(m.id))}
            onMove={(by) => void change(() => modelsApi.order(moved(ids, m.id, by)))}
            onRemove={() => {
              if (window.confirm(`Take ${m.name} off the list? Members who chose it go back to the household's model.`))
                void change(() => modelsApi.remove(m.id))
            }}
            onSave={(fields) => change(() => modelsApi.edit({ id: m.id, ...fields }))}
            onTry={() => void tryIt(m.id)}
            onCheck={() => void check(m.id)}
          />
        ))}
        {!snap.models.length ? <li className="px-3 py-3 text-sm text-muted">No models yet.</li> : null}
      </ul>

      <TrialPanel trial={snap.trial} nameOf={nameOf} left={snap.trials_left_today} onCancel={() => void change(async () => {
        await modelsApi.cancelTrial()
        return modelsApi.manage()
      })} />

      <Notice kind="error">{error}</Notice>
      {note ? <Notice kind="info">{note}</Notice> : null}

      <AddModel
        catalogue={snap.catalogue}
        busy={busy}
        onAdd={async (entry) => {
          setNote('')
          const r = await run(() => modelsApi.add(entry), errorMessage)
          if (r) {
            setSnap(r)
            const added = r.models.find((m) => m.id === r.added)?.name ?? r.added
            setNote(
              `${added} is on the list, off the menu until you turn it on.` +
                (r.trial_started ? ' Trying it now.' : r.note ? ` Not tried: ${r.note}` : ''),
            )
            return true
          }
          return false
        }}
        onError={setError}
      />
    </section>
  )
}

function HealthBadge({ model }: { model: ManagedModel }) {
  if (answering(model)) return null
  return <Badge tone="danger">Not answering</Badge>
}

function ScoreBadge({ model }: { model: ManagedModel }) {
  const t = model.trial
  if (!t) return <Badge>Not tried</Badge>
  const tone = t.verdict === 'good' ? 'success' : t.verdict === 'fair' ? 'warn' : 'danger'
  return <Badge tone={tone}>{verdictLabel(t)}</Badge>
}

interface RowProps {
  model: ManagedModel
  first: boolean
  last: boolean
  busy: boolean
  trialRunning: boolean
  onToggle: (enabled: boolean) => void
  onDefault: () => void
  onMove: (by: -1 | 1) => void
  onRemove: () => void
  onSave: (fields: { name: string; about: string; provider: string; local: boolean }) => Promise<void>
  onTry: () => void
  onCheck: () => void
}

function ModelRow({ model: m, first, last, busy, trialRunning, onToggle, onDefault, onMove, onRemove, onSave, onTry, onCheck }: RowProps) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(m.name)
  const [about, setAbout] = useState(m.about)
  const [provider, setProvider] = useState(m.provider_set)
  const [local, setLocal] = useState(!!m.local)
  const where = m.local ? 'At home' : m.provider || 'Cloud'
  const low = m.trial?.verdict === 'low'
  return (
    <li className="flex flex-col gap-2 px-3 py-3" aria-label={m.name}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 font-medium" dir="auto">
          {m.name}
          <span className="ms-2 break-all font-mono text-xs text-muted">{m.id}</span>
        </span>
        {m.is_default ? <Badge tone="accent">Default</Badge> : null}
        <Badge>{where}</Badge>
        <HealthBadge model={m} />
        <ScoreBadge model={m} />
      </div>
      {m.about ? <p className="text-sm text-muted" dir="auto">{m.about}</p> : null}
      {!answering(m) ? (
        <p className="text-sm text-danger">
          Not answering since {m.health?.since ? new Date(m.health.since).toLocaleString() : 'recently'}: {m.health?.reason}
        </p>
      ) : null}
      {low ? (
        <p className="text-sm text-danger" role="note">
          Low score: on the trial it picked the wrong thing to do in {(m.trial?.total ?? 0) - (m.trial?.passed ?? 0)} of{' '}
          {m.trial?.total} cases. Members may get wrong answers, or events that were never added.
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex min-h-9 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={m.enabled}
            disabled={busy || m.is_default}
            onChange={(e) => onToggle(e.target.checked)}
            className="h-5 w-5 accent-[var(--accent)]"
            aria-label={`${m.name} on the members' menu`}
          />
          On the menu
        </label>
        {!m.is_default ? (
          <Button size="sm" variant="ghost" disabled={busy || !answering(m)} onClick={onDefault}>
            Make default
          </Button>
        ) : null}
        <Button size="sm" variant="ghost" disabled={busy || trialRunning} onClick={onTry} aria-label={`Try ${m.name}`}>
          Try it
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onCheck} aria-label={`Check ${m.name}`}>
          Check
        </Button>
        <Button size="sm" variant="ghost" disabled={busy || first} onClick={() => onMove(-1)} aria-label={`Move ${m.name} up`}>
          ↑
        </Button>
        <Button size="sm" variant="ghost" disabled={busy || last} onClick={() => onMove(1)} aria-label={`Move ${m.name} down`}>
          ↓
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => setEditing((v) => !v)} aria-expanded={editing}>
          Edit
        </Button>
        {!m.is_default ? (
          <Button size="sm" variant="danger" disabled={busy} onClick={onRemove} aria-label={`Remove ${m.name}`}>
            Remove
          </Button>
        ) : null}
      </div>
      {editing ? (
        <form
          className="flex flex-col gap-3 rounded-xl border border-line p-3"
          onSubmit={(e) => {
            e.preventDefault()
            void onSave({ name, about, provider, local }).then(() => setEditing(false))
          }}
        >
          <Input label="Name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} dir="auto" required />
          <Input
            label="About"
            hint="Shown beside it in members' settings: say where what they ask is sent."
            value={about}
            maxLength={300}
            onChange={(e) => setAbout(e.target.value)}
            dir="auto"
          />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={local} onChange={(e) => setLocal(e.target.checked)} className="h-5 w-5 accent-[var(--accent)]" />
            Runs on our own computer (nothing leaves the house)
          </label>
          {!local ? (
            <Input
              label="Who runs it"
              hint={`As the privacy page says it. Empty: worked out from the id (${m.provider || 'a cloud provider'}).`}
              value={provider}
              maxLength={80}
              onChange={(e) => setProvider(e.target.value)}
            />
          ) : null}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" busy={busy}>
              Save
            </Button>
          </div>
        </form>
      ) : null}
    </li>
  )
}

function TrialPanel({
  trial,
  nameOf,
  left,
  onCancel,
}: {
  trial: ModelTrial | null
  nameOf: (id: string) => string
  left: number
  onCancel: () => void
}) {
  const leftLine = <p className="text-xs text-muted">{left === 1 ? '1 trial' : `${left} trials`} left today.</p>
  if (!trial) return leftLine
  const name = nameOf(trial.model)
  if (trial.status === 'running') {
    return (
      <div className="flex flex-col gap-2 rounded-xl border border-line p-3" role="status" aria-live="polite">
        <div className="flex items-center gap-2 text-sm">
          <Spinner />
          <span className="flex-1">
            Trying {name}: {trial.done} of {trial.total || 12} cases
          </span>
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
        <progress className="h-2 w-full accent-[var(--accent)]" max={trial.total || 12} value={trial.done} aria-label={`Trial of ${name}`} />
        {leftLine}
      </div>
    )
  }
  const failed = trial.cases.filter((c) => !c.ok)
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-line p-3 text-sm">
      {trial.status === 'done' ? (
        <p>
          Last trial: {name}, <strong>{verdictLabel(trial)}</strong>
          {trial.verdict === 'low' ? ' — not one to put on the menu.' : '.'}
        </p>
      ) : (
        <p>
          Last trial of {name} {trial.status === 'cancelled' ? 'was cancelled' : `did not finish: ${trial.error}`}.
        </p>
      )}
      {failed.length ? (
        <details>
          <summary className="cursor-pointer text-muted">What it got wrong</summary>
          <ul className="mt-1 list-disc ps-5 text-muted">
            {failed.map((c) => (
              <li key={c.case}>
                {c.about}: {c.problems.join('; ')}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {leftLine}
    </div>
  )
}

function AddModel({
  catalogue,
  busy,
  onAdd,
  onError,
}: {
  catalogue: ModelsSnapshot['catalogue']
  busy: boolean
  onAdd: (entry: { id: string; name?: string; about?: string; local?: boolean }) => Promise<boolean>
  onError: (message: string) => void
}) {
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<CatalogueAnswer | null>(null)
  const [searching, setSearching] = useState(false)
  const [picked, setPicked] = useState<CatalogueEntry | { id: string; name: string } | null>(null)
  const [name, setName] = useState('')
  const [about, setAbout] = useState('')
  const [local, setLocal] = useState(false)
  const [byId, setById] = useState('')
  const ctl = useRef<AbortController | null>(null)

  const search = async (q: string) => {
    ctl.current?.abort()
    const c = new AbortController()
    ctl.current = c
    setSearching(true)
    try {
      setFound(await modelsApi.catalogue(q, c.signal))
    } catch (e) {
      if (!c.signal.aborted) onError(errorMessage(e))
    } finally {
      if (ctl.current === c) setSearching(false)
    }
  }
  const pick = (entry: CatalogueEntry | { id: string; name: string }) => {
    setPicked(entry)
    setName(entry.name.slice(0, 60))
    setAbout('provider' in entry && entry.provider ? `Runs at ${entry.provider}: what you ask is sent there.` : '')
    setLocal(false)
  }

  if (picked) {
    return (
      <form
        className="flex flex-col gap-3 rounded-xl border border-line p-3"
        aria-label="Add a model"
        onSubmit={(e) => {
          e.preventDefault()
          void onAdd({ id: picked.id, name, about, local }).then((ok) => ok && setPicked(null))
        }}
      >
        <p className="text-sm">
          Adding <span className="break-all font-mono">{picked.id}</span>. It goes on the list off the menu, and luach tries it.
        </p>
        <Input label="Name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} dir="auto" required />
        <Input label="About" value={about} maxLength={300} onChange={(e) => setAbout(e.target.value)} dir="auto" />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={local} onChange={(e) => setLocal(e.target.checked)} className="h-5 w-5 accent-[var(--accent)]" />
          Runs on our own computer (nothing leaves the house)
        </label>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => setPicked(null)}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" busy={busy}>
            Add and try it
          </Button>
        </div>
      </form>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold">Add a model</h3>
      {catalogue.configured ? (
        <form
          role="search"
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            void search(query)
          }}
        >
          <Input
            label={`Search ${catalogue.source}'s models`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="gemini flash, deepseek…"
            className="flex-1"
          />
          <Button type="submit" busy={searching}>
            Search
          </Button>
        </form>
      ) : (
        <p className="text-sm text-muted">No catalogue to search: add a model by its id.</p>
      )}
      {found?.error ? <Notice kind="error">{found.error}</Notice> : null}
      {found && !found.error ? (
        found.models.length ? (
          <ul className="flex max-h-96 flex-col divide-y divide-line overflow-y-auto rounded-xl border border-line" aria-label="Catalogue">
            {found.models.map((m) => (
              <li key={m.id} className="flex items-start gap-3 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium">{m.name}</span>
                    {m.recommended ? <Badge tone="success">Always the newest version</Badge> : null}
                    {m.tools === false ? <Badge tone="danger">No tools</Badge> : null}
                  </div>
                  <div className="break-all font-mono text-xs text-muted">{m.id}</div>
                  <div className="text-xs text-muted">
                    {[contextLabel(m.context_length), m.tools ? 'takes tools' : '', priceLabel(m.price_in, m.price_out), m.provider]
                      .filter(Boolean)
                      .join(' · ')}
                  </div>
                  {m.alias_of_it ? (
                    <div className="text-xs text-muted">
                      A pinned version; <span className="font-mono">{m.alias_of_it}</span> follows the newest.
                    </div>
                  ) : null}
                </div>
                <Button size="sm" disabled={m.on_menu || busy} onClick={() => pick(m)} aria-label={`Add ${m.name}`}>
                  {m.on_menu ? 'On the list' : 'Add'}
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">Nothing matches.</p>
        )
      ) : null}
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          const id = byId.trim()
          if (id) pick({ id, name: id })
        }}
      >
        <Input label="Or by its id" value={byId} onChange={(e) => setById(e.target.value)} placeholder="provider/model-name" className="flex-1" />
        <Button type="submit" disabled={!byId.trim()}>
          Add
        </Button>
      </form>
    </div>
  )
}
