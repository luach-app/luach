import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChatTurn } from '../ChatTurn'
import { Composer } from '../Composer'
import { applyFrame, newTurn, turnsFromThread } from '../../lib/turns'
import type { StreamFrame } from '../../lib/types'

const ctx = { tz: 'America/New_York', locale: 'en', onOpenEvent: () => {}, onDecided: () => {} }

describe('the model that answered', () => {
  it('is the one the stream last named, and done has the final word', () => {
    const frames = [
      { type: 'model', name: 'qwen3.6-35b' },
      { type: 'model', name: 'fallback' },
      { type: 'token', text: 'Hi' },
      { type: 'done', reply: 'Hi', thread_id: 't', tool_calls: [], held: [], created: [], model: 'fallback' },
    ] as StreamFrame[]
    const t = frames.reduce((acc, f) => applyFrame(acc, f), newTurn('assistant', '', true))
    expect(t.model).toBe('fallback')
  })

  it('is shown under a finished answer, not while it streams', () => {
    const turn = { ...newTurn('assistant', 'Two things.', true), model: 'qwen3.6-35b' }
    const { rerender } = render(<ChatTurn turn={turn} {...ctx} />)
    expect(screen.queryByTestId('turn-model')).toBeNull()
    rerender(<ChatTurn turn={{ ...turn, streaming: false }} {...ctx} />)
    expect(screen.getByTestId('turn-model')).toHaveTextContent('qwen3.6-35b')
  })
})

describe('copying an answer', () => {
  it('puts the words on the clipboard and says so', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    render(<ChatTurn turn={newTurn('assistant', 'Dinner is at 7.')} {...ctx} />)
    await user.click(screen.getByRole('button', { name: 'Copy the answer' }))
    expect(writeText).toHaveBeenCalledWith('Dinner is at 7.')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument())
  })
})

describe('stopping an answer', () => {
  it('turns Send into Stop while luach is answering', async () => {
    const onStop = vi.fn()
    const { rerender } = render(<Composer micAvailable={false} onSend={() => {}} onError={() => {}} />)
    expect(screen.queryByRole('button', { name: 'Stop answering' })).toBeNull()
    rerender(<Composer disabled streaming onStop={onStop} micAvailable={false} onSend={() => {}} onError={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Stop answering' }))
    expect(onStop).toHaveBeenCalled()
  })

  it('comes back from the thread as stopped, without the mark in the words', () => {
    const [, t] = turnsFromThread([
      { role: 'user', content: 'picnic', events: [], created_at: '' },
      { role: 'assistant', content: 'Added\n\n(stopped)', events: [], created_at: '' },
    ] as never)
    expect(t?.text).toBe('Added')
    expect(t?.stopped).toBe(true)
  })

  it('keeps a turn stopped before it said a word', () => {
    const turns = turnsFromThread([
      { role: 'user', content: 'add piano for Lily', events: [], created_at: '' },
      { role: 'assistant', content: '(stopped)', events: [], created_at: '' },
    ] as never)
    expect(turns).toHaveLength(2)
    expect(turns[1]?.text).toBe('')
    expect(turns[1]?.stopped).toBe(true)
  })
})
