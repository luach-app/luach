import { useState } from 'react'
import { inkOn, type BoardPerson } from '../lib/board'
import { boardLocale, weekdayName, weekOf, type BoardLocale } from '../lib/boardText'
import type { Task, TaskInput } from '../lib/types'
import { errorMessage } from '../lib/api'
import { useAction } from '../lib/hooks'
import { Button } from './Button'
import { Input, Notice } from './Field'
import { Sheet } from './Sheet'

const ENGLISH = boardLocale('en')

export interface TaskClient {
  add: (body: TaskInput) => Promise<Task>
  update: (id: number, body: Partial<TaskInput>) => Promise<Task>
  remove: (id: number) => Promise<unknown>
}

export type TaskSheetState = { mode: 'open'; task: Task } | { mode: 'new'; person: string } | null

/**
 * A task opened on the board: what it is, whose, and when — a one-off with a
 * day it is due, or a chore on some weekdays. Change it, hand it to someone
 * else, or remove it. On a screen that only shows the day, it only shows.
 * It speaks the board's language, and reads right to left where the board does.
 */
export function BoardTaskSheet({
  state,
  people,
  canEdit,
  client,
  onClose,
  onChanged,
  loc = ENGLISH,
}: {
  state: TaskSheetState
  people: BoardPerson[]
  canEdit: boolean
  client: TaskClient
  onClose: () => void
  onChanged: () => void
  loc?: BoardLocale
}) {
  if (!state) return null
  return (
    <Form
      key={state.mode === 'open' ? state.task.id : `new-${state.person}`}
      state={state}
      people={people}
      canEdit={canEdit}
      client={client}
      onClose={onClose}
      onChanged={onChanged}
      loc={loc}
    />
  )
}

function Form({
  state,
  people,
  canEdit,
  client,
  onClose,
  onChanged,
  loc,
}: {
  state: Exclude<TaskSheetState, null>
  people: BoardPerson[]
  canEdit: boolean
  client: TaskClient
  onClose: () => void
  onChanged: () => void
  loc: BoardLocale
}) {
  const t = loc.t
  const task = state.mode === 'open' ? state.task : null
  const [title, setTitle] = useState(task?.title ?? '')
  const [person, setPerson] = useState(task ? task.person : state.mode === 'new' ? state.person : '')
  const [chore, setChore] = useState(!!task?.chore)
  const [days, setDays] = useState<string[]>(task?.days ?? [])
  const [due, setDue] = useState(task?.due ?? '')
  const [confirm, setConfirm] = useState(false)
  const { busy, error, setError, run } = useAction()
  const whose = people.find((p) => p.key === person)

  const save = async () => {
    const body: TaskInput = { title: title.trim(), person, days: chore ? days : [], due: chore ? '' : due }
    if (!body.title) return setError(t.giveItAName)
    if (chore && !days.length) return setError(t.pickTheDays)
    const ok = await run(() => (task ? client.update(task.id, body) : client.add(body)), errorMessage)
    if (ok) {
      onChanged()
      onClose()
    }
  }
  const remove = async () => {
    if (!task) return
    const ok = await run(() => client.remove(task.id), errorMessage)
    if (ok) {
      onChanged()
      onClose()
    }
  }

  return (
    <Sheet
      open
      dir={loc.dir}
      lang={loc.lang}
      closeLabel={t.close}
      title={task ? (canEdit ? t.taskTitle : task.title) : whose ? t.aTaskFor(whose.name) : t.aTask}
      onClose={onClose}
      footer={
        !canEdit ? null : confirm ? (
          <>
            <Button variant="ghost" onClick={() => setConfirm(false)} disabled={busy}>
              {t.keep}
            </Button>
            <Button variant="danger" onClick={remove} busy={busy}>
              {t.remove}
            </Button>
          </>
        ) : (
          <>
            {task ? (
              <Button variant="danger" onClick={() => setConfirm(true)}>
                {t.remove}
              </Button>
            ) : (
              <Button variant="ghost" onClick={onClose}>
                {t.cancel}
              </Button>
            )}
            <Button variant="primary" onClick={save} busy={busy}>
              {task ? t.save : t.addTask}
            </Button>
          </>
        )
      }
    >
      <fieldset disabled={!canEdit} className="flex flex-col gap-4">
        <Input label={t.what} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t.somethingToDo} dir="auto" maxLength={200} />
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium">{t.who}</span>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={t.taskFor}>
            {[{ key: '', name: t.anyone, hex: '' }, ...people].map((p) => {
              const on = p.key === person
              return (
                <button
                  key={p.key || 'anyone'}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => setPerson(p.key)}
                  className={`inline-flex min-h-10 items-center gap-2 rounded-full border px-3 text-base ${on ? 'border-transparent font-medium' : 'border-line hover:border-line-strong'}`}
                  style={on ? { background: p.hex || 'var(--accent)', color: p.hex ? inkOn(p.hex) : 'var(--accent-on)' } : undefined}
                >
                  {p.hex && !on ? <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: p.hex }} /> : null}
                  <span dir="auto">{p.name}</span>
                </button>
              )
            })}
          </div>
        </div>
        <label className="flex items-center gap-2 text-base">
          <input type="checkbox" checked={chore} onChange={(e) => setChore(e.target.checked)} className="h-5 w-5" />
          {t.repeats}
        </label>
        {chore ? (
          // Seven fixed 44px circles were wider than a 375px phone's sheet: they
          // shrink to share the row instead, never under 40px, and wrap on anything narrower.
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={t.repeatsOn}>
            {weekOf(t).map((code) => {
              const on = days.includes(code)
              return (
                <button
                  key={code}
                  type="button"
                  aria-label={weekdayName(code, loc.locale)}
                  aria-pressed={on}
                  onClick={() => setDays(on ? days.filter((d) => d !== code) : [...days, code])}
                  className={`h-11 max-w-11 min-w-10 flex-1 rounded-full border text-base ${on ? 'border-transparent bg-accent font-semibold text-accent-on' : 'border-line'}`}
                >
                  {t.dayInitials[code]}
                </button>
              )
            })}
          </div>
        ) : (
          <Input label={t.dueOptional} type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        )}
      </fieldset>
      {error ? (
        <div className="mt-3">
          <Notice kind="error">{error}</Notice>
        </div>
      ) : null}
    </Sheet>
  )
}
