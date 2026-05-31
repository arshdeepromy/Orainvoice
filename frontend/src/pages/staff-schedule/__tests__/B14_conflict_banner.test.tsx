/**
 * Tests for the ConflictBanner (B14):
 *   - Renders one row per conflict.
 *   - Click → onScrollToCell with the right (staffId, date).
 *   - Dismiss → onDismiss.
 *
 * Validates: R13.1, R13.3, R13.4, R13.5.
 */

import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import ConflictBanner from '../components/ConflictBanner'
import type { BulkConflictItem } from '@/types/schedule'

afterEach(() => cleanup())

function makeConflict(idx: number, staff: string, dateIso: string): BulkConflictItem {
  return {
    index: idx,
    attempted: {
      staff_id: staff,
      title: `Attempted ${idx}`,
      start_time: `${dateIso}T09:00:00.000Z`,
      end_time: `${dateIso}T17:00:00.000Z`,
      entry_type: 'job',
      recurrence: 'none',
    },
    conflicts_with: [
      {
        id: `existing-${idx}`,
        org_id: 'o',
        staff_id: staff,
        title: `Existing ${idx}`,
        start_time: `${dateIso}T08:00:00.000Z`,
        end_time: `${dateIso}T16:00:00.000Z`,
        entry_type: 'job',
        status: 'scheduled',
        created_at: '',
        updated_at: '',
      },
    ],
  }
}

describe('ConflictBanner', () => {
  it('renders one row per conflict', () => {
    const onScrollToCell = vi.fn()
    const onDismiss = vi.fn()
    render(
      <ConflictBanner
        conflicts={[
          { conflict: makeConflict(0, 's1', '2025-06-02'), staff_name: 'Alice', date: '2025-06-02' },
          { conflict: makeConflict(1, 's2', '2025-06-03'), staff_name: 'Bob', date: '2025-06-03' },
        ]}
        onScrollToCell={onScrollToCell}
        onDismiss={onDismiss}
      />,
    )
    expect(screen.getByText(/2 conflicts found/i)).toBeInTheDocument()
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('Bob')).toBeInTheDocument()
  })

  it('fires onScrollToCell with the right staffId+date when clicked', () => {
    const onScrollToCell = vi.fn()
    render(
      <ConflictBanner
        conflicts={[
          { conflict: makeConflict(0, 's1', '2025-06-02'), staff_name: 'Alice', date: '2025-06-02' },
        ]}
        onScrollToCell={onScrollToCell}
        onDismiss={() => {}}
      />,
    )
    const row = screen.getByText('Alice').closest('button')!
    fireEvent.click(row)
    expect(onScrollToCell).toHaveBeenCalledWith('s1', '2025-06-02')
  })

  it('fires onDismiss when dismiss button is clicked', () => {
    const onDismiss = vi.fn()
    render(
      <ConflictBanner
        conflicts={[
          { conflict: makeConflict(0, 's1', '2025-06-02'), staff_name: 'Alice', date: '2025-06-02' },
        ]}
        onScrollToCell={() => {}}
        onDismiss={onDismiss}
      />,
    )
    fireEvent.click(screen.getByLabelText(/dismiss conflict banner/i))
    expect(onDismiss).toHaveBeenCalled()
  })

  it('returns null when no conflicts', () => {
    const { container } = render(
      <ConflictBanner
        conflicts={[]}
        onScrollToCell={() => {}}
        onDismiss={() => {}}
      />,
    )
    expect(container.firstChild).toBeNull()
  })
})
