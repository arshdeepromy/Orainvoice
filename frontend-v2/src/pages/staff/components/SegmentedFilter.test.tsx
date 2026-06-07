import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SegmentedFilter, { type SegmentedFilterOption } from './SegmentedFilter'

/**
 * SegmentedFilter component tests (Task 9.9).
 *
 * Covers R2.3: every option renders, clicking an option calls `onChange` with
 * that option's value, and the controlled `value` marks the matching option
 * active via `aria-pressed`.
 */

const roleOptions: SegmentedFilterOption[] = [
  { label: 'All roles', value: '' },
  { label: 'Employees', value: 'employee' },
  { label: 'Contractors', value: 'contractor' },
]

describe('SegmentedFilter', () => {
  it('renders every option label', () => {
    render(
      <SegmentedFilter value="" onChange={() => {}} options={roleOptions} ariaLabel="Filter by role" />,
    )
    expect(screen.getByRole('button', { name: 'All roles' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Employees' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Contractors' })).toBeInTheDocument()
  })

  it('exposes the group with its accessible label', () => {
    render(
      <SegmentedFilter value="" onChange={() => {}} options={roleOptions} ariaLabel="Filter by role" />,
    )
    expect(screen.getByRole('group', { name: 'Filter by role' })).toBeInTheDocument()
  })

  it('marks the option matching `value` as active (aria-pressed)', () => {
    render(
      <SegmentedFilter value="employee" onChange={() => {}} options={roleOptions} ariaLabel="Filter by role" />,
    )
    expect(screen.getByRole('button', { name: 'Employees' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'All roles' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'Contractors' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('calls onChange with the clicked option value (R2.3)', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <SegmentedFilter value="" onChange={onChange} options={roleOptions} ariaLabel="Filter by role" />,
    )
    await user.click(screen.getByRole('button', { name: 'Contractors' }))
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith('contractor')
  })
})
