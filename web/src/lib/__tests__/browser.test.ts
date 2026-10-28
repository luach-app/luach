import { afterEach, describe, expect, it, vi } from 'vitest'
import { pushState, pushSupported, registerServiceWorker, urlBase64ToUint8Array } from '../push'
import { baseContentType, pickMimeType, voiceSupported } from '../voice'
import * as api from '../api'

/** Hand jsdom the browser bits it does not ship with. */
function givePushApis(over: { permission?: NotificationPermission; subscription?: unknown } = {}) {
  const registration = {
    pushManager: {
      getSubscription: vi.fn().mockResolvedValue(over.subscription ?? null),
      subscribe: vi.fn(),
    },
  }
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: {
      register: vi.fn().mockResolvedValue(registration),
      getRegistration: vi.fn().mockResolvedValue(registration),
    },
  })
  vi.stubGlobal('PushManager', class {})
  vi.stubGlobal('Notification', { permission: over.permission ?? 'granted' })
  return registration
}

afterEach(() => {
  vi.unstubAllGlobals()
  Reflect.deleteProperty(navigator, 'serviceWorker')
})

describe('push, where the browser allows it', () => {
  it('knows when it is not supported at all', async () => {
    expect(pushSupported()).toBe(false)
    await expect(pushState()).resolves.toBe('unsupported')
    await expect(registerServiceWorker()).resolves.toBeNull()
  })

  it('registers the worker when there is one', async () => {
    givePushApis()
    await expect(registerServiceWorker()).resolves.toBeTruthy()
  })

  it('reports what state the member is actually in', async () => {
    givePushApis({ permission: 'denied' })
    await expect(pushState()).resolves.toBe('denied')

    givePushApis({ permission: 'granted' })
    vi.spyOn(api.push, 'key').mockResolvedValue({ public_key: '' } as never)
    await expect(pushState()).resolves.toBe('unconfigured')

    vi.spyOn(api.push, 'key').mockResolvedValue({ public_key: 'BKey' } as never)
    await expect(pushState()).resolves.toBe('off')

    givePushApis({ permission: 'granted', subscription: { endpoint: 'https://push.example/1' } })
    await expect(pushState()).resolves.toBe('on')
  })

  it('decodes a VAPID key the way the push API wants it', () => {
    const bytes = urlBase64ToUint8Array('AQAB')
    expect(bytes).toBeInstanceOf(Uint8Array)
    expect(Array.from(bytes)).toEqual([1, 0, 1])
    // URL-safe characters and missing padding are both handled.
    expect(urlBase64ToUint8Array('-_8').length).toBeGreaterThan(0)
  })
})

describe('the microphone', () => {
  it('needs both a recorder and a way to reach the mic', () => {
    expect(voiceSupported()).toBe(false)
    vi.stubGlobal('MediaRecorder', class {})
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: vi.fn() } })
    expect(voiceSupported()).toBe(true)
  })

  it('picks a type the browser says it can record, and strips the codec for the server', () => {
    vi.stubGlobal('MediaRecorder', { isTypeSupported: (t: string) => t.startsWith('audio/webm') })
    expect(pickMimeType()).toContain('audio/webm')
    expect(baseContentType('audio/webm;codecs=opus')).toBe('audio/webm')
    expect(baseContentType('audio/mp4')).toBe('audio/mp4')
    expect(baseContentType('')).toBeTruthy()
  })
})
