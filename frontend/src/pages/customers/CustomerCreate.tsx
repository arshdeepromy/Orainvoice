import { useNavigate } from 'react-router-dom'
import { CustomerCreateModal } from '../../components/customers/CustomerCreateModal'

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
