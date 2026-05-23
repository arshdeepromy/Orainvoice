/**
 * Version check hook — polls /fleet/api/version every 60s and shows
 * a toast when the backend version differs from the build version.
 *
 * Implements: B2B Fleet Portal — Requirements 22.2, 22.3.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { getVersion } from '../api/endpoints'

const POLL_INTERVAL_MS = 60_000 // 60 seconds
const BUILD_VERSION: string = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'unknown'

export interface VersionCheckState {
  updateAvailable: boolean
  currentVersion: string
  latestVersion: string | null
  dismiss: () => void
  checkNow: () => Promise<void>
}

export function useVersionCheck(): VersionCheckState {
  const [updateAvailable, setUpdateAvailable] = useState(false)
  const [latestVersion, setLatestVersion] = useState<string | null>(null)
  const dismissed = useRef(false)

  const check = useCallback(async () => {
    try {
      const info = await getVersion()
      setLatestVersion(info.version)
      if (
        info.version !== 'unknown' &&
        BUILD_VERSION !== 'unknown' &&
        info.version !== BUILD_VERSION &&
        !dismissed.current
      ) {
        setUpdateAvailable(true)
      }
    } catch {
      // Silently ignore — network errors shouldn't break the UI
    }
  }, [])

  useEffect(() => {
    // Only poll when the document is visible
    let timer: ReturnType<typeof setInterval> | null = null

    const startPolling = () => {
      check()
      timer = setInterval(check, POLL_INTERVAL_MS)
    }

    const stopPolling = () => {
      if (timer) {
        clearInterval(timer)
        timer = null
      }
    }

    const handleVisibility = () => {
      if (document.hidden) {
        stopPolling()
      } else {
        startPolling()
      }
    }

    if (!document.hidden) {
      startPolling()
    }
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      stopPolling()
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [check])

  const dismiss = useCallback(() => {
    dismissed.current = true
    setUpdateAvailable(false)
  }, [])

  return {
    updateAvailable,
    currentVersion: BUILD_VERSION,
    latestVersion,
    dismiss,
    checkNow: check,
  }
}
