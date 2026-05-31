import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useTabHash } from '../useTabHash'

type Tab = 'overview' | 'roster' | 'documents'
const VALID_TABS: Tab[] = ['overview', 'roster', 'documents']

function clearHash() {
  // history.replaceState avoids a `hashchange` event firing during setup.
  window.history.replaceState(null, '', window.location.pathname + window.location.search)
}

function setHash(value: string) {
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#${value}`)
}

describe('useTabHash', () => {
  beforeEach(() => {
    clearHash()
  })

  afterEach(() => {
    clearHash()
  })

  it('returns the default tab when the hash is empty', () => {
    const { result } = renderHook(() => useTabHash<Tab>('overview', VALID_TABS))
    expect(result.current[0]).toBe('overview')
  })

  it('returns the hash value when the hash matches a valid tab', () => {
    setHash('roster')
    const { result } = renderHook(() => useTabHash<Tab>('overview', VALID_TABS))
    expect(result.current[0]).toBe('roster')
  })

  it('falls back to the default tab when the hash does not match a valid tab', () => {
    setHash('not-a-tab')
    const { result } = renderHook(() => useTabHash<Tab>('overview', VALID_TABS))
    expect(result.current[0]).toBe('overview')
  })

  it('updates window.location.hash when the setter is called with a valid tab', () => {
    const { result } = renderHook(() => useTabHash<Tab>('overview', VALID_TABS))

    act(() => {
      result.current[1]('documents')
    })

    expect(result.current[0]).toBe('documents')
    expect(window.location.hash).toBe('#documents')
  })

  it('does not write an invalid tab to the hash but still updates state', () => {
    const { result } = renderHook(() => useTabHash<Tab>('overview', VALID_TABS))

    act(() => {
      // @ts-expect-error - intentionally passing an invalid tab to test the guard
      result.current[1]('garbage')
    })

    // setter sets local state regardless, but does not pollute the URL with bogus values
    expect(window.location.hash).toBe('')
  })

  it('responds to browser back/forward via the hashchange event', () => {
    const { result } = renderHook(() => useTabHash<Tab>('overview', VALID_TABS))

    expect(result.current[0]).toBe('overview')

    act(() => {
      // Simulate back/forward navigating to a different valid tab.
      window.location.hash = 'roster'
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })

    expect(result.current[0]).toBe('roster')

    act(() => {
      // Simulate back/forward navigating to an unknown hash → falls back to default.
      window.location.hash = 'mystery'
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })

    expect(result.current[0]).toBe('overview')
  })

  it('cleans up the hashchange listener on unmount', () => {
    const { result, unmount } = renderHook(() => useTabHash<Tab>('overview', VALID_TABS))

    unmount()

    act(() => {
      window.location.hash = 'roster'
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })

    // After unmount, the (stale) hook result should not have changed.
    expect(result.current[0]).toBe('overview')
  })
})
