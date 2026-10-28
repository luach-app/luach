import { describe, expect, it } from 'vitest'
import { changesTheCalendar } from '../assistantFrames'
import type { StreamFrame } from '../../lib/types'

/**
 * The calendar used to redraw on every frame, so asking "when does Messi play"
 * rebuilt the month for an answer that touched nothing.
 */
describe('when the calendar beside the chat should refresh', () => {
  const frame = (f: unknown) => changesTheCalendar(f as StreamFrame)

  it('refreshes once a write tool has actually written', () => {
    expect(frame({ type: 'tool_result', tool: 'create_event', result: {} })).toBe(true)
    expect(frame({ type: 'tool_result', tool: 'update_event', result: {} })).toBe(true)
    expect(frame({ type: 'tool_result', tool: 'delete_event', result: {} })).toBe(true)
    expect(frame({ type: 'done', created: [{ title: 'Tennis', start: '2026-09-19T16:00' }] })).toBe(true)
  })

  it('leaves the month alone for anything that only looked', () => {
    expect(frame({ type: 'tool_result', tool: 'search_the_web', result: {} })).toBe(false)
    expect(frame({ type: 'tool_result', tool: 'list_events', result: {} })).toBe(false)
    expect(frame({ type: 'tool_result', tool: 'just_talking', result: {} })).toBe(false)
    expect(frame({ type: 'token', text: 'Added' })).toBe(false)
    expect(frame({ type: 'done', created: [] })).toBe(false)
  })

  it('leaves it alone when the write failed', () => {
    expect(frame({ type: 'tool_result', tool: 'create_event', error: 'calendar said no' })).toBe(false)
  })
})
