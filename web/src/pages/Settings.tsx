import { useMemo, useState, type FormEvent } from 'react'
import { auth, emails as emailsApi, errorMessage } from '../lib/api'
import type { Member } from '../lib/types'
import { resolveLocale, timeZones } from '../lib/time'
import { useAction } from '../lib/hooks'
import { answering, useModels } from '../lib/models'
import { Audit } from '../components/Audit'
import { Booking } from '../components/Booking'
import { BusyCalendars } from '../components/BusyCalendars'
import { CalendarFeed } from '../components/CalendarFeed'
import { Reminders } from '../components/Reminders'
import { EmailChips } from '../components/EmailChips'
import { Emails } from '../components/Emails'
import { Household } from '../components/Household'
import { Models } from '../components/Models'
import { Mailbox } from '../components/Mailbox'
import { Memory } from '../components/Memory'
import { Passkeys } from '../components/Passkeys'
import { Button } from '../components/Button'
import { Input, Notice, Select } from '../components/Field'
import { PushToggle } from '../components/PushToggle'

interface Props {
  member: Member
  onMember: (m: Member) => void
  onSignOut: () => void
}

const LANGUAGES: { value: string; label: string }[] = [
  { value: 'auto', label: 'Automatic' },
  { value: 'en', label: 'English' },
  { value: 'es', label: 'Español' },
  { value: 'he', label: 'עברית' },
]

