import { describe, expect, it, vi } from 'vitest'
import { ApiError, auth, booking, busy, calendar, errorMessage, setUnauthorizedHandler } from '../api'
import { boardApi } from '../board'

/** A fresh Response per call: a body can only be read once. */
const replies = (status: number, body: unknown) =>
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  )

describe('talking to luach', () => {
  it('sends JSON and reads JSON back', async () => {
    const fetchMock = replies(200, { ok: true })
    await expect(booking.update({ enabled: true })).resolves.toEqual({ ok: true })
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/booking')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(String(init.body))).toEqual({ enabled: true })
  })

  it('turns a refusal into an ApiError carrying the server’s sentence', async () => {
    replies(400, { error: 'that time has just been taken' })
    await expect(booking.take('robin', { start: 'x', name: 'Dana', email: 'd@x.io' })).rejects.toMatchObject({
      status: 400,
      message: 'that time has just been taken',
    })
  })

  it('escalates a lost session exactly once, and not for the login form', async () => {
    const lost = vi.fn()
    setUnauthorizedHandler(lost)
    replies(401, { error: 'sign in first' })
    await expect(calendar.list('2026-09-01', '2026-09-30')).rejects.toBeInstanceOf(ApiError)
    expect(lost).toHaveBeenCalledTimes(1)

    lost.mockClear()
    await expect(auth.login('robin', 'wrong')).rejects.toBeInstanceOf(ApiError)
    expect(lost).not.toHaveBeenCalled()
    setUnauthorizedHandler(null)
  })

  it('encodes what goes into a path', async () => {
    const fetchMock = replies(200, {})
    await busy.remove(7)
    await booking.manage('robin k', 'a/b')
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/busy/7')
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/book/robin%20k/manage/a%2Fb')
  })

  it('says which calendar, and for one occurrence of a repeat which of them, in the query', async () => {
    const fetchMock = replies(200, {})
    await calendar.update('s1_20260917T190000Z', { title: 'x' }, 'family@x', 'this')
    await calendar.remove('s1_20260917T190000Z', '', 'series')
    await calendar.remove('e1')
    await boardApi.events('t').update('s1_x', { title: 'x' }, 'home', 'series')
    await boardApi.events('t').remove('s1_x', '', 'this')
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      '/api/calendar/events/s1_20260917T190000Z?calendar=family%40x&scope=this',
      '/api/calendar/events/s1_20260917T190000Z?scope=series',
      '/api/calendar/events/e1',
      '/api/board/events/s1_x?calendar=home&scope=series',
      '/api/board/events/s1_x?scope=this',
    ])
  })
})

describe('what a person is told went wrong', () => {
  it('passes the server’s words through', () => {
    expect(errorMessage(new ApiError(400, 'confirm that address first'))).toBe('confirm that address first')
  })

  it('says when to try again after a throttle', () => {
    expect(errorMessage(new ApiError(429, 'too many bookings.', 42))).toContain('42 s')
  })

  it('explains a request that ran out of time, and stays quiet about one that was cancelled', () => {
    expect(errorMessage(new DOMException('timeout', 'TimeoutError'))).toContain('too long')
    expect(errorMessage(new DOMException('aborted', 'AbortError'))).toBe('')
  })

  it('never returns an empty message for a real error', () => {
    expect(errorMessage(new Error(''))).toBe('Something went wrong.')
    expect(errorMessage('a string')).toBe('Something went wrong.')
  })
})
