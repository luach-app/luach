import { useEffect, useState, type ReactNode } from 'react'
import { Logo } from './Logo'
import type { Member } from '../lib/types'

export type Tab = 'agenda' | 'board' | 'tasks' | 'pending' | 'members' | 'settings'

export interface TabDef {
  id: Tab
  label: string
  icon: ReactNode
  badge?: number
}

/**
 * The tab's name for a screen reader, with its count. The count used to be the
 * badge's own aria-label, which the button's aria-label hid: "Pending" was all
 * anyone heard, with three things waiting.
 */
const tabName = (t: TabDef) => (t.badge ? `${t.label}, ${t.badge} waiting` : t.label)

function CountBadge({ n }: { n?: number }) {
  if (!n) return null
  return (
    <span
      aria-hidden
      className="absolute -top-1 -right-2 min-w-[18px] rounded-full bg-accent px-1 text-center text-[11px] font-semibold leading-[18px] text-accent-on"
    >
      {n > 99 ? '99+' : n}
    </span>
  )
}

interface NavProps {
  tabs: TabDef[]
  active: Tab
  onSelect: (t: Tab) => void
}

/**
 * One bar across the top, on every size. A column down the left spent the
 * widest part of the window on five words, and the calendar is what people
 * came for — so the navigation is icons, and the screen below it is the app.
 */
export function TopNav({ tabs, active, onSelect, member, right }: NavProps & { member: Member; right?: ReactNode }) {
  return (
    <header className="safe-top safe-x sticky top-0 z-40 flex items-center gap-2 border-b border-line bg-[color-mix(in_srgb,var(--bg)_88%,transparent)] px-3 py-2 backdrop-blur-xl sm:px-4">
      <Logo size="sm" className="shrink-0" />
      {/* Icons only on a phone, and the bar scrolls inside itself if it must:
          an owner has six tabs, and with the open tab's word beside its icon
          Members and Settings sat past the edge of a 390px screen while the
          whole page scrolled sideways. */}
      <nav aria-label="Primary" className="no-scrollbar ms-1 flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto sm:gap-1">
        {tabs.map((t) => {
          const on = t.id === active
          return (
            <button
              key={t.id}
              onClick={() => onSelect(t.id)}
              aria-label={tabName(t)}
              title={t.label}
              aria-current={on ? 'page' : undefined}
              className={`flex min-h-10 shrink-0 items-center gap-2 rounded-xl px-2 py-2 text-[15px] transition-colors sm:px-3 ${on ? 'bg-accent/12 text-accent-text' : 'text-muted hover:bg-surface-2 hover:text-text'}`}
            >
              <span className="relative flex items-center">
                {t.icon}
                <CountBadge n={t.badge} />
              </span>
              <span className={`${on ? 'hidden sm:inline' : 'hidden'} lg:inline`}>{t.label}</span>
            </button>
          )
        })}
      </nav>
      {right}
      <span className="hidden truncate text-sm text-muted sm:inline" dir="auto" title={`@${member.username}`}>
        {member.display_name || member.username}
      </span>
    </header>
  )
}

const RAIL_KEY = 'luach.rail'

const readRail = (): boolean => {
  try {
    return localStorage.getItem(RAIL_KEY) !== 'open'
  } catch {
    return true
  }
}

/**
 * The left rail, on a screen with room for one. It starts as icons and opens
 * to names, and it remembers which — someone who works collapsed should not
 * have to collapse it again every morning. Collapsed it costs 56px, which is
 * the difference between a month cell that fits its titles and one that does
 * not, so it is the default.
 */
export function SideRail({ tabs, active, onSelect, member }: NavProps & { member: Member }) {
  const [collapsed, setCollapsed] = useState(readRail)
  useEffect(() => {
    try {
      localStorage.setItem(RAIL_KEY, collapsed ? 'collapsed' : 'open')
    } catch {
      /* private mode */
    }
  }, [collapsed])

  return (
    <aside
      className={`safe-top flex shrink-0 flex-col border-e border-line bg-surface/40 py-3 ${collapsed ? 'w-14 px-2' : 'w-56 px-3'}`}
      aria-label="Primary"
    >
      {/* The toggle sits with the wordmark, where nya-exp's admin keeps it:
          at the top, where a person looks for it, not at the foot of a column
          they have to scan past the navigation to find. */}
      <div className={`mb-4 flex items-center gap-1 ${collapsed ? 'flex-col' : 'justify-between ps-1'}`}>
        {collapsed ? <Logo size="sm" mark /> : <Logo size="sm" />}
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          aria-label={collapsed ? 'Expand the menu' : 'Collapse the menu'}
          aria-expanded={!collapsed}
          title={collapsed ? 'Expand the menu' : 'Collapse the menu'}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-text"
        >
          <ChevronIcon className={collapsed ? 'rotate-180' : ''} />
        </button>
      </div>

      <nav className="flex flex-col gap-1">
        {tabs.map((t) => {
          const on = t.id === active
          return (
            <button
              key={t.id}
              onClick={() => onSelect(t.id)}
              aria-label={tabName(t)}
              title={collapsed ? t.label : undefined}
              aria-current={on ? 'page' : undefined}
              className={`flex min-h-10 items-center gap-3 rounded-xl py-2.5 text-[15px] transition-colors ${collapsed ? 'justify-center px-0' : 'px-3'} ${on ? 'bg-accent/12 text-accent-text' : 'text-muted hover:bg-surface-2 hover:text-text'}`}
            >
              <span className="relative flex items-center">
                {t.icon}
                <CountBadge n={t.badge} />
              </span>
              {collapsed ? null : <span className="truncate">{t.label}</span>}
            </button>
          )
        })}
      </nav>

      {collapsed ? null : (
        <div className="mt-auto px-3 text-sm text-muted">
          <div className="truncate text-text" dir="auto">
            {member.display_name || member.username}
          </div>
          <div className="truncate text-xs">
            {member.is_owner ? 'owner' : 'member'} · @{member.username}
          </div>
        </div>
      )}
    </aside>
  )
}

function ChevronIcon({ className = '' }: { className?: string }) {
  return (
    <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d="M15 6l-6 6 6 6" />
    </svg>
  )
}
