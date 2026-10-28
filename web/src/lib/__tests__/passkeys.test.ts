import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  b64uToBuf,
  bufToB64u,
  conditionalMediationAvailable,
  dismissPasskeyOffer,
  guessDeviceName,
  passkeysSupported,
  shouldOfferPasskey,
} from '../passkeys'

afterEach(() => {
  vi.unstubAllGlobals()
  Reflect.deleteProperty(navigator, 'credentials')
  try {
    localStorage.clear()
  } catch {
    /* private mode */
  }
})

describe('the base64url the WebAuthn API speaks', () => {
  it('round-trips a value, padding and URL-safe characters included', () => {
    const buf = b64uToBuf('AQAB')
    expect(new Uint8Array(buf)).toEqual(new Uint8Array([1, 0, 1]))
    expect(bufToB64u(buf)).toBe('AQAB')
    expect(bufToB64u(b64uToBuf('-_8'))).toBe('-_8')
  })

  it('answers nothing for nothing', () => {
    expect(bufToB64u(null)).toBeNull()
    expect(bufToB64u(undefined)).toBeNull()
  })
})

describe('whether this browser can do passkeys at all', () => {
  it('says no when the API is missing', async () => {
    expect(passkeysSupported()).toBe(false)
    await expect(conditionalMediationAvailable()).resolves.toBe(false)
  })

  it('says yes when it is there, and asks about conditional mediation', async () => {
    Object.defineProperty(navigator, 'credentials', { configurable: true, value: { create: vi.fn(), get: vi.fn() } })
    vi.stubGlobal('PublicKeyCredential', {
      isConditionalMediationAvailable: vi.fn().mockResolvedValue(true),
    })
    expect(passkeysSupported()).toBe(true)
    await expect(conditionalMediationAvailable()).resolves.toBe(true)
  })

  it('survives a browser that throws when asked', async () => {
    Object.defineProperty(navigator, 'credentials', { configurable: true, value: { create: vi.fn(), get: vi.fn() } })
    vi.stubGlobal('PublicKeyCredential', {
      isConditionalMediationAvailable: vi.fn().mockRejectedValue(new Error('no')),
    })
    await expect(conditionalMediationAvailable()).resolves.toBe(false)
  })
})

describe('the offer to make one', () => {
  it('is made once and then left alone', () => {
    Object.defineProperty(navigator, 'credentials', { configurable: true, value: { create: vi.fn(), get: vi.fn() } })
    vi.stubGlobal('PublicKeyCredential', {})
    expect(shouldOfferPasskey()).toBe(true)
    dismissPasskeyOffer()
    expect(shouldOfferPasskey()).toBe(false)
  })

  it('is never made where it cannot work', () => {
    expect(shouldOfferPasskey()).toBe(false)
  })
})

describe('naming the device', () => {
  it('guesses something a person will recognise', () => {
    expect(guessDeviceName()).toBeTruthy()
    expect(typeof guessDeviceName()).toBe('string')
  })
})
