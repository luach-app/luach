import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { applyMove, boardApi, columnsOf, dropAttr, inkOn, planMove, storedToken, storeToken, Unpaired, type BoardDay, type BoardEvent, type BoardMove, type BoardPerson, type DragItem, type DropTarget } from '../lib/board'
import { useBoardDrag } from '../lib/boardDrag'
import { useSelfUpdate } from '../lib/selfUpdate'
import { TaskItems } from '../components/TaskBoard'
import { Logo } from '../components/Logo'
import { EventSheet, type SheetState } from '../components/EventSheet'
import { errorMessage } from '../lib/api'
import { BoardTaskSheet, type TaskSheetState } from '../components/BoardTaskSheet'
import { boardLocale, joinNames, resolveBoardLang, type BoardLocale } from '../lib/boardText'
import type { HouseholdCalendars, Person, Task } from '../lib/types'
import { EVENT_TEXT } from '../lib/eventText'

// A tick on someone's phone reaches the wall within this.
const REFRESH_MS = 20_000
const PAIR_POLL_MS = 3_000

/**
 * The screen on the wall. Paired once, by a code the owner types into luach;
 * after that it shows the family's day — each person's events and tasks — and
 * lets whoever is standing there tick a task off.
 *
 * Opened by someone signed in, it is the same board on their own phone or
 * laptop, with nothing to pair; they can still make the screen a wall board.
 */
export function Board() {
  const [token, setToken] = useState(storedToken)
  const [mode, setMode] = useState<'checking' | 'session' | 'pair'>(token ? 'pair' : 'checking')

  useEffect(() => {
    if (token || mode !== 'checking') return
    let alive = true
    void boardApi.signedIn().then((yes) => alive && setMode(yes ? 'session' : 'pair'))
    return () => {
      alive = false
    }
  }, [token, mode])

  const unpair = useCallback(() => {
    storeToken('')
    setToken('')
    setMode('checking')
  }, [])

  if (token) return <Today token={token} onUnpaired={unpair} />
  if (mode === 'checking') {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <Logo size="lg" />
      </div>
    )
  }
  if (mode === 'session') return <Today token="" onUnpaired={() => setMode('pair')} onMakeWallBoard={() => setMode('pair')} />
  return (
    <Pairing
      onPaired={(t) => {
        storeToken(t)
        setToken(t)
      }}
    />
  )
}

function Pairing({ onPaired }: { onPaired: (token: string) => void }) {
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [round, setRound] = useState(0)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const start = async () => {
      try {
        const p = await boardApi.pair()
        if (!alive) return
        setCode(p.code)
        setError('')
        const poll = async () => {
          try {
            const r = await boardApi.collect(p.code, p.secret)
            if (!alive) return
            if (r.token) onPaired(r.token)
            else timer = setTimeout(poll, PAIR_POLL_MS)
          } catch (e) {
            // The code ran out: ask for a fresh one.
            if (alive && e instanceof Unpaired) setRound((n) => n + 1)
            else if (alive) timer = setTimeout(poll, PAIR_POLL_MS * 3)
          }
        }
        timer = setTimeout(poll, PAIR_POLL_MS)
      } catch (e) {
        if (!alive) return
        setError(e instanceof Error ? e.message : String(e))
        timer = setTimeout(() => setRound((n) => n + 1), 30_000)
      }
    }
    void start()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [round, onPaired])

  // Not a board yet, so no one has chosen its language: the screen's own.
  const loc = boardLocale(resolveBoardLang('auto'))
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-8 px-6 text-center" dir={loc.dir} lang={loc.lang}>
      <Logo size="lg" />
      <div>
        <h1 className="text-3xl font-semibold">{loc.t.pairTitle}</h1>
        <p className="mt-2 text-lg text-muted">{loc.t.pairHow}</p>
      </div>
      {code ? (
        <div className="font-mono text-7xl font-bold tracking-[0.3em] tabular-nums" dir="ltr" aria-label={loc.t.pairingCode(code.split('').join(' '))}>
          {code}
        </div>
      ) : (
        <div className="h-20" />
      )}
      {error ? <p className="text-danger">{error}</p> : <p className="text-muted">{loc.t.pairChanges}</p>}
    </div>
  )
}

