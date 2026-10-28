import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EventSheet } from '../EventSheet'
import * as api from '../../lib/api'
import { invalidateHousehold } from '../../lib/household'
import { event } from '../../test/harness'

beforeEach(() => {
  invalidateHousehold()
  vi.spyOn(api.household, 'calendars').mockResolvedValue({
    available: [{ id: 'home', name: 'Home', writable: true, color: '#f4b942', primary: true }],
    calendars: ['home'],
    default_calendar: 'home',
    default_attendees: ['alex@example.com'],
  } as never)
})

const noop = () => {}

describe('making an event', () => {
  it('prefills the household and the member’s own notify addresses, and can send a repeat', async () => {
    const create = vi.spyOn(api.calendar, 'create').mockResolvedValue(event() as never)
    render(
      <EventSheet
        state={{ mode: 'create', day: '2026-09-18' }}
        tz="America/New_York"
        locale="en"
        onClose={noop}
        onChanged={noop}
        onEdit={noop}
        notifyEmails={['work@corp.com']}
      />,
    )
    await waitFor(() => expect(screen.getByText('alex@example.com')).toBeInTheDocument())
    expect(screen.getByText('work@corp.com')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Title'), 'Standup')
    await userEvent.selectOptions(screen.getByLabelText('Repeats'), 'weekly')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() => expect(create).toHaveBeenCalled())
    const body = create.mock.calls[0]?.[0] as unknown as Record<string, unknown>
    expect(body.title).toBe('Standup')
    // The menu's word: the server puts it on the event's own day, in the member's zone.
    expect(body.recurrence).toBe('weekly')
    expect(body.attendees).toEqual(['alex@example.com', 'work@corp.com'])
  })

  it('will not save an event without a title', async () => {
    const create = vi.spyOn(api.calendar, 'create').mockResolvedValue(event() as never)
    render(
      <EventSheet state={{ mode: 'create', day: '2026-09-18' }} tz="America/New_York" locale="en" onClose={noop} onChanged={noop} onEdit={noop} />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(create).not.toHaveBeenCalled()
  })

  it('will not save one that ends before it starts', async () => {
    const create = vi.spyOn(api.calendar, 'create').mockResolvedValue(event() as never)
    render(
      <EventSheet state={{ mode: 'create', day: '2026-09-18' }} tz="America/New_York" locale="en" onClose={noop} onChanged={noop} onEdit={noop} />,
    )
    await userEvent.type(screen.getByLabelText('Title'), 'Backwards')
    // Both ends set explicitly: the form starts at the next whole hour, so a
    // test that only sets the end passes by day and fails after midnight.
    fireEvent.change(screen.getByLabelText('Starts'), { target: { value: '2026-09-18T15:00' } })
    fireEvent.change(screen.getByLabelText('Ends'), { target: { value: '2026-09-18T08:00' } })
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    // The field's own min stops it first; the form checks again behind that.
    expect(create).not.toHaveBeenCalled()
  })
})

describe('reading an event', () => {
  it('says a repeat in words, and offers to change or delete it', async () => {
    render(
      <EventSheet
        state={{ mode: 'view', event: event({ recurrence: ['RRULE:FREQ=WEEKLY;BYDAY=TH'], location: '123 Main St' }) as never }}
        tz="America/New_York"
        locale="en"
        onClose={noop}
        onChanged={noop}
        onEdit={noop}
      />,
    )
    expect(screen.getByText('Every week on Thursday')).toBeInTheDocument()
    expect(screen.getByText('123 Main St')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })

  it('offers neither for time luach only reads', () => {
    render(
      <EventSheet
        state={{ mode: 'view', event: event({ title: 'Busy', read_only: true }) as never }}
        tz="America/New_York"
        locale="en"
        onClose={noop}
        onChanged={noop}
        onEdit={noop}
      />,
    )
    expect(screen.getByText(/only reads/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })

  it('asks before deleting', async () => {
    const remove = vi.spyOn(api.calendar, 'remove').mockResolvedValue({ ok: true } as never)
    render(
      <EventSheet state={{ mode: 'view', event: event() as never }} tz="America/New_York" locale="en" onClose={noop} onChanged={noop} onEdit={noop} />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(remove).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Delete for real' }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith('e1', 'home', undefined))
  })
})

describe('a repeating event', () => {
  // Thursday's occurrence of a weekly series, as the server lists it.
  const thursday = () =>
    event({ id: 'e1_20260917T190000Z', recurrence: ['RRULE:FREQ=WEEKLY;BYDAY=TH'], recurring_event_id: 'e1', occurrence: true })
  const edit = (ev: ReturnType<typeof event>) =>
    render(<EventSheet state={{ mode: 'edit', event: ev as never }} tz="America/New_York" locale="en" onClose={noop} onChanged={noop} onEdit={noop} />)

  it('opens an occurrence saying how its series repeats', () => {
    edit(thursday())
    expect(screen.getByLabelText('Repeats')).toHaveValue('weekly')
  })

  it('asks whether a change is to this event or every one, and does not send the repeat it showed', async () => {
    const update = vi.spyOn(api.calendar, 'update').mockResolvedValue(event() as never)
    edit(thursday())
    await userEvent.clear(screen.getByLabelText('Title'))
    await userEvent.type(screen.getByLabelText('Title'), 'Dentist, early')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(update).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'This event' }))
    await waitFor(() => expect(update).toHaveBeenCalled())
    const [id, body, calendarId, scope] = update.mock.calls[0]!
    expect([id, calendarId, scope]).toEqual(['e1_20260917T190000Z', 'home', 'this'])
    expect(body.title).toBe('Dentist, early')
    expect(body).not.toHaveProperty('recurrence')
  })

  it('saves for all events when asked to', async () => {
    const update = vi.spyOn(api.calendar, 'update').mockResolvedValue(event() as never)
    edit(thursday())
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await userEvent.click(screen.getByRole('button', { name: 'All events' }))
    await waitFor(() => expect(update).toHaveBeenCalled())
    expect(update.mock.calls[0]![3]).toBe('series')
  })

  it('goes back to the form without saving', async () => {
    const update = vi.spyOn(api.calendar, 'update').mockResolvedValue(event() as never)
    edit(thursday())
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
    expect(update).not.toHaveBeenCalled()
  })

  it('changes how every one repeats without asking: a repeat is the series’', async () => {
    const update = vi.spyOn(api.calendar, 'update').mockResolvedValue(event() as never)
    edit(thursday())
    await userEvent.selectOptions(screen.getByLabelText('Repeats'), 'biweekly')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(update).toHaveBeenCalled())
    const [, body, , scope] = update.mock.calls[0]!
    expect(body.recurrence).toBe('biweekly')
    expect(scope).toBe('series')
  })

  it('sends no repeat and no scope for an event that does not repeat', async () => {
    const update = vi.spyOn(api.calendar, 'update').mockResolvedValue(event() as never)
    edit(event())
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(update).toHaveBeenCalled())
    const [, body, , scope] = update.mock.calls[0]!
    expect(body).not.toHaveProperty('recurrence')
    expect(scope).toBeUndefined()
  })

  it('stops the series repeating when that is what was chosen', async () => {
    const update = vi.spyOn(api.calendar, 'update').mockResolvedValue(event() as never)
    edit(event({ recurrence: ['RRULE:FREQ=WEEKLY;BYDAY=TH'] }))
    await userEvent.selectOptions(screen.getByLabelText('Repeats'), 'none')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(update).toHaveBeenCalled())
    expect(update.mock.calls[0]![1].recurrence).toBe('')
  })

  it.each([
    ['This event', 'this'],
    ['All events', 'series'],
  ])('asks before deleting one: %s', async (button, scope) => {
    const remove = vi.spyOn(api.calendar, 'remove').mockResolvedValue({ ok: true } as never)
    render(<EventSheet state={{ mode: 'view', event: thursday() as never }} tz="America/New_York" locale="en" onClose={noop} onChanged={noop} onEdit={noop} />)
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.getByText(/Delete only this one, or every one/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete for real' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: button }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith('e1_20260917T190000Z', 'home', scope))
  })
})

describe("someone else's invitation", () => {
  it('opens to read, says who can change it, and shows its notes formatted', async () => {
    const invite = event({
      title: 'Interview with Acme',
      read_only: true,
      organizer: 'recruiting@acme.example',
      description: '<b>Join Google Meet:</b> <a href="https://meet.google.com/abc">https://meet.google.com/abc</a><ul><li><p>System design</p></li></ul>',
    } as never)
    render(<EventSheet state={{ mode: 'view', event: invite }} tz="America/New_York" locale="en" onClose={noop} onChanged={noop} onEdit={noop} />)
    expect(await screen.findByText(/An invitation from recruiting@acme\.example\. Only they can change it/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull()
    expect(screen.getByRole('link', { name: 'https://meet.google.com/abc' })).toHaveAttribute('href', 'https://meet.google.com/abc')
    expect(screen.queryByText(/<b>/)).toBeNull()
  })
})
