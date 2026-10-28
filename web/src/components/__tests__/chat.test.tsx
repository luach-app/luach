import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChatTurn } from '../ChatTurn'
import { Composer } from '../Composer'
import { WidgetCard } from '../Widgets'
import { EventCard } from '../EventCard'
import { EmailChips } from '../EmailChips'
import { renderMarkdown } from '../../lib/markdown'
import { applyFrame, newTurn } from '../../lib/turns'
import type { StreamFrame } from '../../lib/types'
import * as api from '../../lib/api'

const ctx = { tz: 'America/New_York', locale: 'en', onOpenEvent: () => {} }

describe('a turn in the conversation', () => {
  it('shows what a person said and what luach answered', () => {
    const { rerender } = render(<ChatTurn turn={{ ...newTurn('user', 'what is on today?') }} {...ctx} onDecided={() => {}} />)
    expect(screen.getByText('what is on today?')).toBeInTheDocument()
    rerender(<ChatTurn turn={{ ...newTurn('assistant', 'Two things.') }} {...ctx} onDecided={() => {}} />)
    expect(screen.getByText('Two things.')).toBeInTheDocument()
  })

  it('marks an answer with the language luach answers this member in', () => {
    const { rerender } = render(<ChatTurn turn={{ ...newTurn('assistant', 'שני דברים.') }} {...ctx} lang="he" onDecided={() => {}} />)
    expect(screen.getByText('שני דברים.').closest('[lang]')).toHaveAttribute('lang', 'he')
    rerender(<ChatTurn turn={{ ...newTurn('assistant', 'Two things.') }} {...ctx} lang="" onDecided={() => {}} />)
    expect(screen.getByText('Two things.').closest('[lang]')).toBeNull()
  })

  it('says what it is doing while it works, and what failed', () => {
    const working = { ...newTurn('assistant', '', true), activity: [{ tool: 'list_events', kind: 'tool' as const, done: false }] }
    const { rerender } = render(<ChatTurn turn={working} {...ctx} onDecided={() => {}} />)
    expect(screen.getByText(/checking|calendar/i)).toBeInTheDocument()
    rerender(<ChatTurn turn={{ ...newTurn('assistant'), error: 'The model got stuck repeating itself.' }} {...ctx} onDecided={() => {}} />)
    expect(screen.getByText(/stuck repeating/)).toBeInTheDocument()
  })

  it('offers the yes or no on something held', async () => {
    const approve = vi.spyOn(api.control, 'approve').mockResolvedValue({ id: 'h1', status: 'approved' } as never)
    const turn = {
      ...newTurn('assistant', 'That one needs your yes.'),
      held: [{ id: 'h1', tool: 'update_event', summary: 'move the dentist', reason: ['mutation-existing'], status: 'pending' as const }],
    }
    render(<ChatTurn turn={turn} {...ctx} onDecided={() => {}} />)
    expect(screen.getByText(/move the dentist/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Approve/i }))
    await waitFor(() => expect(approve).toHaveBeenCalledWith('h1'))
  })
})

