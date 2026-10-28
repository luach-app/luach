import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Board, Today } from '../Board'
import { boardApi, columnsOf, inkOn, storedToken, storeToken, Unpaired, type BoardDay } from '../../lib/board'
import type { Task } from '../../lib/types'

const chore = (over: Partial<Task> = {}): Task => ({ id: 7, title: 'Feed the cat', person: 'lily', due: '', days: ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'], notes: '', done: false, overdue: false, chore: true, ...over })

const day = (over: Partial<BoardDay> = {}): BoardDay => ({
  board: 'Kitchen',
  timezone: 'America/New_York',
  now: '2026-09-22T08:00:00-04:00',
  day: '2026-09-22',
  people: [
    { key: 'lily', name: 'Lily', hex: '#f4511e', kind: 'kid' },
    { key: 'ruby', name: 'Ruby', hex: '#33b679', kind: 'kid' },
  ],
  events: [
    { id: 'e1', title: 'Math test', start: '2026-09-22T09:00:00-04:00', end: '2026-09-22T10:00:00-04:00', all_day: false, location: '', leader: 'lily' },
    { id: 'e2', title: 'Dinner at Oma’s', start: '2026-09-22T18:00:00-04:00', end: '2026-09-22T20:00:00-04:00', all_day: false, location: '', leader: '' },
  ],
  tomorrow: [],
  tasks: [chore()],
  ...over,
})

beforeEach(() => {
  storeToken('')
  vi.spyOn(boardApi, 'signedIn').mockResolvedValue(false)
  vi.spyOn(boardApi, 'build').mockResolvedValue('')
})
afterEach(() => {
  vi.useRealTimers()
  storeToken('')
})

describe('an unpaired screen', () => {
  it('shows a code and becomes a board once the owner types it', async () => {
    vi.spyOn(boardApi, 'pair').mockResolvedValue({ code: 'K7P3QX', secret: 's', expires_at: '' })
    const collect = vi
      .spyOn(boardApi, 'collect')
      .mockResolvedValueOnce({ waiting: true })
      .mockResolvedValueOnce({ token: 'board-token' })
    vi.spyOn(boardApi, 'today').mockResolvedValue(day())
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<Board />)
    expect(await screen.findByText('K7P3QX')).toBeInTheDocument()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_100)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_100)
    })
    await waitFor(() => expect(collect).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('Math test')).toBeInTheDocument()
    expect(storedToken()).toBe('board-token')
  })
})

describe('a paired board', () => {
  it('shows each person’s day in their column, and the family’s things apart', async () => {
    storeToken('t')
    vi.spyOn(boardApi, 'today').mockResolvedValue(day())
    render(<Board />)
    const lily = await screen.findByRole('region', { name: 'Lily' })
    expect(within(lily).getByText('Math test')).toBeInTheDocument()
    expect(within(lily).getByRole('checkbox', { name: /Feed the cat/ })).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Ruby' })).getByText('A free day.')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Family' })).getByText('Dinner at Oma’s')).toBeInTheDocument()
  })

  it('a tap at the wall ticks the task', async () => {
    storeToken('t')
    vi.spyOn(boardApi, 'today').mockResolvedValue(day())
    const tick = vi.spyOn(boardApi, 'tick').mockResolvedValue(chore({ done: true }))
    render(<Board />)
    const box = await screen.findByRole('checkbox', { name: /Feed the cat/ })
    await userEvent.click(box)
    expect(box).toHaveAttribute('aria-checked', 'true')
    expect(tick).toHaveBeenCalledWith('t', 7, true, '')
  })

  it('a board the owner removed goes back to showing a code', async () => {
    storeToken('t')
    vi.spyOn(boardApi, 'today').mockRejectedValue(new Unpaired('401'))
    vi.spyOn(boardApi, 'pair').mockResolvedValue({ code: 'NEWCOD', secret: 's', expires_at: '' })
    vi.spyOn(boardApi, 'collect').mockResolvedValue({ waiting: true })
    render(<Board />)
    expect(await screen.findByText('NEWCOD')).toBeInTheDocument()
    expect(storedToken()).toBe('')
  })

  it('says so when it cannot reach luach, and keeps the last day', async () => {
    storeToken('t')
    const today = vi.spyOn(boardApi, 'today').mockResolvedValueOnce(day())
    render(<Board />)
    await screen.findByText('Math test')
    today.mockRejectedValue(new Error('offline'))
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(await screen.findByText(/offline/)).toBeInTheDocument()
    expect(screen.getByText('Math test')).toBeInTheDocument()
  })
})

