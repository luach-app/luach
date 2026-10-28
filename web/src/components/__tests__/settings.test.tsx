import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Booking } from '../Booking'
import { BusyCalendars } from '../BusyCalendars'
import { Reminders } from '../Reminders'
import { Emails } from '../Emails'
import * as api from '../../lib/api'
import { invalidateHousehold } from '../../lib/household'
import { member } from '../../test/harness'

const settings = {
  enabled: false,
  slug: 'robin',
  slot_minutes: 30,
  max_per_day: 2,
  buffer_minutes: 15,
  lead_hours: 12,
  horizon_days: 21,
  title: 'Meeting with {name}',
  location: '',
  note: '',
  calendar_id: '',
  notify_host: true,
  conferencing: 'none',
  hours: { mon: [['09:00', '17:00']], tue: [], wed: [], thu: [], fri: [], sat: [], sun: [] },
  link: 'https://luach.test/book/robin',
  timezone: 'America/New_York',
  zoom_ready: true,
}

beforeEach(() => {
  invalidateHousehold()
  vi.spyOn(api.household, 'calendars').mockResolvedValue({ available: [], calendars: ['home'], default_calendar: 'home', default_attendees: [] } as never)
})

describe('Meetings with me', () => {
  it('publishes the link and sends only what the server owns', async () => {
    vi.spyOn(api.booking, 'mine').mockResolvedValue(settings as never)
    vi.spyOn(api.booking, 'upcoming').mockResolvedValue({ bookings: [] } as never)
    const update = vi.spyOn(api.booking, 'update').mockResolvedValue({ ...settings, enabled: true } as never)
    render(<Booking tz="America/New_York" locale="en" />)
    await waitFor(() => expect(screen.getByLabelText('The link is live')).toBeInTheDocument())

    await userEvent.click(screen.getByLabelText('The link is live'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(update).toHaveBeenCalled())
    const sent = update.mock.calls[0]?.[0] as Record<string, unknown>
    expect(sent.enabled).toBe(true)
    expect(sent).not.toHaveProperty('link')
    expect(sent).not.toHaveProperty('zoom_ready')
  })

  it('offers Zoom only when the server has credentials for it', async () => {
    vi.spyOn(api.booking, 'mine').mockResolvedValue({ ...settings, zoom_ready: false } as never)
    vi.spyOn(api.booking, 'upcoming').mockResolvedValue({ bookings: [] } as never)
    render(<Booking tz="America/New_York" locale="en" />)
    await waitFor(() => expect(screen.getByLabelText('Where you meet')).toBeInTheDocument())
    const zoom = within(screen.getByLabelText('Where you meet')).getByRole('option', { name: /Zoom/ })
    expect(zoom).toBeDisabled()
  })

  it('cancels a booking from the host’s side, after asking', async () => {
    vi.spyOn(api.booking, 'mine').mockResolvedValue(settings as never)
    vi.spyOn(api.booking, 'upcoming').mockResolvedValue({
      bookings: [{ start: '2026-09-18T09:00:00-04:00', day: '2026-09-18', name: 'Dana', email: 'dana@example.com', note: '', event_id: 'e9' }],
    } as never)
    const remove = vi.spyOn(api.calendar, 'remove').mockResolvedValue({ ok: true } as never)
    render(<Booking tz="America/New_York" locale="en" />)
    await waitFor(() => expect(screen.getByText('Dana')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(remove).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel it' }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith('e9'))
    await waitFor(() => expect(screen.queryByText('Dana')).not.toBeInTheDocument())
  })
})

describe('the work calendar', () => {
  const source = { id: 1, name: 'Acme', url: 'https://example.com/w.ics', enabled: true, show_in_agenda: true, last_fetched: null, last_error: '', blocks: 4 }

  it('adds a feed and shows what it read', async () => {
    vi.spyOn(api.busy, 'list').mockResolvedValue({ sources: [] } as never)
    const add = vi.spyOn(api.busy, 'add').mockResolvedValue({ sources: [source] } as never)
    render(<BusyCalendars />)
    await waitFor(() => expect(screen.getByText('No work calendar yet.')).toBeInTheDocument())

    await userEvent.type(screen.getByLabelText('Name'), 'Acme')
    await userEvent.type(screen.getByLabelText('Feed address (ICS)'), 'https://example.com/w.ics')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(add).toHaveBeenCalledWith({ name: 'Acme', url: 'https://example.com/w.ics' }))
    await waitFor(() => expect(screen.getByText('4 busy')).toBeInTheDocument())
  })

  it('says when a feed could not be read, and keeps it visible', async () => {
    vi.spyOn(api.busy, 'list').mockResolvedValue({ sources: [{ ...source, last_error: 'TimeoutError: their server' }] } as never)
    render(<BusyCalendars />)
    await waitFor(() => expect(screen.getByText('could not read')).toBeInTheDocument())
    expect(screen.getByText(/TimeoutError/)).toBeInTheDocument()
  })

  it('turns blocking and showing on and off separately', async () => {
    vi.spyOn(api.busy, 'list').mockResolvedValue({ sources: [source] } as never)
    const update = vi.spyOn(api.busy, 'update').mockResolvedValue({ sources: [{ ...source, show_in_agenda: false }] } as never)
    render(<BusyCalendars />)
    await waitFor(() => expect(screen.getByLabelText('Show in the agenda')).toBeChecked())
    await userEvent.click(screen.getByLabelText('Show in the agenda'))
    await waitFor(() => expect(update).toHaveBeenCalledWith(1, { show_in_agenda: false }))
  })
})

describe('reminders', () => {
  it('saves the three choices as numbers', async () => {
    vi.spyOn(api.reminders, 'get').mockResolvedValue({ lead_minutes: 0, evening_hour: -1, weekly_day: -1, weekly_hour: 18, by_email: false } as never)
    const update = vi.spyOn(api.reminders, 'update').mockResolvedValue({ lead_minutes: 60, evening_hour: 20, weekly_day: 6, weekly_hour: 18, by_email: true } as never)
    render(<Reminders tz="America/New_York" />)
    await waitFor(() => expect(screen.getByLabelText('Before something starts')).toBeInTheDocument())

    await userEvent.selectOptions(screen.getByLabelText('Before something starts'), '60')
    await userEvent.selectOptions(screen.getByLabelText('The evening before, a list of tomorrow'), '20')
    await userEvent.selectOptions(screen.getByLabelText('The week ahead, on'), '6')
    await userEvent.click(screen.getByLabelText('Email them to me as well'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(update).toHaveBeenCalled())
    expect(update.mock.calls[0]?.[0]).toMatchObject({ lead_minutes: 60, evening_hour: 20, weekly_day: 6, by_email: true })
  })
})

describe('the addresses a member holds', () => {
  it('marks an unconfirmed one and offers to send the link again', async () => {
    vi.spyOn(api.emails, 'list').mockResolvedValue({
      primary: 'robin@example.com',
      emails: [
        { email: 'robin@example.com', added_at: '2026-01-01T00:00:00', verified: true },
        { email: 'work@corp.com', added_at: '2026-09-01T00:00:00', verified: false },
      ],
    } as never)
    const resend = vi.spyOn(api.emails, 'resend').mockResolvedValue({ sent: true, email: 'work@corp.com' } as never)
    render(<Emails member={member} onMember={() => {}} />)
    await waitFor(() => expect(screen.getByText('unconfirmed')).toBeInTheDocument())
    expect(screen.getByText('primary')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Resend' }))
    await waitFor(() => expect(resend).toHaveBeenCalledWith('work@corp.com'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Sent' })).toBeInTheDocument())
  })
})
