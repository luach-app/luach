import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Today } from '../Board'
import { applyMove, boardApi, planMove, shiftEvent, type BoardDay, type BoardEvent } from '../../lib/board'
import { LIFT_MS } from '../../lib/boardDrag'
import type { Task } from '../../lib/types'

const task = (over: Partial<Task> = {}): Task => ({ id: 7, title: 'Feed the cat', person: 'lily', due: '', days: [], notes: '', done: false, overdue: false, chore: false, ...over })
const mathTest: BoardEvent = { id: 'e1', title: 'Math test', start: '2026-09-22T09:00:00-04:00', end: '2026-09-22T10:00:00-04:00', all_day: false, location: '', leader: 'lily', leaders: ['lily'], calendar_id: 'home' }

const day = (over: Partial<BoardDay> = {}): BoardDay => ({
  board: 'Kitchen',
  can_edit: true,
  timezone: 'America/New_York',
  now: '2026-09-22T08:00:00-04:00',
  today: '2026-09-22',
  day: '2026-09-22',
  people: [
    { key: 'lily', name: 'Lily', hex: '#f4511e', kind: 'kid' },
    { key: 'ruby', name: 'Ruby', hex: '#33b679', kind: 'kid' },
  ],
  events: [mathTest],
  tomorrow: [],
  tasks: [task()],
  ...over,
})

const taskUpdate = vi.fn()
const eventUpdate = vi.fn()
let under: Element | null = null
let todayCall: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  taskUpdate.mockReset().mockResolvedValue(task())
  eventUpdate.mockReset().mockResolvedValue(mathTest)
  vi.spyOn(boardApi, 'tasks').mockReturnValue({ add: vi.fn(), update: taskUpdate, remove: vi.fn() } as never)
  vi.spyOn(boardApi, 'events').mockReturnValue({ get: vi.fn().mockResolvedValue({ ...mathTest, description: '', recurrence: [], recurring_event_id: '', html_link: '', creator: '', updated: '' }), create: vi.fn(), update: eventUpdate, remove: vi.fn() } as never)
  vi.spyOn(boardApi, 'build').mockResolvedValue('')
  under = null
  // jsdom lays nothing out: the element "under the finger" is whatever the test says.
  document.elementFromPoint = vi.fn(() => under)
})
afterEach(() => {
  vi.useRealTimers()
  // @ts-expect-error put jsdom back the way it was
  delete document.elementFromPoint
})

async function board(over: Partial<BoardDay> = {}) {
  todayCall = vi.spyOn(boardApi, 'today').mockImplementation(async (_t, d = '') => day({ ...over, day: d || over.day || '2026-09-22' }))
  render(<Today token="t" onUnpaired={() => {}} />)
  await screen.findByRole('region', { name: over.language === 'he' ? 'Ruby' : 'Lily' })
  vi.useFakeTimers({ shouldAdvanceTime: true })
}

const rowOf = (name: string) => screen.getByRole('button', { name: new RegExp(`(Open|פתיחת) ${name}`) }).closest('li') as HTMLElement
const at = (x: number, y: number, pointerType = 'touch') => ({ pointerId: 1, clientX: x, clientY: y, pointerType, button: 0 })

/** Press on `el` and hold until it lifts. */
async function hold(el: Element, pointerType = 'touch') {
  fireEvent.pointerDown(el, at(100, 100, pointerType))
  await act(async () => {
    vi.advanceTimersByTime(LIFT_MS + 10)
  })
}

/** Carry what is held over `target`, and let go there. */
async function dropOn(target: Element | null) {
  under = target
  fireEvent.pointerMove(window, at(400, 300))
  fireEvent.pointerUp(window, at(400, 300))
  await act(async () => {})
}

const ghost = () => document.querySelector('[data-ghost]')
const chip = (iso: string) => document.querySelector(`[data-drop="day:${iso}"]`) as HTMLElement

