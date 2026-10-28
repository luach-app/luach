import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, errorMessage } from '../lib/api'
import { useAction } from '../lib/hooks'
import { relativeTime } from '../lib/time'
import { Button } from './Button'
import { Input, Notice, Select } from './Field'
import { BOARD_LANGUAGES, type BoardLanguage } from '../lib/boardText'

interface BoardRow {
  id: number
  name: string
  created_at: string
  last_seen: string | null
  /** Whether the screen may add, change and remove, or only show the day and tick. */
  can_edit?: boolean
  /** The language the screen speaks: 'auto' follows its own browser. */
  language?: BoardLanguage
}

const boards = {
  list: () => api.get<{ boards: BoardRow[] }>('/api/boards'),
  claim: (code: string, name: string) => api.post<{ id: number; name: string }>('/api/boards', { code, name }),
  remove: (id: number) => api.del<{ ok: boolean }>(`/api/boards/${id}`),
  change: (id: number, body: { can_edit?: boolean; language?: BoardLanguage }) => api.patch<{ boards: BoardRow[] }>(`/api/boards/${id}`, body),
}

/**
 * Screens on the wall. The screen shows a code at /board; typing it here makes
 * it a board. A board reads today and ticks tasks, and nothing else.
 */
export function Boards({ locale }: { locale: string }) {
  const [list, setList] = useState<BoardRow[]>([])
  const [code, setCode] = useState('')
  const [name, setName] = useState('Kitchen')
  const [loadError, setLoadError] = useState('')
  const [confirmRemove, setConfirmRemove] = useState<number | null>(null)
  /** The board whose change last went through, to say so beside it. */
  const [saved, setSaved] = useState<number | null>(null)
  const pair = useAction()
  const act = useAction()

  const load = useCallback(async () => {
    try {
      setList((await boards.list()).boards)
      setLoadError('')
    } catch (e) {
      // Said out loud: an empty list read as "no boards", and someone would pair
      // the kitchen screen a second time.
      setLoadError(errorMessage(e) || 'Could not load the boards.')
    }
  }, [])
  useEffect(() => {
    void load()
  }, [load])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const ok = await pair.run(() => boards.claim(code.trim(), name.trim()), errorMessage)
    if (ok) {
      setCode('')
      void load()
    }
  }
  const change = async (id: number, body: { can_edit?: boolean; language?: BoardLanguage }) => {
    setSaved(null)
    const ok = await act.run(() => boards.change(id, body), errorMessage)
    if (ok) {
      setList(ok.boards)
      setSaved(id)
    }
  }
  const remove = async (id: number) => {
    const ok = await act.run(() => boards.remove(id), errorMessage)
    setConfirmRemove(null)
    if (ok) void load()
  }

  return (
    <section className="mt-8" aria-labelledby="boards-heading">
      <h2 id="boards-heading" className="px-1 text-lg font-semibold">
        House boards
      </h2>
      <p className="px-1 text-sm text-muted">
        A tablet on the wall showing everyone’s day. Open <span className="font-mono">{window.location.origin}/board</span> on it and type the code it shows.
      </p>
      {loadError ? (
        <div className="mt-3">
          <Notice kind="error">{loadError}</Notice>
        </div>
      ) : null}
      {list.length ? (
        <ul className="mt-3 flex flex-col gap-2">
          {list.map((b) => (
            <li key={b.id} className="card flex items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="font-medium">{b.name}</div>
                <div className="text-xs text-muted">{b.last_seen ? `seen ${relativeTime(b.last_seen, locale)}` : 'not seen yet'}</div>
                <label className="mt-1.5 flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={b.can_edit !== false} onChange={(e) => void change(b.id, { can_edit: e.target.checked })} className="h-4 w-4" />
                  Anyone at it can add, change and remove — not only tick
                </label>
                <div className="mt-2 flex flex-wrap items-end gap-x-3 gap-y-1">
                  <Select
                    label="Language"
                    className="w-44"
                    value={b.language ?? 'auto'}
                    disabled={act.busy}
                    onChange={(e) => void change(b.id, { language: e.target.value as BoardLanguage })}
                  >
                    {BOARD_LANGUAGES.map((l) => (
                      <option key={l.value} value={l.value} lang={l.value === 'auto' ? undefined : l.value}>
                        {l.label}
                      </option>
                    ))}
                  </Select>
                  {saved === b.id ? (
                    <span role="status" className="pb-2.5 text-xs text-muted">
                      Saved.
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-xs text-muted">Automatic follows the screen’s own language. In Hebrew the board reads right to left.</p>
              </div>
              {/* Removing unpairs the screen on the wall, which then needs its code typed again. */}
              {confirmRemove === b.id ? (
                <div className="flex gap-1.5">
                  <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(null)} disabled={act.busy}>
                    Keep
                  </Button>
                  <Button size="sm" variant="danger" busy={act.busy} onClick={() => void remove(b.id)}>
                    Remove
                  </Button>
                </div>
              ) : (
                <Button variant="ghost" onClick={() => setConfirmRemove(b.id)} aria-label={`Remove ${b.name}`}>
                  Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      <form onSubmit={submit} className="card mt-3 flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-end">
        <div className="flex-1">
          <Input label="Code on the screen" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="K7P3QX" required autoComplete="off" autoCapitalize="characters" spellCheck={false} />
        </div>
        <div className="flex-1">
          <Input label="Call it" value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
        </div>
        <Button type="submit" variant="primary" busy={pair.busy}>
          Pair
        </Button>
      </form>
      <div className="mt-2">
        <Notice kind="error">{pair.error || act.error}</Notice>
      </div>
    </section>
  )
}
