import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MobileSearchBar } from '../MobileSearchBar'

describe('MobileSearchBar', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders with placeholder', () => {
    render(<MobileSearchBar value="" onChange={vi.fn()} placeholder="Search customers" />)
    expect(screen.getByPlaceholderText('Search customers')).toBeInTheDocument()
  })

  it('has search icon', () => {
    const { container } = render(<MobileSearchBar value="" onChange={vi.fn()} />)
    expect(container.querySelector('svg')).toBeTruthy()
  })

  it('debounces onChange calls', () => {
    const onChange = vi.fn()
    render(<MobileSearchBar value="" onChange={onChange} debounceMs={300} />)

    const input = screen.getByRole('searchbox')
    fireEvent.change(input, { target: { value: 'test' } })

    // onChange should not have been called yet
    expect(onChange).not.toHaveBeenCalled()

    // Advance timers past debounce
    act(() => {
      vi.advanceTimersByTime(300)
    })

    expect(onChange).toHaveBeenCalledWith('test')
  })

  it('shows clear button when value is present and clears on click', () => {
    const onChange = vi.fn()
    render(<MobileSearchBar value="hello" onChange={onChange} />)

    const clearBtn = screen.getByLabelText('Clear search')
    expect(clearBtn).toBeInTheDocument()

    fireEvent.click(clearBtn)
    expect(onChange).toHaveBeenCalledWith('')
  })

  it('does not show clear button when value is empty', () => {
    render(<MobileSearchBar value="" onChange={vi.fn()} />)
    expect(screen.queryByLabelText('Clear search')).not.toBeInTheDocument()
  })
})
