import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BUILD_POLL_MS, IDLE_MS, ownBuild, useNewBuild, useSelfUpdate } from '../selfUpdate'

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-02T09:00:00Z'))
})
afterEach(() => {
  vi.useRealTimers()
  document.head.innerHTML = ''
})

const settle = () => act(async () => {})

function wall({ server = ['/assets/index-B2.js'], quiet = true, touched = Date.now() - 2 * IDLE_MS, mine = 'index-A1.js' }: { server?: string[]; quiet?: boolean; touched?: number; mine?: string } = {}) {
  const reload = vi.fn()
  const answers = [...server]
  const serverBuild = vi.fn(async () => (answers.length > 1 ? answers.shift() : answers[0]) ?? '')
  const state = { quiet, touched }
  const hook = renderHook(({ enabled }) => useSelfUpdate(enabled, { serverBuild, quiet: () => state.quiet, lastTouch: () => state.touched, reload, mine }), { initialProps: { enabled: true } })
  return { reload, serverBuild, state, hook }
}

describe('a wall board after a deploy', () => {
  it('reloads itself when the server hands out a new build and nobody is using it', async () => {
    const { reload } = wall()
    await settle()
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('stays put while the build is the one it runs', async () => {
    const { reload, serverBuild } = wall({ server: ['/assets/index-A1.js'] })
    await settle()
    await act(async () => {
      vi.advanceTimersByTime(BUILD_POLL_MS * 3)
    })
    expect(serverBuild.mock.calls.length).toBeGreaterThanOrEqual(3)
    expect(reload).not.toHaveBeenCalled()
  })

  it('waits for a minute without a touch before reloading', async () => {
    const { reload, state } = wall({ touched: Date.now() })
    await settle()
    expect(reload).not.toHaveBeenCalled()
    await act(async () => {
      vi.advanceTimersByTime(IDLE_MS / 2)
    })
    expect(reload).not.toHaveBeenCalled()
    state.touched = Date.now() // someone tapped again
    await act(async () => {
      vi.advanceTimersByTime(IDLE_MS - 1_000)
    })
    expect(reload).not.toHaveBeenCalled()
    await act(async () => {
      vi.advanceTimersByTime(15_000)
    })
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('never reloads under an open sheet or a card being carried', async () => {
    const { reload, state } = wall({ quiet: false })
    await settle()
    await act(async () => {
      vi.advanceTimersByTime(IDLE_MS * 5)
    })
    expect(reload).not.toHaveBeenCalled()
    state.quiet = true
    await act(async () => {
      vi.advanceTimersByTime(10_000)
    })
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('does nothing when the server cannot say which build it has, or is out of reach', async () => {
    const { reload } = wall({ server: [''] })
    await settle()
    const failing = vi.fn().mockRejectedValue(new Error('offline'))
    const reload2 = vi.fn()
    renderHook(() => useSelfUpdate(true, { serverBuild: failing, quiet: () => true, lastTouch: () => 0, reload: reload2, mine: 'index-A1.js' }))
    await settle()
    expect(reload).not.toHaveBeenCalled()
    expect(reload2).not.toHaveBeenCalled()
  })

  it('under the dev server, where the page names no build, the first answer is its own', async () => {
    const { reload } = wall({ mine: '', server: ['/assets/index-A1.js', '/assets/index-A1.js', '/assets/index-B2.js'] })
    await settle()
    expect(reload).not.toHaveBeenCalled()
    await act(async () => {
      vi.advanceTimersByTime(BUILD_POLL_MS)
    })
    expect(reload).not.toHaveBeenCalled()
    await act(async () => {
      vi.advanceTimersByTime(BUILD_POLL_MS)
    })
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('inside the app it does not ask at all', async () => {
    const serverBuild = vi.fn().mockResolvedValue('/assets/index-B2.js')
    renderHook(() => useSelfUpdate(false, { serverBuild, quiet: () => true, lastTouch: () => 0, reload: vi.fn() }))
    await settle()
    expect(serverBuild).not.toHaveBeenCalled()
  })

  it('reads its own build from the script tag it was loaded with', () => {
    expect(ownBuild()).toBe('')
    document.head.innerHTML = '<script type="module" crossorigin src="/assets/index-Xy9.js"></script>'
    expect(ownBuild()).toBe('index-Xy9.js')
  })
})

/** The app never said it was behind: after an upgrade it ran the old code until a hard reload. */
describe('the app after a deploy', () => {
  function app(server: string[], mine = 'index-A1.js') {
    const answers = [...server]
    const serverBuild = vi.fn(async () => (answers.length > 1 ? answers.shift() : answers[0]) ?? '')
    const hook = renderHook(() => useNewBuild(true, { serverBuild, mine }))
    return { serverBuild, hook }
  }

  it('says nothing while the build is the one it runs', async () => {
    const { hook, serverBuild } = app(['/assets/index-A1.js'])
    await settle()
    await act(async () => {
      vi.advanceTimersByTime(BUILD_POLL_MS * 2)
    })
    expect(serverBuild.mock.calls.length).toBeGreaterThanOrEqual(3)
    expect(hook.result.current).toBe(false)
  })

  it('says a new version is ready once the server hands out another, and stops asking', async () => {
    const { hook, serverBuild } = app(['/assets/index-A1.js', '/assets/index-B2.js'])
    await settle()
    expect(hook.result.current).toBe(false)
    await act(async () => {
      vi.advanceTimersByTime(BUILD_POLL_MS)
    })
    await settle()
    expect(hook.result.current).toBe(true)
    const asked = serverBuild.mock.calls.length
    await act(async () => {
      vi.advanceTimersByTime(BUILD_POLL_MS * 3)
    })
    expect(serverBuild).toHaveBeenCalledTimes(asked)
  })

  it('asks when the tab comes back into view, and not while it is hidden', async () => {
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    const { hook, serverBuild } = app(['/assets/index-B2.js'])
    await settle()
    expect(serverBuild).not.toHaveBeenCalled()
    visibility.mockReturnValue('visible')
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await settle()
    expect(hook.result.current).toBe(true)
  })

  it('under the dev server takes the first answer as its own', async () => {
    const { hook } = app(['/assets/index-B2.js'], '')
    await settle()
    expect(hook.result.current).toBe(false)
  })
})