function useClock(): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 15_000)
    return () => clearInterval(id)
  }, [])
  return now
}

/** Keep the screen awake while the board is showing, where the browser allows it. */
function useWakeLock(wanted: boolean) {
  useEffect(() => {
    if (!wanted) return
    let lock: { release: () => Promise<void> } | null = null
    const nav = navigator as Navigator & { wakeLock?: { request: (t: 'screen') => Promise<{ release: () => Promise<void> }> } }
    const take = async () => {
      if (document.visibilityState !== 'visible' || !nav.wakeLock) return
      try {
        lock = await nav.wakeLock.request('screen')
      } catch {
        /* battery saver, or not allowed: the tablet's own settings decide */
      }
    }
    void take()
    document.addEventListener('visibilitychange', take)
    return () => {
      document.removeEventListener('visibilitychange', take)
      void lock?.release()
    }
  }, [wanted])
}

/** How long a wall screen stays on another day before coming back to today. */
const BACK_TO_TODAY_MS = 3 * 60_000
/** Day chips across the top: today and the next thirteen. */
const DAY_CHIPS = 14
/** How far a finger must travel sideways to turn the page. */
const SWIPE_PX = 60
/** What the footer lists of the next day before it says how many more. */
const TOMORROW_SHOWN = 6
/** How long "Undo" stays after something was carried somewhere. */
const UNDO_MS = 6_000

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

