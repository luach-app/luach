import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Audit } from '../Audit'
import { Household } from '../Household'
import { Emails } from '../Emails'
import { PushToggle } from '../PushToggle'
import { ApprovalCard } from '../ApprovalCard'
import * as api from '../../lib/api'
import * as push from '../../lib/push'
import { invalidateHousehold } from '../../lib/household'
import { member } from '../../test/harness'

describe('the audit trail', () => {
  it('stays shut until asked, then shows the chain and whether it verifies', async () => {
    const audit = vi.spyOn(api.control, 'audit').mockResolvedValue({
      entries: [{ seq: 1, ts: '2026-09-17T18:00:00Z', event_type: 'event.created', payload: { title: 'Dentist' }, hash: 'abc' }],
      total: 1,
      chain_verified: true,
      head: 'abc',
    } as never)
    render(<Audit tz="America/New_York" locale="en" />)
    expect(audit).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /Show/i }))
    await waitFor(() => expect(screen.getByText(/event.created/)).toBeInTheDocument())
    expect(screen.getByText(/verifies|verified/i)).toBeInTheDocument()
  })

  it('says loudly when the chain does not verify', async () => {
    vi.spyOn(api.control, 'audit').mockResolvedValue({ entries: [], total: 0, chain_verified: false, head: '' } as never)
    render(<Audit tz="America/New_York" locale="en" />)
    await userEvent.click(screen.getByRole('button', { name: /Show/i }))
    await waitFor(() => expect(screen.getByText(/chain broken/i)).toBeInTheDocument())
  })
})

describe('the household’s own settings', () => {
  beforeEach(() => {
    invalidateHousehold()
    vi.spyOn(api.household, 'calendars').mockResolvedValue({
      available: [
        { id: 'home', name: 'Home', writable: true, primary: true, enabled: true, default: true, color: '#f4b942' },
        { id: 'work', name: 'Work', writable: true, enabled: false, default: false, color: '#4488ff' },
      ],
      calendars: ['home'],
      default_calendar: 'home',
      default_attendees: ['alex@example.com'],
    } as never)
  })

  it('turns another calendar on and saves who is always invited', async () => {
    const update = vi.spyOn(api.household, 'update').mockResolvedValue({ calendars: ['home', 'work'], default_calendar: 'home', default_attendees: ['alex@example.com'] } as never)
    render(<Household />)
    await waitFor(() => expect(screen.getByText('Work')).toBeInTheDocument())
    await userEvent.click(screen.getByLabelText(/Use Work/i))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(update).toHaveBeenCalled())
    expect(update.mock.calls[0]?.[0]).toMatchObject({ calendars: ['home', 'work'] })
  })

  it('shows the server’s refusal', async () => {
    vi.spyOn(api.household, 'update').mockRejectedValue(new api.ApiError(403, 'only the owner can do that'))
    render(<Household />)
    await waitFor(() => expect(screen.getByText('Work')).toBeInTheDocument())
    await userEvent.click(screen.getByLabelText(/Use Work/i))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(screen.getByText('only the owner can do that')).toBeInTheDocument())
  })
})

describe('addresses', () => {
  const listing = {
    primary: 'robin@example.com',
    emails: [
      { email: 'robin@example.com', added_at: '2026-01-01T00:00:00', verified: true },
      { email: 'alt@example.com', added_at: '2026-02-01T00:00:00', verified: true },
    ],
  }

  it('makes one primary, and removes another after asking', async () => {
    vi.spyOn(api.emails, 'list').mockResolvedValue(listing as never)
    const primary = vi.spyOn(api.emails, 'primary').mockResolvedValue({ ...listing, primary: 'alt@example.com' } as never)
    const remove = vi.spyOn(api.emails, 'remove').mockResolvedValue(listing as never)
    render(<Emails member={member} onMember={() => {}} />)
    await waitFor(() => expect(screen.getByText('alt@example.com')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /Make alt@example.com primary/i }))
    await waitFor(() => expect(primary).toHaveBeenCalledWith('alt@example.com'))

    await userEvent.click(screen.getByRole('button', { name: /Remove robin@example.com/i }))
    expect(remove).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(remove).toHaveBeenCalled())
  })

  it('adds one and says it is on its way', async () => {
    vi.spyOn(api.emails, 'list').mockResolvedValue(listing as never)
    const add = vi.spyOn(api.emails, 'add').mockResolvedValue(listing as never)
    render(<Emails member={member} onMember={() => {}} />)
    await waitFor(() => expect(screen.getByLabelText('Add an address')).toBeInTheDocument())
    await userEvent.type(screen.getByLabelText('Add an address'), 'third@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(add).toHaveBeenCalledWith('third@example.com'))
  })
})

