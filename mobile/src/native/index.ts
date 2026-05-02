/**
 * Native feature barrel export.
 *
 * Consumers can import everything from `@/native`:
 *
 *   import { useCamera, takePhoto, useHaptics, light } from '@/native'
 */

// Capacitor initialisation
export { capacitorInit } from './capacitor-init'

// Camera
export { useCamera, takePhoto } from './camera'
export type { CameraPhoto, UseCameraResult } from './camera'

// Geolocation
export { useGeolocation, getCurrentPosition } from './geolocation'
export type { UseGeolocationResult } from './geolocation'

// Haptics
export { useHaptics, light, medium, heavy, selection } from './haptics'
export type { UseHapticsResult } from './haptics'

// Push Notifications
export { usePushNotifications } from './pushNotifications'
export type { UsePushNotificationsResult } from './pushNotifications'

// Network
export { useNetworkStatus } from './network'
export type { UseNetworkStatusResult } from './network'