export function Settings({ member, onMember, onSignOut }: Props) {
  const tz = member.timezone || 'UTC'
  const locale = resolveLocale(member.language)
  const zones = useMemo(() => {
    const list = timeZones()
    return list.includes(tz) ? list : [tz, ...list]
  }, [tz])

  // Eleven cards in one column was a page you scrolled rather than read. The
  // sections are how a person thinks about them: who I am, what the household
  // shares, how people book me, what luach tells me, and the record. The calendar feed
  // has its own: it is about the phone's calendar, not any of those.
  const sections = [
    { id: 'you', label: 'You' },
    { id: 'feed', label: 'Calendar feed' },
    ...(member.is_owner ? [{ id: 'household', label: 'Household' }] : []),
    { id: 'meetings', label: 'Meetings' },
    { id: 'alerts', label: 'Reminders' },
    { id: 'security', label: 'Security' },
  ] as const
  type Section = (typeof sections)[number]['id']
  const [section, setSection] = useState<Section>('you')

  return (
    <div className="fade-up flex flex-col gap-4">
      <header className="px-1">
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-sm text-muted">
          Signed in as @{member.username}
          {member.is_owner ? ' · owner' : ''}
        </p>
      </header>

      <div role="tablist" aria-label="Settings sections" className="no-scrollbar -mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
        {sections.map((s) => (
          <button
            key={s.id}
            role="tab"
            aria-selected={section === s.id}
            onClick={() => setSection(s.id)}
            className={`shrink-0 rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${section === s.id ? 'bg-accent text-accent-on' : 'border border-line-strong text-muted hover:text-text'}`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {section === 'you' ? (
        <>
          <Profile member={member} onMember={onMember} zones={zones} />
          <Emails member={member} onMember={onMember} />
          <Mailbox />
          <NotifyEmails member={member} onMember={onMember} />
          <Memory />
        </>
      ) : null}

      {section === 'feed' ? <CalendarFeed /> : null}

      {section === 'household' && member.is_owner ? (
        <>
          <Household />
          <Models />
        </>
      ) : null}

      {section === 'meetings' ? (
        <>
          <Booking tz={tz} locale={locale} />
          <BusyCalendars />
        </>
      ) : null}

      {section === 'alerts' ? (
        <>
          <PushToggle />
          <Reminders tz={tz} />
        </>
      ) : null}

      {section === 'security' ? (
        <>
          <Passkeys tz={tz} locale={locale} />
          <Password />
          {/* The raw record of every write, with the hash chain that seals it: the
              owner's tool for "what happened?", not something the family reads. */}
          {member.is_owner ? <Audit tz={tz} locale={locale} /> : null}
        </>
      ) : null}

      <SignOut onSignOut={onSignOut} />
    </div>
  )
}

function Profile({ member, onMember, zones }: { member: Member; onMember: (m: Member) => void; zones: string[] }) {
  const [displayName, setDisplayName] = useState(member.display_name)
  const [timezone, setTimezone] = useState(member.timezone)
  const [language, setLanguage] = useState(member.language || 'auto')
  const { options: models, defaultModel } = useModels()
  // "" is the household's own; the select shows it by its id so it reads as a choice.
  const savedModel = member.model || defaultModel
  const [model, setModel] = useState('')
  const shownModel = model || savedModel
  const [saved, setSaved] = useState(false)
  const { busy, error, run } = useAction()

  const modelChanged = !!model && model !== savedModel
  const dirty =
    displayName !== member.display_name || timezone !== member.timezone || language !== (member.language || 'auto') || modelChanged

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSaved(false)
    const body: Partial<Pick<Member, 'display_name' | 'timezone' | 'language' | 'model'>> = {}
    if (displayName !== member.display_name) body.display_name = displayName.trim()
    if (timezone !== member.timezone) body.timezone = timezone
    if (language !== (member.language || 'auto')) body.language = language
    if (modelChanged) body.model = model === defaultModel ? '' : model
    const m = await run(() => auth.update(body), errorMessage)
    if (m) {
      onMember(m)
      setModel('')
      setSaved(true)
    }
  }

  return (
    <form onSubmit={submit} className="card flex flex-col gap-4 px-4 py-4">
      <h2 className="font-semibold">Profile</h2>
      <Input label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} dir="auto" autoComplete="name" />
      <Select label="Timezone" value={timezone} onChange={(e) => setTimezone(e.target.value)}>
        {zones.map((z) => (
          <option key={z} value={z}>
            {z}
          </option>
        ))}
      </Select>
      <Select label="Language luach answers in" hint="Dates are written this way too." value={language} onChange={(e) => setLanguage(e.target.value)}>
        {LANGUAGES.map((l) => (
          <option key={l.value} value={l.value}>
            {l.label}
          </option>
        ))}
      </Select>
      {models.length > 1 ? (
        <Select
          label="Model that answers you"
          value={shownModel}
          onChange={(e) => setModel(e.target.value)}
          hint={modelHint(models.find((o) => o.id === shownModel))}
        >
          {models.map((o) => (
            // One that is not answering cannot be chosen; it is shown so its absence is explained.
            <option key={o.id} value={o.id} disabled={!answering(o) && o.id !== shownModel}>
              {o.id === defaultModel ? `${o.name} (default)` : o.name}
              {answering(o) ? '' : ' — not answering'}
            </option>
          ))}
        </Select>
      ) : null}
      <Notice kind="error">{error}</Notice>
      {saved && !dirty ? <Notice kind="success">Saved.</Notice> : null}
      <Button type="submit" variant="primary" busy={busy} disabled={!dirty} className="self-end">
        Save
      </Button>
    </form>
  )
}

function modelHint(o: ReturnType<typeof useModels>['options'][number] | undefined): string | undefined {
  if (!o) return undefined
  if (!answering(o)) return `Not answering right now${o.health?.reason ? ` (${o.health.reason})` : ''}. The household's model answers you meanwhile.`
  return o.about
}

/** Settings › Also notify: inboxes that get an invitation to every event you create. */
function NotifyEmails({ member, onMember }: { member: Member; onMember: (m: Member) => void }) {
  const confirmed = member.notify_emails ?? []
  const pending = member.notify_pending ?? []
  const saved = [...confirmed, ...pending]
  const [list, setList] = useState(saved)
  const [draft, setDraft] = useState('')
  const [done, setDone] = useState(false)
  const [sentTo, setSentTo] = useState('')
  const { busy, error, run } = useAction()
  const dirty = list.join() !== saved.join() || !!draft

  const resend = async (email: string) => {
    const sent = await run(() => emailsApi.resend(email), errorMessage)
    if (sent) setSentTo(email)
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setDone(false)
    const next = draft && !list.includes(draft) ? [...list, draft] : list
    const m = await run(() => auth.update({ notify_emails: next }), errorMessage)
    if (m) {
      onMember(m)
      setList([...(m.notify_emails ?? []), ...(m.notify_pending ?? [])])
      setDone(true)
    }
  }

  return (
    <form onSubmit={submit} className="card flex flex-col gap-4 px-4 py-4">
      <div>
        <h2 className="font-semibold">Also notify</h2>
        <p className="text-sm text-muted">Every event <em>you</em> add — here, by asking, or by email — also sends a Google Calendar invitation to these addresses, such as a work inbox. Nobody else's events reach them.</p>
      </div>
      <EmailChips label="Addresses" value={list} onChange={(v) => { setList(v); setDone(false) }} onDraft={setDraft} placeholder="you@work.com" hint="Press Enter after each address. Say “don’t invite anyone” to skip them for one event." disabled={busy} />
      {pending.length ? (
        <div className="rounded-xl border border-line bg-surface-2/50 px-3 py-2.5">
          <p className="text-sm text-muted">Waiting for confirmation — these are invited to nothing until the link is followed:</p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {pending.map((email) => (
              <li key={email} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="min-w-0 flex-1 truncate" dir="ltr">
                  {email}
                </span>
                <Button size="sm" variant="ghost" busy={busy} onClick={() => void resend(email)}>
                  {sentTo === email ? 'Sent' : 'Resend'}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <Notice kind="error">{error}</Notice>
      {done && !dirty ? <Notice kind="success">Saved.</Notice> : null}
      <Button type="submit" variant="primary" busy={busy} disabled={!dirty} className="self-end">
        Save
      </Button>
    </form>
  )
}

function Password() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [done, setDone] = useState(false)
  const { busy, error, setError, run } = useAction()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setDone(false)
    if (next !== confirm) {
      setError('The two new passwords do not match.')
      return
    }
    const ok = await run(() => auth.password(current, next), errorMessage)
    if (ok) {
      setDone(true)
      setCurrent('')
      setNext('')
      setConfirm('')
    }
  }

  return (
    <form onSubmit={submit} className="card flex flex-col gap-4 px-4 py-4">
      <h2 className="font-semibold">Change password</h2>
      <Input label="Current password" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
      <Input label="New password" type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required minLength={8} />
      <Input label="Repeat new password" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
      <Notice kind="error">{error}</Notice>
      {done ? <Notice kind="success">Password changed.</Notice> : null}
      <Button type="submit" busy={busy} className="self-end">
        Update password
      </Button>
    </form>
  )
}

function SignOut({ onSignOut }: { onSignOut: () => void }) {
  const { busy, run } = useAction()
  const go = async () => {
    await run(() => auth.logout(), () => '')
    onSignOut()
  }
  return (
    <div className="flex justify-center py-2">
      <Button variant="ghost" busy={busy} onClick={() => void go()} className="text-danger">
        Sign out
      </Button>
    </div>
  )
}
