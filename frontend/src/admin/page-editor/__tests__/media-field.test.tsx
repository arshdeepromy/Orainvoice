/**
 * Unit tests for the custom MediaField Puck adapter (Task 6.6).
 *
 * Validates: Requirements 12.2 — a Puck field that lets editors
 * browse the media library or paste a URL.
 *
 * The media library modal itself is added in Task 7.8. These tests
 * exercise only the field contract:
 *   1. Renders a label, input, and "Browse Library" button.
 *   2. Typing in the input forwards the new value through `onChange`.
 *   3. Clicking "Browse Library" opens the modal (proven by a dialog
 *      appearing — whether the real modal or the Suspense fallback).
 *   4. `readOnly` disables the input and the browse button.
 *   5. The exported `mediaField()` factory produces a Puck custom
 *      field config (`type: 'custom'`, `render: function`).
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MediaFieldRenderer, mediaField } from '../fields/MediaField'

describe('MediaFieldRenderer', () => {
  it('renders label, input, and Browse Library button', () => {
    render(
      <MediaFieldRenderer value="" onChange={() => {}} label="Hero image" />,
    )
    expect(screen.getByLabelText('Hero image')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /browse library/i }),
    ).toBeInTheDocument()
  })

  it('forwards input changes through onChange', async () => {
    const handleChange = vi.fn()
    render(
      <MediaFieldRenderer
        value=""
        onChange={handleChange}
        label="OG image"
      />,
    )
    const input = screen.getByLabelText('OG image') as HTMLInputElement
    await userEvent.type(input, 'x')
    expect(handleChange).toHaveBeenLastCalledWith('x')
  })

  it('opens the library modal on Browse Library click', async () => {
    render(<MediaFieldRenderer value="" onChange={() => {}} label="Image" />)
    await userEvent.click(
      screen.getByRole('button', { name: /browse library/i }),
    )
    // Either the real modal or the Suspense fallback renders a dialog.
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('disables the input and button when readOnly', () => {
    render(
      <MediaFieldRenderer
        value="https://example.com/img.png"
        onChange={() => {}}
        label="Image"
        readOnly
      />,
    )
    const input = screen.getByLabelText('Image') as HTMLInputElement
    expect(input.readOnly).toBe(true)
    const button = screen.getByRole('button', { name: /browse library/i })
    expect(button).toBeDisabled()
  })

  it('renders a preview <img> when value is a URL', () => {
    render(
      <MediaFieldRenderer
        value="https://cdn.example.com/pic.jpg"
        onChange={() => {}}
      />,
    )
    const img = document.querySelector('img')
    expect(img).not.toBeNull()
    expect(img?.getAttribute('src')).toBe('https://cdn.example.com/pic.jpg')
  })
})

describe('mediaField() factory', () => {
  it('returns a Puck custom field config', () => {
    const cfg = mediaField({ label: 'Hero image' })
    expect(cfg.type).toBe('custom')
    expect(cfg.label).toBe('Hero image')
    expect(typeof cfg.render).toBe('function')
  })
})
