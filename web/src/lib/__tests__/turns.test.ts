import { describe, expect, it } from 'vitest'
import { applyFrame, isWidget, newTurn, settle, turnsFromThread } from '../turns'
import type { StreamFrame } from '../types'

// Not `reduce(applyFrame)`: reduce passes the index third, where the clock goes.
const fold = (frames: StreamFrame[], start = 1000) =>
  frames.reduce((t, f, i) => applyFrame(t, f, start + i * 100), newTurn('assistant', '', true))

describe('folding a stream into a turn', () => {
  it('builds the reply from its tokens', () => {
    const t = fold([
      { type: 'token', text: 'Added ' },
      { type: 'token', text: 'Dentist.' },
    ] as StreamFrame[])
    expect(t.text).toBe('Added Dentist.')
  })

  it('drops the words a retract takes back, so a repeated answer shows once', () => {
    // The answer, a tool, the same answer again: the server takes the first back.
    const t = fold([
      { type: 'token', text: 'Hi there!' },
      { type: 'retract' },
      { type: 'token', text: 'Hi ' },
      { type: 'token', text: 'there!' },
    ] as StreamFrame[])
    expect(t.text).toBe('Hi there!')
  })

  it('marks a tool done when its result comes back, and keeps the error', () => {
    const t = fold([
      { type: 'tool_start', tool: 'create_event', args: { title: 'Dentist' } },
      { type: 'tool_result', tool: 'create_event', result: {}, error: 'nope' },
    ] as StreamFrame[])
    expect(t.activity).toEqual([
      {
        tool: 'create_event',
        args: { title: 'Dentist' },
        kind: 'tool',
        done: true,
        error: 'nope',
        summary: "couldn't: nope",
        startedAt: 1000,
        endedAt: 1100,
      },
    ])
  })

  it('keeps what each step was asked and what it found', () => {
    const t = fold([
      { type: 'tool_start', tool: 'list_events', args: { start_date: '2026-10-05', end_date: '2026-10-11' } },
      { type: 'tool_result', tool: 'list_events', result: { count: 4, events: [] } },
      { type: 'tool_start', tool: 'check_availability', args: { start: '2026-10-02T16:00', end: '2026-10-02T17:00' } },
      { type: 'tool_result', tool: 'check_availability', result: { free: false, clashes: [{ title: 'Swim' }] } },
    ] as StreamFrame[])
    expect(t.activity.map((a) => a.summary)).toEqual(['4 events', 'busy — clashes with Swim'])
    expect(t.activity[0]?.args).toEqual({ start_date: '2026-10-05', end_date: '2026-10-11' })
    expect(t.activity.every((a) => a.done && !a.error)).toBe(true)
  })

  it('counts a refusal the tool wrote as a step that failed', () => {
    const t = fold([
      { type: 'tool_start', tool: 'get_event', args: { event_id: 'x' } },
      { type: 'tool_result', tool: 'get_event', result: { error: 'no such event' } },
    ] as StreamFrame[])
    expect(t.activity[0]?.error).toBe('no such event')
    expect(t.activity[0]?.summary).toBe("couldn't: no such event")
  })

  it('tells a held write from one that went through', () => {
    const t = fold([
      { type: 'tool_start', tool: 'create_event', args: { title: 'Dentist' } },
      { type: 'tool_result', tool: 'create_event', result: { status: 'held_for_approval', approval_id: 'h1' } },
    ] as StreamFrame[])
    expect(t.activity[0]).toMatchObject({ done: true, held: true, summary: 'waiting for your yes' })
    expect(t.activity[0]?.error).toBeUndefined()
  })

  it('records a guide it read as a finished step of its own', () => {
    const t = fold([
      { type: 'skill', name: 'repeating-events' },
      { type: 'tool_start', tool: 'create_event', args: {} },
    ] as StreamFrame[])
    expect(t.activity.map((a) => [a.kind, a.tool, a.done])).toEqual([
      ['skill', 'repeating-events', true],
      ['tool', 'create_event', false],
    ])
  })

  it('keeps the step when the widget it drew arrives', () => {
    // The chip used to vanish when its widget came. The trace is the record of
    // the work: a step does not stop having happened because it found something.
    const t = fold([
      { type: 'tool_start', tool: 'list_events', args: {} },
      { type: 'tool_result', tool: 'list_events', result: { count: 0, events: [] } },
      { type: 'widget', kind: 'agenda', data: { events: [] } },
    ] as unknown as StreamFrame[])
    expect(t.widgets).toHaveLength(1)
    expect(t.activity).toHaveLength(1)
  })

  it('times the turn from its first frame to done', () => {
    const t = fold([
      { type: 'model', name: 'm' },
      { type: 'tool_start', tool: 'list_events', args: {} },
      { type: 'done', reply: 'ok' },
    ] as unknown as StreamFrame[])
    expect(t.startedAt).toBe(1000)
    expect(t.endedAt).toBe(1200)
    // A step still running when the turn ended is finished then, not left pulsing.
    expect(t.activity[0]).toMatchObject({ done: true, endedAt: 1200 })
  })

  it('settles a turn the stream left mid-step, once', () => {
    const working = fold([{ type: 'tool_start', tool: 'find_events', args: { query: 'dentist' } }] as StreamFrame[])
    const once = settle(working, 5000)
    expect(once).toMatchObject({ streaming: false, endedAt: 5000 })
    expect(once.activity[0]).toMatchObject({ done: true, endedAt: 5000 })
    expect(settle(once, 9000).endedAt).toBe(5000)
  })

  it('holds an approval once, however many times it is announced', () => {
    const held = { type: 'held', id: 'h1', tool: 'update_event', summary: 'move it', reason: ['past'] }
    const t = fold([held, held] as unknown as StreamFrame[])
    expect(t.held).toHaveLength(1)
    expect(t.held[0]?.status).toBe('pending')
  })

  it('finishes on done, and the server has the last word', () => {
    // Normally `reply` is just what streamed, so preferring it changes nothing.
    // It matters when the server replaced the answer — a turn that called no
    // tool, ran out of steps, or went quiet. Those rewrites exist precisely
    // because the streamed text was not true, and keeping the tokens threw
    // every one of them away.
    const t = fold([
      { type: 'token', text: 'Added: Tennis, Sat 19 Sep 16:00' },
      { type: 'done', reply: 'I did not actually do anything just then.', created: [{ id: 'e1', title: 'Dentist' }] },
    ] as unknown as StreamFrame[])
    expect(t.text).toBe('I did not actually do anything just then.')
    expect(t.created).toHaveLength(1)
    expect(t.streaming).toBe(false)
  })

  it('keeps what streamed when done carries no reply', () => {
    const t = fold([
      { type: 'token', text: 'Added it.' },
      { type: 'done', created: [] },
    ] as unknown as StreamFrame[])
    expect(t.text).toBe('Added it.')
  })

  it('takes the reply from done when nothing streamed', () => {
    const t = fold([{ type: 'done', reply: 'Nothing on the calendar.' }] as unknown as StreamFrame[])
    expect(t.text).toBe('Nothing on the calendar.')
  })

  it('carries an error through instead of pretending', () => {
    const t = fold([{ type: 'error', message: 'The model got stuck repeating itself.' }] as StreamFrame[])
    expect(t.error).toContain('stuck')
    expect(t.streaming).toBe(false)
  })

  it('ignores a frame it does not know', () => {
    const before = newTurn('assistant')
    expect(applyFrame(before, { type: 'session', thread_id: 'x' } as StreamFrame)).toEqual(before)
  })
})

