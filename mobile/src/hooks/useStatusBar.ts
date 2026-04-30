import { useEffect } from 'react'

/**
 * Check if we're running inside a native Capacitor shell.
 */
function isNativePlatform(): boolean {
  return !!(window as any).Capacitor?.isNativePlatform?.()
}

/**
 * Configures the native status bar style.
 * Dark text on light backgrounds, light text on dark backgrounds.
 *
 * Requirements: 54.1, 54.2, 54.3
 */
export function useStatusBar(style: 'light' | 'dark' = 'dark') {
  useEffect(() => {
    if (!isNativePlatform()) return

    async function configure() {
      try {
        const { StatusBar, Style } = await import('@capacitor/status-bar')
        await StatusBar.setStyle({
          style: style === 'dark' ? Style.Dark : Style.Light,
        })
      } catch {
        // Silently ignore — plugin may not be available
      }
    }

    configure()
  }, [style])
}

/**
 * Hides the splash screen after the app has loaded.
 * Called once on app mount.
 *
 * Requirements: 54.1
 */
export async function hideSplashScreen(): Promise<void> {
  if (!isNativePlatform()) return

  try {
    const { SplashScreen } = await import('@capacitor/splash-screen')
    await SplashScreen.hide()
  } catch {
    // Silently ignore
  }
}
