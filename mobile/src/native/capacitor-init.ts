import { Capacitor } from '@capacitor/core'

/**
 * Initialise Capacitor-specific native features.
 *
 * Call this once before React renders. On web it's a no-op so the app
 * stays fully runnable in the browser.
 */
export async function capacitorInit(): Promise<void> {
  const platform = Capacitor.getPlatform()
  const isNative = Capacitor.isNativePlatform()

  if (!isNative) {
    // Running in a browser — nothing to configure
    return
  }

  // --- Status Bar ---
  try {
    const { StatusBar, Style } = await import('@capacitor/status-bar')
    await StatusBar.setStyle({ style: Style.Light })
    if (platform === 'android') {
      await StatusBar.setBackgroundColor({ color: '#0F172A' })
    }
  } catch {
    // Plugin not available — ignore
  }

  // --- Splash Screen ---
  // Hide after a short delay so the first paint has time to render
  try {
    const { SplashScreen } = await import('@capacitor/splash-screen')
    setTimeout(async () => {
      try {
        await SplashScreen.hide({ fadeOutDuration: 300 })
      } catch {
        // ignore
      }
    }, 500)
  } catch {
    // Plugin not available — ignore
  }

  // --- App state listeners (resume / pause) ---
  try {
    const { App } = await import('@capacitor/app')

    App.addListener('appStateChange', ({ isActive }) => {
      if (isActive) {
        // App resumed — could refresh auth token, sync data, etc.
        console.debug('[capacitor-init] App resumed')
      } else {
        // App paused — save any pending state
        console.debug('[capacitor-init] App paused')
      }
    })

    // --- Hardware back button (Android) ---
    App.addListener('backButton', ({ canGoBack }) => {
      if (canGoBack) {
        window.history.back()
      } else {
        // At the root of the app — minimise instead of exiting
        App.minimizeApp()
      }
    })
  } catch {
    // Plugin not available — ignore
  }

  // --- Keyboard (Android) ---
  if (platform === 'android') {
    try {
      const { Keyboard } = await import('@capacitor/keyboard')
      // Keyboard plugin auto-configures from capacitor.config.ts
      // Additional runtime listeners can be added here if needed
      Keyboard.addListener('keyboardWillShow', () => {
        document.body.classList.add('keyboard-open')
      })
      Keyboard.addListener('keyboardWillHide', () => {
        document.body.classList.remove('keyboard-open')
      })
    } catch {
      // Plugin not available — ignore
    }
  }

  console.debug(`[capacitor-init] Initialised for platform: ${platform}`)
}
