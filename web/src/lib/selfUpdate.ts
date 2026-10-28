import { useEffect, useRef, useState } from 'react'

/** How often a wall board asks which build the server hands out. */
export const BUILD_POLL_MS = 5 * 60_000
/** How long nobody must have touched it before it reloads under them. */
export const IDLE_MS = 60_000
/** Once it knows it is behind, how often it looks for a quiet moment. */
const RETRY_MS = 10_000

const name = (src: string) => src.split('?')[0]?.split('/').pop() ?? ''

/** The entry script this page was loaded with: /assets/index-<hash>.js in a build, nothing under the dev server. */
export function ownBuild(doc: Document = document): string {
  for (const s of Array.from(doc.querySelectorAll<HTMLScriptElement>('script[type="module"][src]'))) {
    const src = s.getAttribute('src') ?? ''
    if (src.includes('/assets/')) return name(src)
  }
  return ''
}

interface Options {
  /** Which build the server hands out now ('' when it cannot say). */
  serverBuild: () => Promise<string>
  /** Whether nobody is using the screen: no sheet open, nothing held. */
  quiet: () => boolean
  /** When it was last touched (ms since the epoch). */
  lastTouch: () => number
  reload?: () => void
  /** The build this page runs; read from its own script tag by default. */
  mine?: string
  every?: number
}

/**
 * A wall board nobody reloads by hand: after a deploy it notices that the server
 * hands out a different build than the one it is running, waits until nobody is
 * using it, and reloads itself. Under the dev server, where the page names no
 * build, the first answer it gets is taken as its own.
 */
export function useSelfUpdate(enabled: boolean, opts: Options) {
  const o = useRef(opts)
  useEffect(() => {
    o.current = opts
  })
  useEffect(() => {
    if (!enabled) return
    let mine = o.current.mine ?? ownBuild()
    let behind = false
    let gone = false
    let retry: ReturnType<typeof setInterval> | undefined
    const tryReload = () => {
      const { quiet, lastTouch, reload = () => window.location.reload() } = o.current
      if (gone || !behind || !quiet() || Date.now() - lastTouch() < IDLE_MS) return
      gone = true
      clearInterval(retry)
      reload()
    }
    const check = async () => {
      let now = ''
      try {
        now = await o.current.serverBuild()
      } catch {
        return // offline: the board says so already, and the next poll asks again
      }
      if (!now) return
      if (!mine) mine = name(now)
      if (name(now) === mine || behind) return
      behind = true
      retry = setInterval(tryReload, RETRY_MS)
      tryReload()
    }
    void check()
    const id = setInterval(() => void check(), o.current.every ?? BUILD_POLL_MS)
    return () => {
      clearInterval(id)
      clearInterval(retry)
    }
  }, [enabled])
}

/** Which build the server hands out now: its entry script, from /api/health. '' when it cannot say. */
export async function serverBuild(): Promise<string> {
  const r = await fetch('/api/health', { credentials: 'omit', cache: 'no-store' })
  if (!r.ok) return ''
  return String(((await r.json()) as { build?: string }).build ?? '')
}

/**
 * Whether the server now hands out a different build than this page runs. The app,
 * unlike the wall, never reloads itself under someone — a half-typed message would
 * go — so it only says so, and the person reloads when it suits them. Asked every
 * BUILD_POLL_MS while the tab is visible, and when it comes back into view.
 */
export function useNewBuild(enabled: boolean, opts: { serverBuild?: () => Promise<string>; mine?: string; every?: number } = {}): boolean {
  const [ready, setReady] = useState(false)
  const o = useRef(opts)
  useEffect(() => {
    o.current = opts
  })
  useEffect(() => {
    if (!enabled || ready) return
    let mine = o.current.mine ?? ownBuild()
    let alive = true
    const check = async () => {
      if (document.visibilityState !== 'visible') return
      let now = ''
      try {
        now = await (o.current.serverBuild ?? serverBuild)()
      } catch {
        return // offline: nothing to say, and the next check asks again
      }
      if (!now || !alive) return
      if (!mine) mine = name(now)
      if (name(now) !== mine) setReady(true)
    }
    void check()
    const id = setInterval(() => void check(), o.current.every ?? BUILD_POLL_MS)
    const onVisible = () => void check()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      alive = false
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [enabled, ready])
  return ready
}
