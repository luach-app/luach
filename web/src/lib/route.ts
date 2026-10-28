export type Deep = { kind: 'board' } | { kind: 'invite'; token: string } | { kind: 'reset'; token: string } | { kind: 'book'; slug: string; manage?: string } | { kind: 'verify'; token: string } | null

/** `/book/<slug>` is the public booking page; the rest are query-string links. */
export function readDeepLink(): Deep {
  // The screen on the kitchen wall: its own token, never a session.
  if (/^\/board\/?$/.test(window.location.pathname)) return { kind: 'board' }
  const booked = /^\/book\/([a-z0-9-]{2,40})\/?$/i.exec(window.location.pathname)
  if (booked?.[1]) {
    const manage = new URLSearchParams(window.location.search).get('manage')
    return { kind: 'book', slug: booked[1].toLowerCase(), manage: manage ?? undefined }
  }
  const q = new URLSearchParams(window.location.search)
  const invite = q.get('invite')
  if (invite) return { kind: 'invite', token: invite }
  const reset = q.get('reset')
  if (reset) return { kind: 'reset', token: reset }
  const verify = q.get('verify')
  if (verify) return { kind: 'verify', token: verify }
  return null
}

/** Drop the query string once a deep link has been handled. */
export function cleanQuery() {
  if (window.location.search) {
    window.history.replaceState(null, '', window.location.pathname + window.location.hash)
  }
}
