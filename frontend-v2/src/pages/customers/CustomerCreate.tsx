import { useNavigate } from 'react-router-dom'
import { CustomerCreateModal } from '@/components/customers/CustomerCreateModal'

/**
 * CustomerCreate — Task 23 port of frontend/src/pages/customers/CustomerCreate.
 *
 * A thin route wrapper that renders the shared CustomerCreateModal in the
 * always-open state — copied VERBATIM from the original (close → /customers,
 * success → /customers/:id). The create modal itself (ported in Task 20)
 * preserves the project rule that customer creation only requires First Name.
 * No standalone design prototype exists for this route (it's the modal over the
 * customer list), so the modal's own token styling is the design (FR-2b).
 */
export default function CustomerCreate() {
  const navigate = useNavigate()

  const handleClose = () => {
    navigate('/customers')
  }

  const handleSuccess = (customer: { id: string }) => {
    navigate(`/customers/${customer.id}`)
  }

  return (
    <CustomerCreateModal
      open={true}
      onClose={handleClose}
      onCustomerCreated={handleSuccess}
    />
  )
}
