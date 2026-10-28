import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Boards } from '../Boards'
import * as api from '../../lib/api'

const kitchen = { id: 3, name: 'Kitchen', created_at: '2026-09-01T00:00:00Z', last_seen: null, can_edit: true }

describe('house boards', () => {
  it('says so when the list cannot load, rather than showing none', async () => {
    vi.spyOn(api.api, 'get').mockRejectedValue(new api.ApiError(500, 'luach is having a moment'))
    render(<Boards locale="en" />)
    expect(await screen.findByText('luach is having a moment')).toBeInTheDocument()
  })

  it('asks before unpairing a screen on the wall', async () => {
    vi.spyOn(api.api, 'get').mockResolvedValue({ boards: [kitchen] })
    const del = vi.spyOn(api.api, 'del').mockResolvedValue({ ok: true })
    render(<Boards locale="en" />)
    await userEvent.click(await screen.findByRole('button', { name: 'Remove Kitchen' }))
    await userEvent.click(screen.getByRole('button', { name: 'Keep' }))
    expect(del).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Remove Kitchen' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('/api/boards/3'))
  })

  it('gives each screen its language, and says when it is saved', async () => {
    vi.spyOn(api.api, 'get').mockResolvedValue({ boards: [kitchen] })
    const patch = vi.spyOn(api.api, 'patch').mockResolvedValue({ boards: [{ ...kitchen, language: 'he' }] })
    render(<Boards locale="en" />)
    const select = await screen.findByLabelText('Language')
    // A board from before languages follows its screen.
    expect(select).toHaveValue('auto')
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Automatic', 'English', 'Español', 'עברית'])
    await userEvent.selectOptions(select, 'he')
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/api/boards/3', { language: 'he' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Saved.')
    expect(screen.getByLabelText('Language')).toHaveValue('he')
  })

  it('keeps the language it had when the change does not go through, and says why', async () => {
    vi.spyOn(api.api, 'get').mockResolvedValue({ boards: [{ ...kitchen, language: 'es' }] })
    vi.spyOn(api.api, 'patch').mockRejectedValue(new api.ApiError(400, 'language is one of auto, en, es, he'))
    render(<Boards locale="en" />)
    await userEvent.selectOptions(await screen.findByLabelText('Language'), 'en')
    expect(await screen.findByText('language is one of auto, en, es, he')).toBeInTheDocument()
    expect(screen.getByLabelText('Language')).toHaveValue('es')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('still lets the owner make a screen show only', async () => {
    vi.spyOn(api.api, 'get').mockResolvedValue({ boards: [kitchen] })
    const patch = vi.spyOn(api.api, 'patch').mockResolvedValue({ boards: [{ ...kitchen, can_edit: false }] })
    render(<Boards locale="en" />)
    await userEvent.click(await screen.findByRole('checkbox', { name: /Anyone at it can add/ }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/api/boards/3', { can_edit: false }))
  })
})
