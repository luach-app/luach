import { ApiError, passkeys } from './api'
import type { Member, PasskeyListing } from './types'

/* ---- base64url --------------------------------------------------------- */
export function b64uToBuf(s: string): ArrayBuffer {
  const b64 = s.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(s.length / 4) * 4, '=')
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out.buffer
}
export function bufToB64u(buf: ArrayBuffer | null | undefined): string | null {
  if (!buf) return null
  let bin = ''
  for (const b of new Uint8Array(buf)) bin += String.fromCharCode(b)
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/* ---- capability --------------------------------------------------------- */
export function passkeysSupported(): boolean {
  return typeof window !== 'undefined' && !!window.PublicKeyCredential && !!navigator.credentials
}

export async function conditionalMediationAvailable(): Promise<boolean> {
  if (!passkeysSupported()) return false
  const pkc = window.PublicKeyCredential as unknown as { isConditionalMediationAvailable?: () => Promise<boolean> }
  try {
    return !!(await pkc.isConditionalMediationAvailable?.())
  } catch {
    return false
  }
}

/** "iPhone", "This Mac", … — the default passkey name. */
export function guessDeviceName(): string {
  const ua = typeof navigator === 'undefined' ? '' : navigator.userAgent
  if (/iPhone/.test(ua)) return 'iPhone'
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return 'iPad'
  if (/Android/.test(ua)) return 'Android phone'
  if (/Macintosh/.test(ua)) return 'This Mac'
  if (/Windows/.test(ua)) return 'This Windows PC'
  if (/CrOS/.test(ua)) return 'This Chromebook'
  if (/Linux/.test(ua)) return 'This Linux PC'
  return 'This device'
}

/* ---- the one-time "add a passkey?" offer ------------------------------- */
const DISMISS_KEY = 'luach.passkey.offer.dismissed'
export function shouldOfferPasskey(): boolean {
  if (!passkeysSupported()) return false
  try {
    return localStorage.getItem(DISMISS_KEY) !== '1'
  } catch {
    return true
  }
}
export function dismissPasskeyOffer() {
  try {
    localStorage.setItem(DISMISS_KEY, '1')
  } catch {
    /* private mode */
  }
}

/* ---- option decoding / credential serialising --------------------------- */
type Json = Record<string, unknown>
const withId = (list: unknown) =>
  Array.isArray(list) ? list.map((c) => ({ ...(c as Json), id: b64uToBuf(String((c as Json).id)) })) : undefined

function toCreationOptions(o: Json): PublicKeyCredentialCreationOptions {
  const user = (o.user ?? {}) as Json
  return {
    ...(o as object),
    challenge: b64uToBuf(String(o.challenge)),
    user: { ...(user as object), id: b64uToBuf(String(user.id)) } as PublicKeyCredentialUserEntity,
    excludeCredentials: withId(o.excludeCredentials) as PublicKeyCredentialDescriptor[] | undefined,
  } as PublicKeyCredentialCreationOptions
}

function toRequestOptions(o: Json): PublicKeyCredentialRequestOptions {
  return {
    ...(o as object),
    challenge: b64uToBuf(String(o.challenge)),
    allowCredentials: withId(o.allowCredentials) as PublicKeyCredentialDescriptor[] | undefined,
  } as PublicKeyCredentialRequestOptions
}

function serialise(cred: PublicKeyCredential): Json {
  const r = cred.response as AuthenticatorAttestationResponse & AuthenticatorAssertionResponse
  const response: Json = { clientDataJSON: bufToB64u(r.clientDataJSON) }
  if (r.attestationObject) {
    response.attestationObject = bufToB64u(r.attestationObject)
    if (typeof r.getTransports === 'function') response.transports = r.getTransports()
  } else {
    response.authenticatorData = bufToB64u(r.authenticatorData)
    response.signature = bufToB64u(r.signature)
    response.userHandle = bufToB64u(r.userHandle)
  }
  const out: Json = { id: cred.id, rawId: bufToB64u(cred.rawId), type: cred.type, response, clientExtensionResults: cred.getClientExtensionResults() }
  const attachment = (cred as PublicKeyCredential & { authenticatorAttachment?: string | null }).authenticatorAttachment
  if (attachment) out.authenticatorAttachment = attachment
  return out
}

/* ---- flows ------------------------------------------------------------- */
const cancelled = (e: unknown) => e instanceof DOMException && (e.name === 'NotAllowedError' || e.name === 'AbortError')

/** Create a passkey for the signed-in member. `undefined` when the user cancelled. */
export async function registerPasskey(name?: string): Promise<PasskeyListing | undefined> {
  const { challenge_id, options } = await passkeys.registerOptions()
  let cred: Credential | null
  try {
    cred = await navigator.credentials.create({ publicKey: toCreationOptions(options) })
  } catch (e) {
    if (cancelled(e)) return undefined
    throw e
  }
  if (!cred) return undefined
  return passkeys.registerVerify({ challenge_id, credential: serialise(cred as PublicKeyCredential), name: name?.trim() || undefined })
}

async function assert(mediation: CredentialMediationRequirement, signal?: AbortSignal): Promise<Member | undefined> {
  const { challenge_id, options } = await passkeys.loginOptions()
  let cred: Credential | null
  try {
    cred = await navigator.credentials.get({ publicKey: toRequestOptions(options), mediation, signal })
  } catch (e) {
    if (cancelled(e)) return undefined
    throw e
  }
  if (!cred) return undefined
  return passkeys.loginVerify({ challenge_id, credential: serialise(cred as PublicKeyCredential) })
}

/** Modal passkey sign-in (the button). `undefined` when the user cancelled. */
export const signInWithPasskey = (signal?: AbortSignal) => assert('optional', signal)

/**
 * Arm the browser's inline passkey suggestion on a `autocomplete="username webauthn"` field.
 * Resolves `undefined` when unavailable, aborted, or dismissed; the member when one was used.
 */
export async function conditionalPasskeySignIn(signal: AbortSignal): Promise<Member | undefined> {
  if (!(await conditionalMediationAvailable()) || signal.aborted) return undefined
  return assert('conditional', signal)
}

/** '' when the user simply cancelled; otherwise the server sentence or a short line. */
export function passkeyErrorMessage(e: unknown): string {
  if (cancelled(e)) return ''
  if (e instanceof ApiError) return e.message
  if (e instanceof DOMException) {
    if (e.name === 'InvalidStateError') return 'This device already has a passkey for your account.'
    if (e.name === 'SecurityError') return 'Passkeys only work over https on the real address.'
    if (e.name === 'NotSupportedError') return 'This device cannot create that kind of passkey.'
  }
  return 'Could not use a passkey on this device.'
}
