import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CalendarFeed } from '../CalendarFeed'
import { lastRead } from '../../lib/feed'
import * as api from '../../lib/api'
import type { FeedLink, FeedStatus } from '../../lib/types'

const off: FeedStatus = { enabled: false, scope: 'household', created_at: null, last_read: null }
const on: FeedStatus = { enabled: true, scope: 'household', created_at: '2026-10-20T12:00:00+00:00', last_read: null }
const TOKEN = 'testfeedtokenAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
const made: FeedLink = { ...on, url: `https://luach.test/feed/${TOKEN}.ics`, webcal: `webcal://luach.test/feed/${TOKEN}.ics` }

afterEach(() => vi.restoreAllMocks())

describe('Settings › Calendar feed', () => {
  it('is off until turned on, and says what it holds and who can read it', async () => {
    vi.spyOn(api.calendarFeed, 'status').mockResolvedValue(off)
    render(<CalendarFeed />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Turn on' })).toBeInTheDocument())
    expect(screen.getByText('off')).toBeInTheDocument()
    expect(screen.getByText(/Never who is invited, nothing waiting for approval/)).toBeInTheDocument()
    expect(screen.getByText(/Anyone with the link can read the calendar/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reset link' })).not.toBeInTheDocument()
  })

  it('turns on with the chosen scope and shows the link once, to copy or subscribe to', async () => {
    vi.spyOn(api.calendarFeed, 'status').mockResolvedValue(off)
    const turnOn = vi.spyOn(api.calendarFeed, 'turnOn').mockResolvedValue({ ...made, scope: 'mine' })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<CalendarFeed />)
    await userEvent.click(await screen.findByLabelText(/Only mine/))
    await userEvent.click(screen.getByRole('button', { name: 'Turn on' }))
    expect(turnOn).toHaveBeenCalledWith('mine')
    expect(await screen.findByText(made.url)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Subscribe' })).toHaveAttribute('href', made.webcal)
    await userEvent.click(screen.getByRole('button', { name: 'Copy link' }))
    expect(writeText).toHaveBeenCalledWith(made.url)
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
    expect(screen.getByText(/this is the one time it is shown/)).toBeInTheDocument()
  })

  it('once on, it shows no link, and resetting asks first', async () => {
    vi.spyOn(api.calendarFeed, 'status').mockResolvedValue(on)
    const reset = vi.spyOn(api.calendarFeed, 'reset').mockResolvedValue(made)
    render(<CalendarFeed />)
    await waitFor(() => expect(screen.getByText(/On, not read by a calendar yet/)).toBeInTheDocument())
    expect(screen.queryByText(/luach\.test\/feed/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Reset link' }))
    expect(screen.getByText(/Calendars subscribed to the old one stop updating/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Keep it' }))
    expect(reset).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Reset link' }))
    await userEvent.click(screen.getAllByRole('button', { name: 'Reset link' }).at(-1)!)
    expect(reset).toHaveBeenCalledOnce()
    expect(await screen.findByText(made.url)).toBeInTheDocument()
  })

  it('turns off after asking, and the link goes from the screen', async () => {
    vi.spyOn(api.calendarFeed, 'status').mockResolvedValue(off)
    vi.spyOn(api.calendarFeed, 'turnOn').mockResolvedValue(made)
    const turnOff = vi.spyOn(api.calendarFeed, 'turnOff').mockResolvedValue(off)
    render(<CalendarFeed />)
    await userEvent.click(await screen.findByRole('button', { name: 'Turn on' }))
    await screen.findByText(made.url)
    await userEvent.click(screen.getByRole('button', { name: 'Turn off' }))
    await userEvent.click(screen.getAllByRole('button', { name: 'Turn off' }).at(-1)!)
    expect(turnOff).toHaveBeenCalledOnce()
    await waitFor(() => expect(screen.queryByText(made.url)).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Turn on' })).toBeInTheDocument()
  })

  it('changes what it shows on the same link, and goes back if the server refuses', async () => {
    vi.spyOn(api.calendarFeed, 'status').mockResolvedValue(on)
    const change = vi.spyOn(api.calendarFeed, 'change').mockResolvedValueOnce({ ...on, scope: 'mine' }).mockRejectedValueOnce(new Error('nope'))
    render(<CalendarFeed />)
    const mine = await screen.findByLabelText(/Only mine/)
    await userEvent.click(mine)
    expect(change).toHaveBeenCalledWith('mine')
    await waitFor(() => expect(mine).toBeChecked())
    await userEvent.click(screen.getByLabelText(/The whole household/))
    await waitFor(() => expect(mine).toBeChecked())
    expect(screen.getByRole('alert')).toHaveTextContent('nope')
  })

  it('says when a calendar last read it', () => {
    const now = Date.parse('2026-10-20T12:00:00Z')
    expect(lastRead(null, now)).toBe('not read by a calendar yet')
    expect(lastRead('2026-10-20T11:59:30+00:00', now)).toBe('read just now')
    expect(lastRead('2026-10-20T11:48:00+00:00', now)).toBe('read 12 min ago')
    expect(lastRead('2026-10-20T09:00:00+00:00', now)).toBe('read 3 h ago')
    expect(lastRead('2026-10-17T12:00:00+00:00', now)).toBe('read 3 d ago')
  })

  it('says why when it cannot load', async () => {
    vi.spyOn(api.calendarFeed, 'status').mockRejectedValue(new Error('offline'))
    render(<CalendarFeed />)
    expect(await screen.findByText('offline')).toBeInTheDocument()
  })
})
