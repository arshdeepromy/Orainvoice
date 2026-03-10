import { useNavigate } from 'react-router-dom'
import { CustomerCreateModal } from '../../components/customers/CustomerCreateModal'

export default function CustomerCreate() {
  const navigate = useNavigate()

  const handleClose = () => {
    navigate('/customers')
  }

  const handleSuccess = (customerId: string) => {
    navigate(`/customers/${customerId}`)
  }

  return (
    <CustomerCreateModal
      open={true}
      onClose={handleClose}
      onSuccess={handleSuccess}
    />
  )
}
