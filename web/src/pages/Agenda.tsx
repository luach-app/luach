import { useEffect, useState } from 'react'
import type { CalendarEvent, Member } from '../lib/types'
import { resolveLocale, todayISO } from '../lib/time'
import { invalidateMonths } from '../lib/monthCache'
import { useMediaQuery } from '../lib/hooks'
import { Assistant } from '../components/Assistant'
import { Button } from '../components/Button'
import { EventSheet, type SheetState } from '../components/EventSheet'
import { ChatIcon, CloseIcon, ExpandIcon, PlusIcon, ShrinkIcon } from '../components/Icons'
import { MonthView } from './agenda/MonthView'
import { Upcoming } from './agenda/Upcoming'

type Mode = 'month' | 'upcoming'
const MODE_KEY = 'luach.agenda.mode'
const CHAT_KEY = 'luach.agenda.chat'

const readRailPref = (): boolean => {
  try {
    return localStorage.getItem(CHAT_KEY) !== 'closed'
  } catch {
    return true
  }
}

const readMode = (): Mode => {
  try {
    return localStorage.getItem(MODE_KEY) === 'upcoming' ? 'upcoming' : 'month'
  } catch {
    return 'month'
  }
}

/**
 * One screen: the calendar, and the assistant beside it. Asking for something
 * and seeing it land on the grid is the whole point, so they share a page —
 * a rail on a wide screen, a sheet over the month on a phone.
 */
export function Agenda({ member, onHoldsChanged }: { member: Member; onHoldsChanged: () => void }) {
  const tz = member.timezone || 'UTC'
  const locale = resolveLocale(member.language)
  const [mode, setMode] = useState<Mode>(readMode)
  const [selected, setSelected] = useState(() => todayISO(tz))
  const [sheet, setSheet] = useState<SheetState>(null)
  const [version, setVersion] = useState(0)
  const [chatOpen, setChatOpen] = useState(false)
  // The rail is a choice, not furniture: some days the month is the whole job.
  const [railOpen, setRailOpen] = useState(readRailPref)
  const [full, setFull] = useState(false)
  const wide = useMediaQuery('(min-width: 1100px)')

  useEffect(() => {
    try {
      localStorage.setItem(CHAT_KEY, railOpen ? 'open' : 'closed')
    } catch {
      /* private mode */
    }
  }, [railOpen])

  // Esc and the browser's own chrome can leave full screen without asking us,
  // so the button follows the document rather than its own memory.
  useEffect(() => {
    const sync = () => setFull(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])

  const toggleFullScreen = () => {
    const el = document.documentElement
    if (document.fullscreenElement) void document.exitFullscreen?.()
    else void el.requestFullscreen?.().catch(() => setFull(false))
  }

  useEffect(() => {
    try {
      localStorage.setItem(MODE_KEY, mode)
    } catch {
      /* private mode */
    }
  }, [mode])

  const changed = () => {
    invalidateMonths()
    setVersion((v) => v + 1)
  }
  const open = (ev: CalendarEvent) => setSheet({ mode: 'view', event: ev })
  const create = (day: string) => setSheet({ mode: 'create', day })

  const view = { tz, locale, version, selected, onSelect: setSelected, onOpen: open, onCreate: create }

  return (
    <div className="flex h-full min-h-0">
      <div className="safe-x flex min-w-0 flex-1 flex-col overflow-y-auto px-3 pt-3 pb-24 sm:px-4 xl:pb-6">
        <header className="flex items-center justify-between gap-3 px-1">
          <div role="tablist" aria-label="Agenda view" className="flex rounded-full border border-line-strong bg-surface p-0.5 text-sm">
            {(['month', 'upcoming'] as const).map((m) => (
              <button
                key={m}
                role="tab"
                aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={`rounded-full px-3.5 py-1.5 font-medium transition-colors ${mode === m ? 'bg-accent text-accent-on' : 'text-muted hover:text-text'}`}
              >
                {m === 'month' ? 'Month' : 'Upcoming'}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1.5">
            {wide && !railOpen ? (
              <Button variant="ghost" size="icon" aria-label="Open the assistant" onClick={() => setRailOpen(true)}>
                <ChatIcon />
              </Button>
            ) : null}
            <Button variant="ghost" size="icon" aria-label={full ? 'Leave full screen' : 'Full screen'} onClick={toggleFullScreen}>
              {full ? <ShrinkIcon /> : <ExpandIcon />}
            </Button>
            <Button variant="primary" size="icon" aria-label="Add event" onClick={() => create(selected)}>
              <PlusIcon />
            </Button>
          </div>
        </header>

        <div className="mt-2 min-h-0 flex-1">{mode === 'month' ? <MonthView {...view} /> : <Upcoming {...view} />}</div>
      </div>

      {wide && railOpen ? (
        <aside className="safe-top flex w-[24rem] shrink-0 flex-col overflow-hidden border-s border-line bg-surface/30 px-4 py-3 2xl:w-[27rem]" aria-label="Ask luach">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Ask luach</h2>
            <button
              type="button"
              onClick={() => setRailOpen(false)}
              aria-label="Close the assistant"
              className="flex h-9 w-9 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-text"
            >
              <CloseIcon width={18} height={18} />
            </button>
          </div>
          <div className="min-h-0 flex-1 pt-1">
            <Assistant member={member} onHoldsChanged={onHoldsChanged} onCalendarChanged={changed} compact heading={false} />
          </div>
        </aside>
      ) : wide ? null : (
        <>
          <button
            type="button"
            onClick={() => setChatOpen(true)}
            aria-label="Ask luach"
            className="safe-bottom fixed bottom-4 end-4 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-accent text-accent-on shadow-[var(--shadow)] active:scale-95"
          >
            <ChatIcon width={24} height={24} />
          </button>
          {chatOpen ? (
            <div className="fixed inset-0 z-50 flex flex-col bg-[color-mix(in_srgb,var(--bg)_97%,transparent)] backdrop-blur-xl">
              <div className="safe-top flex items-center justify-between border-b border-line px-4 py-2.5">
                <span className="font-semibold">Ask luach</span>
                <button type="button" onClick={() => setChatOpen(false)} aria-label="Close" className="flex h-10 w-10 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-text">
                  <CloseIcon />
                </button>
              </div>
              <div className="safe-bottom min-h-0 flex-1 px-4 pb-2 pt-2">
                <Assistant member={member} onHoldsChanged={onHoldsChanged} onCalendarChanged={changed} heading={false} />
              </div>
            </div>
          ) : null}
        </>
      )}

      <EventSheet
        state={sheet}
        tz={tz}
        locale={locale}
        onClose={() => setSheet(null)}
        onChanged={changed}
        onEdit={(ev) => setSheet({ mode: 'edit', event: ev })}
        notifyEmails={member.notify_emails}
      />
    </div>
  )
}
