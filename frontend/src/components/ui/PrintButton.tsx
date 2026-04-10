import { Button } from './Button'

interface PrintButtonProps {
  /** Accessible label for the button. Defaults to "Print" */
  label?: string
  /** Button size variant */
  size?: 'sm' | 'md' | 'lg'
  /** Additional CSS classes */
  className?: string
}

/**
 * Triggers the browser print dialog. Hidden during print via the
 * `no-print` class applied by the global print stylesheet.
 * Requirements: 75.3
 */
export function PrintButton({
  label = 'Print',
  size = 'sm',
  className = '',
}: PrintButtonProps) {
  const handlePrint = () => {
    window.print()
  }

  return (
    <Button
      variant="secondary"
      size={size}
      onClick={handlePrint}
      className={`no-print ${className}`.trim()}
      aria-label={label}
    >
      <PrinterIcon />
      {label}
    </Button>
  )
}

function PrinterIcon() {
  return (
    <svg
      className="mr-1.5 h-4 w-4"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.5}
      stroke="currentColor"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M6.72 13.829c-.24.03-.48.062-.72.096m.72-.096a42.415 42.415 0 0110.56 0m-10.56 0L6.34 18m10.94-4.171c.24.03.48.062.72.096m-.72-.096L17.66 18m0 0l.229 2.523a1.125 1.125 0 01-1.12 1.227H7.231c-.662 0-1.18-.568-1.12-1.227L6.34 18m11.318 0h1.091A2.25 2.25 0 0021 15.75V9.456c0-1.081-.768-2.015-1.837-2.175a48.055 48.055 0 00-1.913-.247M6.34 18H5.25A2.25 2.25 0 013 15.75V9.456c0-1.081.768-2.015 1.837-2.175a48.041 48.041 0 011.913-.247m10.5 0a48.536 48.536 0 00-10.5 0m10.5 0V3.375c0-.621-.504-1.125-1.125-1.125h-8.25c-.621 0-1.125.504-1.125 1.125v3.659M18.25 7.034V3.375"
      />
    </svg>
  )
}
