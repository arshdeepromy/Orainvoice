import type { CapacitorConfig } from '@capacitor/cli'

/**
 * Capacitor configuration for OraInvoice mobile app.
 *
 * Live reload modes:
 *   1. CAPACITOR_SERVER_URL set explicitly → uses that URL
 *   2. Running on emulator without CAPACITOR_SERVER_URL → auto-uses
 *      http://10.0.2.2:5173/mobile/ (Android emulator host alias)
 *   3. Production build → no server URL, uses bundled web assets
 *
 * The 10.0.2.2 address is Android emulator's alias for the host machine's
 * loopback (127.0.0.1). This lets the emulator reach the Vite dev server
 * running on the host without any manual IP configuration.
 */

const serverUrl = process.env.CAPACITOR_SERVER_URL || undefined

const config: CapacitorConfig = {
  appId: 'nz.oraflows.orainvoice',
  appName: 'OraInvoice',
  webDir: 'dist',
  server: {
    // Set CAPACITOR_SERVER_URL for live reload during development.
    // For emulator: CAPACITOR_SERVER_URL=http://10.0.2.2:5173/mobile/
    // For real device on LAN: CAPACITOR_SERVER_URL=http://192.168.1.x:5173/mobile/
    url: serverUrl,
    cleartext: true, // Allow HTTP for local dev — disable in production builds
    androidScheme: 'https',
  },
  android: {
    allowMixedContent: true,
  },
  allowNavigation: [
    'devin.oraflow.co.nz',
    'api.oraflows.co.nz',
    '*.oraflows.co.nz',
    '*.oraflow.co.nz',
    '10.0.2.2',       // Android emulator host alias
    '192.168.*.*',     // LAN addresses for real device dev
  ],
  plugins: {
    SplashScreen: {
      launchShowDuration: 2000,
      backgroundColor: '#2563EB',
      launchAutoHide: true,
      launchFadeOutDuration: 300,
    },
    StatusBar: {
      // Style is configured at runtime via JS (capacitor-init.ts)
    },
    Keyboard: {
      resize: 'body',
      style: 'dark',
      resizeOnFullScreen: true,
    },
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
    Camera: {},
    BiometricAuth: {},
  },
}

export default config
