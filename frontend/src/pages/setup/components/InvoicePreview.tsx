export interface InvoicePreviewData {
  businessName: string
  tradingName?: string
  address?: string
  phone?: string
  website?: string
  logoUrl?: string
  primaryColour: string
  secondaryColour: string
  taxLabel: string
  taxRate: number
  currency: string
  dateFormat: string
}

interface InvoicePreviewProps {
  data: InvoicePreviewData
}

function formatSampleDate(format: string): string {
  const now = new Date()
  const day = String(now.getDate()).padStart(2, '0')
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const year = now.getFullYear()
  if (format === 'MM/dd/yyyy') return `${month}/${day}/${year}`
  if (format === 'yyyy-MM-dd') return `${year}-${month}-${day}`
  return `${day}/${month}/${year}`
}

export function InvoicePreview({ data }: InvoicePreviewProps) {
  const sampleDate = formatSampleDate(data.dateFormat)
  const sampleSubtotal = 250.0
  const taxAmount = sampleSubtotal * (data.taxRate / 100)
  const total = sampleSubtotal + taxAmount

  const formatCurrency = (amount: number) =>
    `${data.currency} ${amount.toFixed(2)}`

  return (
    <div
      className="border border-gray-300 rounded-lg bg-white shadow-sm overflow-hidden text-xs"
      role="img"
      aria-label="Live invoice preview"
    >
      {/* Header */}
      <div
        className="px-4 py-3 flex items-center justify-between"
        style={{ backgroundColor: data.primaryColour }}
      >
        <div className="flex items-center gap-2">
          {data.logoUrl ? (
            <img
              src={data.logoUrl}
              alt="Logo preview"
              className="h-8 w-8 object-contain rounded bg-white p-0.5"
            />
          ) : (
            <div className="h-8 w-8 rounded bg-white/20 flex items-center justify-center text-white text-xs font-bold">
              {(data.businessName || 'Co')[0]}
            </div>
          )}
          <div className="text-white">
            <p className="font-bold text-sm leading-tight">
              {data.tradingName || data.businessName || 'Your Business'}
            </p>
            {data.address && (
              <p className="opacity-80 text-[10px]">{data.address}</p>
            )}
          </div>
        </div>
        <div className="text-white text-right">
          <p className="font-bold text-sm">INVOICE</p>
          <p className="opacity-80 text-[10px]">#INV-0001</p>
        </div>
      </div>

      {/* Invoice details */}
      <div className="px-4 py-2 border-b border-gray-200 flex justify-between text-gray-600">
        <div>
          <p className="font-medium text-gray-800">Bill To:</p>
          <p>Sample Customer</p>
          <p>123 Example Street</p>
        </div>
        <div className="text-right">
          <p>Date: {sampleDate}</p>
          <p>Due: {sampleDate}</p>
          {data.phone && <p>Ph: {data.phone}</p>}
        </div>
      </div>

      {/* Line items */}
      <div className="px-4 py-2">
        <table className="w-full text-left">
          <thead>
            <tr
              className="text-white text-[10px]"
              style={{ backgroundColor: data.secondaryColour }}
            >
              <th className="px-2 py-1 rounded-l">Description</th>
              <th className="px-2 py-1 text-right">Qty</th>
              <th className="px-2 py-1 text-right">Price</th>
              <th className="px-2 py-1 text-right rounded-r">Total</th>
            </tr>
          </thead>
          <tbody className="text-gray-700">
            <tr className="border-b border-gray-100">
              <td className="px-2 py-1">Sample Service</td>
              <td className="px-2 py-1 text-right">2</td>
              <td className="px-2 py-1 text-right">{formatCurrency(75)}</td>
              <td className="px-2 py-1 text-right">{formatCurrency(150)}</td>
            </tr>
            <tr className="border-b border-gray-100">
              <td className="px-2 py-1">Sample Product</td>
              <td className="px-2 py-1 text-right">1</td>
              <td className="px-2 py-1 text-right">{formatCurrency(100)}</td>
              <td className="px-2 py-1 text-right">{formatCurrency(100)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Totals */}
      <div className="px-4 py-2 border-t border-gray-200">
        <div className="flex justify-end">
          <div className="w-40 space-y-1">
            <div className="flex justify-between">
              <span className="text-gray-600">Subtotal:</span>
              <span>{formatCurrency(sampleSubtotal)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">{data.taxLabel} ({data.taxRate}%):</span>
              <span>{formatCurrency(taxAmount)}</span>
            </div>
            <div
              className="flex justify-between font-bold text-sm pt-1 border-t"
              style={{ color: data.primaryColour }}
            >
              <span>Total:</span>
              <span>{formatCurrency(total)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div
        className="px-4 py-1.5 text-center text-[10px] text-white/80"
        style={{ backgroundColor: data.secondaryColour }}
      >
        {data.website || 'www.yourbusiness.com'} • Thank you for your business
      </div>
    </div>
  )
}
