import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { REVALIDATE_MS, forgetMonths, invalidateMonths, useMonthEvents } from '../monthCache'
import * as api from '../api'

function Probe({ ym = '2026-09' }: { ym?: string }) {
  const { events, error, reload } = useMonthEvents(ym, 'America/New_York')
  return (
    <div>
      <span data-testid="count">{events === null ? 'loading' : String(events.length)}</span>
      <span data-testid="error">{error}</span>
      <button onClick={reload}>retry</button>
    </div>
  )
}

const oneEvent = { events: [{ id: 'e1', title: 'Dentist', start: '2026-09-17T15:00:00-04:00', end: '2026-09-17T16:00:00-04:00', all_day: false }] }

beforeEach(() => {
  forgetMonths()
})

describe('the month a person is looking at', () => {
  it('asks the server once and serves the rest from memory', async () => {
    const list = vi.spyOn(api.calendar, 'list').mockResolvedValue(oneEvent as never)
    const first = render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
    first.unmount()
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
    expect(list).toHaveBeenCalledTimes(1)
  })

  it('asks again after something changes the calendar', async () => {
    const list = vi.spyOn(api.calendar, 'list').mockResolvedValue(oneEvent as never)
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
    act(() => invalidateMonths())
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2))
  })

  /** A tab open through an outage stayed empty for ever. */
  it('retries a month that failed when the tab is looked at again', async () => {
    const list = vi
      .spyOn(api.calendar, 'list')
      .mockRejectedValueOnce(new Error('luach is down'))
      .mockResolvedValue(oneEvent as never)
    render(<Probe />)
    // waitFor's default second was not enough under CI's coverage run, which failed
    // this at 1017ms while it passes in a fraction of that locally.
    await waitFor(() => expect(screen.getByTestId('error')).toHaveTextContent('luach is down'), { timeout: 5000 })
    expect(screen.getByTestId('count')).toHaveTextContent('loading')

    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'), { timeout: 5000 })
    expect(list.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('retries when the network comes back', async () => {
    // Driven by call count rather than by what has rendered: on a slower runner
    // the assertion on the error text raced the retry it was meant to observe,
    // and failed in CI while passing locally.
    let calls = 0
    const list = vi.spyOn(api.calendar, 'list').mockImplementation(async () => {
      calls += 1
      if (calls === 1) throw new Error('offline')
      return oneEvent as never
    })
    render(<Probe />)
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByTestId('error')).toHaveTextContent('offline'))

    act(() => {
      window.dispatchEvent(new Event('online'))
    })
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
  })

  it('retries when a person asks it to', async () => {
    const list = vi.spyOn(api.calendar, 'list').mockRejectedValueOnce(new Error('nope')).mockResolvedValue(oneEvent as never)
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('error')).toHaveTextContent('nope'))
    act(() => screen.getByText('retry').click())
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
    expect(list.mock.calls.length).toBeGreaterThanOrEqual(2)
  })
})

/**
 * A jump that happened: every assistant frame cleared the cache, the grid
 * fell back to skeletons and the whole calendar visibly rebuilt itself.
 */
describe('a month that is refreshing', () => {
  it('keeps showing the events it has while it asks again', async () => {
    vi.spyOn(api.calendar, 'list').mockResolvedValue(oneEvent as never)
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
    act(() => invalidateMonths())
    // No 'loading' in between: the grid never blanks.
    expect(screen.getByTestId('count')).toHaveTextContent('1')
  })

  it('shows nothing it should not after a sign-out', async () => {
    vi.spyOn(api.calendar, 'list').mockResolvedValue(oneEvent as never)
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
    act(() => forgetMonths())
    expect(screen.getByTestId('count')).toHaveTextContent('loading')
  })
})

/**
 * An approved hold, or a partner's change, appeared only after a hard reload: the
 * month was asked once and kept for good.
 */
describe('a month that someone else changed', () => {
  const twoEvents = { events: [...oneEvent.events, { ...oneEvent.events[0], id: 'e2', title: 'Swim' }] }

  function okFetch() {
    return vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ id: 'p1', status: 'approved' }), { status: 200 }))
  }

  it('is asked again after an approve or a deny made anywhere in the app', async () => {
    const list = vi.spyOn(api.calendar, 'list').mockResolvedValueOnce(oneEvent as never).mockResolvedValue(twoEvents as never)
    okFetch()
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
    await act(async () => {
      await api.control.approve('p1')
    })
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('2'))
    await act(async () => {
      await api.control.deny('p2')
    })
    await waitFor(() => expect(list).toHaveBeenCalledTimes(3))
  })

  it('is not asked again after a write that cannot touch the calendar', async () => {
    const list = vi.spyOn(api.calendar, 'list').mockResolvedValue(oneEvent as never)
    okFetch()
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
    await act(async () => {
      await api.push.unsubscribe('https://push.example/1')
    })
    expect(list).toHaveBeenCalledTimes(1)
  })

  it('is asked again when the tab is looked at, but not twice in a breath', async () => {
    let now = 1_000_000
    vi.spyOn(Date, 'now').mockImplementation(() => now)
    const list = vi.spyOn(api.calendar, 'list').mockResolvedValueOnce(oneEvent as never).mockResolvedValue(twoEvents as never)
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(list).toHaveBeenCalledTimes(1)
    now += 60_000
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('2'))
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('is asked again every little while the tab is visible, and not while hidden', async () => {
    let now = 1_000_000
    vi.spyOn(Date, 'now').mockImplementation(() => now)
    const ticks: (() => void)[] = []
    const realSetInterval = window.setInterval
    vi.spyOn(window, 'setInterval').mockImplementation(((fn: () => void, ms?: number) => {
      if (ms === REVALIDATE_MS) ticks.push(fn)
      return realSetInterval(() => {}, 1_000_000)
    }) as typeof window.setInterval)
    const list = vi.spyOn(api.calendar, 'list').mockResolvedValueOnce(oneEvent as never).mockResolvedValue(twoEvents as never)
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
    expect(REVALIDATE_MS).toBeGreaterThanOrEqual(60_000)
    expect(REVALIDATE_MS).toBeLessThanOrEqual(120_000)
    expect(ticks.length).toBe(1)

    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    now += REVALIDATE_MS
    act(() => ticks[0]!())
    expect(list).toHaveBeenCalledTimes(1)

    visibility.mockReturnValue('visible')
    act(() => ticks[0]!())
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('2'))
  })

  it('keeps one request in flight per month, and a load that predates a change does not stick', async () => {
    let release: (v: unknown) => void = () => {}
    const list = vi
      .spyOn(api.calendar, 'list')
      .mockImplementationOnce(() => new Promise((r) => (release = r)) as never)
      .mockResolvedValue(twoEvents as never)
    render(<Probe />)
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1))
    // Three changes while the first load is out: no second request yet.
    act(() => invalidateMonths())
    act(() => invalidateMonths())
    act(() => invalidateMonths())
    expect(list).toHaveBeenCalledTimes(1)
    // The old load lands; exactly one more is asked, and its answer is what shows.
    await act(async () => {
      release(oneEvent)
    })
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('2'))
    expect(list).toHaveBeenCalledTimes(2)
  })
})
