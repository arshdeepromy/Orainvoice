import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { BranchBadge } from '../BranchBadge'

const mockSelectBranch = vi.fn()
const mockUseBranch = vi.fn()

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => mockUseBranch(),
}))

describe('BranchBadge', () => {
  beforeEach(() => {
    mockSelectBranch.mockClear()
  })

  it('renders nothing when no branches and not locked', () => {
    mockUseBranch.mockReturnValue({
      selectedBranchId: null,
      branches: [],
      selectBranch: mockSelectBranch,
      isLoading: false,
      isBranchLocked: false,
    })
    const { container } = render(<BranchBadge />)
    expect(container.querySelector('button')).toBeNull()
  })

  it('renders "All Branches" when no branch is selected', () => {
    mockUseBranch.mockReturnValue({
      selectedBranchId: null,
      branches: [
        { id: 'b1', name: 'Auckland', is_active: true },
        { id: 'b2', name: 'Wellington', is_active: true },
      ],
      selectBranch: mockSelectBranch,
      isLoading: false,
      isBranchLocked: false,
    })
    render(<BranchBadge />)
    expect(screen.getByText('All Branches')).toBeInTheDocument()
  })

  it('renders selected branch name', () => {
    mockUseBranch.mockReturnValue({
      selectedBranchId: 'b1',
      branches: [
        { id: 'b1', name: 'Auckland', is_active: true },
        { id: 'b2', name: 'Wellington', is_active: true },
      ],
      selectBranch: mockSelectBranch,
      isLoading: false,
      isBranchLocked: false,
    })
    render(<BranchBadge />)
    expect(screen.getByText('Auckland')).toBeInTheDocument()
  })

  it('opens dropdown on tap and shows branch options', () => {
    mockUseBranch.mockReturnValue({
      selectedBranchId: null,
      branches: [
        { id: 'b1', name: 'Auckland', is_active: true },
        { id: 'b2', name: 'Wellington', is_active: true },
      ],
      selectBranch: mockSelectBranch,
      isLoading: false,
      isBranchLocked: false,
    })
    render(<BranchBadge />)

    // Open dropdown
    fireEvent.click(screen.getByRole('button'))

    // Should show all options
    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(3) // All Branches + 2 branches
    expect(screen.getByText('Auckland')).toBeInTheDocument()
    expect(screen.getByText('Wellington')).toBeInTheDocument()
  })

  it('calls selectBranch when a branch is selected', () => {
    mockUseBranch.mockReturnValue({
      selectedBranchId: null,
      branches: [
        { id: 'b1', name: 'Auckland', is_active: true },
        { id: 'b2', name: 'Wellington', is_active: true },
      ],
      selectBranch: mockSelectBranch,
      isLoading: false,
      isBranchLocked: false,
    })
    render(<BranchBadge />)

    fireEvent.click(screen.getByRole('button'))
    fireEvent.click(screen.getByText('Wellington'))

    expect(mockSelectBranch).toHaveBeenCalledWith('b2')
  })

  it('does not open dropdown when branch is locked', () => {
    mockUseBranch.mockReturnValue({
      selectedBranchId: 'b1',
      branches: [],
      selectBranch: mockSelectBranch,
      isLoading: false,
      isBranchLocked: true,
    })
    render(<BranchBadge />)

    fireEvent.click(screen.getByRole('button'))

    // Dropdown should not appear
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('has minimum 44px touch target', () => {
    mockUseBranch.mockReturnValue({
      selectedBranchId: 'b1',
      branches: [{ id: 'b1', name: 'Auckland', is_active: true }],
      selectBranch: mockSelectBranch,
      isLoading: false,
      isBranchLocked: false,
    })
    render(<BranchBadge />)

    const button = screen.getByRole('button')
    expect(button.className).toContain('min-h-[44px]')
    expect(button.className).toContain('min-w-[44px]')
  })
})
