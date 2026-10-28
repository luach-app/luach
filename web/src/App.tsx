import { useCallback, useEffect, useState } from 'react'
import { auth, control, setUnauthorizedHandler } from './lib/api'
import { shouldOfferPasskey } from './lib/passkeys'
import { registerServiceWorker } from './lib/push'
import { cleanQuery, readDeepLink, type Deep } from './lib/route'
import { useMediaQuery, useVisiblePoll } from './lib/hooks'
import { forgetMonths } from './lib/monthCache'
import { useNewBuild } from './lib/selfUpdate'
import type { AuthStatus, Member } from './lib/types'
import { Spinner } from './components/Button'
import { Logo } from './components/Logo'
import { SideRail, TopNav, type Tab, type TabDef } from './components/Nav'
import { BoardIcon, CalendarIcon, GearIcon, ListCheckIcon, PeopleIcon, ShieldIcon } from './components/Icons'
import { AcceptInvite } from './pages/gate/AcceptInvite'
import { Bootstrap } from './pages/gate/Bootstrap'
import { Login } from './pages/gate/Login'
import { PasskeyOffer } from './pages/gate/PasskeyOffer'
import { Reset } from './pages/gate/Reset'
import { Agenda } from './pages/Agenda'
import { Book } from './pages/Book'
import { ConfirmAddress } from './pages/gate/ConfirmAddress'
import { Board, Today as BoardToday } from './pages/Board'
import { Members } from './pages/Members'
import { Tasks } from './pages/Tasks'
import { Pending } from './pages/Pending'
import { Settings } from './pages/Settings'

/** The language the app's own words are in. */
const UI_LANG = 'en'

type Phase = { kind: 'loading' } | { kind: 'gate'; status: AuthStatus } | { kind: 'offer'; member: Member } | { kind: 'app'; member: Member }

export default function App() {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })
  const [deep, setDeep] = useState<Deep>(() => readDeepLink())
  // Kept apart from the phase: signing out returns to the gate without asking the server again.
  const [household, setHousehold] = useState('')

  const refreshStatus = useCallback(async () => {
    try {
      const s = await auth.status()
      setHousehold(s.household ?? '')
      if (s.authenticated && s.member) setPhase({ kind: 'app', member: s.member })
      else setPhase({ kind: 'gate', status: s })
    } catch {
      setPhase({ kind: 'gate', status: { users_exist: true, authenticated: false } })
    }
  }, [])

  useEffect(() => {
    void refreshStatus()
    void registerServiceWorker()
  }, [refreshStatus])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setPhase((p) => (p.kind === 'app' ? { kind: 'gate', status: { users_exist: true, authenticated: false } } : p))
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  /** `fresh` = the account was just created: offer a passkey for this device once. */
  const signedIn = (m: Member, fresh = false) => {
    cleanQuery()
    setDeep(null)
    setPhase(fresh && shouldOfferPasskey() ? { kind: 'offer', member: m } : { kind: 'app', member: m })
  }
  const leaveDeepLink = () => {
    cleanQuery()
    setDeep(null)
  }
  const signOut = () => {
    forgetMonths()
    setPhase({ kind: 'gate', status: { users_exist: true, authenticated: false } })
  }

  // The page is the app's English: a member's language is the one luach answers
  // in (and writes dates in), not the one its buttons are in. lang="he" on an
  // English page had a screen reader read every label with a Hebrew voice. Their
  // answers carry their own lang (ChatTurn), and each runs in its own direction.
  useEffect(() => {
    document.documentElement.lang = UI_LANG
    document.documentElement.dir = 'ltr'
  }, [phase])

  if (deep?.kind === 'board') return <Board />

  // The booking page belongs to whoever has the link, signed in or not.
  if (deep?.kind === 'book') return <Book slug={deep.slug} manage={deep.manage} />

  // A confirmation link is read wherever the mail was opened, so it does not
  // wait for the gate: the token is the proof, and the account is untouched.
  if (deep?.kind === 'verify') {
    return (
      <ConfirmAddress
        token={deep.token}
        onDone={() => {
          leaveDeepLink()
          void refreshStatus()
        }}
      />
    )
  }

  if (phase.kind === 'loading') {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-6">
        <Logo size="lg" />
        <Spinner className="text-muted" />
      </div>
    )
  }

  if (phase.kind === 'offer') {
    return <PasskeyOffer member={phase.member} onDone={() => setPhase({ kind: 'app', member: phase.member })} />
  }

  if (phase.kind === 'gate') {
    if (deep?.kind === 'invite') return <AcceptInvite token={deep.token} onSignedIn={signedIn} onCancel={leaveDeepLink} />
    if (deep?.kind === 'reset') return <Reset token={deep.token} onSignedIn={signedIn} onCancel={leaveDeepLink} />
    if (!phase.status.users_exist) return <Bootstrap onSignedIn={signedIn} />
    return <Login onSignedIn={signedIn} sso={phase.status.sso} household={household} mail={phase.status.mail} />
  }

  return <Shell member={phase.member} onMember={(m) => setPhase({ kind: 'app', member: m })} onSignOut={signOut} />
}

