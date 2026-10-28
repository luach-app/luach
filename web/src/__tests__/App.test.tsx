import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import * as api from '../lib/api'
import { invalidateHousehold } from '../lib/household'
import { invalidateMonths } from '../lib/monthCache'
import { member } from '../test/harness'

const go = (url: string) => window.history.replaceState(null, '', url)

beforeEach(() => {
  go('/')
  invalidateHousehold()
  invalidateMonths()
  vi.spyOn(api.calendar, 'list').mockResolvedValue({ events: [], timezone: 'America/New_York', start: '', end: '' } as never)
  vi.spyOn(api.household, 'calendars').mockResolvedValue({ available: [], calendars: ['home'], default_calendar: 'home', default_attendees: [] } as never)
  vi.spyOn(api.control, 'pending').mockResolvedValue({ pending: [] } as never)
  vi.spyOn(api.voice, 'status').mockResolvedValue({ available: false } as never)
  vi.spyOn(api.threads, 'get').mockResolvedValue({ turns: [] } as never)
})

describe('what a person lands on', () => {
  it('shows the gate when nobody is signed in', async () => {
    vi.spyOn(api.auth, 'status').mockResolvedValue({ users_exist: true, authenticated: false } as never)
    render(<App />)
    await waitFor(() => expect(screen.getByLabelText(/username|email/i)).toBeInTheDocument())
  })

  it('names the household on the gate as the server names it', async () => {
    vi.spyOn(api.auth, 'status').mockResolvedValue({ users_exist: true, authenticated: false, household: 'Rivera' } as never)
    render(<App />)
    await waitFor(() => expect(screen.getByText('The Rivera household calendar.')).toBeInTheDocument())
  })

  it('opens on the calendar with the navigation across the top, and no Ask tab', async () => {
    vi.spyOn(api.auth, 'status').mockResolvedValue({ users_exist: true, authenticated: true, member } as never)
    render(<App />)
    await waitFor(() => expect(screen.getByRole('grid', { name: 'Month' })).toBeInTheDocument())

    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Agenda' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ask' })).not.toBeInTheDocument()
  })

  it('moves between the sections from the top bar', async () => {
    vi.spyOn(api.auth, 'status').mockResolvedValue({ users_exist: true, authenticated: true, member } as never)
    render(<App />)
    await waitFor(() => expect(screen.getByRole('grid', { name: 'Month' })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Pending' }))
    await waitFor(() => expect(screen.queryByRole('grid', { name: 'Month' })).not.toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Agenda' }))
    await waitFor(() => expect(screen.getByRole('grid', { name: 'Month' })).toBeInTheDocument())
  })
})

describe('the links that bypass the gate', () => {
  it('opens a booking page for whoever has the link, signed in or not', async () => {
    go('/book/robin')
    vi.spyOn(api.auth, 'status').mockResolvedValue({ users_exist: true, authenticated: false } as never)
    vi.spyOn(api.booking, 'page').mockResolvedValue({
      host: 'Robin',
      slug: 'robin',
      timezone: 'America/New_York',
      slot_minutes: 30,
      note: '',
      location: '',
      days: [],
    } as never)
    render(<App />)
    await waitFor(() => expect(screen.getByText('Book time with Robin')).toBeInTheDocument())
  })

  it('confirms an address without asking anyone to sign in', async () => {
    go('/?verify=tok')
    vi.spyOn(api.auth, 'status').mockResolvedValue({ users_exist: true, authenticated: false } as never)
    const verify = vi.spyOn(api.emails, 'verify').mockResolvedValue({ email: 'work@corp.com', kind: 'alias' } as never)
    render(<App />)
    await waitFor(() => expect(screen.getByText('Address confirmed')).toBeInTheDocument())
    expect(verify).toHaveBeenCalledWith('tok')
    expect(screen.getByText('work@corp.com')).toBeInTheDocument()
  })

  it('says so when a confirmation link has expired', async () => {
    go('/?verify=old')
    vi.spyOn(api.auth, 'status').mockResolvedValue({ users_exist: true, authenticated: false } as never)
    vi.spyOn(api.emails, 'verify').mockRejectedValue(new api.ApiError(400, 'this confirmation link is no longer valid'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('That link has expired')).toBeInTheDocument())
  })
})

describe('after an upgrade', () => {
  it('says a new version is ready, and reloads when asked', async () => {
    document.head.innerHTML = '<script type="module" src="/assets/index-A1.js"></script>'
    vi.spyOn(api.auth, 'status').mockResolvedValue({ users_exist: true, authenticated: true, member } as never)
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ ok: true, build: '/assets/index-B2.js' }), { status: 200 }))
    const reload = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, reload } as Location)
    render(<App />)
    const banner = await screen.findByText('A new version is ready.')
    await userEvent.click(within(banner.parentElement!).getByRole('button', { name: 'Reload' }))
    expect(reload).toHaveBeenCalled()
    document.head.innerHTML = ''
  })
})

/** lang="he" on the English page had a screen reader read every label in a Hebrew voice. */
describe('the page’s language', () => {
  it('is the app’s English, left to right, whatever luach answers in', async () => {
    vi.spyOn(api.auth, 'status').mockResolvedValue({ users_exist: true, authenticated: true, member: { ...member, language: 'he' } } as never)
    render(<App />)
    await waitFor(() => expect(screen.getByRole('grid', { name: 'Month' })).toBeInTheDocument())
    expect(document.documentElement).toHaveAttribute('lang', 'en')
    expect(document.documentElement).toHaveAttribute('dir', 'ltr')
  })
})
