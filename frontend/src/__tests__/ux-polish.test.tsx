import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Collapsible } from '../components/ui/Collapsible'
import { FormField } from '../components/ui/FormField'
import { LoadingOverlay } from '../components/ui/LoadingOverlay'
import { ActionFeedback } from '../components/ui/ActionFeedback'
import { useFormValidation, rules } from '../hooks/useFormValidation'
import { renderHook, act as actHook } from '@testing-library/react'

/**
 * Validates: Requirements 56.1, 56.2, 56.3, 56.4, 56.5
 * - 56.1: Plain language with no technical jargon
 * - 56.2: Clean, minimal visual design with consistent spacing
 * - 56.3: Immediate visual feedback for all user actions
 * - 56.4: Progressive disclosure — relevant options first, advanced on demand
 * - 56.5: Inline form validation with specific error messages next to fields
 */

// ===========================================================================
// Collapsible — Progressive disclosure (Req 56.4)
// ===========================================================================
describe('Collapsible', () => {
  it('hides content by default', () => {
    render(
      <Collapsible label="Advanced options">
        <p>Hidden content</p>
      </Collapsible>,
    )
    const content = screen.getByText('Hidden content')
    expect(content.closest('[hidden]')).not.toBeNull()
  })

  it('shows content when toggled open', async () => {
    const user = userEvent.setup()
    render(
      <Collapsible label="Advanced options">
        <p>Revealed content</p>
      </Collapsible>,
    )
    const trigger = screen.getByRole('button', { name: 'Advanced options' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')

    await user.click(trigger)

    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    const content = screen.getByText('Revealed content')
    expect(content.closest('[hidden]')).toBeNull()
  })

  it('hides content again when toggled closed', async () => {
    const user = userEvent.setup()
    render(
      <Collapsible label="More settings">
        <p>Toggle me</p>
      </Collapsible>,
    )
    const trigger = screen.getByRole('button', { name: 'More settings' })
    await user.click(trigger) // open
    await user.click(trigger) // close

    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    const content = screen.getByText('Toggle me')
    expect(content.closest('[hidden]')).not.toBeNull()
  })

  it('starts open when defaultOpen is true', () => {
    render(
      <Collapsible label="Details" defaultOpen>
        <p>Visible from start</p>
      </Collapsible>,
    )
    const trigger = screen.getByRole('button', { name: 'Details' })
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    const content = screen.getByText('Visible from start')
    expect(content.closest('[hidden]')).toBeNull()
  })

  it('has aria-controls linking trigger to content region', () => {
    render(
      <Collapsible label="Options">
        <p>Content</p>
      </Collapsible>,
    )
    const trigger = screen.getByRole('button', { name: 'Options' })
    const controlsId = trigger.getAttribute('aria-controls')
    expect(controlsId).toBeTruthy()
    const region = document.getElementById(controlsId!)
    expect(region).toBeInTheDocument()
  })
})

// ===========================================================================
// FormField — Inline validation with error messages (Req 56.5)
// ===========================================================================
describe('FormField', () => {
  it('renders label and child input', () => {
    render(
      <FormField label="Email address">
        {(props) => <input {...props} type="email" />}
      </FormField>,
    )
    expect(screen.getByText('Email address')).toBeInTheDocument()
    const input = screen.getByRole('textbox')
    expect(input).toBeInTheDocument()
  })

  it('displays inline error message next to field', () => {
    render(
      <FormField label="Name" error="Please enter your name">
        {(props) => <input {...props} type="text" />}
      </FormField>,
    )
    const error = screen.getByRole('alert')
    expect(error).toHaveTextContent('Please enter your name')
    const input = screen.getByRole('textbox')
    expect(input).toHaveAttribute('aria-invalid', 'true')
  })

  it('displays helper text when no error', () => {
    render(
      <FormField label="Phone" helperText="Include area code">
        {(props) => <input {...props} type="tel" />}
      </FormField>,
    )
    expect(screen.getByText('Include area code')).toBeInTheDocument()
  })

  it('hides helper text when error is present', () => {
    render(
      <FormField label="Phone" helperText="Include area code" error="Please enter a valid phone number">
        {(props) => <input {...props} type="tel" />}
      </FormField>,
    )
    expect(screen.queryByText('Include area code')).not.toBeInTheDocument()
    expect(screen.getByText('Please enter a valid phone number')).toBeInTheDocument()
  })

  it('shows required indicator', () => {
    render(
      <FormField label="Email" required>
        {(props) => <input {...props} type="email" />}
      </FormField>,
    )
    expect(screen.getByText('*')).toBeInTheDocument()
    expect(screen.getByText('(required)')).toBeInTheDocument()
  })
})

// ===========================================================================
// useFormValidation — Inline validation hook (Req 56.5, 56.1)
// ===========================================================================
describe('useFormValidation', () => {
  const config = {
    name: { rules: [rules.required('Name')] },
    email: { rules: [rules.required('Email'), rules.email()] },
  }

  it('initialises with empty values and no errors', () => {
    const { result } = renderHook(() => useFormValidation(config))
    expect(result.current.values.name).toBe('')
    expect(result.current.values.email).toBe('')
    expect(result.current.errors).toEqual({})
  })

  it('validates a single field with plain language error', () => {
    const { result } = renderHook(() => useFormValidation(config))
    let error: string
    actHook(() => {
      error = result.current.validateField('name')
    })
    expect(error!).toBe('Please enter your name')
    expect(result.current.errors.name).toBe('Please enter your name')
  })

  it('clears error when field becomes valid', () => {
    const { result } = renderHook(() => useFormValidation(config))
    actHook(() => {
      result.current.validateField('name')
    })
    expect(result.current.errors.name).toBeTruthy()

    actHook(() => {
      result.current.setValue('name', 'Alice')
    })
    actHook(() => {
      result.current.validateField('name')
    })
    expect(result.current.errors.name).toBeUndefined()
  })

  it('validateAll returns false when fields are invalid', () => {
    const { result } = renderHook(() => useFormValidation(config))
    let valid: boolean
    actHook(() => {
      valid = result.current.validateAll()
    })
    expect(valid!).toBe(false)
    expect(Object.keys(result.current.errors).length).toBeGreaterThan(0)
  })

  it('validateAll returns true when all fields are valid', () => {
    const { result } = renderHook(() => useFormValidation(config))
    actHook(() => {
      result.current.setValue('name', 'Alice')
      result.current.setValue('email', 'alice@example.com')
    })
    let valid: boolean
    actHook(() => {
      valid = result.current.validateAll()
    })
    expect(valid!).toBe(true)
    expect(result.current.errors).toEqual({})
  })

  it('reset clears values, errors, and touched state', () => {
    const { result } = renderHook(() => useFormValidation(config))
    actHook(() => {
      result.current.setValue('name', 'Bob')
      result.current.setTouched('name')
    })
    actHook(() => {
      result.current.reset()
    })
    expect(result.current.values.name).toBe('')
    expect(result.current.errors).toEqual({})
    expect(result.current.touched).toEqual({})
  })

  it('uses plain language in all built-in rule messages', () => {
    // Verify no technical jargon in error messages (Req 56.1)
    const requiredMsg = rules.required('Name').message
    expect(requiredMsg).toBe('Please enter your name')
    expect(requiredMsg).not.toMatch(/required|invalid|null|undefined|error/i)

    const emailMsg = rules.email().message
    expect(emailMsg).toBe('Please enter a valid email address')

    const phoneMsg = rules.phone().message
    expect(phoneMsg).toBe('Please enter a valid phone number')
  })
})

// ===========================================================================
// LoadingOverlay — Visual feedback for async actions (Req 56.3)
// ===========================================================================
describe('LoadingOverlay', () => {
  it('renders nothing when not visible', () => {
    const { container } = render(<LoadingOverlay visible={false} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows spinner and message when visible', () => {
    render(<LoadingOverlay visible={true} message="Saving your changes…" />)
    const overlays = screen.getAllByRole('status')
    // Outer overlay container has the aria-label
    const outer = overlays.find((el) => el.getAttribute('aria-label') === 'Saving your changes…')
    expect(outer).toBeTruthy()
    // Visible message text is rendered
    const messages = screen.getAllByText('Saving your changes…')
    expect(messages.length).toBeGreaterThanOrEqual(1)
  })

  it('uses default message when none provided', () => {
    render(<LoadingOverlay visible={true} />)
    const messages = screen.getAllByText('Loading…')
    expect(messages.length).toBeGreaterThanOrEqual(1)
  })
})

// ===========================================================================
// ActionFeedback — Success/error feedback after actions (Req 56.3)
// ===========================================================================
describe('ActionFeedback', () => {
  it('renders nothing when not visible', () => {
    const { container } = render(
      <ActionFeedback variant="success" message="Saved" visible={false} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('shows success feedback with status role', () => {
    render(<ActionFeedback variant="success" message="Changes saved" visible={true} />)
    const feedback = screen.getByRole('status')
    expect(feedback).toHaveTextContent('Changes saved')
  })

  it('shows error feedback with alert role', () => {
    render(
      <ActionFeedback variant="error" message="Something went wrong. Please try again." visible={true} />,
    )
    const feedback = screen.getByRole('alert')
    expect(feedback).toHaveTextContent('Something went wrong. Please try again.')
  })

  it('auto-dismisses after specified duration', () => {
    vi.useFakeTimers()
    const onDismiss = vi.fn()
    render(
      <ActionFeedback
        variant="success"
        message="Done"
        visible={true}
        onDismiss={onDismiss}
        autoDismissMs={3000}
      />,
    )
    expect(onDismiss).not.toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(3000)
    })
    expect(onDismiss).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('has a dismiss button when onDismiss is provided', async () => {
    const user = userEvent.setup()
    const onDismiss = vi.fn()
    render(
      <ActionFeedback
        variant="error"
        message="Failed"
        visible={true}
        onDismiss={onDismiss}
        autoDismissMs={0}
      />,
    )
    const dismissBtn = screen.getByRole('button', { name: 'Dismiss' })
    await user.click(dismissBtn)
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('uses plain language in messages — no jargon (Req 56.1)', () => {
    render(
      <ActionFeedback variant="error" message="Something went wrong. Please try again." visible={true} />,
    )
    const text = screen.getByRole('alert').textContent
    expect(text).not.toMatch(/exception|stack trace|500|internal server/i)
  })
})