describe('a member on their own device', () => {
  it('sees the board at /board with nothing to pair', async () => {
    vi.spyOn(boardApi, 'signedIn').mockResolvedValue(true)
    const today = vi.spyOn(boardApi, 'today').mockResolvedValue(day({ board: '', viewer: 'Robin' }))
    const pair = vi.spyOn(boardApi, 'pair')
    render(<Board />)
    expect(await screen.findByText('Math test')).toBeInTheDocument()
    expect(today).toHaveBeenCalledWith('', '')
    expect(pair).not.toHaveBeenCalled()
  })

  it('can still make the screen a wall board', async () => {
    vi.spyOn(boardApi, 'signedIn').mockResolvedValue(true)
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ board: '' }))
    vi.spyOn(boardApi, 'pair').mockResolvedValue({ code: 'WALL22', secret: 's', expires_at: '' })
    vi.spyOn(boardApi, 'collect').mockResolvedValue({ waiting: true })
    render(<Board />)
    await userEvent.click(await screen.findByRole('button', { name: 'Make this screen a wall board' }))
    expect(await screen.findByText('WALL22')).toBeInTheDocument()
  })

  it('inside the app it offers the full screen, and ticks as the member', async () => {
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ board: '' }))
    const tick = vi.spyOn(boardApi, 'tick').mockResolvedValue(chore({ done: true }))
    render(<Today token="" embedded onUnpaired={() => {}} />)
    expect(await screen.findByRole('link', { name: 'Open full screen' })).toHaveAttribute('href', '/board')
    await userEvent.click(screen.getByRole('checkbox', { name: /Feed the cat/ }))
    expect(tick).toHaveBeenCalledWith('', 7, true, '')
  })
})

describe('columns', () => {
  it('leaves out the family column when nothing is shared', () => {
    const cols = columnsOf(day({ events: [], tasks: [] }))
    expect(cols.map((c) => c.name)).toEqual(['Lily', 'Ruby'])
  })
})

describe('columns where the viewer can edit', () => {
  it('keep the family column, so something can be added for everyone', () => {
    const cols = columnsOf(day({ events: [], tasks: [] }), true)
    expect(cols.map((c) => c.name)).toEqual(['Lily', 'Ruby', 'Family'])
  })
})

describe('ink on a person’s colour', () => {
  it('is black on light colours and white on dark ones', () => {
    expect(inkOn('#f6bf26')).toBe('#000000') // banana
    expect(inkOn('#ffffff')).toBe('#000000')
    expect(inkOn('#fff')).toBe('#000000')
    expect(inkOn('#3f51b5')).toBe('#ffffff') // blueberry
    expect(inkOn('#000')).toBe('#ffffff')
    expect(inkOn('#D50000')).toBe('#ffffff') // tomato
  })

  it('is white for anything that is not a colour it can read', () => {
    expect(inkOn('')).toBe('#ffffff')
    expect(inkOn('var(--accent)')).toBe('#ffffff')
  })
})

describe('an event for several people', () => {
  it('is in each of their columns, and not in the family one', () => {
    const d = {
      board: '', timezone: 'America/New_York', now: '', day: '2026-09-24', tomorrow: [], tasks: [],
      people: [
        { key: 'lily', name: 'Lily', hex: '#f00', kind: 'kid' as const },
        { key: 'ruby', name: 'Ruby', hex: '#0f0', kind: 'kid' as const },
      ],
      events: [{ id: 'b', title: 'Breakfast', start: '', end: '', all_day: false, location: '', leader: 'ruby', leaders: ['ruby', 'lily'] }],
    }
    const cols = columnsOf(d)
    expect(cols.map((c) => [c.name, c.events.map((e) => e.title)])).toEqual([
      ['Lily', ['Breakfast']],
      ['Ruby', ['Breakfast']],
    ])
  })
})