describe('holding a card on the board', () => {
  it('a long press lifts it: a card follows the finger, the original fades, and it buzzes and says so', async () => {
    const vibrate = vi.fn()
    Object.defineProperty(navigator, 'vibrate', { value: vibrate, configurable: true })
    await board()
    const row = rowOf('Feed the cat')
    fireEvent.pointerDown(row, at(100, 100))
    await act(async () => {
      vi.advanceTimersByTime(LIFT_MS - 50)
    })
    expect(ghost()).toBeNull()
    await act(async () => {
      vi.advanceTimersByTime(60)
    })
    expect(ghost()).toHaveTextContent('Feed the cat')
    expect(ghost()).toHaveAttribute('aria-hidden')
    expect(rowOf('Feed the cat')).toHaveClass('opacity-40')
    expect(vibrate).toHaveBeenCalledWith(10)
    expect(screen.getByText('Picked up Feed the cat. Drop it on a person or a day.')).toBeInTheDocument()
    // The ghost goes where the finger goes.
    fireEvent.pointerMove(window, at(321, 222))
    expect((ghost() as HTMLElement).style.left).toBe('321px')
    // @ts-expect-error not every test screen buzzes
    delete navigator.vibrate
  })

  it('a quick tap still opens it', async () => {
    await board()
    const row = rowOf('Feed the cat')
    fireEvent.pointerDown(row, at(100, 100))
    await act(async () => {
      vi.advanceTimersByTime(120)
    })
    fireEvent.pointerUp(window, at(100, 100))
    fireEvent.click(within(row).getByRole('button', { name: 'Open Feed the cat' }))
    expect(screen.getByRole('dialog', { name: 'Task' })).toBeInTheDocument()
    await act(async () => {
      vi.advanceTimersByTime(LIFT_MS * 2)
    })
    expect(ghost()).toBeNull()
  })

  it('a finger that moves before the hold is up is scrolling, and lifts nothing', async () => {
    await board()
    fireEvent.pointerDown(rowOf('Feed the cat'), at(100, 100))
    fireEvent.pointerMove(window, at(112, 100))
    await act(async () => {
      vi.advanceTimersByTime(LIFT_MS * 2)
    })
    expect(ghost()).toBeNull()
  })

  it('dropped on another person’s column, the task is theirs — and Undo gives it back', async () => {
    await board()
    await hold(rowOf('Feed the cat'))
    const ruby = screen.getByRole('region', { name: 'Ruby' })
    under = ruby
    fireEvent.pointerMove(window, at(500, 300))
    expect(ruby).toHaveClass('ring-4')
    await dropOn(ruby)
    expect(taskUpdate).toHaveBeenCalledWith(7, { person: 'ruby' })
    expect(ghost()).toBeNull()
    expect(await screen.findByText('Feed the cat is now Ruby’s.')).toBeInTheDocument()
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Undo' }), at(10, 10))
    fireEvent.pointerUp(screen.getByRole('button', { name: 'Undo' }), at(10, 10))
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(taskUpdate).toHaveBeenLastCalledWith(7, { person: 'lily' }))
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
  })

  it('Undo goes away by itself after a few seconds', async () => {
    await board()
    await hold(rowOf('Feed the cat'))
    await dropOn(screen.getByRole('region', { name: 'Ruby' }))
    expect(await screen.findByRole('button', { name: 'Undo' })).toBeInTheDocument()
    await act(async () => {
      vi.advanceTimersByTime(6_100)
    })
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
  })

  it('an event dropped on someone else is handed over, the way the edit form hands it', async () => {
    await board()
    await hold(rowOf('Math test'))
    await dropOn(within(screen.getByRole('region', { name: 'Ruby' })).getByText('A free day.'))
    expect(eventUpdate).toHaveBeenCalledWith('e1', { leaders: ['ruby'] }, 'home')
  })

  it('an event dropped on the family column is nobody’s in particular', async () => {
    await board()
    await hold(rowOf('Math test'))
    await dropOn(screen.getByRole('region', { name: 'Family' }))
    expect(eventUpdate).toHaveBeenCalledWith('e1', { leaders: [] }, 'home')
  })

  it('dropped on a day chip, an event moves to that day at the same time', async () => {
    await board()
    await hold(rowOf('Math test'))
    await dropOn(chip('2026-09-24'))
    // 9:00–10:00 in New York, two days on.
    expect(eventUpdate).toHaveBeenCalledWith('e1', { start: '2026-09-24T13:00:00.000Z', end: '2026-09-24T14:00:00.000Z' }, 'home')
    expect(await screen.findByText('Math test moved to Thursday, September 24.')).toBeInTheDocument()
    await act(async () => {
      vi.advanceTimersByTime(1_000)
    })
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(eventUpdate).toHaveBeenLastCalledWith('e1', { start: mathTest.start, end: mathTest.end }, 'home'))
  })

  it('dropped on a day chip, a to-do is due that day', async () => {
    await board()
    await hold(rowOf('Feed the cat'))
    await dropOn(chip('2026-09-23'))
    expect(taskUpdate).toHaveBeenCalledWith(7, { due: '2026-09-23' })
  })

  it('one day of something that repeats is not moved to another day: the editor does that', async () => {
    await board({ tasks: [task({ chore: true, days: ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'] })], events: [{ ...mathTest, recurring: true }] })
    await hold(rowOf('Feed the cat'))
    await dropOn(chip('2026-09-23'))
    expect(screen.getByText('This one repeats — change it in the editor.')).toBeInTheDocument()
    await hold(rowOf('Math test'))
    await dropOn(chip('2026-09-23'))
    expect(taskUpdate).not.toHaveBeenCalled()
    expect(eventUpdate).not.toHaveBeenCalled()
    // Handing it to someone else is still fine.
    await hold(rowOf('Feed the cat'))
    await dropOn(screen.getByRole('region', { name: 'Ruby' }))
    expect(taskUpdate).toHaveBeenCalledWith(7, { person: 'ruby' })
  })

  it('dropped where it was, or on nothing, changes nothing', async () => {
    await board()
    await hold(rowOf('Feed the cat'))
    await dropOn(screen.getByRole('region', { name: 'Lily' }))
    await hold(rowOf('Feed the cat'))
    await dropOn(chip('2026-09-22'))
    await hold(rowOf('Feed the cat'))
    await dropOn(null)
    expect(taskUpdate).not.toHaveBeenCalled()
    expect(screen.getByText('Feed the cat is back where it was.')).toBeInTheDocument()
  })

  it('someone else’s invitation cannot be lifted, and a hold says why', async () => {
    await board({ events: [{ ...mathTest, read_only: true, organizer: 'coach@club.test' }] })
    await hold(rowOf('Math test'))
    expect(ghost()).toBeNull()
    expect(screen.getByText('Only the organizer can change this.')).toBeInTheDocument()
    await dropOn(screen.getByRole('region', { name: 'Ruby' }))
    expect(eventUpdate).not.toHaveBeenCalled()
  })

  it('a screen that only shows the day lifts nothing', async () => {
    await board({ can_edit: false })
    await hold(rowOf('Feed the cat'))
    expect(ghost()).toBeNull()
    expect(document.querySelector('[data-drop]')).toBeNull()
  })

  it('a swipe that carried something does not also turn the page', async () => {
    await board()
    const lily = screen.getByRole('region', { name: 'Lily' })
    fireEvent.touchStart(lily, { touches: [{ clientX: 300, clientY: 100 }] })
    await hold(rowOf('Feed the cat'))
    await dropOn(null)
    fireEvent.touchEnd(lily, { changedTouches: [{ clientX: 60, clientY: 105 }] })
    await act(async () => {})
    expect(todayCall).not.toHaveBeenCalledWith('t', '2026-09-23')
  })

  it('on a Hebrew board, right to left, it lands on the column under the finger', async () => {
    await board({ language: 'he' })
    await hold(rowOf('Feed the cat'))
    await dropOn(within(screen.getByRole('region', { name: 'Ruby' })).getByRole('heading'))
    expect(taskUpdate).toHaveBeenCalledWith(7, { person: 'ruby' })
    expect(await screen.findByText('העברנו את Feed the cat אל Ruby.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ביטול פעולה' })).toBeInTheDocument()
  })

  it('a change that does not save is put back, and the board says why', async () => {
    taskUpdate.mockRejectedValue(new Error('luach said no (500)'))
    await board()
    await hold(rowOf('Feed the cat'))
    await dropOn(screen.getByRole('region', { name: 'Ruby' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('“Feed the cat” did not save: luach said no (500)')
    expect(within(screen.getByRole('region', { name: 'Lily' })).getByText('Feed the cat')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
  })

  it('works with a mouse too, and the click a hold ends with does not open the card', async () => {
    await board()
    await hold(rowOf('Feed the cat'), 'mouse')
    expect(ghost()).not.toBeNull()
    await dropOn(screen.getByRole('region', { name: 'Ruby' }))
    fireEvent.click(screen.getByRole('button', { name: 'Open Feed the cat' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(taskUpdate).toHaveBeenCalledWith(7, { person: 'ruby' })
  })
})

describe('what a drop means', () => {
  const d = day()
  it('an all-day event stays all day', () => {
    const ev: BoardEvent = { ...mathTest, all_day: true, start: '2026-09-22', end: '2026-09-23' }
    expect(shiftEvent(ev, 3, 'America/New_York')).toEqual({ start: '2026-09-25', end: '2026-09-26' })
  })

  it('keeps the clock time across a change of the clocks', () => {
    // New York leaves daylight time on 1 November 2026: 9:00 is 13:00Z before, 14:00Z after.
    const ev: BoardEvent = { ...mathTest, start: '2026-10-30T09:00:00-04:00', end: '2026-10-30T09:30:00-04:00' }
    expect(shiftEvent(ev, 4, 'America/New_York')).toEqual({ start: '2026-11-03T14:00:00.000Z', end: '2026-11-03T14:30:00.000Z' })
  })

  it('an event for two people, carried from one to a third, is the other’s and the third’s', () => {
    const ev: BoardEvent = { ...mathTest, leaders: ['lily', 'ruby'] }
    expect(planMove({ kind: 'event', event: ev, from: 'lily', }, { kind: 'person', key: 'noa' }, d.day, d.timezone)).toMatchObject({ body: { leaders: ['noa', 'ruby'] }, undo: { leaders: ['lily', 'ruby'] } })
    // Carried onto the other one of the two: just theirs now.
    expect(planMove({ kind: 'event', event: ev, from: 'lily' }, { kind: 'person', key: 'ruby' }, d.day, d.timezone)).toMatchObject({ body: { leaders: ['ruby'] } })
  })

  it('a to-do moved to a later day leaves this page; handed over it stays, in its new column', () => {
    const later = planMove({ kind: 'task', task: task(), from: 'lily' }, { kind: 'day', iso: '2026-09-25' }, d.day, d.timezone)
    expect(later && later !== 'repeats' && applyMove(d, later).tasks).toEqual([])
    const handed = planMove({ kind: 'task', task: task(), from: 'lily' }, { kind: 'person', key: 'ruby' }, d.day, d.timezone)
    expect(handed && handed !== 'repeats' && applyMove(d, handed).tasks[0]?.person).toBe('ruby')
  })
})
