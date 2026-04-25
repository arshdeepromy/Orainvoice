import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { MobileInput } from '../MobileInput'

describe('MobileInput', () => {
  it('renders with label', () => {
    render(<MobileInput label="Email" />)
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
  })

  it('has 44px min height for touch target', () => {
    render(<MobileInput label="Name" />)
    const input = screen.getByLabelText('Name')
    expect(input.className).toContain('min-h-[44px]')
  })

  it('shows required asterisk when required', () => {
    render(<MobileInput label="Name" required />)
    expect(screen.getByText('*')).toBeInTheDocument()
  })

  it('shows error message and sets aria-invalid', () => {
    render(<MobileInput label="Email" error="Invalid email" />)
    const input = screen.getByLabelText('Email')
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid email')
  })

  it('shows helper text when no error', () => {
    render(<MobileInput label="Phone" helperText="Include country code" />)
    expect(screen.getByText('Include country code')).toBeInTheDocument()
  })

  it('hides helper text when error is present', () => {
    render(
      <MobileInput label="Phone" helperText="Include country code" error="Required" />,
    )
    expect(screen.queryByText('Include country code')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Required')
  })

  it('accepts user input', async () => {
    const user = userEvent.setup()
    render(<MobileInput label="Name" />)
    const input = screen.getByLabelText('Name')
    await user.type(input, 'John')
    expect(input).toHaveValue('John')
  })

  it('applies error border styles', () => {
    render(<MobileInput label="Email" error="Bad" />)
    const input = screen.getByLabelText('Email')
    expect(input.className).toContain('border-red-500')
  })
})