describe('a touch board', () => {
  const add = vi.fn()
  beforeEach(() => {
    add.mockReset()
    vi.spyOn(boardApi, 'tasks').mockReturnValue({ add, update: vi.fn(), remove: vi.fn() } as never)
  })

  it('a + in Lily’s column adds a task that is hers', async () => {
    add.mockResolvedValue(chore({ title: 'Pack the gym bag' }))
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ board: '', viewer: 'Robin', can_edit: true }))
    render(<Today token="" onUnpaired={() => {}} embedded />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add for Lily' }))
    await userEvent.click(screen.getByRole('button', { name: 'Task' }))
    expect(screen.getByRole('radio', { name: 'Lily', checked: true })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('What'), 'Pack the gym bag')
    await userEvent.click(screen.getByRole('button', { name: 'Add task' }))
    await waitFor(() => expect(add).toHaveBeenCalledWith({ title: 'Pack the gym bag', person: 'lily', days: [], due: '' }))
  })

  it('a + for an event opens the form already for that person', async () => {
    const api = await import('../../lib/api')
    vi.spyOn(api.family, 'get').mockResolvedValue({
      people: [
        { key: 'lily', name: 'Lily', color: '6', hex: '#f4511e', kind: 'kid', email: '', user_id: null, position: 0 },
        { key: 'ruby', name: 'Ruby', color: '2', hex: '#33b679', kind: 'kid', email: '', user_id: null, position: 1 },
      ],
      colors: [],
    } as never)
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ board: '', viewer: 'Robin', can_edit: true }))
    render(<Today token="" onUnpaired={() => {}} embedded />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add for Ruby' }))
    await userEvent.click(screen.getByRole('button', { name: 'Event' }))
    expect(await screen.findByRole('button', { name: 'Ruby', pressed: true })).toBeInTheDocument()
  })

  it('a task opens, and can be handed to someone else', async () => {
    const update = vi.fn().mockResolvedValue(chore({ person: 'ruby' }))
    vi.spyOn(boardApi, 'tasks').mockReturnValue({ add, update, remove: vi.fn() } as never)
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ can_edit: true }))
    render(<Today token="t" onUnpaired={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Open Feed the cat' }))
    await userEvent.click(screen.getByRole('radio', { name: 'Ruby' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(update).toHaveBeenCalledWith(7, expect.objectContaining({ person: 'ruby' })))
  })

  it('pages to another day with the chips, and comes back', async () => {
    const today = vi.spyOn(boardApi, 'today').mockImplementation(async (_t, d = '') => day({ day: d || '2026-09-22', today: '2026-09-22' }))
    render(<Today token="t" onUnpaired={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Tomorrow' }))
    await waitFor(() => expect(today).toHaveBeenLastCalledWith('t', '2026-09-23'))
    await userEvent.click(await screen.findByRole('button', { name: 'Back to today' }))
    await waitFor(() => expect(today).toHaveBeenLastCalledWith('t', ''))
  })

  it('a screen that only shows the day has no + and no editing', async () => {
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ can_edit: false }))
    render(<Today token="t" onUnpaired={() => {}} />)
    await screen.findByRole('region', { name: 'Lily' })
    expect(screen.queryByRole('button', { name: /^Add for/ })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Open Feed the cat' }))
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
  })

  it('a + on a light colour is dark, and the family’s + wears the accent’s own ink', async () => {
    vi.spyOn(boardApi, 'today').mockResolvedValue(
      day({ can_edit: true, events: [], tasks: [], people: [{ key: 'lily', name: 'Lily', hex: '#f6bf26', kind: 'kid' }] }),
    )
    render(<Today token="t" onUnpaired={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Add for Lily' })).toHaveStyle({ color: '#000000' })
    expect(screen.getByRole('button', { name: 'Add for the family' }).style.color).toBe('var(--accent-on)')
  })

  it('with nothing shared, the family column is still there to add to', async () => {
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ can_edit: true, events: [], tasks: [] }))
    render(<Today token="t" onUnpaired={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Add for the family' })).toBeInTheDocument()
  })

  it('with no one in the family, it says where to add them instead of showing nothing', async () => {
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ can_edit: false, people: [], events: [], tasks: [] }))
    render(<Today token="t" onUnpaired={() => {}} />)
    expect(await screen.findByText(/Members › Family on the web, or Settings › Household › Family on the iPhone/)).toBeInTheDocument()
  })

  it('stops at the last chip, lights it, and scrolls it into view', async () => {
    const scroll = vi.spyOn(Element.prototype, 'scrollIntoView')
    const today = vi.spyOn(boardApi, 'today').mockImplementation(async (_t, d = '') => day({ day: d || '2026-09-22', today: '2026-09-22' }))
    render(<Today token="t" onUnpaired={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Previous day' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '5 Mon' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Next day' })).toBeDisabled())
    expect(screen.getByRole('button', { name: '5 Mon' })).toHaveAttribute('aria-current', 'date')
    expect(scroll).toHaveBeenLastCalledWith({ block: 'nearest', inline: 'center' })
    expect(scroll.mock.contexts.at(-1)).toBe(screen.getByRole('button', { name: '5 Mon' }))
    const calls = today.mock.calls.length
    await userEvent.click(screen.getByRole('button', { name: 'Next day' }))
    expect(today).toHaveBeenCalledTimes(calls)
  })

  it('a swipe across the board turns the page, but scrolling the chips does not', async () => {
    const today = vi.spyOn(boardApi, 'today').mockImplementation(async (_t, d = '') => day({ day: d || '2026-09-22', today: '2026-09-22' }))
    render(<Today token="t" onUnpaired={() => {}} />)
    const chip = await screen.findByRole('button', { name: 'Tomorrow' })
    const swipeLeft = (el: Element) => {
      fireEvent.touchStart(el, { touches: [{ clientX: 300, clientY: 100 }] })
      fireEvent.touchEnd(el, { changedTouches: [{ clientX: 100, clientY: 105 }] })
    }
    swipeLeft(chip)
    expect(today).not.toHaveBeenCalledWith('t', '2026-09-23')
    swipeLeft(screen.getByRole('region', { name: 'Lily' }))
    await waitFor(() => expect(today).toHaveBeenLastCalledWith('t', '2026-09-23'))
  })

  it('a tick that does not save springs back and says why', async () => {
    const today = vi.spyOn(boardApi, 'today').mockResolvedValue(day())
    vi.spyOn(boardApi, 'tick').mockRejectedValue(new Error('the board could not reach luach (500)'))
    render(<Today token="t" onUnpaired={() => {}} />)
    const box = await screen.findByRole('checkbox', { name: /Feed the cat/ })
    await userEvent.click(box)
    expect(await screen.findByRole('alert')).toHaveTextContent('“Feed the cat” did not save: the board could not reach luach (500)')
    await waitFor(() => expect(today).toHaveBeenCalledTimes(2))
    expect(screen.getByRole('checkbox', { name: /Feed the cat/ })).toHaveAttribute('aria-checked', 'false')
  })

  it('says how many more there are tomorrow than it lists', async () => {
    const ev = (i: number) => ({ id: `t${i}`, title: `Thing ${i}`, start: '2026-09-23T09:00:00-04:00', end: '', all_day: false, location: '', leader: '' })
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ tomorrow: Array.from({ length: 8 }, (_, i) => ev(i + 1)) }))
    render(<Today token="t" onUnpaired={() => {}} />)
    expect(await screen.findByText(/Thing 6/)).toBeInTheDocument()
    expect(screen.queryByText(/Thing 7/)).toBeNull()
    expect(screen.getByText('· +2 more', { exact: false })).toBeInTheDocument()
  })

  it('the repeat days share a phone-wide row, each still a finger wide', async () => {
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ can_edit: true }))
    render(<Today token="t" onUnpaired={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Open Feed the cat' }))
    const row = screen.getByRole('group', { name: 'Repeats on' })
    expect(row).toHaveClass('flex-wrap')
    for (const b of within(row).getAllByRole('button')) expect(b).toHaveClass('flex-1', 'min-w-10')
  })

  it('removing a task asks first, like everywhere else', async () => {
    const remove = vi.fn().mockResolvedValue({ ok: true })
    vi.spyOn(boardApi, 'tasks').mockReturnValue({ add, update: vi.fn(), remove } as never)
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ can_edit: true }))
    render(<Today token="t" onUnpaired={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Open Feed the cat' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await userEvent.click(screen.getByRole('button', { name: 'Keep' }))
    expect(remove).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith(7))
  })
})

