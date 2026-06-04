/**
 * Modal for resolving a claim with a resolution type and optional details.
 *
 * Requirements: 3.1-3.7
 */

import { useState } from 'react'
import { Modal, Button } from '@/components/ui'

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
      <div className="space-y-4" data-testid="resolve-modal">
        {/* Resolution type */}
        <div>
          <label htmlFor="resolution-type" className="mb-1 block text-sm font-medium text-text">
            Resolution Type
          </label>
          <select
            id="resolution-type"
            value={resolutionType}
            onChange={e => setResolutionType(e.target.value)}
            className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent"
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
            <label htmlFor="resolution-amount" className="mb-1 block text-sm font-medium text-text">
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
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent"
            />
          </div>
        )}

        {/* Conditional stock item selector */}
        {needsStockItems && (
          <div>
            <label htmlFor="stock-item-ids" className="mb-1 block text-sm font-medium text-text">
              Return Stock Item IDs (comma-separated)
            </label>
            <input
              id="stock-item-ids"
              type="text"
              value={stockItemIds}
              onChange={e => setStockItemIds(e.target.value)}
              placeholder="uuid1, uuid2…"
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent"
            />
          </div>
        )}

        {/* Notes */}
        <div>
          <label htmlFor="resolution-notes" className="mb-1 block text-sm font-medium text-text">
            Notes
          </label>
          <textarea
            id="resolution-notes"
            value={notes}
            onChange={e => setNotes(e.target.value)}
            rows={3}
            placeholder="Optional resolution notes…"
            className="w-full resize-y rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent"
          />
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" size="sm" onClick={handleClose} disabled={loading}>
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
