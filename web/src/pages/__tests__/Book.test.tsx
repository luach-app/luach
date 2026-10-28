import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Book } from '../Book'
import * as api from '../../lib/api'

const page = {
  host: 'Robin',
  slug: 'robin',
  timezone: 'America/New_York',
  slot_minutes: 30,
  note: 'Happy to talk.',
  location: 'Google Meet',
  days: [{ day: '2026-09-18', slots: [{ start: '2026-09-18T09:00:00-04:00', end: '2026-09-18T09:30:00-04:00' }] }],
}

beforeEach(() => {
  vi.spyOn(api.booking, 'page').mockResolvedValue(page as never)
})

describe('the page a stranger opens', () => {
  it('offers the free times and takes one', async () => {
    const take = vi.spyOn(api.booking, 'take').mockResolvedValue({
      booked: true,
      start: page.days[0]!.slots[0]!.start,
      end: page.days[0]!.slots[0]!.end,
      when: 'Fri 18 Sep 2026, 09:00–09:30',
      host: 'Robin',
      manage: 'https://luach.test/book/robin?manage=tok',
      confirmation_sent: true,
    } as never)
    render(<Book slug="robin" />)
    await waitFor(() => expect(screen.getByText('Book time with Robin')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /9:00/ }))
    await userEvent.type(screen.getByLabelText('Your name'), 'Dana Cohen')
    await userEvent.type(screen.getByLabelText('Your email'), 'dana@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Book it' }))

    await waitFor(() => expect(screen.getByText('You are booked in.')).toBeInTheDocument())
    // The visitor's own timezone travels with the booking.
    expect(take.mock.calls[0]?.[1]).toMatchObject({ name: 'Dana Cohen', email: 'dana@example.com' })
    expect(take.mock.calls[0]?.[1].timezone).toBeTruthy()
    // And they are told how to change it later.
    expect(screen.getByRole('link', { name: /Move or cancel/ })).toBeInTheDocument()
  })

  it('says so when the slot went in the meantime, and offers what is left', async () => {
    vi.spyOn(api.booking, 'take').mockRejectedValue(new api.ApiError(400, 'that time has just been taken; pick another'))
    render(<Book slug="robin" />)
    await waitFor(() => expect(screen.getByText('Book time with Robin')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /9:00/ }))
    await userEvent.type(screen.getByLabelText('Your name'), 'Dana')
    await userEvent.type(screen.getByLabelText('Your email'), 'dana@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Book it' }))
    await waitFor(() => expect(screen.getByText(/just been taken/)).toBeInTheDocument())
  })

  it('tells a visitor when there is nothing on offer', async () => {
    vi.spyOn(api.booking, 'page').mockResolvedValue({ ...page, days: [] } as never)
    render(<Book slug="robin" />)
    await waitFor(() => expect(screen.getByText(/No free slots/)).toBeInTheDocument())
  })

  it('says plainly when the link is not a booking page', async () => {
    vi.spyOn(api.booking, 'page').mockRejectedValue(new api.ApiError(404, 'there is no booking page at that link'))
    render(<Book slug="nobody" />)
    await waitFor(() => expect(screen.getByText(/no booking page/)).toBeInTheDocument())
  })
})

describe('the link in the confirmation mail', () => {
  const meeting = {
    host: 'Robin',
    slug: 'robin',
    timezone: 'America/New_York',
    slot_minutes: 30,
    name: 'Dana',
    start: '2026-09-18T09:00:00-04:00',
    when: 'Fri 18 Sep 2026, 09:00–09:30',
    cancelled: false,
    past: false,
    days: [{ day: '2026-09-18', slots: [{ start: '2026-09-18T10:00:00-04:00', end: '2026-09-18T10:30:00-04:00' }] }],
  }

  it('moves the meeting to another free time', async () => {
    vi.spyOn(api.booking, 'manage').mockResolvedValue(meeting as never)
    const move = vi.spyOn(api.booking, 'move').mockResolvedValue({ moved: true, start: meeting.days[0]!.slots[0]!.start, when: 'later' } as never)
    render(<Book slug="robin" manage="tok" />)
    await waitFor(() => expect(screen.getByText('Your meeting with Robin')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: 'Move it' }))
    await userEvent.click(screen.getByRole('button', { name: /10:00/ }))
    await waitFor(() => expect(move).toHaveBeenCalledWith('robin', 'tok', meeting.days[0]!.slots[0]!.start))
  })

  it('cancels it, but asks first', async () => {
    vi.spyOn(api.booking, 'manage').mockResolvedValue(meeting as never)
    const cancel = vi.spyOn(api.booking, 'cancel').mockResolvedValue({ cancelled: true } as never)
    render(<Book slug="robin" manage="tok" />)
    await waitFor(() => expect(screen.getByText('Your meeting with Robin')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: 'Cancel it' }))
    expect(cancel).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel for real' }))
    await waitFor(() => expect(screen.getByText('That meeting is cancelled.')).toBeInTheDocument())
  })

  it('offers nothing to do with a meeting already cancelled', async () => {
    vi.spyOn(api.booking, 'manage').mockResolvedValue({ ...meeting, cancelled: true } as never)
    render(<Book slug="robin" manage="tok" />)
    await waitFor(() => expect(screen.getByText('That meeting is cancelled.')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Move it' })).not.toBeInTheDocument()
  })
})
