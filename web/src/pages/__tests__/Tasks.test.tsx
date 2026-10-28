import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Tasks } from '../Tasks'
import * as api from '../../lib/api'
import { invalidateFamily } from '../../lib/family'
import { columnsFor, describeDays } from '../../lib/tasks'
import type { Family, Task } from '../../lib/types'
import { member } from '../../test/harness'

const harpers: Family = {
  people: [
    { key: 'ruby', name: 'Ruby', color: '2', hex: '#33b679', kind: 'kid', email: '', user_id: null, position: 0 },
    { key: 'lily', name: 'Lily', color: '6', hex: '#f4511e', kind: 'kid', email: '', user_id: null, position: 1 },
  ],
  colors: [],
}

const task = (over: Partial<Task>): Task => ({ id: 1, title: 'Bins out', person: 'ruby', due: '', days: ['TU'], notes: '', done: false, overdue: false, chore: true, ...over })

beforeEach(() => {
  invalidateFamily()
  vi.spyOn(api.family, 'get').mockResolvedValue(harpers)
})

describe('the tasks board', () => {
  it('puts each task in its person’s column and ticks it at once', async () => {
    vi.spyOn(api.tasks, 'day').mockResolvedValue({
      day: '2026-09-22',
      may_assign: true,
      tasks: [task({}), task({ id: 2, title: 'Library book', person: 'lily', days: [], chore: false, due: '2026-09-20', overdue: true })],
    })
    const tick = vi.spyOn(api.tasks, 'tick').mockResolvedValue(task({ done: true }))
    render(<Tasks member={member} />)
    const ruby = await screen.findByRole('region', { name: 'Ruby’s tasks' })
    const bins = within(ruby).getByRole('checkbox', { name: /Bins out/ })
    expect(within(screen.getByRole('region', { name: 'Lily’s tasks' })).getByText(/late/)).toBeInTheDocument()
    await userEvent.click(bins)
    expect(bins).toHaveAttribute('aria-checked', 'true')
    expect(tick).toHaveBeenCalledWith(1, expect.any(String), true)
  })

  it('a grown-up adds a chore for someone, on the days picked', async () => {
    vi.spyOn(api.tasks, 'day').mockResolvedValue({ day: '2026-09-22', may_assign: true, tasks: [] })
    const add = vi.spyOn(api.tasks, 'add').mockResolvedValue(task({}))
    render(<Tasks member={member} />)
    await userEvent.type(await screen.findByLabelText('What'), 'Dishes')
    await userEvent.click(await screen.findByRole('radio', { name: 'Lily' }))
    await userEvent.click(screen.getByLabelText('A chore that repeats'))
    await userEvent.click(screen.getByRole('button', { name: 'Thursday' }))
    await userEvent.click(screen.getByRole('button', { name: 'Tuesday' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add task' }))
    await waitFor(() => expect(add).toHaveBeenCalledWith({ title: 'Dishes', person: 'lily', days: ['TU', 'TH'] }))
  })

  it('a chore with no days is not sent', async () => {
    vi.spyOn(api.tasks, 'day').mockResolvedValue({ day: '2026-09-22', may_assign: true, tasks: [] })
    const add = vi.spyOn(api.tasks, 'add').mockResolvedValue(task({}))
    render(<Tasks member={member} />)
    await userEvent.type(await screen.findByLabelText('What'), 'Dishes')
    await userEvent.click(screen.getByLabelText('A chore that repeats'))
    await userEvent.click(screen.getByRole('button', { name: 'Add task' }))
    expect(await screen.findByText('Pick the days it repeats on.')).toBeInTheDocument()
    expect(add).not.toHaveBeenCalled()
  })

  it('the bin asks first, and only a yes removes', async () => {
    vi.spyOn(api.tasks, 'day').mockResolvedValue({ day: '2026-09-22', may_assign: true, tasks: [task({ chore: false, days: [] })] })
    const remove = vi.spyOn(api.tasks, 'remove').mockResolvedValue({ ok: true })
    render(<Tasks member={member} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Remove Bins out' }))
    expect(remove).not.toHaveBeenCalled()
    const ask = screen.getByRole('group', { name: 'Remove Bins out?' })
    expect(within(ask).getByRole('button', { name: 'Keep' })).toHaveFocus()
    await userEvent.click(within(ask).getByRole('button', { name: 'Keep' }))
    expect(remove).not.toHaveBeenCalled()
    expect(screen.getByRole('checkbox', { name: /Bins out/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove Bins out' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith(1))
  })

  it('a chore says it goes from every day', async () => {
    vi.spyOn(api.tasks, 'day').mockResolvedValue({ day: '2026-09-22', may_assign: true, tasks: [task({})] })
    const remove = vi.spyOn(api.tasks, 'remove').mockResolvedValue({ ok: true })
    render(<Tasks member={member} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Remove Bins out' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove from every day' }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith(1))
  })

  it('a child sees no form and no remove buttons', async () => {
    vi.spyOn(api.tasks, 'day').mockResolvedValue({ day: '2026-09-22', may_assign: false, tasks: [task({})] })
    render(<Tasks member={member} />)
    await screen.findByRole('checkbox', { name: /Bins out/ })
    expect(screen.queryByRole('form', { name: 'New task' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Remove/ })).toBeNull()
    expect(screen.getByText(/A grown-up hands out the tasks/)).toBeInTheDocument()
  })
})

describe('helpers', () => {
  it('says the days the way a person would', () => {
    expect(describeDays(['MO', 'TU', 'WE', 'TH', 'FR'])).toBe('weekdays')
    expect(describeDays(['TU', 'TH'])).toBe('Tue, Thu')
    expect(describeDays(['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'])).toBe('every day')
  })
  it('a task for nobody, or for someone since removed, goes under Anyone', () => {
    const cols = columnsFor(harpers.people, [task({ person: '' }), task({ id: 2, person: 'gone' })])
    expect(cols.map((c) => [c.name, c.tasks.length])).toEqual([
      ['Ruby', 0],
      ['Lily', 0],
      ['Anyone', 2],
    ])
  })
})
