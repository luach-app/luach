import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Assistant } from '../Assistant'
import * as api from '../../lib/api'
import * as sse from '../../lib/sse'
import { member } from '../../test/harness'

const summary = (over: Record<string, unknown> = {}) => ({
  id: 't1',
  title: 'what is on this week?',
  door: 'web',
  turns: 4,
  created_at: '2026-09-18T10:00:00+00:00',
  updated_at: '2026-09-21T10:00:00+00:00',
  ...over,
})

beforeEach(() => {
  sessionStorage.clear()
  vi.spyOn(api.voice, 'status').mockResolvedValue({ available: false } as never)
  vi.spyOn(api.threads, 'get').mockResolvedValue({ turns: [] } as never)
  vi.spyOn(api.threads, 'list').mockResolvedValue({
    threads: [summary(), summary({ id: 't2', title: 'dentist in october', turns: 2 })],
    retention_days: 60,
  } as never)
})

const open = async () => {
  render(<Assistant member={member} onHoldsChanged={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: 'Earlier conversations' }))
  return screen.findByRole('heading', { name: 'Conversations' })
}

describe('the conversations a member has already had', () => {
  it('lists them, newest first, with when and how long', async () => {
    await open()
    expect(screen.getByText('what is on this week?')).toBeInTheDocument()
    expect(screen.getByText(/4 messages/)).toBeInTheDocument()
    expect(screen.getByText(/2 messages/)).toBeInTheDocument()
  })

  it('opens one and shows the turns the server kept', async () => {
    const get = vi.spyOn(api.threads, 'get').mockResolvedValue({
      turns: [
        { role: 'user', content: 'what is on this week?', events: [], created_at: '' },
        { role: 'assistant', content: 'Two things.', events: [], created_at: '' },
      ],
    } as never)
    await open()
    await userEvent.click(screen.getByRole('button', { name: 'Open what is on this week?' }))
    await waitFor(() => expect(screen.getByText('Two things.')).toBeInTheDocument())
    expect(get).toHaveBeenCalledWith('t1')
    // Back on the conversation, not the list.
    expect(screen.queryByRole('heading', { name: 'Conversations' })).not.toBeInTheDocument()
  })

  it('renames one, because the first thing typed is rarely what it was about', async () => {
    const rename = vi.spyOn(api.threads, 'rename').mockResolvedValue({ id: 't1', title: 'the dentist' } as never)
    await open()
    await userEvent.click(screen.getByRole('button', { name: /Rename what is on this week/ }))
    const field = screen.getByRole('textbox', { name: 'Conversation name' })
    await userEvent.clear(field)
    await userEvent.type(field, 'the dentist{Enter}')
    await waitFor(() => expect(rename).toHaveBeenCalledWith('t1', 'the dentist'))
    await waitFor(() => expect(screen.getByText('the dentist')).toBeInTheDocument())
  })

  it('leaves the name alone on Escape', async () => {
    const rename = vi.spyOn(api.threads, 'rename')
    await open()
    await userEvent.click(screen.getByRole('button', { name: /Rename dentist in october/ }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Conversation name' }), 'x{Escape}')
    expect(rename).not.toHaveBeenCalled()
    expect(screen.getByText('dentist in october')).toBeInTheDocument()
  })

  it('deletes one and takes it out of the list', async () => {
    const remove = vi.spyOn(api.threads, 'remove').mockResolvedValue({ ok: true } as never)
    await open()
    await userEvent.click(screen.getByRole('button', { name: /Delete dentist in october/ }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith('t2'))
    await waitFor(() => expect(screen.queryByText('dentist in october')).not.toBeInTheDocument())
    expect(screen.getByText('what is on this week?')).toBeInTheDocument()
  })

  it('says how long they are kept, and where a thing worth keeping goes instead', async () => {
    await open()
    expect(screen.getByText(/kept for 60 days/)).toBeInTheDocument()
    expect(screen.getByText(/tell it to remember/)).toBeInTheDocument()
  })

  it('says so plainly when there are none', async () => {
    vi.spyOn(api.threads, 'list').mockResolvedValue({ threads: [], retention_days: 60 } as never)
    await open()
    expect(screen.getByText(/Nothing yet/)).toBeInTheDocument()
    // No retention footnote when there is nothing to retain.
    expect(screen.queryByText(/kept for/)).not.toBeInTheDocument()
  })

  it('marks the one that is open', async () => {
    vi.spyOn(sse, 'streamAgent').mockImplementation(async (_b, onFrame) => {
      onFrame({ type: 'session', thread_id: 't1' } as never)
      onFrame({ type: 'done', reply: 'ok', thread_id: 't1' } as never)
    })
    render(<Assistant member={member} onHoldsChanged={() => {}} />)
    await userEvent.type(screen.getByPlaceholderText(/Ask luach/i), 'hello{Enter}')
    await waitFor(() => expect(screen.getByText('ok')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: 'Earlier conversations' }))
    const row = await screen.findByRole('button', { name: 'Open what is on this week?' })
    expect(row).toHaveAttribute('aria-current', 'true')
    expect(within(screen.getByRole('list')).getAllByRole('listitem')).toHaveLength(2)
  })

  it('lets the panel go back to the conversation', async () => {
    await open()
    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.queryByRole('heading', { name: 'Conversations' })).not.toBeInTheDocument()
    expect(screen.getByPlaceholderText(/Ask luach/i)).toBeInTheDocument()
  })
})
