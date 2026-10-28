import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Memory } from '../Memory'
import * as api from '../../lib/api'

const fact = (f: string, key = f.toLowerCase()) => ({ key, topic: '', fact: f, saved_at: '' })

describe('what luach remembers', () => {
  it('lists your facts, keeps a new one, and forgets one', async () => {
    vi.spyOn(api.memory, 'list').mockResolvedValue({ facts: [fact('I only book mornings')] })
    const add = vi.spyOn(api.memory, 'add').mockResolvedValue({ facts: [fact('I only book mornings'), fact('We keep Friday nights clear')] })
    const remove = vi.spyOn(api.memory, 'remove').mockResolvedValue({ ok: true, facts: [fact('We keep Friday nights clear')] })
    render(<Memory />)
    expect(await screen.findByText('I only book mornings')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Tell luach something to keep'), 'We keep Friday nights clear')
    await userEvent.click(screen.getByRole('button', { name: 'Keep' }))
    await waitFor(() => expect(add).toHaveBeenCalledWith('We keep Friday nights clear'))
    await userEvent.click(await screen.findByRole('button', { name: 'Forget: I only book mornings' }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith('i only book mornings'))
    expect(screen.queryByText('I only book mornings')).toBeNull()
  })

  it('says so when this box has no memory', async () => {
    vi.spyOn(api.memory, 'list').mockRejectedValue(new Error('luach has no memory configured here'))
    render(<Memory />)
    expect(await screen.findByText(/no memory configured/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Keep' })).toBeNull()
  })
})