// Ask is not one of these any more: the assistant sits beside the calendar
// rather than being somewhere a person goes.
function tabsFor(member: Member, pendingCount: number): TabDef[] {
  const tabs: TabDef[] = [
    { id: 'agenda', label: 'Agenda', icon: <CalendarIcon /> },
    { id: 'board', label: 'Board', icon: <BoardIcon /> },
    { id: 'tasks', label: 'Tasks', icon: <ListCheckIcon /> },
    { id: 'pending', label: 'Pending', icon: <ShieldIcon />, badge: pendingCount },
  ]
  if (member.is_owner) tabs.push({ id: 'members', label: 'Members', icon: <PeopleIcon /> })
  tabs.push({ id: 'settings', label: 'Settings', icon: <GearIcon /> })
  return tabs
}

function Shell({ member, onMember, onSignOut }: { member: Member; onMember: (m: Member) => void; onSignOut: () => void }) {
  // A link can open a tab: "?tab=pending" from a notification, "?tab=settings" back from Google.
  const [tab, setTab] = useState<Tab>(() => {
    const asked = new URLSearchParams(window.location.search).get('tab')
    const known: Tab[] = ['agenda', 'board', 'tasks', 'pending', 'members', 'settings']
    return known.includes(asked as Tab) ? (asked as Tab) : 'agenda'
  })
  const [pendingCount, setPendingCount] = useState(0)

  const refreshPending = useCallback(async () => {
    try {
      const res = await control.pending(false)
      setPendingCount(res.pending.filter((r) => r.status === 'pending').length)
    } catch {
      /* the badge is best-effort */
    }
  }, [])
  useVisiblePoll(refreshPending, 30_000)

  useEffect(() => {
    if (tab === 'members' && !member.is_owner) setTab('agenda')
  }, [tab, member.is_owner])

  const tabs = tabsFor(member, pendingCount)
  const agenda = tab === 'agenda'
  const board = tab === 'board'
  const wide = useMediaQuery('(min-width: 768px)')
  // After an upgrade, this page still runs the old code: say so, and let the person reload.
  const newBuild = useNewBuild(true)
  return (
    <div className="flex h-dvh min-h-0">
      {/* One or the other, never both: a rail where there is width for one, a
          bar where there is not. Rendering both and hiding one with CSS leaves
          a screen reader announcing the navigation twice. */}
      {wide ? <SideRail tabs={tabs} active={tab} onSelect={setTab} member={member} /> : null}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {wide ? null : <TopNav tabs={tabs} active={tab} onSelect={setTab} member={member} />}
        {newBuild ? (
          <div role="status" className="safe-x flex items-center justify-center gap-3 border-b border-line bg-surface-2 px-4 py-2 text-sm">
            <span>A new version is ready.</span>
            <button type="button" onClick={() => window.location.reload()} className="rounded-full border border-line-strong px-3 py-1 font-medium text-accent-text hover:bg-surface">
              Reload
            </button>
          </div>
        ) : null}
      {/* The agenda owns the whole screen and scrolls inside itself; the
          reading pages keep a column and scroll the page. */}
        <main className={agenda ? 'min-h-0 flex-1' : board ? 'min-h-0 flex-1 overflow-y-auto' : 'safe-x mx-auto w-full max-w-3xl flex-1 overflow-y-auto px-4 pt-5 pb-10 md:pt-8'}>
        {agenda ? <Agenda member={member} onHoldsChanged={() => void refreshPending()} /> : null}
        {board ? <BoardToday token="" embedded onUnpaired={() => setTab('agenda')} /> : null}
        {tab === 'tasks' ? <Tasks member={member} /> : null}
        {tab === 'pending' ? <Pending member={member} onHoldsChanged={() => void refreshPending()} /> : null}
        {tab === 'members' && member.is_owner ? <Members member={member} /> : null}
        {tab === 'settings' ? <Settings member={member} onMember={onMember} onSignOut={onSignOut} /> : null}
        </main>
      </div>
    </div>
  )
}
