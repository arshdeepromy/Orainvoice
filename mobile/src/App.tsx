import { App as KonstaApp } from 'konsta/react'
import { Capacitor } from '@capacitor/core'
import { AuthProvider } from '@/contexts/AuthContext'
import { TenantProvider } from '@/contexts/TenantContext'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { BranchProvider } from '@/contexts/BranchContext'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { OfflineProvider } from '@/contexts/OfflineContext'
import { BiometricProvider } from '@/contexts/BiometricContext'
import { KonstaShell } from '@/components/konsta/KonstaShell'
import { AppRoutes } from '@/navigation/AppRoutes'
import { DeepLinkHandler } from '@/navigation/DeepLinkHandler'

/**
 * Detect platform to select the correct Konsta UI theme.
 * Capacitor.getPlatform() returns 'ios', 'android', or 'web'.
 * Use 'ios' theme for iOS devices, 'material' for Android and web.
 */
const platform = Capacitor.getPlatform()
const konstaTheme = platform === 'ios' ? 'ios' : 'material'

/**
 * Root App component with provider hierarchy.
 *
 * KonstaApp wraps everything as the outermost element, providing
 * platform-aware theming (iOS or Material Design) and safe area insets.
 *
 * Provider order (inside KonstaApp):
 * AuthProvider → TenantProvider → ModuleProvider → BranchProvider →
 * ThemeProvider → OfflineProvider → BiometricProvider → KonstaShell → AppRoutes
 *
 * DeepLinkHandler listens for incoming deep links and navigates accordingly.
 * If the user is unauthenticated, the deep link target is stored and
 * navigation occurs after login.
 *
 * Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 39.2, 42.5
 */
export default function App() {
  return (
    <KonstaApp theme={konstaTheme} safeAreas>
      <AuthProvider>
        <TenantProvider>
          <ModuleProvider>
            <BranchProvider>
              <ThemeProvider>
                <OfflineProvider>
                  <BiometricProvider>
                    <KonstaShell>
                      <DeepLinkHandler />
                      <AppRoutes />
                    </KonstaShell>
                  </BiometricProvider>
                </OfflineProvider>
              </ThemeProvider>
            </BranchProvider>
          </ModuleProvider>
        </TenantProvider>
      </AuthProvider>
    </KonstaApp>
  )
}