describe('a board in its own language', () => {
  const paged = (language: string) => vi.spyOn(boardApi, 'today').mockImplementation(async (_t, d = '') => day({ language, day: d || '2026-09-22', today: '2026-09-22' }))
  const swipe = (el: Element, from: number, to: number) => {
    fireEvent.touchStart(el, { touches: [{ clientX: from, clientY: 100 }] })
    fireEvent.touchEnd(el, { changedTouches: [{ clientX: to, clientY: 105 }] })
  }
  const boardRoot = (inside: Element) => inside.closest('[lang]') as HTMLElement

  it('in Hebrew reads right to left, in Hebrew words and a Hebrew calendar', async () => {
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ language: 'he', can_edit: true, day: '2026-09-24', today: '2026-09-22' }))
    render(<Today token="t" onUnpaired={() => {}} />)
    const lily = await screen.findByRole('region', { name: 'Lily' })
    expect(boardRoot(lily)).toHaveAttribute('dir', 'rtl')
    expect(boardRoot(lily)).toHaveAttribute('lang', 'he')
    expect(screen.getByRole('button', { name: 'היום הקודם' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'היום הבא' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'היום' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'מחר' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'חזרה להיום' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'הוספה ל־Lily' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'הוספה למשפחה' })).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'משפחה' })).getByText('Dinner at Oma’s')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Ruby' })).getByText('יום פנוי.')).toBeInTheDocument()
    // The page's date, and the times on a 24-hour clock.
    expect(screen.getByText('יום חמישי, 24 בספטמבר')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'משפחה' })).getByText('18:00')).toBeInTheDocument()
    // A name or a title is the family's own: it sets its own direction.
    expect(within(lily).getByText('Math test')).toHaveAttribute('dir', 'auto')
    expect(within(lily).getByText('Lily')).toHaveAttribute('dir', 'auto')
  })

  it('in Hebrew the arrows point the way the days run: the next day is on the left, pointing left', async () => {
    paged('he')
    render(<Today token="t" onUnpaired={() => {}} />)
    const next = await screen.findByRole('button', { name: 'היום הבא' })
    const prev = screen.getByRole('button', { name: 'היום הקודם' })
    expect(next).toHaveTextContent('‹')
    expect(prev).toHaveTextContent('›')
    // Kept out of the text's direction, or the browser would mirror them back.
    expect(next.querySelector('[data-arrow]')).toHaveAttribute('dir', 'ltr')
    // The earlier day's button comes first in the row, which in Hebrew is its right-hand end.
    const nav = screen.getByRole('navigation', { name: 'ימים' })
    expect(nav.firstElementChild).toBe(prev)
    expect(nav.lastElementChild).toBe(next)
  })

  it('in English the arrows point the other way', async () => {
    paged('en')
    render(<Today token="t" onUnpaired={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Next day' })).toHaveTextContent('›')
    expect(screen.getByRole('button', { name: 'Previous day' })).toHaveTextContent('‹')
  })

  it('in Hebrew the next-day arrow still turns to the next day', async () => {
    const today = paged('he')
    render(<Today token="t" onUnpaired={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'היום הבא' }))
    await waitFor(() => expect(today).toHaveBeenLastCalledWith('t', '2026-09-23'))
    await userEvent.click(await screen.findByRole('button', { name: 'היום הקודם' }))
    await waitFor(() => expect(today).toHaveBeenLastCalledWith('t', ''))
  })

  it('in Hebrew a swipe to the right turns to the next day, and to the left comes back', async () => {
    const today = paged('he')
    render(<Today token="t" onUnpaired={() => {}} />)
    const lily = await screen.findByRole('region', { name: 'Lily' })
    // Leftwards is back, and there is nothing before today.
    swipe(lily, 300, 100)
    expect(today).not.toHaveBeenCalledWith('t', '2026-09-23')
    swipe(lily, 100, 300)
    await waitFor(() => expect(today).toHaveBeenLastCalledWith('t', '2026-09-23'))
    swipe(screen.getByRole('region', { name: 'Lily' }), 300, 100)
    await waitFor(() => expect(today).toHaveBeenLastCalledWith('t', ''))
  })

  it('in English a swipe to the right goes nowhere from today', async () => {
    const today = paged('en')
    render(<Today token="t" onUnpaired={() => {}} />)
    const lily = await screen.findByRole('region', { name: 'Lily' })
    swipe(lily, 100, 300)
    swipe(lily, 100, 300)
    expect(today).not.toHaveBeenCalledWith('t', '2026-09-23')
  })

  it('in Spanish speaks Spanish, left to right, on a 24-hour clock', async () => {
    const futbol = { id: 'x', title: 'Fútbol', start: '2026-09-25T17:30:00-04:00', end: '', all_day: false, location: '', leader: 'lily' }
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ language: 'es', can_edit: true, day: '2026-09-24', today: '2026-09-22', tomorrow: [futbol] }))
    render(<Today token="t" onUnpaired={() => {}} />)
    const lily = await screen.findByRole('region', { name: 'Lily' })
    expect(boardRoot(lily)).toHaveAttribute('dir', 'ltr')
    expect(boardRoot(lily)).toHaveAttribute('lang', 'es')
    expect(screen.getByRole('button', { name: 'Día anterior' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Día siguiente' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hoy' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mañana' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Añadir para Lily' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Añadir para la familia' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Familia' })).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Ruby' })).getByText('Un día libre.')).toBeInTheDocument()
    expect(screen.getByText('jueves, 24 de septiembre')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Familia' })).getByText('18:00')).toBeInTheDocument()
    expect(screen.getByText('Al día siguiente:', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('17:30 Fútbol (Lily)')).toBeInTheDocument()
  })

  it('in Spanish a tick that does not save says so in Spanish', async () => {
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ language: 'es' }))
    vi.spyOn(boardApi, 'tick').mockRejectedValue(new Error('the board could not reach luach (500)'))
    render(<Today token="t" onUnpaired={() => {}} />)
    await userEvent.click(await screen.findByRole('checkbox', { name: /Feed the cat/ }))
    // What the server said is passed on as it said it.
    expect(await screen.findByRole('alert')).toHaveTextContent('«Feed the cat» no se guardó: the board could not reach luach (500)')
  })

  it('a task opened on a Hebrew board reads right to left, with the week starting on Sunday', async () => {
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ language: 'he', can_edit: true }))
    render(<Today token="t" onUnpaired={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'פתיחת Feed the cat' }))
    const sheet = screen.getByRole('dialog', { name: 'משימה' })
    expect(sheet.closest('[dir]')).toHaveAttribute('dir', 'rtl')
    expect(within(sheet).getByLabelText('מה')).toHaveValue('Feed the cat')
    const days = within(within(sheet).getByRole('group', { name: 'חוזרת בימים' })).getAllByRole('button')
    expect(days.map((b) => b.textContent)).toEqual(['א׳', 'ב׳', 'ג׳', 'ד׳', 'ה׳', 'ו׳', 'ש׳'])
    expect(days[0]).toHaveAccessibleName('יום ראשון')
    expect(screen.getByRole('button', { name: 'שמירה' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'הסרה' }))
    expect(screen.getByRole('button', { name: 'השארה' })).toBeInTheDocument()
  })

  it('a new task on a Spanish board asks in Spanish', async () => {
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ language: 'es', can_edit: true }))
    render(<Today token="t" onUnpaired={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Añadir para Lily' }))
    await userEvent.click(screen.getByRole('button', { name: 'Tarea' }))
    const sheet = screen.getByRole('dialog', { name: 'Una tarea para Lily' })
    expect(within(sheet).getByRole('radiogroup', { name: 'Tarea para' })).toBeInTheDocument()
    expect(within(sheet).getByRole('radio', { name: 'Cualquiera' })).toBeInTheDocument()
    await userEvent.click(within(sheet).getByRole('button', { name: 'Añadir tarea' }))
    expect(within(sheet).getByText('Ponle un nombre.')).toBeInTheDocument()
    expect(within(sheet).getByRole('button', { name: 'Cancelar' })).toBeInTheDocument()
  })

  it('on "auto" follows the screen’s own browser', async () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('he-IL')
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ language: 'auto' }))
    render(<Today token="t" onUnpaired={() => {}} />)
    const lily = await screen.findByRole('region', { name: 'Lily' })
    expect(boardRoot(lily)).toHaveAttribute('dir', 'rtl')
    expect(screen.getByRole('button', { name: 'מחר' })).toBeInTheDocument()
  })

  it('on "auto" in a Spanish browser speaks Spanish, and in any other English', async () => {
    const lang = vi.spyOn(navigator, 'language', 'get').mockReturnValue('es-MX')
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ language: 'auto' }))
    const { unmount } = render(<Today token="t" onUnpaired={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Mañana' })).toBeInTheDocument()
    unmount()
    lang.mockReturnValue('fr-FR')
    render(<Today token="t" onUnpaired={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Tomorrow' })).toBeInTheDocument()
  })

  it('the owner’s choice wins over the browser', async () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('he-IL')
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ language: 'en' }))
    render(<Today token="t" onUnpaired={() => {}} />)
    const lily = await screen.findByRole('region', { name: 'Lily' })
    expect(boardRoot(lily)).toHaveAttribute('dir', 'ltr')
    expect(screen.getByRole('button', { name: 'Tomorrow' })).toBeInTheDocument()
  })

  it('inside the app it speaks the app’s English, whatever the browser', async () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('he-IL')
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ board: '', language: 'auto' }))
    render(<Today token="" embedded onUnpaired={() => {}} />)
    expect(await screen.findByRole('link', { name: 'Open full screen' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'The family’s day' })).toBeInTheDocument()
  })

  it('a screen waiting to be paired speaks its browser’s language', async () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('he')
    vi.spyOn(boardApi, 'pair').mockResolvedValue({ code: 'K7P3QX', secret: 's', expires_at: '' })
    vi.spyOn(boardApi, 'collect').mockResolvedValue({ waiting: true })
    render(<Board />)
    expect(await screen.findByText('K7P3QX')).toHaveAttribute('dir', 'ltr')
    expect(screen.getByRole('heading', { name: 'הפכו את המסך הזה ללוח הבית' }).closest('[lang]')).toHaveAttribute('dir', 'rtl')
  })
})

