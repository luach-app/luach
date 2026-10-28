import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { errorMessage, tasks as tasksApi } from '../lib/api'
import { useFamily } from '../lib/family'
import { useAction } from '../lib/hooks'
import { addDays, formatDateLong, resolveLocale, todayISO } from '../lib/time'
import type { Member, Task } from '../lib/types'
import { Button } from '../components/Button'
import { Input, Notice } from '../components/Field'
import { TaskBoard } from '../components/TaskBoard'

const WEEK = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
const SHORT: Record<string, string> = { MO: 'M', TU: 'T', WE: 'W', TH: 'T', FR: 'F', SA: 'S', SU: 'S' }
const LONG: Record<string, string> = { MO: 'Monday', TU: 'Tuesday', WE: 'Wednesday', TH: 'Thursday', FR: 'Friday', SA: 'Saturday', SU: 'Sunday' }

/** The family's tasks for a day, one column per person. */
export function Tasks({ member }: { member: Member }) {
  const tz = member.timezone
  const locale = resolveLocale(member.language)
  const today = todayISO(tz)
  const [day, setDay] = useState(today)
  const [list, setList] = useState<Task[]>([])
  const [mayAssign, setMayAssign] = useState(false)
  const [error, setError] = useState('')
  const people = useFamily()?.people ?? []

  const load = useCallback(async () => {
    try {
      const r = await tasksApi.day(day)
      setList(r.tasks)
      setMayAssign(r.may_assign)
      setError('')
    } catch (e) {
      setError(errorMessage(e))
    }
  }, [day])
  useEffect(() => {
    void load()
  }, [load])

  const tick = async (t: Task) => {
    // Shown at once; put back if the server says no.
    setList((l) => l.map((x) => (x.id === t.id ? { ...x, done: !t.done } : x)))
    try {
      await tasksApi.tick(t.id, day, !t.done)
    } catch (e) {
      setError(errorMessage(e))
      void load()
    }
  }
  const remove = async (t: Task) => {
    try {
      await tasksApi.remove(t.id)
      void load()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <div className="fade-up">
      <header className="flex flex-wrap items-end justify-between gap-3 px-1">
        <div>
          <h1 className="text-2xl font-semibold">Tasks</h1>
          <p className="text-sm text-muted">{day === today ? 'Today' : formatDateLong(day, locale)}</p>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" onClick={() => setDay(addDays(day, -1))} aria-label="Previous day">
            ‹
          </Button>
          <Button variant="ghost" onClick={() => setDay(today)} disabled={day === today}>
            Today
          </Button>
          <Button variant="ghost" onClick={() => setDay(addDays(day, 1))} aria-label="Next day">
            ›
          </Button>
        </div>
      </header>
      <div className="mt-4">
        <Notice kind="error">{error}</Notice>
      </div>
      <div className="mt-2">
        <TaskBoard people={people} tasks={list} onTick={tick} onRemove={mayAssign ? remove : undefined} />
      </div>
      {mayAssign ? <AddTask people={people} day={day} onAdded={load} /> : <p className="mt-4 px-1 text-sm text-muted">Tick what you have done. A grown-up hands out the tasks.</p>}
    </div>
  )
}

function AddTask({ people, day, onAdded }: { people: { key: string; name: string; hex: string }[]; day: string; onAdded: () => void }) {
  const [title, setTitle] = useState('')
  const [person, setPerson] = useState('')
  const [repeat, setRepeat] = useState(false)
  const [days, setDays] = useState<string[]>([])
  const [due, setDue] = useState('')
  const { busy, error, setError, run } = useAction()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (repeat && !days.length) {
      setError('Pick the days it repeats on.')
      return
    }
    const ok = await run(() => tasksApi.add({ title: title.trim(), person, ...(repeat ? { days } : due ? { due } : {}) }), errorMessage)
    if (ok) {
      setTitle('')
      setDays([])
      setDue('')
      onAdded()
    }
  }

  return (
    <form onSubmit={submit} className="card mt-5 flex flex-col gap-4 px-4 py-4" aria-label="New task">
      <h2 className="text-lg font-semibold">New task</h2>
      <Input label="What" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Take the bins out" required autoComplete="off" dir="auto" />
      <fieldset>
        <legend className="mb-2 text-sm font-medium">For</legend>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Task for">
          {[{ key: '', name: 'Anyone', hex: '' }, ...people].map((p) => {
            const on = p.key === person
            return (
              <button
                key={p.key || 'anyone'}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => setPerson(p.key)}
                className={`inline-flex min-h-9 items-center gap-2 rounded-full border px-3 text-sm ${on ? 'border-transparent font-medium text-white' : 'border-line hover:border-line-strong'}`}
                style={on ? { background: p.hex || 'var(--accent)' } : undefined}
              >
                {p.hex && !on ? <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: p.hex }} /> : null}
                {p.name}
              </button>
            )
          })}
        </div>
      </fieldset>
      <label className="flex min-h-9 items-center gap-2.5 text-sm">
        <input type="checkbox" checked={repeat} onChange={(e) => setRepeat(e.target.checked)} className="h-5 w-5 accent-[var(--accent)]" />
        A chore that repeats
      </label>
      {repeat ? (
        <div className="flex gap-1.5" role="group" aria-label="Repeats on">
          {WEEK.map((d) => {
            const on = days.includes(d)
            return (
              <button
                key={d}
                type="button"
                aria-pressed={on}
                aria-label={LONG[d]}
                onClick={() => setDays(on ? days.filter((x) => x !== d) : WEEK.filter((x) => x === d || days.includes(x)))}
                className={`h-10 w-10 rounded-full border text-sm font-medium ${on ? 'border-transparent bg-accent text-accent-on' : 'border-line'}`}
              >
                {SHORT[d]}
              </button>
            )
          })}
        </div>
      ) : (
        <Input label="Due (optional)" type="date" value={due} min={day} onChange={(e) => setDue(e.target.value)} />
      )}
      <Notice kind="error">{error}</Notice>
      <div className="flex justify-end">
        <Button type="submit" variant="primary" busy={busy}>
          Add task
        </Button>
      </div>
    </form>
  )
}
