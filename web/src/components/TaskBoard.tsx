import { useEffect, useRef, useState, type HTMLAttributes } from 'react'
import { columnsFor, describeDays } from '../lib/tasks'
import { inkOn } from '../lib/board'
import { describeChoreDays, shortDate, type BoardLocale } from '../lib/boardText'
import type { Person, Task } from '../lib/types'
import { CheckIcon, RepeatIcon, TrashIcon } from './Icons'

interface Props {
  people: Person[]
  tasks: Task[]
  onTick: (t: Task) => void
  /** Only for someone who may decide the tasks. */
  onRemove?: (t: Task) => void
  /** The wall board: bigger targets, read from across a kitchen. */
  wall?: boolean
}

export function TaskBoard({ people, tasks, onTick, onRemove, wall = false }: Props) {
  const cols = columnsFor(people, tasks)
  return (
    <div className={`grid gap-3 ${wall ? 'grid-cols-[repeat(auto-fit,minmax(15rem,1fr))] gap-4' : 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3'}`}>
      {cols.map((c) => {
        const done = c.tasks.filter((t) => t.done).length
        return (
          <section key={c.key || 'anyone'} className="card flex flex-col px-3 py-3" aria-label={`${c.name}’s tasks`}>
            <header className="flex items-center gap-2 px-1 pb-2">
              <span aria-hidden className={`${wall ? 'h-4 w-4' : 'h-3 w-3'} rounded-full`} style={{ background: c.hex || 'var(--muted)' }} />
              <h3 className={`flex-1 font-semibold ${wall ? 'text-2xl' : 'text-base'}`} dir="auto">
                {c.name}
              </h3>
              {c.tasks.length ? (
                <span className={`tabular-nums text-muted ${wall ? 'text-lg' : 'text-sm'}`}>
                  {done}/{c.tasks.length}
                </span>
              ) : null}
            </header>
            {c.tasks.length ? (
              <TaskItems tasks={c.tasks} hex={c.hex} onTick={onTick} onRemove={onRemove} wall={wall} />
            ) : (
              <p className={`px-1 text-muted ${wall ? 'text-lg' : 'text-sm'}`}>Nothing today.</p>
            )}
          </section>
        )
      })}
    </div>
  )
}

/** A person's tasks as tick boxes, in their colour. With `onOpen` the box ticks and the
 * words open the task — on the board, tapping a chore should not be the only thing it does.
 * With `loc` (the house board) its words are the board's language; without, the app's English. */
export function TaskItems({
  tasks,
  hex,
  onTick,
  onRemove,
  onOpen,
  wall = false,
  loc,
  hold,
  lifted,
}: {
  tasks: Task[]
  hex: string
  onTick: (t: Task) => void
  onRemove?: (t: Task) => void
  onOpen?: (t: Task) => void
  wall?: boolean
  loc?: BoardLocale
  /** On the board: what makes a row something a finger can hold and carry. */
  hold?: (t: Task) => HTMLAttributes<HTMLLIElement>
  /** The one being carried, shown faded where it was. */
  lifted?: number
}) {
  // The bin asks first: one tap took a task away for good, a chore from every day.
  const [asking, setAsking] = useState<number | null>(null)
  const keep = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (asking !== null) keep.current?.focus()
  }, [asking])
  const repeats = (t: Task) => (loc ? describeChoreDays(t.days, loc) : describeDays(t.days))
  const late = (t: Task) => (loc ? loc.t.late(shortDate(t.due, loc.locale)) : `late — was due ${t.due}`)
  const dueOn = (t: Task) => (loc ? loc.t.dueOn(shortDate(t.due, loc.locale)) : `due ${t.due}`)
  const openLabel = (t: Task) => (loc ? loc.t.open(t.title) : `Open ${t.title}`)
  const box = (t: Task) => (
    <span
      aria-hidden
      className={`flex shrink-0 items-center justify-center rounded-lg border-2 ${wall ? 'h-8 w-8' : 'h-6 w-6'} ${t.done ? 'border-transparent' : 'border-line-strong'}`}
      style={t.done ? { background: hex || 'var(--accent)', color: hex ? inkOn(hex) : 'var(--accent-on)' } : undefined}
    >
      {t.done ? <CheckIcon width={wall ? 22 : 16} height={wall ? 22 : 16} strokeWidth={2.6} /> : null}
    </span>
  )
  const words = (t: Task) => (
    <span className="min-w-0 flex-1">
      {/* The title keeps its own direction, but lines up where the list does:
          an English title on a Hebrew board sits by its box, on the right. */}
      <span className={`block break-words ${t.done ? 'text-muted line-through' : ''}`}>
        <span dir="auto">{t.title}</span>
      </span>
      {t.chore || t.overdue || t.due ? (
        <span className={`flex items-center gap-1 ${wall ? 'text-base' : 'text-xs'} ${t.overdue ? 'text-danger' : 'text-muted'}`}>
          {t.chore ? (
            <>
              <RepeatIcon width={12} height={12} /> {repeats(t)}
            </>
          ) : t.overdue ? (
            late(t)
          ) : (
            dueOn(t)
          )}
        </span>
      ) : null}
    </span>
  )
  const row = `flex items-center gap-3 rounded-xl px-2 text-start transition-colors hover:bg-surface-2 ${wall ? 'min-h-14 text-xl' : 'min-h-11'}`
  return (
    <ul className="flex flex-col gap-1.5">
      {tasks.map((t) => (
        <li key={t.id} {...hold?.(t)} className={`flex items-center gap-1 ${lifted === t.id ? 'opacity-40' : ''}`}>
          {onOpen ? (
            <>
              <button type="button" role="checkbox" aria-checked={t.done} aria-label={t.title} onClick={() => onTick(t)} className={`${row} shrink-0`}>
                {box(t)}
              </button>
              <button type="button" onClick={() => onOpen(t)} aria-label={openLabel(t)} className={`${row} min-w-0 flex-1 px-0`}>
                {words(t)}
              </button>
            </>
          ) : (
            <button type="button" role="checkbox" aria-checked={t.done} onClick={() => onTick(t)} className={`${row} min-w-0 flex-1`}>
              {box(t)}
              {words(t)}
            </button>
          )}
          {onRemove && asking === t.id ? (
            <span role="group" aria-label={t.chore ? `Remove ${t.title} from every day?` : `Remove ${t.title}?`} className="flex shrink-0 items-center gap-1">
              <button ref={keep} type="button" onClick={() => setAsking(null)} className="min-h-10 rounded-full px-3 text-sm text-muted hover:bg-surface-2 hover:text-text">
                Keep
              </button>
              <button
                type="button"
                onClick={() => {
                  setAsking(null)
                  onRemove(t)
                }}
                className="min-h-10 rounded-full bg-danger/10 px-3 text-sm font-medium text-danger hover:bg-danger/20"
              >
                {t.chore ? 'Remove from every day' : 'Remove'}
              </button>
            </span>
          ) : onRemove ? (
            <button type="button" onClick={() => setAsking(t.id)} aria-label={`Remove ${t.title}`} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-muted hover:text-danger">
              <TrashIcon width={16} height={16} />
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  )
}
