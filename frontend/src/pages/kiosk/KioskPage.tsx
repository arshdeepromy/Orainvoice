import { useState, useCallback } from 'react'
import { KioskWelcome } from './KioskWelcome'
import { KioskSuccess } from './KioskSuccess'
import { CustomerCreateModal } from '@/components/customers/CustomerCreateModal'

/* ── Types ── */

export type KioskScreen = 'welcome' | 'form' | 'success' | 'error'

export interface KioskFormData {
  first_name: string
  last_name: string
  phone: string
  email: string
  vehicle_rego: string
}

export interface KioskSuccessData {
  customer_first_name: string
}

/* ── KioskPage ── */

export function KioskPage() {
  const [screen, setScreen] = useState<KioskScreen>('welcome')
  const [successData, setSuccessData] = useState<KioskSuccessData | null>(null)

  /** Open the existing customer creation modal. */
  const goToForm = useCallback(() => {
    setScreen('form')
  }, [])

  /** Called when a customer is created via the existing modal. */
  const handleCustomerCreated = useCallback((customer: { first_name: string }) => {
    setSuccessData({ customer_first_name: customer.first_name || 'Customer' })
    setScreen('success')
  }, [])

  /** Close the modal and go back to welcome. */
  const handleModalClose = useCallback(() => {
    setScreen('welcome')
  }, [])

  /** Reset to welcome screen and clear all state. */
  const resetToWelcome = useCallback(() => {
    setScreen('welcome')
    setSuccessData(null)
  }, [])

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-4">
      {screen === 'welcome' && (
        <KioskWelcome onCheckIn={goToForm} />
      )}

      {screen === 'success' && successData && (
        <KioskSuccess
          customerFirstName={successData.customer_first_name}
          onDone={resetToWelcome}
        />
      )}

      {/* Reuse the existing CustomerCreateModal — same form, same API, same DB tables */}
      <CustomerCreateModal
        open={screen === 'form'}
        onClose={handleModalClose}
        onCustomerCreated={handleCustomerCreated}
        kioskMode
      />
    </div>
  )
}

export default KioskPage
