import { useCallback, useEffect, useRef, useState } from 'react'

/** Run `fn` now and every `ms` while the document is visible. */
export function useVisiblePoll(fn: () => void | Promise<void>, ms: number, enabled = true) {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    if (!enabled) return
    let timer: number | undefined
    const tick = () => {
      if (document.visibilityState === 'visible') void ref.current()
    }
    const arm = () => {
      window.clearInterval(timer)
      timer = window.setInterval(tick, ms)
    }
    const onVis = () => {
      if (document.visibilityState === 'visible') {
        tick()
        arm()
      } else {
        window.clearInterval(timer)
      }
    }
    tick()
    arm()
    document.addEventListener('visibilitychange', onVis)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [ms, enabled])
}

export function useMediaQuery(query: string): boolean {
  const get = () => (typeof window !== 'undefined' ? window.matchMedia(query).matches : false)
  const [matches, setMatches] = useState(get)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const handler = () => setMatches(mq.matches)
    handler()
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [query])
  return matches
}

/** Tiny async-action helper: `{busy, error, run}`. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const run = useCallback(async <T,>(task: () => Promise<T>, toMessage: (e: unknown) => string) => {
    setBusy(true)
    setError('')
    try {
      return await task()
    } catch (e) {
      setError(toMessage(e))
      return undefined
    } finally {
      setBusy(false)
    }
  }, [])
  return { busy, error, setError, run }
}
