import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Agenda } from '../Agenda'
import * as api from '../../lib/api'
import * as sse from '../../lib/sse'
import { invalidateMonths } from '../../lib/monthCache'
import { invalidateHousehold } from '../../lib/household'
import { event, freezeTime, member, phoneScreen, wideScreen } from '../../test/harness'

beforeEach(() => {
  freezeTime()
  invalidateMonths()
  invalidateHousehold()
  vi.spyOn(api.calendar, 'list').mockResolvedValue({ events: [event()], timezone: 'America/New_York', start: '', end: '' } as never)
  vi.spyOn(api.household, 'calendars').mockResolvedValue({ available: [], calendars: ['home'], default_calendar: 'home', default_attendees: [] } as never)
  vi.spyOn(api.voice, 'status').mockResolvedValue({ available: false } as never)
  vi.spyOn(api.threads, 'get').mockResolvedValue({ turns: [] } as never)
})

afterEach(() => vi.useRealTimers())

describe('one screen, on a wide display', () => {
  it('shows the calendar and the assistant together, no navigation in between', async () => {
    wideScreen()
    render(<Agenda member={member} onHoldsChanged={() => {}} />)
    await waitFor(() => expect(screen.getByRole('grid', { name: 'Month' })).toBeInTheDocument())

    const rail = screen.getByRole('complementary', { name: 'Ask luach' })
    expect(within(rail).getByText('Ask luach')).toBeInTheDocument()
    expect(within(rail).getByPlaceholderText(/Ask luach/i)).toBeInTheDocument()
    // The rail is the conversation and nothing else: the selected day belongs
    // under the grid it was picked on, not stacked above the chat.
    expect(within(rail).queryByText('Dentist')).not.toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Selected day' })).getByText('Dentist')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ask luach' })).not.toBeInTheDocument()
  })

  it('puts what the assistant creates onto the grid without a reload', async () => {
    wideScreen()
    const list = vi.spyOn(api.calendar, 'list')
    vi.spyOn(sse, 'streamAgent').mockImplementation(async (_body, onFrame) => {
      onFrame({ type: 'tool_start', tool: 'create_event', args: {} } as never)
      onFrame({ type: 'tool_result', tool: 'create_event', result: { created: { id: 'e2', title: 'Piano' } } } as never)
      onFrame({ type: 'done', reply: 'Added Piano.', created: [{ id: 'e2', title: 'Piano' }] } as never)
    })
    render(<Agenda member={member} onHoldsChanged={() => {}} />)
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1))

    await userEvent.type(screen.getByPlaceholderText(/Ask luach/i), 'add piano tuesday{Enter}')
    await waitFor(() => expect(screen.getByText('Added Piano.')).toBeInTheDocument())
    // The month was invalidated and asked for again: the grid beside it is fresh.
    await waitFor(() => expect(list.mock.calls.length).toBeGreaterThan(1))
  })

  it('says so when the stream ends without the turn ending', async () => {
    // A hop that gave up on a quiet socket used to leave half an answer sitting
    // there looking finished. Only a `done` or an `error` frame finishes a turn.
    wideScreen()
    vi.spyOn(sse, 'streamAgent').mockImplementation(async (_body, onFrame) => {
      onFrame({ type: 'session', thread_id: 'th1' } as never)
      onFrame({ type: 'token', text: 'You have ' } as never)
    })
    render(<Agenda member={member} onHoldsChanged={() => {}} />)

    await userEvent.type(screen.getByPlaceholderText(/Ask luach/i), 'what is on?{Enter}')
    await waitFor(() => expect(screen.getByText(/connection dropped/i)).toBeInTheDocument())
    expect(screen.getByText(/You have/)).toBeInTheDocument()
  })
})

describe('one screen, on a phone', () => {
  it('gives the month the screen and keeps the assistant a tap away', async () => {
    phoneScreen()
    render(<Agenda member={member} onHoldsChanged={() => {}} />)
    await waitFor(() => expect(screen.getByRole('grid', { name: 'Month' })).toBeInTheDocument())

    expect(screen.queryByRole('complementary', { name: 'Ask luach' })).not.toBeInTheDocument()
    const bubble = screen.getByRole('button', { name: 'Ask luach' })
    expect(screen.queryByPlaceholderText(/Ask luach/i)).not.toBeInTheDocument()

    await userEvent.click(bubble)
    expect(screen.getByPlaceholderText(/Ask luach/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByPlaceholderText(/Ask luach/i)).not.toBeInTheDocument())
  })
})

describe('the two views', () => {
  it('remembers whether a person reads the month or what is upcoming', async () => {
    wideScreen()
    const { unmount } = render(<Agenda member={member} onHoldsChanged={() => {}} />)
    await waitFor(() => expect(screen.getByRole('grid', { name: 'Month' })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('tab', { name: 'Upcoming' }))
    await waitFor(() => expect(screen.queryByRole('grid', { name: 'Month' })).not.toBeInTheDocument())
    unmount()

    render(<Agenda member={member} onHoldsChanged={() => {}} />)
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Upcoming' })).toHaveAttribute('aria-selected', 'true'))
  })
})

describe('giving the calendar the screen', () => {
  it('closes the assistant and offers it back, remembering which', async () => {
    wideScreen()
    const { unmount } = render(<Agenda member={member} onHoldsChanged={() => {}} />)
    await waitFor(() => expect(screen.getByRole('complementary', { name: 'Ask luach' })).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: 'Close the assistant' }))
    expect(screen.queryByRole('complementary', { name: 'Ask luach' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Open the assistant' }))
    expect(screen.getByRole('complementary', { name: 'Ask luach' })).toBeInTheDocument()

    // Closed stays closed across a visit to another page and back.
    await userEvent.click(screen.getByRole('button', { name: 'Close the assistant' }))
    unmount()
    render(<Agenda member={member} onHoldsChanged={() => {}} />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Open the assistant' })).toBeInTheDocument())
  })

  it('asks the browser for the whole screen, and follows it back out', async () => {
    wideScreen()
    const request = vi.fn().mockResolvedValue(undefined)
    const exit = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(document.documentElement, 'requestFullscreen', { configurable: true, value: request })
    Object.defineProperty(document, 'exitFullscreen', { configurable: true, value: exit })

    render(<Agenda member={member} onHoldsChanged={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Full screen' }))
    expect(request).toHaveBeenCalled()

    // The browser says what state it is in; the button follows rather than guesses.
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: document.documentElement })
    document.dispatchEvent(new Event('fullscreenchange'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Leave full screen' })).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: 'Leave full screen' }))
    expect(exit).toHaveBeenCalled()

    // Esc leaves without telling us first; the button must not be left lying.
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
    document.dispatchEvent(new Event('fullscreenchange'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Full screen' })).toBeInTheDocument())
  })
})
