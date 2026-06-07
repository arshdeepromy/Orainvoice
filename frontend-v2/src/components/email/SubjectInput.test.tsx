import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SubjectInput, SUBJECT_MAX_LENGTH } from './SubjectInput'

/**
 * SubjectInput unit tests (task 12.3, R21.4).
 *
 * SubjectInput is a thin controlled wrapper: it owns no edit-tracking flag (the
 * parent diffs the reported value against the default to drive
 * `subject_was_edited`). These tests cover required/empty inline error, the
 * char-count threshold (visible only past 200 chars), and that the component
 * reports value changes through onChange.
 */

describe('SubjectInput', () => {
  it('renders the labelled Subject input pre-populated with the value', () => {
    render(<SubjectInput value="Your invoice is ready" onChange={vi.fn()} />)
    const input = screen.getByLabelText('Subject') as HTMLInputElement
    expect(input).toHaveValue('Your invoice is ready')
  })

  it('shows "Subject is required." when the value is empty', () => {
    render(<SubjectInput value="" onChange={vi.fn()} />)
    expect(screen.getByText('Subject is required.')).toBeInTheDocument()
  })

  it('treats whitespace-only as empty and shows the required error', () => {
    render(<SubjectInput value="   " onChange={vi.fn()} />)
    expect(screen.getByText('Subject is required.')).toBeInTheDocument()
  })

  it('does NOT show the required error when a subject is present', () => {
    render(<SubjectInput value="Hi" onChange={vi.fn()} />)
    expect(screen.queryByText('Subject is required.')).toBeNull()
  })

  it('hides the character count at or below 200 characters', () => {
    render(<SubjectInput value={'a'.repeat(200)} onChange={vi.fn()} />)
    expect(screen.queryByText(/\/\s*255/)).toBeNull()
  })

  it('shows the character count only once the value exceeds 200 characters', () => {
    render(<SubjectInput value={'a'.repeat(201)} onChange={vi.fn()} />)
    expect(screen.getByText(`201 / ${SUBJECT_MAX_LENGTH}`)).toBeInTheDocument()
  })

  it('caps the input at the 255-character maxLength', () => {
    render(<SubjectInput value="Hi" onChange={vi.fn()} />)
    expect(screen.getByLabelText('Subject')).toHaveAttribute('maxlength', String(SUBJECT_MAX_LENGTH))
  })

  it('reports every change through onChange (parent owns the edited flag)', async () => {
    const onChange = vi.fn()
    render(<SubjectInput value="" onChange={onChange} />)
    await userEvent.type(screen.getByLabelText('Subject'), 'R')
    expect(onChange).toHaveBeenCalledWith('R')
  })
})
