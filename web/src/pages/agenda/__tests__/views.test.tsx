import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MonthPicker } from '../MonthPicker'
import { Upcoming } from '../Upcoming'
import * as api from '../../../lib/api'
import { invalidateHousehold } from '../../../lib/household'
import { event } from '../../../test/harness'

describe('choosing a month', () => {
  it('offers the year’s months and hands back the one picked', async () => {
    const onPick = vi.fn()
    render(<MonthPicker ym="2026-09" todayYm="2026-09" locale="en" onPick={onPick} onClose={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: /^Jan/ }))
    expect(onPick).toHaveBeenCalledWith('2026-01')
  })

  it('closes without choosing', async () => {
    const onClose = vi.fn()
    render(<MonthPicker ym="2026-09" todayYm="2026-09" locale="en" onPick={() => {}} onClose={onClose} />)
    await userEvent.click(screen.getAllByRole('button', { name: /Close/i })[0]!)
    expect(onClose).toHaveBeenCalled()
  })
})

describe('what is upcoming', () => {
  const today = new Date().toISOString().slice(0, 10)

  beforeEach(() => {
    invalidateHousehold()
    vi.spyOn(api.household, 'calendars').mockResolvedValue({ available: [], calendars: ['home'], default_calendar: 'home', default_attendees: [] } as never)
  })

  it('shows the days ahead and opens what is on them', async () => {
    vi.spyOn(api.calendar, 'list').mockResolvedValue({
      events: [event({ start: `${today}T15:00:00-04:00`, end: `${today}T16:00:00-04:00` })],
      timezone: 'America/New_York',
      start: today,
      end: today,
    } as never)
    const onOpen = vi.fn()
    render(<Upcoming tz="America/New_York" locale="en" version={0} selected={today} onSelect={() => {}} onOpen={onOpen} onCreate={() => {}} />)
    await waitFor(() => expect(screen.getAllByText('Dentist').length).toBeGreaterThan(0))
    await userEvent.click(screen.getAllByRole('button', { name: /Dentist/ })[0]!)
    expect(onOpen).toHaveBeenCalled()
  })

  it('says when a day is empty, and offers to fill it', async () => {
    vi.spyOn(api.calendar, 'list').mockResolvedValue({ events: [], timezone: 'America/New_York', start: '', end: '' } as never)
    const onCreate = vi.fn()
    render(<Upcoming tz="America/New_York" locale="en" version={0} selected={today} onSelect={() => {}} onOpen={() => {}} onCreate={onCreate} />)
    await waitFor(() => expect(screen.getByText(/Nothing on/i)).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /Add something/i }))
    expect(onCreate).toHaveBeenCalled()
  })

  it('shows what went wrong rather than an empty strip', async () => {
    vi.spyOn(api.calendar, 'list').mockRejectedValue(new api.ApiError(500, 'the calendar is unreachable'))
    render(<Upcoming tz="America/New_York" locale="en" version={0} selected={today} onSelect={() => {}} onOpen={() => {}} onCreate={() => {}} />)
    await waitFor(() => expect(screen.getByText('the calendar is unreachable')).toBeInTheDocument())
  })
})
