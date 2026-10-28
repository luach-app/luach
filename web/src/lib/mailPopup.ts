/**
 * Connecting Gmail in a popup. Settings opens Google's consent in a small window
 * (/api/mail/connect?popup=1); Google sends it back to luach with ?mail=…&popup=1,
 * and that page reports the result to Settings and closes itself.
 *
 * The report goes over a BroadcastChannel, not window.opener: Google's pages set a
 * Cross-Origin-Opener-Policy, and once the popup has been there the link back to
 * the window that opened it is usually gone. A channel only needs the same origin.
 */
export const CHANNEL = 'luach-mail'

export type MailResult = 'connected' | 'failed' | 'not-yours'

const RESULTS: readonly string[] = ['connected', 'failed', 'not-yours']

/**
 * How a connect ended, from the address luach sent the browser back to: ?mail=connected,
 * or ?mail=failed with &reason=not-yours when the Gmail signed in to is not one of this
 * member's addresses here. Null when the address says nothing about mail.
 */
export function resultOf(search: string): MailResult | null {
  const q = new URLSearchParams(search)
  const mail = q.get('mail')
  if (mail === 'connected') return 'connected'
  if (mail === 'failed') return q.get('reason') === 'not-yours' ? 'not-yours' : 'failed'
  return null
}

/** Open Google's consent in a popup; false when the browser would not open one. */
export function openConsent(): boolean {
  const w = window.open('/api/mail/connect?popup=1', 'luach-gmail', 'popup,width=520,height=680')
  return !!w
}

/** Hear a popup's result, for as long as the returned function is not called. */
export function onConsent(handle: (result: MailResult) => void): () => void {
  if (typeof BroadcastChannel === 'undefined') return () => undefined
  const channel = new BroadcastChannel(CHANNEL)
  channel.onmessage = (e: MessageEvent) => {
    const result = (e.data as { mail?: string } | null)?.mail
    if (result && RESULTS.includes(result)) handle(result as MailResult)
  }
  return () => channel.close()
}

/**
 * Called before the app renders. In the popup on its way back from Google, pass
 * the result on and close; true means this window is that popup and the app
 * should not load in it.
 */
export function finishConsentPopup(): boolean {
  const q = new URLSearchParams(window.location.search)
  const result = resultOf(window.location.search)
  if (q.get('popup') !== '1' || result === null) return false
  try {
    const channel = new BroadcastChannel(CHANNEL)
    channel.postMessage({ mail: result })
    channel.close()
  } catch {
    /* no channel: Settings still refreshes when its window gets the focus back */
  }
  window.close()
  return true
}
