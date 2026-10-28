import { describe, expect, it } from 'vitest'
import { eventLink, isRecurring } from '../events'
import { reasonLabel, stepLabel, stepResult, toolPhrase } from '../labels'

describe('what a card links to', () => {
  it('prefers the full link but takes the compact one', () => {
    expect(eventLink({ title: 'x', html_link: 'a' } as never)).toBe('a')
    expect(eventLink({ title: 'x', link: 'b' } as never)).toBe('b')
    expect(eventLink({ title: 'x' } as never)).toBe('')
  })

  it('knows a repeat however it was described', () => {
    expect(isRecurring({ title: 'x', recurring: true } as never)).toBe(true)
    expect(isRecurring({ title: 'x', recurring_event_id: 'r1' } as never)).toBe(true)
    expect(isRecurring({ title: 'x', recurrence: ['RRULE:FREQ=DAILY'] } as never)).toBe(true)
    expect(isRecurring({ title: 'x' } as never)).toBe(false)
  })
})

describe('the words a person reads', () => {
  it('turns a hold reason into a sentence', () => {
    expect(reasonLabel('past' as never)).toBeTruthy()
    expect(reasonLabel('possible-duplicate' as never)).toBeTruthy()
    // Something luach has no phrase for still reads as itself.
    expect(reasonLabel('brand-new-reason' as never)).toBe('brand new reason')
  })

  it('says what a tool is doing in words', () => {
    expect(toolPhrase('create_event')).toMatch(/calendar|add/i)
    expect(toolPhrase('list_events')).toMatch(/check|calendar/i)
    // A task is not on the calendar: the chip said so while giving Lily a to-do.
    expect(toolPhrase('add_task')).toBe('adding a task…')
    expect(toolPhrase('list_tasks')).not.toMatch(/calendar/)
    expect(toolPhrase('complete_task')).not.toMatch(/calendar/)
    expect(toolPhrase('something_else')).toBeTruthy()
  })
})

describe('a step of the work, in words', () => {
  it('says what it is doing with the particulars it was given', () => {
    expect(stepLabel('list_events', { start_date: '2026-10-06', end_date: '2026-10-12' })).toBe('Reading the calendar · Tue 6 – Mon 12 Oct')
    expect(stepLabel('list_events', { start_date: '2026-09-30', end_date: '2026-10-06' })).toBe('Reading the calendar · Wed 30 Sep – Tue 6 Oct')
    expect(stepLabel('list_events', { start_date: '2026-10-01', end_date: '2026-10-01' })).toBe('Reading the calendar · Thu 1 Oct')
    expect(stepLabel('find_events', { query: 'dentist' })).toBe('Looking for “dentist”')
    expect(stepLabel('check_availability', { start: '2026-10-02T16:00:00-04:00', end: '2026-10-02T17:00:00-04:00' })).toBe('Checking Fri 2 Oct, 16:00–17:00')
    expect(stepLabel('create_event', { title: 'Dentist', start: '2026-10-07T15:00' })).toBe('Adding “Dentist” · Wed 7 Oct 15:00')
    expect(stepLabel('search_email', { query: 'flight' })).toBe('Searching your email for “flight”')
    expect(stepLabel('search_the_web', { query: 'Leafs score' })).toBe('Searching the web for “Leafs score”')
    expect(stepLabel('add_task', { title: 'Pack the bag', for_whom: 'Sam' })).toBe('Adding the task “Pack the bag” for Sam')
    expect(stepLabel('complete_task', { task_id: 3 })).toBe('Ticking a task off')
    expect(stepLabel('forget', { what: 'the gym' })).toBe('Forgetting “the gym”')
  })

  it('keeps a long fact short, and tells recall from remembering', () => {
    const label = stepLabel('remember', { fact: 'Sam is allergic to peanuts and also to tree nuts, so no pesto at all ever' })
    expect(label.startsWith('Remembering: Sam is allergic')).toBe(true)
    expect(label.endsWith('…')).toBe(true)
    expect(label.length).toBeLessThan(64)
    expect(stepLabel('remember', { topic: 'school' })).toBe('Recalling what it knows about “school”')
  })

  it('names a guide in words, not its folder', () => {
    expect(stepLabel('repeating-events', undefined, 'skill')).toBe('Following the guide: repeating events')
  })

  it('falls back gracefully on what it cannot read', () => {
    expect(stepLabel('list_events', {})).toBe('Reading the calendar')
    expect(stepLabel('check_availability', { start: 'friday at 4' })).toBe('Checking friday at 4')
    expect(stepLabel('find_events', { query: 42 })).toBe('Looking through the calendar')
    expect(stepLabel('lookup_weather', {})).toBe('Checking the calendar')
  })
})

describe('what a step found, in a few words', () => {
  it('counts what came back', () => {
    expect(stepResult('list_events', { count: 12, events: [] })).toBe('12 events')
    expect(stepResult('list_events', { count: 1, events: [] })).toBe('1 event')
    expect(stepResult('list_events', { count: 0, events: [] })).toBe('nothing on')
    expect(stepResult('find_events', { count: 3 })).toBe('3 matches')
    expect(stepResult('search_email', { count: 4, emails: [] })).toBe('4 messages')
    expect(stepResult('search_email', { count: 0, emails: [] })).toBe('no email matched')
    expect(stepResult('search_the_web', { count: 5, results: [] })).toBe('5 results')
    expect(stepResult('list_tasks', { day: 'x', count: 2, tasks: [] })).toBe('2 tasks')
  })

  it('says whether the time is free, and what is in the way', () => {
    expect(stepResult('check_availability', { free: true, clashes: [] })).toBe('free')
    expect(stepResult('check_availability', { free: false, clashes: [{ title: 'Swim' }] })).toBe('busy — clashes with Swim')
    expect(stepResult('check_availability', { free: false, clashes: [{ title: 'Swim' }, { title: 'Piano' }] })).toBe('busy — clashes with Swim +1')
  })

  it('says a write went through, or is waiting on a person', () => {
    expect(stepResult('create_event', { created: { title: 'Dentist' } })).toBe('added')
    expect(stepResult('create_event', { status: 'held_for_approval', approval_id: 'h1' })).toBe('waiting for your yes')
    expect(stepResult('delete_event', { deleted: 'e1', title: 'Gym' })).toBe('removed')
    expect(stepResult('add_task', { added: { task: 'x' } })).toBe('added')
    expect(stepResult('read_email', { email: { subject: 'Your flight' } })).toBe('“Your flight”')
  })

  it('says what went wrong without the instructions meant for the model', () => {
    expect(stepResult('get_event', null, 'boom')).toBe("couldn't: boom")
    expect(stepResult('search_email', { error: 'their email is not connected (or needs connecting again); say so' })).toBe(
      "couldn't: their email is not connected (or needs connecting again)",
    )
    expect(stepResult('create_event', { error: 'Not added yet: whose is it? The message names Sam. If it is theirs…' })).toBe(
      "couldn't: Not added yet: whose is it?",
    )
    expect(stepResult('get_event', null, 'x'.repeat(200)).length).toBeLessThanOrEqual(70)
  })

  it('says nothing about a shape it does not know', () => {
    expect(stepResult('list_events', 'not json')).toBe('')
    expect(stepResult('list_events', [1, 2])).toBe('')
    expect(stepResult('mystery_tool', { count: 3 })).toBe('')
    expect(stepResult('find_events', {})).toBe('')
  })
})
