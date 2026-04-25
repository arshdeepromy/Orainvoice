import { AuthProvider } from '@/contexts/AuthContext'
import { TenantProvider } from '@/contexts/TenantContext'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { BranchProvider } from '@/contexts/BranchContext'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { OfflineProvider } from '@/contexts/OfflineContext'
import { BiometricProvider } from '@/contexts/BiometricContext'
import { MobileLayout } from '@/components/layout/MobileLayout'
import { AppRoutes } from '@/navigation/AppRoutes'
import { DeepLinkHandler } from '@/navigation/DeepLinkHandler'

/**
 * Root App component with provider hierarchy.
 *
 * Provider order:
 * AuthProvider → TenantProvider → ModuleProvider → BranchProvider →
 * ThemeProvider → OfflineProvider → BiometricProvider → MobileLayout → AppRoutes
 *
 * DeepLinkHandler listens for incoming deep links and navigates accordingly.
 * If the user is unauthenticated, the deep link target is stored and
 * navigation occurs after login.
 *
 * Requirements: 39.2, 42.5
 */
export default function App() {
  return (
    <AuthProvider>
      <TenantProvider>
        <ModuleProvider>
          <BranchProvider>
            <ThemeProvider>
              <OfflineProvider>
                <BiometricProvider>
                  <MobileLayout>
                    <DeepLinkHandler />
                    <AppRoutes />
                  </MobileLayout>
                </BiometricProvider>
              </OfflineProvider>
            </ThemeProvider>
          </BranchProvider>
        </ModuleProvider>
      </TenantProvider>
    </AuthProvider>
  )
}
