import { useCallback, useEffect, useRef, useState } from 'react'
import { calendar, errorMessage, threads, voice } from '../lib/api'
import { invalidateMonths } from '../lib/monthCache'
import { streamAgent } from '../lib/sse'
import type { CompactEvent, Member, PendingRow, StreamFrame } from '../lib/types'
import { resolveLocale } from '../lib/time'
import { applyFrame, newTurn, settle, turnsFromThread, type Turn } from '../lib/turns'
import { Button } from './Button'
import { ChatTurn } from './ChatTurn'
import { Composer } from './Composer'
import { EventSheet, type SheetState } from './EventSheet'
import { Notice } from './Field'
import { HistoryIcon } from './Icons'
import { ThreadList } from './ThreadList'
import { changesTheCalendar } from './assistantFrames'

const SUGGESTIONS = ["What's on this week?", 'Add dentist Tuesday 3pm', 'Am I free Friday at 4?', '¿Qué hay mañana?', 'מה יש מחר?']
const THREAD_KEY = 'luach.thread'

const readThreadKey = () => {
  try {
    return sessionStorage.getItem(THREAD_KEY) ?? undefined
  } catch {
    return undefined
  }
}
const writeThreadKey = (id: string | undefined) => {
  try {
    if (id) sessionStorage.setItem(THREAD_KEY, id)
    else sessionStorage.removeItem(THREAD_KEY)
  } catch {
    /* private mode */
  }
}

interface Props {
  member: Member
  onHoldsChanged: () => void
  /** Anything the assistant changes, the calendar beside it should show. */
  onCalendarChanged?: () => void
  /** Rail and sheet are tight; a page has room to breathe. */
  compact?: boolean
  /** The sheet already names itself in its own bar; the rail does not. */
  heading?: boolean
}

/**
 * The conversation — wherever it is shown. It lives in the rail beside the
 * month on a wide screen and in a sheet over it on a phone, so it is one
 * component with one thread rather than a place a person navigates to.
 */