describe('rebuilding a thread', () => {
  it('keeps the turns that said something and drops the empty ones', () => {
    const turns = turnsFromThread([
      { role: 'user', content: 'what is on today?', events: [] },
      { role: 'assistant', content: 'One thing.', events: [{ widget: { kind: 'agenda', data: { events: [] } } }] },
      { role: 'assistant', content: '', events: [] },
      { role: 'tool', content: 'internal', events: [] },
    ] as never)
    expect(turns.map((t) => t.role)).toEqual(['user', 'assistant'])
    expect(turns[1]?.widgets).toHaveLength(1)
  })

  it('recognises a widget only when it is really one', () => {
    expect(isWidget({ kind: 'agenda', data: {} })).toBe(true)
    expect(isWidget({ kind: 'nonsense', data: {} })).toBe(false)
    expect(isWidget({ kind: 'agenda' })).toBe(false)
    expect(isWidget(null)).toBe(false)
  })
})

describe('reasoning', () => {
  it('collects thinking separately from the answer', () => {
    let t = newTurn('assistant', '', true)
    t = applyFrame(t, { type: 'thinking', text: 'they mean Saturday. ' })
    t = applyFrame(t, { type: 'thinking', text: 'checking for a clash' })
    t = applyFrame(t, { type: 'token', text: 'Added: Tennis' })
    expect(t.thinking).toBe('they mean Saturday. checking for a clash')
    expect(t.text).toBe('Added: Tennis')
  })
})


describe('a question back is not a failure', () => {
  it('shows "whose is it?" as waiting for the person, not as an error', async () => {
    const { applyFrame, newTurn } = await import('../turns')
    let t = newTurn('assistant', '', true)
    t = applyFrame(t, { type: 'tool_start', tool: 'add_task', args: { title: 'Pack the swim bag' } }, 1000)
    t = applyFrame(t, { type: 'tool_result', tool: 'add_task', result: { error: 'Not added yet: whose is it? The message names Sam. If it is theirs…' } }, 1500)
    const step = t.activity[0]!
    expect(step.error).toBeUndefined()
    expect(step.held).toBe(true)
    expect(step.summary).toBe('asking whose it is')
  })

  it('a real refusal is still a failure', async () => {
    const { applyFrame, newTurn } = await import('../turns')
    let t = newTurn('assistant', '', true)
    t = applyFrame(t, { type: 'tool_start', tool: 'get_event', args: { event_id: 'x' } }, 1000)
    t = applyFrame(t, { type: 'tool_result', tool: 'get_event', result: { error: 'no such event' } }, 1200)
    expect(t.activity[0]!.error).toBe('no such event')
  })
})
