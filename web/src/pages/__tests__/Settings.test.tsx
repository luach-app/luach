import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Settings } from '../Settings'
import * as api from '../../lib/api'
import { invalidateHousehold } from '../../lib/household'
import { member } from '../../test/harness'

const booking = {
  enabled: false, slug: 'robin', slot_minutes: 30, max_per_day: 2, buffer_minutes: 15, lead_hours: 12,
  horizon_days: 21, title: 'Meeting with {name}', location: '', note: '', calendar_id: '', notify_host: true,
  conferencing: 'none', hours: { mon: [['09:00', '17:00']], tue: [], wed: [], thu: [], fri: [], sat: [], sun: [] },
  link: 'https://luach.test/book/robin', timezone: 'America/New_York', zoom_ready: false,
}

/** Answers /api/models only; every other GET goes where it went before. */
function serveModels(menu: unknown) {
  const real = api.api.get.bind(api.api)
  vi.spyOn(api.api, 'get').mockImplementation(((path: string) =>
    path === '/api/models' ? Promise.resolve(menu) : real(path)) as never)
}

beforeEach(() => {
  invalidateHousehold()
  vi.spyOn(api.household, 'calendars').mockResolvedValue({
    available: [{ id: 'home', name: 'Home', writable: true, primary: true, color: '#f4b942' }],
    calendars: ['home'], default_calendar: 'home', default_attendees: [],
  } as never)
  vi.spyOn(api.emails, 'list').mockResolvedValue({ primary: 'robin@example.com', emails: [{ email: 'robin@example.com', added_at: '2026-01-01T00:00:00', verified: true }] } as never)
  vi.spyOn(api.booking, 'mine').mockResolvedValue(booking as never)
  vi.spyOn(api.booking, 'upcoming').mockResolvedValue({ bookings: [] } as never)
  vi.spyOn(api.busy, 'list').mockResolvedValue({ sources: [] } as never)
  vi.spyOn(api.reminders, 'get').mockResolvedValue({ lead_minutes: 0, evening_hour: -1, weekly_day: -1, weekly_hour: 18, by_email: false } as never)
  vi.spyOn(api.passkeys, 'list').mockResolvedValue({ passkeys: [] } as never)
  vi.spyOn(api.control, 'audit').mockResolvedValue({ entries: [], total: 0, chain_verified: true, head: '' } as never)
})

