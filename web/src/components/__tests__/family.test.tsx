import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EventSheet } from '../EventSheet'
import { FamilyEditor } from '../FamilyEditor'
import * as api from '../../lib/api'
import { eventColor, invalidateFamily } from '../../lib/family'
import { invalidateHousehold } from '../../lib/household'
import type { Family, HouseholdCalendars } from '../../lib/types'
import { event } from '../../test/harness'

const harpers: Family = {
  people: [
    { key: 'robin', name: 'Robin', color: '7', hex: '#039be5', kind: 'adult', email: 'robin@x.io', user_id: 1, position: 0 },
    { key: 'lily', name: 'Lily', color: '6', hex: '#f4511e', kind: 'kid', email: '', user_id: null, position: 1 },
    { key: 'ruby', name: 'Ruby', color: '2', hex: '#33b679', kind: 'kid', email: 'ruby@x.io', user_id: null, position: 2 },
  ],
  colors: [
    { id: '6', name: 'Tangerine', hex: '#f4511e' },
    { id: '3', name: 'Grape', hex: '#8e24aa' },
  ],
}

beforeEach(() => {
  invalidateHousehold()
  invalidateFamily()
  vi.spyOn(api.household, 'calendars').mockResolvedValue({
    available: [{ id: 'home', name: 'Home', writable: true, color: '#f4b942', primary: true }],
    calendars: ['home'],
    default_calendar: 'home',
    default_attendees: [],
  } as never)
  vi.spyOn(api.family, 'get').mockResolvedValue(harpers)
})

const noop = () => {}

describe('whose event it is', () => {
  it('a new event can be for one of the family, and says they are invited', async () => {
    const create = vi.spyOn(api.calendar, 'create').mockResolvedValue(event() as never)
    render(<EventSheet state={{ mode: 'create', day: '2026-09-18' }} tz="America/New_York" locale="en" onClose={noop} onChanged={noop} onEdit={noop} />)
    await userEvent.type(screen.getByLabelText('Title'), 'Football')
    await userEvent.click(await screen.findByRole('button', { name: 'Ruby', pressed: false }))
    expect(screen.getByText(/Ruby is invited/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(create).toHaveBeenCalled())
    expect((create.mock.calls[0]?.[0] as { leader?: string }).leader).toBe('ruby')
  })

  it('an event for everyone sends no leader at all', async () => {
    const create = vi.spyOn(api.calendar, 'create').mockResolvedValue(event() as never)
    render(<EventSheet state={{ mode: 'create', day: '2026-09-18' }} tz="America/New_York" locale="en" onClose={noop} onChanged={noop} onEdit={noop} />)
    await userEvent.type(screen.getByLabelText('Title'), 'Dinner')
    await screen.findByRole('button', { name: 'Everyone', pressed: true })
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create.mock.calls[0]?.[0]).not.toHaveProperty('leader')
  })

  it('editing hands it to someone else, and only then says so', async () => {
    const update = vi.spyOn(api.calendar, 'update').mockResolvedValue(event() as never)
    const ev = { ...event(), leader: 'lily' } as never
    render(<EventSheet state={{ mode: 'edit', event: ev }} tz="America/New_York" locale="en" onClose={noop} onChanged={noop} onEdit={noop} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Lily', pressed: true }))
    await userEvent.click(screen.getByRole('button', { name: 'Robin', pressed: false }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(update).toHaveBeenCalled())
    expect((update.mock.calls[0]?.[1] as { leader?: string }).leader).toBe('robin')
  })

  it('an event can be for two of them, and says so', async () => {
    const create = vi.spyOn(api.calendar, 'create').mockResolvedValue(event() as never)
    render(<EventSheet state={{ mode: 'create', day: '2026-09-18' }} tz="America/New_York" locale="en" onClose={noop} onChanged={noop} onEdit={noop} />)
    await userEvent.type(screen.getByLabelText('Title'), 'Breakfast')
    await userEvent.click(await screen.findByRole('button', { name: 'Ruby', pressed: false }))
    await userEvent.click(screen.getByRole('button', { name: 'Lily', pressed: false }))
    expect(screen.getByText(/On Lily and Ruby’s board/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(create).toHaveBeenCalled())
    expect((create.mock.calls[0]?.[0] as { leader?: string }).leader).toBe('lily,ruby')
  })

  it('the view names everyone it is for', async () => {
    const ev = { ...event(), leader: 'ruby', leaders: ['ruby', 'lily'] } as never
    render(<EventSheet state={{ mode: 'view', event: ev }} tz="America/New_York" locale="en" onClose={noop} onChanged={noop} onEdit={noop} />)
    expect(await screen.findByText('For Ruby and Lily')).toBeInTheDocument()
  })

  it('the event view names who it is for', async () => {
    const ev = { ...event(), leader: 'lily' } as never
    render(<EventSheet state={{ mode: 'view', event: ev }} tz="America/New_York" locale="en" onClose={noop} onChanged={noop} onEdit={noop} />)
    expect(await screen.findByText('For Lily')).toBeInTheDocument()
  })

  it('an event wears its leader’s colour, else its calendar’s', () => {
    const h = { available: [{ id: 'home', color: '#f4b942' }] } as unknown as HouseholdCalendars
    expect(eventColor(harpers, h, { leader: 'lily', calendar_id: 'home' })).toBe('#f4511e')
    expect(eventColor(harpers, h, { leader: '', calendar_id: 'home' })).toBe('#f4b942')
    expect(eventColor(null, h, { leader: 'lily', calendar_id: 'home' })).toBe('#f4b942')
  })
})

describe('the owner’s family editor', () => {
  it('adds a child', async () => {
    const add = vi.spyOn(api.family, 'add').mockResolvedValue(harpers.people[1]!)
    render(<FamilyEditor />)
    await screen.findByText('Ruby')
    await userEvent.type(screen.getByLabelText('Add someone'), 'Alex')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(add).toHaveBeenCalledWith({ name: 'Alex', kind: 'adult' }))
  })

  it('changes a colour and removes someone, asking first', async () => {
    const update = vi.spyOn(api.family, 'update').mockResolvedValue(harpers.people[1]!)
    const remove = vi.spyOn(api.family, 'remove').mockResolvedValue({ ok: true })
    render(<FamilyEditor />)
    await userEvent.click(await screen.findByRole('button', { name: /Lily/ }))
    await userEvent.click(screen.getByRole('radio', { name: 'Grape' }))
    await waitFor(() => expect(update).toHaveBeenCalledWith('lily', { color: '3' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(remove).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Remove Lily' }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith('lily'))
  })
})