describe('a wall board keeps itself up to date', () => {
  it('asks which build the server hands out; inside the app it does not', async () => {
    const build = vi.spyOn(boardApi, 'build').mockResolvedValue('')
    vi.spyOn(boardApi, 'today').mockResolvedValue(day())
    const { unmount } = render(<Today token="t" onUnpaired={() => {}} />)
    await screen.findByRole('region', { name: 'Lily' })
    await waitFor(() => expect(build).toHaveBeenCalled())
    unmount()
    build.mockClear()
    render(<Today token="" embedded onUnpaired={() => {}} />)
    await screen.findByRole('region', { name: 'Lily' })
    expect(build).not.toHaveBeenCalled()
  })
})

/** A 404 from a tick is a chore a parent just deleted, not a screen that was unpaired. */
describe('the board’s client', () => {
  const answer = (status: number, body: unknown = {}) => vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify(body), { status }))

  it('a tick on a task that is gone says so, and keeps the board paired', async () => {
    answer(404, { error: 'no such task' })
    const err = await boardApi.tick('t', 7, true).catch((e: unknown) => e)
    expect(err).not.toBeInstanceOf(Unpaired)
    expect((err as Error).message).toBe('no such task')
  })

  it('only a 401 means unpaired', async () => {
    answer(401, { error: 'pair it again' })
    await expect(boardApi.tick('t', 7, true)).rejects.toBeInstanceOf(Unpaired)
    await expect(boardApi.today('t')).rejects.toBeInstanceOf(Unpaired)
  })

  it('a pairing code that ran out still starts again', async () => {
    answer(404, { error: 'no screen is waiting with that code' })
    await expect(boardApi.collect('K7P3QX', 's')).rejects.toBeInstanceOf(Unpaired)
  })

  it('at the wall, a chore deleted a moment ago leaves the token where it is', async () => {
    storeToken('t')
    vi.spyOn(boardApi, 'today').mockResolvedValue(day())
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ error: 'no such task' }), { status: 404 }))
    render(<Board />)
    await userEvent.click(await screen.findByRole('checkbox', { name: /Feed the cat/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('“Feed the cat” did not save: no such task')
    expect(storedToken()).toBe('t')
    expect(screen.getByRole('region', { name: 'Lily' })).toBeInTheDocument()
  })
})