describe('everything a member can set', () => {
  it('opens on you, and keeps the rest a tab away rather than a scroll away', async () => {
    render(<Settings member={member} onMember={() => {}} onSignOut={() => {}} />)
    // What a person sees first: themselves. Not eleven cards.
    for (const heading of ['Profile', 'Addresses you sign in with', 'Also notify']) {
      await waitFor(() => expect(screen.getByText(heading)).toBeInTheDocument())
    }
    expect(screen.queryByText('Meetings with me')).not.toBeInTheDocument()
    expect(screen.queryByText('Change password')).not.toBeInTheDocument()
  })

  it('has a section for each thing a person came to change', async () => {
    render(<Settings member={member} onMember={() => {}} onSignOut={() => {}} />)
    const go = async (tab: string, heading: string) => {
      await userEvent.click(screen.getByRole('tab', { name: tab }))
      await waitFor(() => expect(screen.getByText(heading)).toBeInTheDocument())
    }
    // "Household" names both the tab and the card, so look for the card's own line.
    await go('Household', 'The calendars luach reads, where new things go, and who is invited to everything.')
    await go('Meetings', 'Meetings with me')
    await waitFor(() => expect(screen.getByText('Work calendar')).toBeInTheDocument())
    await go('Reminders', 'Before something starts')
    await go('Security', 'Change password')
    await waitFor(() => expect(screen.getByText('Audit')).toBeInTheDocument())
    // Signing out is reachable from wherever you are.
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  })

  it('shows the booking link before it is live, because that is how you decide', async () => {
    render(<Settings member={member} onMember={() => {}} onSignOut={() => {}} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Meetings' }))
    await waitFor(() => expect(screen.getByText('https://luach.test/book/robin')).toBeInTheDocument())
    expect(screen.getByText('not live yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy link' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open it' })).toHaveAttribute('href', 'https://luach.test/book/robin')
  })

  it('saves a change of name, and only the changed field', async () => {
    const update = vi.spyOn(api.auth, 'update').mockResolvedValue({ ...member, display_name: 'Rob' } as never)
    render(<Settings member={member} onMember={() => {}} onSignOut={() => {}} />)
    const name = screen.getByLabelText('Display name')
    await userEvent.clear(name)
    await userEvent.type(name, 'Rob')
    await userEvent.click(screen.getAllByRole('button', { name: 'Save' })[0]!)
    await waitFor(() => expect(update).toHaveBeenCalledWith({ display_name: 'Rob' }))
  })

  it('chooses the model from a short menu, the home server by default, and saves it', async () => {
    const menu = {
      default: 'qwen3.6-35b',
      catalogue: [
        { id: 'qwen3.6-35b', name: 'Home server · Qwen 3.6', about: 'Runs on the household\'s own machine.' },
        { id: 'cloud-deepseek-v4-flash', name: 'DeepSeek V4 Flash', about: 'A fast cloud model.' },
        { id: 'openrouter/google/gemini-3.8-flash', name: 'Gemini 3.8 Flash', about: 'Google\'s cloud model.' },
      ],
    }
    serveModels(menu)
    const update = vi.spyOn(api.auth, 'update').mockResolvedValue({ ...member, model: 'openrouter/google/gemini-3.8-flash' } as never)
    render(<Settings member={member} onMember={() => {}} onSignOut={() => {}} />)
    const select = await screen.findByLabelText('Model that answers you')
    expect(select).toHaveValue('qwen3.6-35b')
    expect(screen.getAllByRole('option').filter((o) => menu.catalogue.some((c) => o.getAttribute('value') === c.id))).toHaveLength(3)
    expect(screen.getByRole('option', { name: 'Home server · Qwen 3.6 (default)' })).toBeInTheDocument()
    expect(screen.getByText('Runs on the household\'s own machine.')).toBeInTheDocument()
    await userEvent.selectOptions(select, 'openrouter/google/gemini-3.8-flash')
    await userEvent.click(screen.getAllByRole('button', { name: 'Save' })[0]!)
    await waitFor(() => expect(update).toHaveBeenCalledWith({ model: 'openrouter/google/gemini-3.8-flash' }))
  })

  it('saves going back to the default as no choice at all', async () => {
    serveModels({
      default: 'qwen3.6-35b',
      catalogue: [
        { id: 'qwen3.6-35b', name: 'Home server · Qwen 3.6', about: '' },
        { id: 'cloud-deepseek-v4-flash', name: 'DeepSeek V4 Flash', about: '' },
      ],
    })
    const update = vi.spyOn(api.auth, 'update').mockResolvedValue({ ...member, model: '' } as never)
    render(<Settings member={{ ...member, model: 'cloud-deepseek-v4-flash' }} onMember={() => {}} onSignOut={() => {}} />)
    const select = await screen.findByLabelText('Model that answers you')
    await waitFor(() => expect(select).toHaveValue('cloud-deepseek-v4-flash'))
    await userEvent.selectOptions(select, 'qwen3.6-35b')
    await userEvent.click(screen.getAllByRole('button', { name: 'Save' })[0]!)
    await waitFor(() => expect(update).toHaveBeenCalledWith({ model: '' }))
  })

  it('shows a model that is not answering, and will not let it be chosen', async () => {
    serveModels({
      default: 'qwen3.6-35b',
      catalogue: [
        { id: 'qwen3.6-35b', name: 'Home server', about: 'At home.', local: true, health: { status: 'ok', since: null, reason: '' } },
        {
          id: 'cloud-deepseek-v4-flash',
          name: 'DeepSeek V4 Flash',
          about: 'Fast.',
          health: { status: 'not_answering', since: '2026-10-28T12:00:00Z', reason: '404: No endpoints found' },
        },
        { id: 'openrouter/google/gemini-3.8-flash', name: 'Gemini', about: 'Google.', health: { status: 'ok', since: null, reason: '' } },
      ],
    })
    render(<Settings member={member} onMember={() => {}} onSignOut={() => {}} />)
    await screen.findByLabelText('Model that answers you')
    const broken = screen.getByRole('option', { name: 'DeepSeek V4 Flash — not answering' })
    expect(broken).toBeDisabled()
    expect(screen.getByRole('option', { name: 'Gemini' })).not.toBeDisabled()
  })

  it('says why the model a member had is not answering', async () => {
    serveModels({
      default: 'qwen3.6-35b',
      catalogue: [
        { id: 'qwen3.6-35b', name: 'Home server', about: 'At home.' },
        { id: 'cloud-deepseek-v4-flash', name: 'DeepSeek V4 Flash', about: 'Fast.', health: { status: 'not_answering', since: null, reason: '404: gone' } },
      ],
    })
    render(<Settings member={{ ...member, model: 'cloud-deepseek-v4-flash' }} onMember={() => {}} onSignOut={() => {}} />)
    await waitFor(() => expect(screen.getByText(/Not answering right now \(404: gone\)/)).toBeInTheDocument())
  })

  it('gives the owner the model menu under Household', async () => {
    vi.spyOn(api.models, 'manage').mockResolvedValue({
      default: 'qwen3.6-35b', configured: true, trial: null, trials_left_today: 6,
      catalogue: { configured: false, source: '' },
      models: [],
    } as never)
    render(<Settings member={member} onMember={() => {}} onSignOut={() => {}} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Household' }))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Models' })).toBeInTheDocument())
  })

  it('saves an address that was typed but never turned into a chip', async () => {
    // Save stayed disabled: only Enter made it a change, and a disabled button
    // does not take the focus, so the blur that would have added it never came.
    const update = vi.spyOn(api.auth, 'update').mockResolvedValue({ ...member, notify_pending: ['work@corp.com'] } as never)
    render(<Settings member={member} onMember={() => {}} onSignOut={() => {}} />)
    await userEvent.type(screen.getByLabelText('Addresses'), 'work@corp.com')
    const saves = screen.getAllByRole('button', { name: 'Save' }).filter((b) => !(b as HTMLButtonElement).disabled)
    expect(saves).toHaveLength(1)
    await userEvent.click(saves[0]!)
    await waitFor(() => expect(update).toHaveBeenCalledWith({ notify_emails: ['work@corp.com'] }))
  })

  it('keeps the audit trail for the owner', async () => {
    const { unmount } = render(<Settings member={member} onMember={() => {}} onSignOut={() => {}} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Security' }))
    await waitFor(() => expect(screen.getByText('Audit')).toBeInTheDocument())
    unmount()
    render(<Settings member={{ ...member, is_owner: false }} onMember={() => {}} onSignOut={() => {}} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Security' }))
    await waitFor(() => expect(screen.getByText('Change password')).toBeInTheDocument())
    expect(screen.queryByText('Audit')).not.toBeInTheDocument()
  })

  it('adds an also-notify address and reports it is waiting for confirmation', async () => {
    const update = vi.spyOn(api.auth, 'update').mockResolvedValue({ ...member, notify_emails: [], notify_pending: ['work@corp.com'] } as never)
    const onMember = vi.fn()
    const { rerender } = render(<Settings member={member} onMember={onMember} onSignOut={() => {}} />)
    await userEvent.type(screen.getByLabelText('Addresses'), 'work@corp.com{Enter}')
    // The card's own Save: the one that is enabled, since the others are clean.
    const saves = screen.getAllByRole('button', { name: 'Save' }).filter((b) => !(b as HTMLButtonElement).disabled)
    await userEvent.click(saves[0]!)
    await waitFor(() => expect(update).toHaveBeenCalled())
    expect(update.mock.calls.at(-1)?.[0]).toEqual({ notify_emails: ['work@corp.com'] })

    rerender(<Settings member={{ ...member, notify_pending: ['work@corp.com'] }} onMember={onMember} onSignOut={() => {}} />)
    expect(screen.getByText(/Waiting for confirmation/)).toBeInTheDocument()
  })

  it('changes a password only when the two new ones match', async () => {
    const change = vi.spyOn(api.auth, 'password').mockResolvedValue({ ok: true } as never)
    render(<Settings member={member} onMember={() => {}} onSignOut={() => {}} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Security' }))
    await userEvent.type(screen.getByLabelText('Current password'), 'correct horse battery')
    await userEvent.type(screen.getByLabelText('New password'), 'a brand new one')
    await userEvent.type(screen.getByLabelText('Repeat new password'), 'a different one')
    await userEvent.click(screen.getByRole('button', { name: 'Update password' }))
    await waitFor(() => expect(screen.getByText(/do not match/)).toBeInTheDocument())
    expect(change).not.toHaveBeenCalled()
  })

  it('signs out when asked', async () => {
    vi.spyOn(api.auth, 'logout').mockResolvedValue({ ok: true } as never)
    const onSignOut = vi.fn()
    render(<Settings member={member} onMember={() => {}} onSignOut={onSignOut} />)
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(onSignOut).toHaveBeenCalled())
  })
})
