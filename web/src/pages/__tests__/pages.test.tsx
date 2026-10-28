import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Pending } from '../Pending'
import { Members } from '../Members'
import * as api from '../../lib/api'
import { member } from '../../test/harness'

const hold = {
  id: 'h1',
  tool: 'create_event',
  summary: 'Dentist on Tuesday at 15:00',
  reason: ['ambiguous'],
  principal: 'robin',
  door: 'web',
  status: 'pending',
  created_at: '2026-09-17T18:00:00',
  decided_at: null,
  decided_by: '',
  result: null,
}

describe('what is waiting for a yes', () => {
  beforeEach(() => {
    vi.spyOn(api.control, 'pending').mockResolvedValue({ pending: [hold] } as never)
  })

  it('shows a hold with the reason it was held, and approves it', async () => {
    const approve = vi.spyOn(api.control, 'approve').mockResolvedValue({ ...hold, status: 'approved' } as never)
    const changed = vi.fn()
    render(<Pending member={member} onHoldsChanged={changed} />)
    await waitFor(() => expect(screen.getByText(/Dentist on Tuesday/)).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /Approve/i }))
    await waitFor(() => expect(approve).toHaveBeenCalledWith('h1'))
    expect(changed).toHaveBeenCalled()
  })

  it('denies one too', async () => {
    const deny = vi.spyOn(api.control, 'deny').mockResolvedValue({ ...hold, status: 'denied' } as never)
    render(<Pending member={member} onHoldsChanged={() => {}} />)
    await waitFor(() => expect(screen.getByText(/Dentist on Tuesday/)).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /Deny/i }))
    await waitFor(() => expect(deny).toHaveBeenCalledWith('h1'))
  })

  it('says so plainly when nothing is waiting', async () => {
    vi.spyOn(api.control, 'pending').mockResolvedValue({ pending: [] } as never)
    render(<Pending member={member} onHoldsChanged={() => {}} />)
    await waitFor(() => expect(screen.getByText(/Nothing/i)).toBeInTheDocument())
  })

  it('shows the server’s complaint rather than an empty page', async () => {
    vi.spyOn(api.control, 'pending').mockRejectedValue(new api.ApiError(500, 'the trail is unreadable'))
    render(<Pending member={member} onHoldsChanged={() => {}} />)
    await waitFor(() => expect(screen.getByText('the trail is unreadable')).toBeInTheDocument())
  })
})

describe('the household', () => {
  const listing = {
    members: [
      { ...member, last_seen: '2026-09-17T12:00:00' },
      { id: 2, username: 'ana', email: 'ana@example.com', display_name: 'Ana', timezone: 'America/New_York', language: 'en', is_owner: false, last_seen: null },
    ],
    invites: [],
  }

  it('lists who is in it and invites someone by email', async () => {
    vi.spyOn(api.members, 'list').mockResolvedValue(listing as never)
    const invite = vi.spyOn(api.members, 'invite').mockResolvedValue({ sent: true } as never)
    render(<Members member={member} />)
    await waitFor(() => expect(screen.getByText('Ana')).toBeInTheDocument())

    await userEvent.type(screen.getByLabelText(/Invite by email/i), 'new@example.com')
    await userEvent.click(screen.getByRole('button', { name: /Send invitation/i }))
    await waitFor(() => expect(invite).toHaveBeenCalledWith('new@example.com'))
  })

  it('hands over the link itself when mail is not configured', async () => {
    vi.spyOn(api.members, 'list').mockResolvedValue(listing as never)
    vi.spyOn(api.members, 'invite').mockResolvedValue({ sent: false, link: 'https://luach.test/?invite=tok' } as never)
    render(<Members member={member} />)
    await waitFor(() => expect(screen.getByText('Ana')).toBeInTheDocument())
    await userEvent.type(screen.getByLabelText(/Invite by email/i), 'new@example.com')
    await userEvent.click(screen.getByRole('button', { name: /Send invitation/i }))
    await waitFor(() => expect(screen.getByText(/luach.test\/\?invite=tok/)).toBeInTheDocument())
  })

  it('says mail is off differently from a send that failed, and passes on the server’s warning', async () => {
    vi.spyOn(api.members, 'list').mockResolvedValue(listing as never)
    const invite = vi
      .spyOn(api.members, 'invite')
      .mockResolvedValueOnce({ sent: false, link: 'https://luach.test/?invite=a', mail: 'not_configured' })
      .mockResolvedValueOnce({
        sent: false,
        link: 'https://calendar.example.com/?invite=b',
        mail: 'failed',
        warning: 'LUACH_APP_URL is http://localhost:8004, so this link uses the address you are using now',
      })
    render(<Members member={member} />)
    await waitFor(() => expect(screen.getByText('Ana')).toBeInTheDocument())
    await userEvent.type(screen.getByLabelText(/Invite by email/i), 'new@example.com')
    await userEvent.click(screen.getByRole('button', { name: /Send invitation/i }))
    await waitFor(() => expect(screen.getByText(/does not send email/)).toBeInTheDocument())
    expect(screen.queryByText(/could not be emailed/)).not.toBeInTheDocument()

    await userEvent.type(screen.getByLabelText(/Invite by email/i), 'other@example.com')
    await userEvent.click(screen.getByRole('button', { name: /Send invitation/i }))
    await waitFor(() => expect(invite).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByText(/could not be emailed/)).toBeInTheDocument())
    expect(screen.getByText(/LUACH_APP_URL is http:\/\/localhost:8004/)).toBeInTheDocument()
  })
})