export function Assistant({ member, onHoldsChanged, onCalendarChanged, compact = false, heading = true }: Props) {
  const tz = member.timezone || 'UTC'
  const locale = resolveLocale(member.language)
  const [turns, setTurns] = useState<Turn[]>([])
  const [threadId, setThreadId] = useState<string | undefined>(readThreadKey)
  const [streaming, setStreaming] = useState(false)
  const [micAvailable, setMicAvailable] = useState(false)
  const [error, setError] = useState('')
  const [seed, setSeed] = useState<{ text: string; nonce: number } | undefined>()
  const [sheet, setSheet] = useState<SheetState>(null)
  const [browsing, setBrowsing] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    voice
      .status()
      .then((s) => setMicAvailable(!!s.available))
      .catch(() => setMicAvailable(false))
  }, [])

  // Pick the conversation back up after a reload or a trip to Settings.
  useEffect(() => {
    const id = readThreadKey()
    if (!id) return
    const ac = new AbortController()
    threads
      .get(id, ac.signal)
      .then((r) => {
        if (!ac.signal.aborted) setTurns(turnsFromThread(r.turns))
      })
      .catch(() => {
        if (ac.signal.aborted) return
        writeThreadKey(undefined)
        setThreadId(undefined)
      })
    return () => ac.abort()
  }, [])

  /** Open one of the member's earlier conversations, from the list. */
  const openThread = async (id: string) => {
    abortRef.current?.abort()
    setError('')
    setBrowsing(false)
    try {
      const r = await threads.get(id)
      setTurns(turnsFromThread(r.turns))
      setThreadId(id)
      writeThreadKey(id)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [turns])

  const patch = useCallback((id: string, fn: (t: Turn) => Turn) => {
    setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)))
  }, [])

  const adoptThread = (id: string | undefined) => {
    if (!id) return
    setThreadId(id)
    writeThreadKey(id)
  }

  const send = async (text: string) => {
    if (streaming) return
    setError('')
    const botTurn = newTurn('assistant', '', true)
    const botId = botTurn.id
    setTurns((prev) => [...prev, newTurn('user', text), botTurn])
    setStreaming(true)
    const ac = new AbortController()
    abortRef.current = ac

    // A turn is over when the server says so. Anything else that ends the
    // stream — a dropped connection, a hop that gave up on a quiet socket —
    // used to leave a half-written answer sitting there looking finished.
    let ended = false

    const onFrame = (f: StreamFrame) => {
      if (f.type === 'done' || f.type === 'error') ended = true
      if (f.type === 'session') adoptThread(f.thread_id)
      if (f.type === 'done') adoptThread(f.thread_id)
      patch(botId, (t) => applyFrame(t, f))
      if (f.type === 'held') onHoldsChanged()
      // An event the assistant just made belongs on the grid beside it, now —
      // but only then. Refreshing on every frame meant a web search, or a
      // question about next week, redrew the whole month for no reason.
      if (changesTheCalendar(f)) {
        invalidateMonths()
        onCalendarChanged?.()
      }
    }

    try {
      // No model is sent: the server answers with the one chosen in Settings.
      await streamAgent({ text, thread_id: threadId }, onFrame, ac.signal)
      if (!ended && !ac.signal.aborted) {
        patch(botId, (t) => ({ ...t, error: 'The connection dropped before luach finished. Ask again.' }))
      }
    } catch (e) {
      const msg = ac.signal.aborted ? '' : errorMessage(e)
      if (msg) patch(botId, (t) => ({ ...t, error: msg }))
    } finally {
      patch(botId, (t) => settle(t))
      setStreaming(false)
      abortRef.current = null
    }
  }

  /** Stop the answer. The server keeps what the turn already did (it may have
   * written an event a moment before), so the thread says "stopped", not gone. */
  const stop = () => {
    const ac = abortRef.current
    if (!ac) return
    ac.abort()
    setTurns((prev) => {
      const last = prev[prev.length - 1]
      return last?.role === 'assistant' && last.streaming ? [...prev.slice(0, -1), { ...last, stopped: true }] : prev
    })
  }

  const onDecided = (turnId: string, row: PendingRow) => {
    patch(turnId, (t) => ({
      ...t,
      held: t.held.map((h) => (h.id === row.id ? { ...h, status: row.status, result: row.result } : h)),
    }))
    onHoldsChanged()
    invalidateMonths()
    onCalendarChanged?.()
  }

  /** Widget rows carry the compact shape; fetch the full event so the sheet can edit it. */
  const openEvent = async (ev: CompactEvent) => {
    if (!ev.id) return
    setError('')
    try {
      setSheet({ mode: 'view', event: await calendar.get(ev.id) })
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const reset = () => {
    abortRef.current?.abort()
    setTurns([])
    setThreadId(undefined)
    writeThreadKey(undefined)
    setStreaming(false)
    setError('')
  }

  const empty = turns.length === 0
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 pb-1">
        {heading ? <h2 className={`font-semibold ${compact ? 'text-sm' : 'text-lg'}`}>Ask luach</h2> : <span />}
        <div className="flex items-center gap-0.5">
          {!empty ? (
            <Button size="sm" variant="ghost" onClick={reset} aria-label="New conversation">
              New
            </Button>
          ) : null}
          <button
            type="button"
            onClick={() => setBrowsing((v) => !v)}
            aria-label="Earlier conversations"
            aria-pressed={browsing}
            className={`flex h-8 w-8 items-center justify-center rounded-full hover:bg-surface-2 ${browsing ? 'text-accent-text' : 'text-muted hover:text-text'}`}
          >
            <HistoryIcon width={17} height={17} />
          </button>
        </div>
      </div>

      {browsing ? (
        <div className="min-h-0 flex-1 py-1">
          <ThreadList
            locale={locale}
            current={threadId}
            onOpen={(id) => void openThread(id)}
            onDeletedCurrent={reset}
            onClose={() => setBrowsing(false)}
          />
        </div>
      ) : (
      <>
      <div className="min-h-0 flex-1 overflow-y-auto py-2" aria-live="polite">
        {empty ? (
          <p className={`text-muted ${compact ? 'text-xs' : 'text-sm'}`}>
            Ask what is coming up, add something, or move it — in any language. Anything that touches an event you did not just make waits for your yes.
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            {turns.map((t) => (
              <ChatTurn key={t.id} turn={t} tz={tz} locale={locale} lang={member.language === 'auto' ? '' : member.language} onDecided={onDecided} onOpenEvent={(ev) => void openEvent(ev)} />
            ))}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex flex-col gap-2 pt-1">
        {empty ? (
          <div className="no-scrollbar flex gap-1.5 overflow-x-auto pb-0.5" aria-label="Suggestions">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                dir="auto"
                onClick={() => setSeed({ text: s, nonce: Date.now() })}
                className="shrink-0 rounded-full border border-line-strong bg-surface px-3 py-1 text-xs text-text/90 hover:border-accent/50 hover:text-accent-text"
              >
                {s}
              </button>
            ))}
          </div>
        ) : null}
        {error ? <Notice kind="error">{error}</Notice> : null}
        <Composer disabled={streaming} streaming={streaming} onStop={stop} micAvailable={micAvailable} onSend={(t) => void send(t)} onError={setError} seed={seed} />
      </div>
      </>
      )}

      <EventSheet
        state={sheet}
        tz={tz}
        locale={locale}
        onClose={() => setSheet(null)}
        onChanged={() => {
          invalidateMonths()
          onCalendarChanged?.()
        }}
        onEdit={(ev) => setSheet({ mode: 'edit', event: ev })}
        notifyEmails={member.notify_emails}
      />
    </div>
  )
}
