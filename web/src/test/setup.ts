import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  try {
    localStorage.clear()
    sessionStorage.clear()
  } catch {
    /* jsdom without storage */
  }
})

// jsdom has neither; the app asks both on every render of the agenda.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}
if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {}
