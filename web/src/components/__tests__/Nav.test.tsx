import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SideRail, TopNav, type TabDef } from '../Nav'
import { CalendarIcon, GearIcon, ShieldIcon } from '../Icons'
import { member } from '../../test/harness'

const tabs: TabDef[] = [
  { id: 'agenda', label: 'Agenda', icon: <CalendarIcon /> },
  { id: 'pending', label: 'Pending', icon: <ShieldIcon />, badge: 3 },
  { id: 'settings', label: 'Settings', icon: <GearIcon /> },
]

describe('the rail', () => {
  it('starts as icons, opens to names, and says which it is', async () => {
    render(<SideRail tabs={tabs} active="agenda" onSelect={() => {}} member={member} />)
    // Collapsed: the buttons are still named for a screen reader, but the
    // labels are not drawn and the member's name is not taking up room.
    expect(screen.getByRole('button', { name: 'Agenda' })).toBeInTheDocument()
    expect(screen.queryByText('Robin')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Expand the menu' }))
    expect(screen.getByText('Agenda')).toBeInTheDocument()
    expect(screen.getByText('Robin')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Collapse the menu' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('remembers how it was left', async () => {
    const first = render(<SideRail tabs={tabs} active="agenda" onSelect={() => {}} member={member} />)
    await userEvent.click(screen.getByRole('button', { name: 'Expand the menu' }))
    first.unmount()

    render(<SideRail tabs={tabs} active="agenda" onSelect={() => {}} member={member} />)
    expect(screen.getByRole('button', { name: 'Collapse the menu' })).toBeInTheDocument()
    expect(screen.getByText('Agenda')).toBeInTheDocument()
  })

  it('survives a browser that refuses storage', async () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('private mode')
    })
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('private mode')
    })
    render(<SideRail tabs={tabs} active="agenda" onSelect={() => {}} member={member} />)
    await userEvent.click(screen.getByRole('button', { name: 'Expand the menu' }))
    expect(screen.getByText('Agenda')).toBeInTheDocument()
    getItem.mockRestore()
    setItem.mockRestore()
  })

  it('moves between sections and carries the count of what is waiting', async () => {
    const onSelect = vi.fn()
    render(<SideRail tabs={tabs} active="agenda" onSelect={onSelect} member={member} />)
    // The count is in the name a screen reader says, not hidden behind it.
    await userEvent.click(screen.getByRole('button', { name: 'Pending, 3 waiting' }))
    expect(onSelect).toHaveBeenCalledWith('pending')
    expect(screen.getByRole('button', { name: 'Agenda' })).toBeInTheDocument()
  })
})

describe('the bar, where a rail will not fit', () => {
  it('names the sections and marks the one in view', async () => {
    const onSelect = vi.fn()
    render(<TopNav tabs={tabs} active="pending" onSelect={onSelect} member={member} />)
    expect(screen.getByRole('button', { name: 'Pending, 3 waiting' })).toHaveAttribute('aria-current', 'page')
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith('settings'))
  })
})
