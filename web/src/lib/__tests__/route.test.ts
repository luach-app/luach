import { beforeEach, describe, expect, it } from 'vitest'
import { cleanQuery, readDeepLink } from '../route'

const go = (url: string) => window.history.replaceState(null, '', url)

beforeEach(() => go('/'))

describe('the links that arrive by mail', () => {
  it('finds an invitation, a reset and a confirmation', () => {
    go('/?invite=abc')
    expect(readDeepLink()).toEqual({ kind: 'invite', token: 'abc' })
    go('/?reset=def')
    expect(readDeepLink()).toEqual({ kind: 'reset', token: 'def' })
    go('/?verify=ghi')
    expect(readDeepLink()).toEqual({ kind: 'verify', token: 'ghi' })
  })

  it('reads a booking page from the path, and its manage token', () => {
    go('/book/robin')
    expect(readDeepLink()).toEqual({ kind: 'book', slug: 'robin', manage: undefined })
    go('/book/Robin-K/?manage=tok-1')
    expect(readDeepLink()).toEqual({ kind: 'book', slug: 'robin-k', manage: 'tok-1' })
  })

  it('is not fooled by a path that only looks like one', () => {
    go('/booking/robin')
    expect(readDeepLink()).toBeNull()
    go('/book/')
    expect(readDeepLink()).toBeNull()
    go('/')
    expect(readDeepLink()).toBeNull()
  })

  it('tidies the query once a link has been used', () => {
    go('/?invite=abc#x')
    cleanQuery()
    expect(window.location.search).toBe('')
  })
})
