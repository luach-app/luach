import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage, threads } from '../lib/api'
import { relativeTime } from '../lib/time'
import type { ThreadSummary } from '../lib/types'
import { Button, Spinner } from './Button'
import { Notice } from './Field'
import { CheckIcon, CloseIcon, PencilIcon, TrashIcon } from './Icons'

interface Props {
  locale: string
  /** The thread being shown in the chat, so the list can mark it. */
  current?: string
  onOpen: (id: string) => void
  /** The open thread was deleted, so the chat beside this has to let go of it. */
  onDeletedCurrent: () => void
  onClose: () => void
}

/**
 * Every conversation this member has had with luach.
 *
 * The thread id used to live in sessionStorage and nowhere else: closing the
 * tab lost it, and "New" threw the old one away with no way back — while the
 * server had been keeping all of them, and offering them, the whole time.
 */
export function ThreadList({ locale, current, onOpen, onDeletedCurrent, onClose }: Props) {
  const [rows, setRows] = useState<ThreadSummary[] | null>(null)
  const [retention, setRetention] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const r = await threads.list()
      if (signal?.aborted) return
      setRows(r.threads)
      setRetention(r.retention_days ?? 0)
      setError('')
    } catch (e) {
      if (!signal?.aborted) setError(errorMessage(e))
    }
  }, [])

  useEffect(() => {
    const ac = new AbortController()
    void load(ac.signal)
    return () => ac.abort()
  }, [load])

  // On the id, not on the whole edit: keyed to `editing` this re-selected the
  // field after every keystroke, so each new character replaced the last one.
  useEffect(() => {
    if (editing?.id) inputRef.current?.select()
  }, [editing?.id])

  const remove = async (id: string) => {
    setBusy(id)
    try {
      await threads.remove(id)
      setRows((prev) => (prev ?? []).filter((t) => t.id !== id))
      if (id === current) onDeletedCurrent()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy('')
    }
  }

  const rename = async () => {
    if (!editing) return
    const { id, title } = editing
    setEditing(null)
    if (!title.trim()) return
    try {
      const saved = await threads.rename(id, title.trim())
      setRows((prev) => (prev ?? []).map((t) => (t.id === id ? { ...t, title: saved.title } : t)))
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 pb-1">
        <h3 className="text-sm font-semibold">Conversations</h3>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Back
        </Button>
      </div>

      {error ? <Notice kind="error">{error}</Notice> : null}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {rows === null && !error ? (
          <div className="flex justify-center py-8 text-muted">
            <Spinner />
          </div>
        ) : rows && rows.length === 0 ? (
          <p className="px-1 py-6 text-center text-sm text-muted">Nothing yet — ask luach something.</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {(rows ?? []).map((t) => (
              <li
                key={t.id}
                className={`group flex items-center gap-1 rounded-xl px-1 ${t.id === current ? 'bg-surface-2' : 'hover:bg-surface-2/60'}`}
              >
                {editing?.id === t.id ? (
                  <>
                    <input
                      ref={inputRef}
                      value={editing.title}
                      dir="auto"
                      aria-label="Conversation name"
                      onChange={(e) => setEditing({ id: t.id, title: e.target.value })}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void rename()
                        if (e.key === 'Escape') setEditing(null)
                      }}
                      className="min-w-0 flex-1 rounded-lg bg-transparent px-2 py-2 text-sm focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => void rename()}
                      aria-label="Save the name"
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted hover:text-accent-text"
                    >
                      <CheckIcon width={16} height={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditing(null)}
                      aria-label="Keep the old name"
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted hover:text-text"
                    >
                      <CloseIcon width={16} height={16} />
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => onOpen(t.id)}
                      dir="auto"
                      className="min-w-0 flex-1 px-2 py-2 text-start"
                      aria-label={`Open ${t.title}`}
                      aria-current={t.id === current ? 'true' : undefined}
                    >
                      <span className="block truncate text-sm">{t.title}</span>
                      <span className="block text-xs text-muted">
                        {relativeTime(t.updated_at, locale)}
                        {t.turns ? ` · ${t.turns} message${t.turns === 1 ? '' : 's'}` : ''}
                      </span>
                    </button>
                    {/* Always present, never hidden behind hover: a phone has no
                        hover, and a control that only a mouse can reach is a
                        control half the household does not have. */}
                    <button
                      type="button"
                      onClick={() => setEditing({ id: t.id, title: t.title })}
                      aria-label={`Rename ${t.title}`}
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted hover:text-accent-text"
                    >
                      <PencilIcon width={15} height={15} />
                    </button>
                    <button
                      type="button"
                      onClick={() => void remove(t.id)}
                      disabled={busy === t.id}
                      aria-label={`Delete ${t.title}`}
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted hover:text-danger disabled:opacity-40"
                    >
                      <TrashIcon width={15} height={15} />
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {retention > 0 && rows && rows.length > 0 ? (
        <p className="pt-2 text-xs text-muted">
          Conversations are kept for {retention} days. What luach should remember about you for longer, tell it to remember.
        </p>
      ) : null}
    </div>
  )
}
