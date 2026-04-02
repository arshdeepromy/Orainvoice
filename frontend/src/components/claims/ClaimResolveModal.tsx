/**
 * Modal for resolving a claim with a resolution type and optional details.
 *
 * Requirements: 3.1-3.7
 */

import { useState } from 'react'
import { Modal, Button } from '../ui'

const RESOLUTION_TYPES = [
  { value: 'full_refund', label: 'Full Refund' },
  { value: 'partial_refund', label: 'Partial Refund' },
  { value: 'credit_note', label: 'Credit Note' },
  { value: 'exchange', label: 'Exchange' },
  { value: 'redo_service', label: 'Redo Service' },
  { value: 'no_action', label: 'No Action' },
]

interface ClaimResolveModalProps {
  open: boolean
  onClose: () => void
  onSubmit: (payload: {
    resolution_type: string
    resolution_amount?: number | null
    resolution_notes?: string | null
    return_stock_item_ids?: string[]
  }) => void
  loading?: boolean
}

export function ClaimResolveModal({ open, onClose, onSubmit, loading = false }: ClaimResolveModalProps) {
  const [resolutionType, setResolutionType] = useState('')
  const [amount, setAmount] = useState('')
  const [notes, setNotes] = useState('')
  const [stockItemIds, setStockItemIds] = useState('')

  const needsAmount = resolutionType === 'partial_refund' || resolutionType === 'credit_note'
  const needsStockItems = resolutionType === 'exchange'

  const canSubmit = resolutionType && (!needsAmount || (amount && Number(amount) > 0))

  const handleSubmit = () => {
    if (!canSubmit) return
    onSubmit({
      resolution_type: resolutionType,
      resolution_amount: needsAmount ? Number(amount) : undefined,
      resolution_notes: notes.trim() || undefined,
      return_stock_item_ids: needsStockItems && stockItemIds.trim()
        ? stockItemIds.split(',').map(s => s.trim()).filter(Boolean)
        : undefined,
    })
  }

  const handleClose = () => {
    setResolutionType('')
    setAmount('')
    setNotes('')
    setStockItemIds('')
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title="Resolve Claim">
      <div className="space-y-4">
        {/* Resolution type */}
        <div>
          <label htmlFor="resolution-type" className="block text-sm font-medium text-gray-700 mb-1">
            Resolution Type
          </label>
          <select
            id="resolution-type"
            value={resolutionType}
            onChange={e => setResolutionType(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
          >
            <option value="">Select resolution…</option>
            {RESOLUTION_TYPES.map(rt => (
              <option key={rt.value} value={rt.value}>{rt.label}</option>
            ))}
          </select>
        </div>

        {/* Conditional amount input */}
        {needsAmount && (
          <div>
            <label htmlFor="resolution-amount" className="block text-sm font-medium text-gray-700 mb-1">
              Amount
            </label>
            <input
              id="resolution-amount"
              type="number"
              min="0"
              step="0.01"
              value={amount}
              onChange={e => setAmount(e.target.value)}
              placeholder="0.00"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
            />
          </div>
        )}

        {/* Conditional stock item selector */}
        {needsStockItems && (
          <div>
            <label htmlFor="stock-item-ids" className="block text-sm font-medium text-gray-700 mb-1">
              Return Stock Item IDs (comma-separated)
            </label>
            <input
              id="stock-item-ids"
              type="text"
              value={stockItemIds}
              onChange={e => setStockItemIds(e.target.value)}
              placeholder="uuid1, uuid2…"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
            />
          </div>
        )}

        {/* Notes */}
        <div>
          <label htmlFor="resolution-notes" className="block text-sm font-medium text-gray-700 mb-1">
            Notes
          </label>
          <textarea
            id="resolution-notes"
            value={notes}
            onChange={e => setNotes(e.target.value)}
            rows={3}
            placeholder="Optional resolution notes…"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none resize-y"
          />
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" size="sm" onClick={handleClose} disabled={loading}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleSubmit} disabled={!canSubmit} loading={loading}>
            Resolve Claim
          </Button>
        </div>
      </div>
    </Modal>
  )
}