describe('notifications on this device', () => {
  it('says why it cannot offer them', async () => {
    vi.spyOn(push, 'pushState').mockResolvedValue('unsupported')
    render(<PushToggle />)
    await waitFor(() => expect(screen.getByText(/cannot receive push/i)).toBeInTheDocument())
  })

  it('turns them on', async () => {
    vi.spyOn(push, 'pushState').mockResolvedValue('off')
    const enable = vi.spyOn(push, 'enablePush').mockResolvedValue(undefined)
    render(<PushToggle />)
    await waitFor(() => expect(screen.getByRole('button', { name: /Turn on|Enable/i })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /Turn on|Enable/i }))
    await waitFor(() => expect(enable).toHaveBeenCalled())
  })
})

describe('an approval card', () => {
  const hold = { id: 'h1', tool: 'delete_event', summary: 'remove the dentist', reason: ['mutation-existing'], status: 'pending' as const }

  it('shows what an approval did in words or as the event, never as JSON', () => {
    const { unmount } = render(
      <ApprovalCard
        item={{ ...hold, tool: 'create_event', status: 'approved', result: { created: { id: 'e1', title: 'Picture Day', start: '2026-10-16', end: '2026-10-17', all_day: true } } }}
        tz="America/New_York"
        locale="en"
        onDecided={() => {}}
      />,
    )
    expect(screen.getByText('Picture Day')).toBeInTheDocument()
    expect(screen.queryByText(/"created"/)).toBeNull()
    unmount()
    render(
      <ApprovalCard
        item={{ ...hold, tool: 'update_event', status: 'failed', result: { error: '<HttpError 400 when requesting https://www.googleapis.com/calendar/v3/…>' } }}
        tz="America/New_York"
        locale="en"
        onDecided={() => {}}
      />,
    )
    expect(screen.getByText('Google refused that change, so nothing was done.')).toBeInTheDocument()
    expect(screen.queryByText(/HttpError/)).toBeNull()
  })

  it('says what an approved task from an email added, never as JSON', () => {
    const { unmount } = render(
      <ApprovalCard
        item={{ ...hold, tool: 'add_task', status: 'approved', result: { added: { id: 7, task: 'Return the permission slip', done: false, for: 'Lily', due: '2026-10-09' } } }}
        tz="America/New_York"
        locale="en"
        onDecided={() => {}}
      />,
    )
    expect(screen.getByText('Added the task “Return the permission slip” for Lily.')).toBeInTheDocument()
    expect(screen.queryByText(/"added"/)).toBeNull()
    unmount()
    render(
      <ApprovalCard
        item={{ ...hold, tool: 'add_task', status: 'approved', result: { already: { id: 7, task: 'Return the permission slip', done: false, for: 'Lily' } } }}
        tz="America/New_York"
        locale="en"
        onDecided={() => {}}
      />,
    )
    expect(screen.getByText('“Return the permission slip” was already on the list.')).toBeInTheDocument()
  })

  it("says an older hold's change in words", () => {
    render(
      <ApprovalCard
        item={{ ...hold, tool: 'update_event', summary: "Change event 7uq7u4vnhlfscmlrm11mm7jr78: {'start': '2026-10-16T09:00', 'end': '2026-10-16T12:00'}" }}
        tz="America/New_York"
        locale="en"
        onDecided={() => {}}
      />,
    )
    expect(screen.getByText('Change an event')).toBeInTheDocument()
    expect(screen.queryByText(/7uq7u4/)).toBeNull()
  })

  it('shows what was decided once it is decided', () => {
    render(<ApprovalCard item={{ ...hold, status: 'approved' }} tz="America/New_York" locale="en" onDecided={() => {}} />)
    expect(screen.getByText(/approved/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Approve/i })).not.toBeInTheDocument()
  })

  it('shows the email a proposal was found in, with a way to open it', () => {
    render(
      <ApprovalCard
        item={{ ...hold, reason: ['from-your-email'], source: { kind: 'email', id: 'm1', subject: 'Your appointment', from: 'Clinic <desk@clinic.example>', when: 'Tue 29 Sep 2026 09:00' } }}
        tz="America/New_York"
        locale="en"
        onDecided={() => {}}
      />,
    )
    expect(screen.getByText('Your appointment')).toBeInTheDocument()
    expect(screen.getByText('Clinic <desk@clinic.example>')).toBeInTheDocument()
    expect(screen.getByText('Found in your email')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open in Gmail' })).toHaveAttribute('href', 'https://mail.google.com/mail/u/0/#all/m1')
  })

  it('says an approval the calendar refused was not done, and why', () => {
    render(
      <ApprovalCard
        item={{ ...hold, status: 'failed', result: { error: 'no such event' } }}
        tz="America/New_York"
        locale="en"
        onDecided={() => {}}
      />,
    )
    expect(screen.getByText('Not done')).toBeInTheDocument()
    expect(screen.queryByText('Approved')).not.toBeInTheDocument()
    expect(screen.getByText('no such event')).toBeInTheDocument()
  })

  it('reports a refusal from the server', async () => {
    vi.spyOn(api.control, 'approve').mockRejectedValue(new api.ApiError(409, 'already denied'))
    render(<ApprovalCard item={hold} tz="America/New_York" locale="en" onDecided={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: /Approve/i }))
    await waitFor(() => expect(screen.getByText('already denied')).toBeInTheDocument())
  })
})