function chipLabel(iso: string, today: string, loc: BoardLocale): string {
  if (iso === today) return loc.t.today
  if (iso === addDays(today, 1)) return loc.t.tomorrow
  return new Intl.DateTimeFormat(loc.locale, { weekday: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(`${iso}T12:00:00Z`))
}

/**
 * The arrow on a day button. In Hebrew the days run right to left: the next day
 * is on the left and points left. The glyph is chosen here and kept out of the
 * text's own direction, which would otherwise mirror it back.
 */
function Arrow({ back, loc }: { back: boolean; loc: BoardLocale }) {
  return (
    <span aria-hidden dir="ltr" data-arrow={back ? 'back' : 'forward'}>
      {back !== (loc.dir === 'rtl') ? '‹' : '›'}
    </span>
  )
}

/**
 * The family's board, one day at a time: today, or any of the next days, paged
 * with the chips, the arrows, or a swipe. Tap an event or a task to open it;
 * where the viewer may change things (a member, or a screen the owner allowed)
 * it can be changed, handed to someone else or taken away there, and each
 * person's + adds something that is theirs.
 */
export function Today({ token, onUnpaired, onMakeWallBoard, embedded = false }: { token: string; onUnpaired: () => void; onMakeWallBoard?: () => void; embedded?: boolean }) {
  const [day, setDay] = useState<BoardDay | null>(null)
  const [page, setPage] = useState('')
  const [stale, setStale] = useState(false)
  const [touched, setTouched] = useState(0)
  const now = useClock()
  useWakeLock(!embedded)
  const eventClient = useMemo(() => boardApi.events(token), [token])
  const taskClient = useMemo(() => boardApi.tasks(token), [token])
  const [sheet, setSheet] = useState<SheetState>(null)
  // The board's own calendars, for its event form: asked when a sheet first opens.
  const [calendars, setCalendars] = useState<HouseholdCalendars | null>(null)
  const [taskSheet, setTaskSheet] = useState<TaskSheetState>(null)
  const [choosing, setChoosing] = useState<string | null>(null)
  const [problem, setProblem] = useState('')
  const swipe = useRef<{ x: number; y: number } | null>(null)
  const dayNav = useRef<HTMLElement>(null)
  const lastTouch = useRef(Date.now())
  const [toast, setToast] = useState<{ text: string; move?: BoardMove } | null>(null)
  // What a screen reader hears as a card is picked up and put down.
  const [said, setSaid] = useState('')
  const shownDay = day?.day
  // A screen speaks the language its owner gave it, or its browser's. Inside the
  // app the board is part of the app, which speaks English.
  const language = day?.language
  const loc = useMemo(() => boardLocale(embedded ? 'en' : resolveBoardLang(language)), [embedded, language])
  const w = loc.t

  const load = useCallback(async () => {
    try {
      setDay(await boardApi.today(token, page))
      setStale(false)
    } catch (e) {
      if (e instanceof Unpaired) onUnpaired()
      else setStale(true)
    }
  }, [token, page, onUnpaired])

  useEffect(() => {
    void load()
    const id = setInterval(() => void load(), REFRESH_MS)
    const onVisible = () => document.visibilityState === 'visible' && void load()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [load])

  const sheetOpen = !!sheet
  useEffect(() => {
    if (!sheetOpen || calendars) return
    let alive = true
    boardApi.calendars(token).then(
      (c) => alive && setCalendars(c),
      () => undefined, // without them the form simply offers no choice of calendar
    )
    return () => {
      alive = false
    }
  }, [sheetOpen, calendars, token])
  const people = day?.people
  const sheetPeople = useMemo<Person[]>(
    () => (people ?? []).map((p, i) => ({ key: p.key, name: p.name, hex: p.hex, kind: p.kind, color: '', email: '', user_id: null, position: i })),
    [people],
  )

  const titleOf = (item: DragItem | BoardMove) => (item.kind === 'task' ? item.task.title : item.event.title)
  /** A move saved, or with `back` taken back, through the same calls the sheets make. */
  const save = (m: BoardMove, back = false) =>
    m.kind === 'task' ? taskClient.update(m.task.id, back ? m.undo : m.body) : eventClient.update(m.event.id, back ? m.undo : m.body, m.event.calendar_id ?? '')
  // The toast is a live region of its own: it says what happened, once.
  const tell = (text: string, move?: BoardMove) => {
    setSaid('')
    setToast({ text, move })
  }
  const failed = (title: string, e: unknown) => {
    if (e instanceof Unpaired) return onUnpaired()
    setProblem(w.didNotSave(title, errorMessage(e) || w.unreachable))
  }
  const longDate = (iso: string) => new Intl.DateTimeFormat(loc.locale, { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(`${iso}T12:00:00Z`))
  const nameOf = (key: string) => day?.people.find((p) => p.key === key)?.name ?? key

  /** Something carried and put down: shown at once, saved, and offered back. */
  const drop = async (item: DragItem, over: DropTarget | null) => {
    if (!day) return
    const move = planMove(item, over, day.day, day.timezone)
    if (move === 'repeats') return tell(w.repeatsUseEditor)
    if (!move) return setSaid(w.putBack(titleOf(item)))
    const before = day
    setDay(applyMove(day, move))
    setProblem('')
    try {
      await save(move)
      const { to } = move
      tell(to.kind === 'day' ? w.movedTo(titleOf(move), longDate(to.iso)) : to.key ? w.handedTo(titleOf(move), nameOf(to.key)) : w.handedToFamily(titleOf(move)), move)
    } catch (e) {
      setDay(before)
      failed(titleOf(move), e)
    }
    void load()
  }

  const undo = async (move: BoardMove) => {
    setToast(null)
    try {
      await save(move, true)
      setSaid(w.putBack(titleOf(move)))
    } catch (e) {
      failed(titleOf(move), e)
    }
    void load()
  }

  const drag = useBoardDrag(!!day?.can_edit, {
    onLift: (item) => {
      // This touch is carrying something now; it is not also a swipe.
      swipe.current = null
      setToast(null)
      setSaid(w.pickedUp(titleOf(item)))
    },
    onRefuse: () => tell(w.onlyOrganizer),
    onDrop: (item, over) => void drop(item, over),
  })
  const dragging = drag.dragging

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), UNDO_MS)
    return () => clearTimeout(t)
  }, [toast])

  // After a deploy the wall picks up the new luach by itself, once nobody is using it.
  useSelfUpdate(!embedded, {
    serverBuild: boardApi.build,
    quiet: () => !sheet && !taskSheet && !drag.isDragging(),
    lastTouch: () => lastTouch.current,
  })

  // A wall left on Friday's page would show Friday all week: back to today
  // once nobody has touched it for a while.
  useEffect(() => {
    if (!page || embedded || sheet || taskSheet) return
    const t = setTimeout(() => setPage(''), BACK_TO_TODAY_MS)
    return () => clearTimeout(t)
  }, [page, embedded, sheet, taskSheet, touched])

  // Paged by the arrows, a swipe or the clock running back to today, the
  // chosen chip can be off the edge of its row: bring it into view.
  useEffect(() => {
    const chip = dayNav.current?.querySelector<HTMLElement>('[aria-current="date"]')
    // jsdom, and some older wall tablets, have no scrollIntoView.
    chip?.scrollIntoView?.({ block: 'nearest', inline: 'center' })
  }, [shownDay])

  if (!day) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <Logo size="lg" />
      </div>
    )
  }

  const tz = day.timezone
  const today = day.today ?? day.day
  const shown = day.day
  const isToday = shown === today
  const canEdit = !!day.can_edit
  // The arrows and a swipe stop where the chips do: a day past the last chip
  // had none lit, and nothing on screen said which day it was among them.
  const lastDay = addDays(today, DAY_CHIPS - 1)
  const go = (iso: string) => {
    setChoosing(null)
    setProblem('')
    setPage(iso === today ? '' : iso)
  }
  const step = (n: number) => {
    const next = addDays(shown, n)
    if (next < today || next > lastDay) return
    go(next)
  }

  const tick = async (t: Task) => {
    setDay((d) => (d ? { ...d, tasks: d.tasks.map((x) => (x.id === t.id ? { ...x, done: !t.done } : x)) } : d))
    try {
      await boardApi.tick(token, t.id, !t.done, isToday ? '' : shown)
      setProblem('')
    } catch (e) {
      if (e instanceof Unpaired) return onUnpaired()
      // The box springs back when the day reloads; say why, or it looks like
      // the tap was missed.
      setProblem(w.didNotSave(t.title, errorMessage(e) || w.unreachable))
      void load()
    }
  }

  const openEvent = async (ev: BoardEvent) => {
    setProblem('')
    try {
      setSheet({ mode: 'view', event: await eventClient.get(ev.id) })
    } catch (e) {
      if (e instanceof Unpaired) onUnpaired()
      else setProblem(errorMessage(e) || w.couldNotOpen)
    }
  }

  const dateLine = new Intl.DateTimeFormat(loc.locale, { weekday: 'long', day: 'numeric', month: 'long', timeZone: tz }).format(isToday ? now : new Date(`${shown}T12:00:00Z`))
  const clock = new Intl.DateTimeFormat(loc.locale, { hour: 'numeric', minute: '2-digit', hourCycle: loc.hourCycle, timeZone: tz }).format(now)
  const columns = columnsOf(day, canEdit)
  const later = day.tomorrow.length - TOMORROW_SHOWN
  const chips = Array.from({ length: DAY_CHIPS }, (_, i) => addDays(today, i))
  const rtl = loc.dir === 'rtl'

  return (
    <div
      dir={loc.dir}
      lang={loc.lang}
      className={`flex flex-col gap-4 select-none ${embedded ? 'px-4 py-5 md:px-6' : 'min-h-dvh px-4 py-5 sm:px-6'}`}
      onPointerDown={() => {
        lastTouch.current = Date.now()
        setTouched((n) => n + 1)
      }}
      onClickCapture={drag.onClickCapture}
      onPointerDownCapture={drag.onPointerDownCapture}
      onTouchStart={(e) => {
        const t = e.touches[0]
        // Scrolling the chips sideways is not a swipe: it turned the page too.
        const inChips = e.target instanceof Node && !!dayNav.current?.contains(e.target)
        swipe.current = t && !inChips ? { x: t.clientX, y: t.clientY } : null
      }}
      onTouchEnd={(e) => {
        const from = swipe.current
        const t = e.changedTouches[0]
        swipe.current = null
        if (!from || !t || sheet || taskSheet || drag.isDragging()) return
        const dx = t.clientX - from.x
        // The page is turned the way the days run: leftwards to the next day,
        // and in Hebrew, where they run right to left, rightwards.
        const forward = rtl ? dx > 0 : dx < 0
        if (Math.abs(dx) > SWIPE_PX && Math.abs(dx) > 2 * Math.abs(t.clientY - from.y)) step(forward ? 1 : -1)
      }}
    >
      <header className="flex items-end justify-between gap-4">
        <div className="min-w-0">
          {isToday ? (
            <div className="text-4xl font-semibold tabular-nums sm:text-5xl">{clock}</div>
          ) : (
            <div className="text-4xl font-semibold sm:text-5xl">{chipLabel(shown, today, loc)}</div>
          )}
          <div className="mt-1 text-xl text-muted sm:text-2xl">{dateLine}</div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-3 text-muted">
          {stale ? <span className="text-lg text-danger">{w.offline}</span> : null}
          {!isToday ? (
            <button type="button" onClick={() => go(today)} className="rounded-full border border-line-strong px-4 py-2 text-base text-text hover:bg-surface-2">
              {w.backToToday}
            </button>
          ) : null}
          {embedded ? (
            <a href="/board" target="_blank" rel="noreferrer" className="text-sm text-accent-text hover:underline">
              {w.openFullScreen}
            </a>
          ) : null}
          {onMakeWallBoard ? (
            <button type="button" onClick={onMakeWallBoard} className="text-sm text-accent-text hover:underline">
              {w.makeWallBoard}
            </button>
          ) : null}
          {embedded ? null : <Logo />}
        </div>
      </header>

      {/* In a right-to-left board the row runs right to left too: the earlier
          day's button is on the right, and the next day's on the left. */}
      <nav ref={dayNav} aria-label={w.days} className="flex items-center gap-2">
        <button type="button" aria-label={w.previousDay} disabled={shown <= today} onClick={() => step(-1)} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-line-strong text-2xl disabled:opacity-30">
          <Arrow back loc={loc} />
        </button>
        <div className="no-scrollbar flex min-w-0 flex-1 gap-2 overflow-x-auto">
          {chips.map((iso) => (
            <button
              key={iso}
              type="button"
              aria-current={iso === shown ? 'date' : undefined}
              onClick={() => go(iso)}
              data-drop={canEdit ? dropAttr({ kind: 'day', iso }) : undefined}
              className={`shrink-0 rounded-full px-4 py-2 text-base whitespace-nowrap ${iso === shown ? 'bg-accent font-semibold text-accent-on' : 'border border-line hover:bg-surface-2'} ${dragging ? (isOver(dragging.over, { kind: 'day', iso }) ? 'bg-surface-2 ring-4 ring-accent ring-inset' : iso === shown ? '' : 'border-dashed border-line-strong') : ''}`}
            >
              {chipLabel(iso, today, loc)}
            </button>
          ))}
        </div>
        <button type="button" aria-label={w.nextDay} disabled={shown >= lastDay} onClick={() => step(1)} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-line-strong text-2xl disabled:opacity-30">
          <Arrow back={false} loc={loc} />
        </button>
      </nav>

      {problem ? (
        <p role="alert" className="text-base text-danger">
          {problem}
        </p>
      ) : null}

      {!day.people.length ? <p className="card px-4 py-4 text-xl text-muted">{w.noOneYet}</p> : null}

      {/* The app already has a <main>; inside it the board is a region, not a second one. */}
      <Columns embedded={embedded} label={w.familysDay} className="grid flex-1 auto-rows-min grid-cols-[repeat(auto-fit,minmax(16rem,1fr))] gap-4">
        {columns.map((c) => {
          const name = c.key ? c.name : w.family
          return (
            <section
              key={c.key || 'family'}
              className={`card flex flex-col gap-3 px-4 py-4 ${dragging && dragging.item.from !== c.key ? (isOver(dragging.over, { kind: 'person', key: c.key }) ? 'ring-4 ring-accent' : 'outline-2 outline-offset-2 outline-dashed outline-line-strong') : ''}`}
              aria-label={name}
              data-drop={canEdit ? dropAttr({ kind: 'person', key: c.key }) : undefined}
            >
              <h2 className="flex items-center gap-3 text-3xl font-semibold">
                <span aria-hidden className="h-5 w-5 shrink-0 rounded-full" style={{ background: c.hex || 'var(--accent)' }} />
                <span className="min-w-0 flex-1 truncate">
                  <span dir="auto">{name}</span>
                </span>
                {canEdit ? (
                  <button
                    type="button"
                    aria-label={c.key ? w.addFor(c.name) : w.addForFamily}
                    aria-expanded={choosing === c.key}
                    onClick={() => setChoosing(choosing === c.key ? null : c.key)}
                    className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-2xl font-normal shadow-sm transition-transform hover:scale-105"
                    style={{ background: c.hex || 'var(--accent)', color: c.hex ? inkOn(c.hex) : 'var(--accent-on)' }}
                  >
                    +
                  </button>
                ) : null}
              </h2>
              {choosing === c.key ? (
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="min-h-11 flex-1 rounded-xl border border-line-strong px-3 py-2 text-lg hover:bg-surface-2"
                    onClick={() => {
                      setChoosing(null)
                      setSheet({ mode: 'create', day: shown, leader: c.key })
                    }}
                  >
                    {w.event}
                  </button>
                  <button
                    type="button"
                    className="min-h-11 flex-1 rounded-xl border border-line-strong px-3 py-2 text-lg hover:bg-surface-2"
                    onClick={() => {
                      setChoosing(null)
                      setTaskSheet({ mode: 'new', person: c.key })
                    }}
                  >
                    {w.task}
                  </button>
                </div>
              ) : null}
              {c.events.length ? (
                <ul className="flex flex-col gap-2">
                  {c.events.map((ev) => (
                    <li
                      key={ev.id}
                      {...drag.holdable({ kind: 'event', event: ev, from: c.key }, !!ev.read_only)}
                      className={isLifted(dragging, 'event', ev.id, c.key) ? 'opacity-40' : undefined}
                    >
                      <button
                        type="button"
                        onClick={() => void openEvent(ev)}
                        aria-label={w.open(ev.title)}
                        className="flex w-full gap-3 rounded-lg py-1 text-start text-xl hover:bg-surface-2"
                        style={{ borderInlineStart: `4px solid ${c.hex || 'var(--accent)'}`, paddingInlineStart: '0.75rem' }}
                      >
                        <span className="min-w-[6.5rem] shrink-0 whitespace-nowrap tabular-nums text-muted">{timeOf(ev, tz, loc)}</span>
                        <span className="min-w-0 break-words">
                          <span dir="auto">{ev.title}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
              {c.tasks.length ? (
                <TaskItems
                  tasks={c.tasks}
                  hex={c.hex}
                  onTick={tick}
                  onOpen={(t) => setTaskSheet({ mode: 'open', task: t })}
                  wall
                  loc={loc}
                  hold={(t) => drag.holdable({ kind: 'task', task: t, from: c.key })}
                  lifted={dragging?.item.kind === 'task' ? dragging.item.task.id : undefined}
                />
              ) : null}
              {!c.events.length && !c.tasks.length ? <p className="text-xl text-muted">{w.freeDay}</p> : null}
            </section>
          )
        })}
      </Columns>
      {day.tomorrow.length ? (
        <footer className="text-lg text-muted">
          <span className="font-medium text-text">{isToday ? w.tomorrow : w.dayAfter}: </span>
          {day.tomorrow.slice(0, TOMORROW_SHOWN).map((ev, i) => (
            <span key={ev.id}>
              {i ? ' · ' : null}
              {/* Each one is someone's own words, in whichever direction they were written. */}
              <bdi>
                {timeOf(ev, tz, loc)} {ev.title}
                {personName(day.people, ev, loc.locale)}
              </bdi>
            </span>
          ))}
          {later > 0 ? <span className="text-text"> · {w.more(later)}</span> : null}
        </footer>
      ) : null}
      {dragging ? <Ghost dragging={dragging} columns={columns} tz={tz} loc={loc} /> : null}
      <div aria-live="assertive" className="sr-only">
        {said}
      </div>
      {toast ? (
        <div role="status" className="pointer-events-none fixed inset-x-0 bottom-6 z-40 flex justify-center px-4">
          <div className="card pointer-events-auto flex max-w-xl items-center gap-4 px-5 py-3 text-lg shadow-lg">
            <span className="min-w-0 flex-1">{toast.text}</span>
            {toast.move ? (
              <button type="button" onClick={() => toast.move && void undo(toast.move)} className="min-h-11 shrink-0 rounded-full border border-line-strong px-4 py-2 font-semibold text-accent-text hover:bg-surface-2">
                {w.undo}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      <EventSheet
        state={sheet}
        tz={tz}
        locale={loc.locale}
        client={eventClient}
        readOnly={!canEdit}
        board={{ text: EVENT_TEXT[loc.lang], dir: loc.dir, lang: loc.lang, people: sheetPeople, household: calendars }}
        onClose={() => setSheet(null)}
        onChanged={() => {
          setSheet(null)
          void load()
        }}
        onEdit={(ev) => setSheet({ mode: 'edit', event: ev })}
      />
      <BoardTaskSheet state={taskSheet} people={day.people} canEdit={canEdit} client={taskClient} loc={loc} onClose={() => setTaskSheet(null)} onChanged={() => void load()} />
    </div>
  )
}

const isOver = (over: DropTarget | null, t: DropTarget) => !!over && dropAttr(over) === dropAttr(t)

const isLifted = (d: { item: DragItem } | null, kind: 'event' | 'task', id: string | number, from: string) =>
  !!d && d.item.kind === kind && d.item.from === from && (d.item.kind === 'task' ? d.item.task.id : d.item.event.id) === id

/** What follows the finger: the card it lifted, in its person's colour. Under the
 * finger is what it will land on, so the card rides just above it. */
function Ghost({ dragging, columns, tz, loc }: { dragging: { item: DragItem; x: number; y: number }; columns: { key: string; hex: string }[]; tz: string; loc: BoardLocale }) {
  const { item, x, y } = dragging
  const hex = columns.find((c) => c.key === item.from)?.hex || 'var(--accent)'
  return (
    <div
      aria-hidden
      data-ghost
      className="pointer-events-none fixed z-50 flex max-w-xs items-center gap-3 rounded-xl bg-surface px-4 py-3 text-xl shadow-2xl motion-safe:scale-105 motion-safe:-rotate-2"
      style={{ left: x, top: y, transform: 'translate(-50%, -125%)', borderInlineStart: `6px solid ${hex}` }}
    >
      {item.kind === 'event' ? <span className="shrink-0 whitespace-nowrap tabular-nums text-muted">{timeOf(item.event, tz, loc)}</span> : null}
      <span className="min-w-0 truncate">
        <span dir="auto">{item.kind === 'event' ? item.event.title : item.task.title}</span>
      </span>
    </div>
  )
}

function Columns({ embedded, label, className, children }: { embedded: boolean; label: string; className: string; children: React.ReactNode }) {
  return embedded ? (
    <div className={className} aria-label={label} role="region">
      {children}
    </div>
  ) : (
    <main className={className}>{children}</main>
  )
}

function timeOf(ev: BoardEvent, tz: string, loc: BoardLocale): string {
  if (ev.all_day || ev.start.length <= 10) return loc.t.allDay
  return new Intl.DateTimeFormat(loc.locale, { hour: 'numeric', minute: '2-digit', hourCycle: loc.hourCycle, timeZone: tz }).format(new Date(ev.start))
}

/** " (Noa and Sam)" — everyone an event is for; it read only the first. */
function personName(people: BoardPerson[], ev: BoardEvent, locale: string): string {
  const keys = ev.leaders?.length ? ev.leaders : ev.leader ? [ev.leader] : []
  const names = keys.map((k) => people.find((x) => x.key === k)?.name).filter(Boolean) as string[]
  if (!names.length) return ''
  return ` (${joinNames(names, locale)})`
}