describe('the work trace', () => {
  const T0 = 1_000_000
  // The frames a real turn sends, folded the way the chat folds them, with a clock.
  const play = (frames: StreamFrame[], start = newTurn('assistant', '', true)) =>
    frames.reduce((t, f, i) => applyFrame(t, f, T0 + i * 400), start)
  const working = [
    { type: 'model', name: 'm' },
    { type: 'skill', name: 'repeating-events' },
    { type: 'tool_start', tool: 'list_events', args: { start_date: '2026-10-05', end_date: '2026-10-11' } },
    { type: 'tool_result', tool: 'list_events', result: { count: 3, events: [] } },
    { type: 'tool_start', tool: 'check_availability', args: { start: '2026-10-02T16:00', end: '2026-10-02T17:00' } },
  ] as StreamFrame[]

  it('lists each step as it happens, with what it found, and a clock', () => {
    vi.useFakeTimers({ now: T0 + 2400, toFake: ['Date', 'setInterval', 'clearInterval'] })
    try {
      render(<ChatTurn turn={play(working)} {...ctx} onDecided={() => {}} />)
      const trace = screen.getByTestId('work-trace')
      expect(within(trace).getByRole('button', { name: /Working…/ })).toHaveAttribute('aria-expanded', 'true')
      expect(within(trace).getByText('Following the guide: repeating events')).toBeInTheDocument()
      expect(within(trace).getByText('Reading the calendar · Mon 5 – Sun 11 Oct')).toBeInTheDocument()
      expect(within(trace).getByText('3 events')).toBeInTheDocument()
      expect(within(trace).getByText('Checking Fri 2 Oct, 16:00–17:00')).toBeInTheDocument()
      expect(within(trace).getByText('running:')).toBeInTheDocument()
      expect(screen.getByTestId('trace-timer')).toHaveTextContent('2.4s')
      act(() => vi.advanceTimersByTime(1000))
      expect(screen.getByTestId('trace-timer')).toHaveTextContent('3.4s')
      // The three dots are for a turn with nothing to show yet; this one has plenty.
      expect(screen.queryByLabelText('Thinking')).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('folds to one line once the answer starts, and stays there', () => {
    const answering = play([...working, { type: 'tool_result', tool: 'check_availability', result: { free: true } }, { type: 'token', text: 'You are free.' }] as StreamFrame[])
    render(<ChatTurn turn={answering} {...ctx} onDecided={() => {}} />)
    const toggle = within(screen.getByTestId('work-trace')).getByRole('button', { name: /Working… · 3 steps/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('free')).not.toBeInTheDocument()
    expect(screen.getByText('You are free.')).toBeInTheDocument()
  })

  it('sums up a finished turn as "Worked for …s · N steps", and opens on a click', async () => {
    const done = play([
      ...working,
      { type: 'tool_result', tool: 'check_availability', result: { free: false, clashes: [{ title: 'Swim' }] } },
      { type: 'token', text: 'You have Swim then.' },
      { type: 'done', reply: 'You have Swim then.', thread_id: 't', tool_calls: [], held: [], created: [] },
    ] as StreamFrame[])
    render(<ChatTurn turn={done} {...ctx} onDecided={() => {}} />)
    // Seven frames 400ms apart: 2.8s from the first to done.
    const toggle = screen.getByRole('button', { name: 'Worked for 2.8s · 3 steps' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('busy — clashes with Swim')).not.toBeInTheDocument()
    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('busy — clashes with Swim')).toBeInTheDocument()
    expect(screen.getByText('Following the guide: repeating events')).toBeInTheDocument()
    await userEvent.click(toggle)
    expect(screen.queryByText('busy — clashes with Swim')).not.toBeInTheDocument()
  })

  it('says one step, not one steps, and shows a step that failed', async () => {
    const done = play([
      { type: 'tool_start', tool: 'get_event', args: { event_id: 'x' } },
      { type: 'tool_result', tool: 'get_event', result: { error: 'no such event' } },
      { type: 'done', reply: 'I could not find it.', thread_id: 't', tool_calls: [], held: [], created: [] },
    ] as StreamFrame[])
    render(<ChatTurn turn={done} {...ctx} onDecided={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Worked for 0.8s · 1 step' }))
    expect(screen.getByText("couldn't: no such event")).toHaveClass('text-danger')
    expect(screen.getByText('failed:')).toBeInTheDocument()
  })

  it('shows reasoning inside the trace, and says it only thought when that is all it did', () => {
    const thinking = play([{ type: 'thinking', text: 'they mean this Saturday' }] as StreamFrame[])
    const { rerender } = render(<ChatTurn turn={thinking} {...ctx} onDecided={() => {}} />)
    const trace = screen.getByTestId('work-trace')
    expect(within(trace).getByText('Thinking')).toBeInTheDocument()
    expect(within(trace).getByText('they mean this Saturday')).toBeInTheDocument()
    const done = applyFrame(thinking, { type: 'done', reply: 'Saturday it is.' } as StreamFrame, T0 + 2100)
    rerender(<ChatTurn turn={done} {...ctx} onDecided={() => {}} />)
    expect(screen.getByRole('button', { name: 'Thought for 2.1s' })).toBeInTheDocument()
  })

  it('keeps the three dots until there is something to show', () => {
    render(<ChatTurn turn={play([{ type: 'model', name: 'm' }] as StreamFrame[])} {...ctx} onDecided={() => {}} />)
    expect(screen.getByLabelText('Thinking')).toBeInTheDocument()
    expect(screen.queryByTestId('work-trace')).not.toBeInTheDocument()
  })

  it('reads as text for a person who cannot see it', () => {
    const done = play([...working, { type: 'tool_result', tool: 'check_availability', result: { free: true } }, { type: 'done', reply: 'Free.' }] as StreamFrame[])
    const { container } = render(<ChatTurn turn={done} {...ctx} onDecided={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /Worked for/ }))
    const steps = within(container).getByRole('list', { name: 'Steps' })
    expect(within(steps).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Following the guide: repeating events',
      'done:Reading the calendar · Mon 5 – Sun 11 Oct3 events0.4s',
      'done:Checking Fri 2 Oct, 16:00–17:00free0.4s',
    ])
  })
})

describe('the widgets luach draws', () => {
  it('lists a day it was asked about', () => {
    render(
      <WidgetCard
        widget={{ kind: 'agenda', data: { range: 'Thu 17 Sep', count: 1, events: [{ id: 'e1', title: 'Dentist', when: '3:00 PM' }] } } as never}
        {...ctx}
      />,
    )
    expect(screen.getByText('Dentist')).toBeInTheDocument()
  })

  it('answers whether the time is free', () => {
    render(<WidgetCard widget={{ kind: 'availability', data: { free: true, start: '2026-09-17T15:00:00-04:00', end: '2026-09-17T16:00:00-04:00', clashes: [] } } as never} {...ctx} />)
    expect(screen.getByText(/free/i)).toBeInTheDocument()
  })

  it('shows one event on its own', () => {
    render(<WidgetCard widget={{ kind: 'event', data: { event: { id: 'e1', title: 'Piano', when: '2:00 PM' } } } as never} {...ctx} />)
    expect(screen.getByText('Piano')).toBeInTheDocument()
  })
})

describe('the composer', () => {
  it('sends what was typed and clears itself', async () => {
    const onSend = vi.fn()
    render(<Composer onSend={onSend} onError={() => {}} micAvailable={false} />)
    const box = screen.getByPlaceholderText(/Ask luach/i)
    await userEvent.type(box, 'add dentist tuesday{Enter}')
    expect(onSend).toHaveBeenCalledWith('add dentist tuesday')
    await waitFor(() => expect(box).toHaveValue(''))
  })

  it('sends nothing when there is nothing to send', async () => {
    const onSend = vi.fn()
    render(<Composer onSend={onSend} onError={() => {}} micAvailable={false} />)
    await userEvent.type(screen.getByPlaceholderText(/Ask luach/i), '   {Enter}')
    expect(onSend).not.toHaveBeenCalled()
  })

  it('offers the microphone only when the server transcribes and the browser can record', () => {
    const { rerender, unmount } = render(<Composer onSend={() => {}} onError={() => {}} micAvailable={false} />)
    expect(screen.queryByRole('button', { name: /Record a voice message/i })).not.toBeInTheDocument()
    // Still nothing: jsdom has no recorder, whatever the server says.
    rerender(<Composer onSend={() => {}} onError={() => {}} micAvailable />)
    expect(screen.queryByRole('button', { name: /Record a voice message/i })).not.toBeInTheDocument()
    unmount()

    // Give the browser both halves and it appears.
    vi.stubGlobal('MediaRecorder', class {})
    Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia: vi.fn() }, configurable: true })
    render(<Composer onSend={() => {}} onError={() => {}} micAvailable />)
    expect(screen.getByRole('button', { name: /Record a voice message/i })).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('takes a suggestion as its starting text', async () => {
    render(<Composer onSend={() => {}} onError={() => {}} micAvailable={false} seed={{ text: 'Am I free Friday?', nonce: 1 }} />)
    await waitFor(() => expect(screen.getByPlaceholderText(/Ask luach/i)).toHaveValue('Am I free Friday?'))
  })
})

describe('small pieces', () => {
  it('draws an event card that can be opened', async () => {
    const onClick = vi.fn()
    render(<EventCard event={{ id: 'e1', title: 'Dentist', start: '2026-09-17T15:00:00-04:00', end: '2026-09-17T16:00:00-04:00', location: 'Main St' } as never} tz="America/New_York" locale="en" onClick={onClick} />)
    await userEvent.click(screen.getByRole('button', { name: /Dentist/ }))
    expect(onClick).toHaveBeenCalled()
    expect(screen.getByText('Main St')).toBeInTheDocument()
  })

  it('collects addresses as chips and refuses nonsense', async () => {
    const onChange = vi.fn()
    const { rerender } = render(<EmailChips label="Invite" value={[]} onChange={onChange} />)
    const box = screen.getByLabelText('Invite')
    await userEvent.type(box, 'dana@example.com{Enter}')
    expect(onChange).toHaveBeenCalledWith(['dana@example.com'])

    await userEvent.clear(box)
    await userEvent.type(box, 'not-an-address{Enter}')
    expect(screen.getByText(/not an email address/i)).toBeInTheDocument()

    rerender(<EmailChips label="Invite" value={['dana@example.com']} onChange={onChange} />)
    await userEvent.click(screen.getByRole('button', { name: 'Remove dana@example.com' }))
    expect(onChange).toHaveBeenLastCalledWith([])
  })

  it('renders the little markdown luach writes', () => {
    render(<div>{renderMarkdown('**bold** and `code` and a list:\n- one\n- two')}</div>)
    expect(screen.getByText('bold')).toBeInTheDocument()
    expect(screen.getByText('code')).toBeInTheDocument()
    expect(screen.getByText('one')).toBeInTheDocument()
  })
})
