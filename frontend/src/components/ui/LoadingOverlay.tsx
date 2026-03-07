import { Spinner } from './Spinner'

interface LoadingOverlayProps {
  visible: boolean
  message?: string
  className?: string
}

export function LoadingOverlay({
  visible,
  message = 'Loading…',
  className = '',
}: LoadingOverlayProps) {
  if (!visible) return null

  return (
    <div
      className={`absolute inset-0 z-40 flex flex-col items-center justify-center bg-white/80 backdrop-blur-sm ${className}`}
      role="status"
      aria-label={message}
    >
      <Spinner size="lg" label={message} />
      <p className="mt-3 text-sm font-medium text-gray-600">{message}</p>
    </div>
  )
}
