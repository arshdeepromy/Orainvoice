import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'nz.co.oraflows.invoice',
  appName: 'OraInvoice',
  webDir: 'dist',
  server: {
    url: process.env.CAPACITOR_SERVER_URL || undefined,
    cleartext: true,
  },
  plugins: {
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
    Camera: {},
    BiometricAuth: {},
  },
}

export default config
