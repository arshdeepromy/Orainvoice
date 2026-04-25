import { useNavigate, useParams } from 'react-router-dom'
import { PDFViewer } from '@/components/common/PDFViewer'
import { MobileButton } from '@/components/ui'

/**
 * Screen wrapper for PDFViewer showing invoice PDF.
 *
 * Loads the PDF from the backend endpoint `/api/v1/invoices/:id/pdf`.
 *
 * Requirements: 8.7
 */
export default function InvoicePDFScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const pdfUrl = `/api/v1/invoices/${id}/pdf`

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="flex min-h-[44px] items-center gap-1 text-blue-600 dark:text-blue-400"
          aria-label="Back"
        >
          <svg
            className="h-5 w-5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="m15 18-6-6 6-6" />
          </svg>
          Back
        </button>
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          Invoice PDF
        </h1>
        <MobileButton
          variant="ghost"
          size="sm"
          onClick={() => window.open(pdfUrl, '_blank')}
        >
          Open
        </MobileButton>
      </div>

      {/* PDF viewer */}
      <div className="flex-1">
        <PDFViewer url={pdfUrl} title={`Invoice ${id ?? ''} PDF`} />
      </div>
    </div>
  )
}