/** The board's event sheet was the member's: English and left to right on a Hebrew
 * wall, its family and calendars refused with 401, and Invite and Google open at a kiosk. */
describe('an event opened on the board', () => {
  const event = {
    id: 'e1',
    title: 'Math test',
    start: '2026-09-22T09:00:00-04:00',
    end: '2026-09-22T10:00:00-04:00',
    all_day: false,
    location: '',
    leader: 'lily',
    leaders: ['lily'],
    calendar_id: 'home',
    html_link: 'https://calendar.google.com/event?eid=x',
    attendees: ['grandma@example.com'],
  }
  const cals = {
    calendars: ['home', 'work'],
    default_calendar: 'home',
    default_attendees: [],
    available: [
      { id: 'home', name: 'Home', color: '#f4b942', primary: true, writable: true, enabled: true, default: true },
      { id: 'work', name: 'Work', color: '#4488ff', primary: false, writable: true, enabled: true, default: false },
    ],
  }

  function board(language: string) {
    vi.spyOn(boardApi, 'today').mockResolvedValue(day({ language, can_edit: true }))
    const calendars = vi.spyOn(boardApi, 'calendars').mockResolvedValue(cals)
    const create = vi.fn().mockResolvedValue(event)
    vi.spyOn(boardApi, 'events').mockReturnValue({ get: vi.fn().mockResolvedValue(event), create, update: vi.fn(), remove: vi.fn() } as never)
    // The member API must not be asked from a screen.
    const member = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response('{}', { status: 401 }))
    return { calendars, create, member }
  }

  it('speaks the board’s Hebrew, right to left, and offers nothing that leaves luach', async () => {
    const { member } = board('he')
    render(<Today token="t" onUnpaired={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'פתיחת Math test' }))
    const sheet = await screen.findByRole('dialog', { name: 'אירוע' })
    expect(sheet.closest('[dir]')).toHaveAttribute('dir', 'rtl')
    expect(sheet.closest('[lang]')).toHaveAttribute('lang', 'he')
    expect(within(sheet).getByText('עבור Lily')).toBeInTheDocument()
    expect(within(sheet).getByRole('button', { name: 'עריכה' })).toBeInTheDocument()
    expect(within(sheet).queryByText(/Google Calendar/)).toBeNull()
    expect(within(sheet).queryByText('grandma@example.com')).toBeNull()
    expect(member).not.toHaveBeenCalled()
  })

  it('adds with the board’s own people and calendars, and invites nobody', async () => {
    const { calendars, create, member } = board('es')
    render(<Today token="t" onUnpaired={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Añadir para Lily' }))
    await userEvent.click(screen.getByRole('button', { name: 'Evento' }))
    const sheet = await screen.findByRole('dialog', { name: 'Nuevo evento' })
    await waitFor(() => expect(calendars).toHaveBeenCalledWith('t'))
    expect(await within(sheet).findByRole('combobox', { name: 'Calendario' })).toHaveValue('home')
    expect(within(sheet).getByRole('button', { name: 'Ruby' })).toBeInTheDocument()
    expect(within(sheet).queryByText('Invitar')).toBeNull()
    await userEvent.type(within(sheet).getByLabelText('Título'), 'Piano')
    await userEvent.click(within(sheet).getByRole('button', { name: 'Añadir' }))
    await waitFor(() => expect(create).toHaveBeenCalled())
    const sent = create.mock.calls[0]![0] as Record<string, unknown>
    expect(sent).not.toHaveProperty('attendees')
    expect(sent).toMatchObject({ title: 'Piano', calendar_id: 'home', leader: 'lily' })
    expect(member).not.toHaveBeenCalled()
  })
})
