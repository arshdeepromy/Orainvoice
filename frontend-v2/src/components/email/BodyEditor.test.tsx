import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BodyEditor, stripUnsafePastedHtml } from './BodyEditor'
import type { SenderPreview } from './types'

/**
 * BodyEditor unit tests (task 12.4, R21.4).
 *
 * TipTap initialises in jsdom well enough to render the toolbar + footers, so we
 * test: default render of the toolbar, the read-only sender footer
 * ("Sender: {from_name} <{from_email}>"), the locale line, and that clicking
 * "Reset to default" calls onResetToDefault. Paste sanitisation is verified by
 * unit-testing the exported pure `stripUnsafePastedHtml` helper, which is the
 * function wired into TipTap's `transformPastedHTML` (R6.4) — far more robust
 * than driving a paste event through the editor in jsdom.
 */

const sender: SenderPreview = {
  from_name: 'Kerikeri Motors',
  from_email: 'billing@kerikerimotors.test',
  reply_to: null,
}

function renderEditor(overrides: Partial<React.ComponentProps<typeof BodyEditor>> = {}) {
  return render(
    <BodyEditor
      valueHtml="<p>Hello there</p>"
      defaultHtml="<p>Hello there</p>"
      onChange={vi.fn()}
      onResetToDefault={vi.fn()}
      senderPreview={sender}
      locale="en"
      {...overrides}
    />,
  )
}

describe('BodyEditor — render', () => {
  it('renders the formatting toolbar', () => {
    renderEditor()
    expect(screen.getByRole('toolbar', { name: 'Text formatting' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Bold' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Link' })).toBeInTheDocument()
  })

  it('renders the read-only sender footer from senderPreview', () => {
    renderEditor()
    expect(
      screen.getByText('Sender: Kerikeri Motors <billing@kerikerimotors.test>'),
    ).toBeInTheDocument()
  })

  it('renders the locale line with a friendly display name', () => {
    renderEditor({ locale: 'en' })
    expect(screen.getByText('Default content rendered in English')).toBeInTheDocument()
  })

  it('falls back to the raw locale code when unknown', () => {
    renderEditor({ locale: 'xx' })
    expect(screen.getByText('Default content rendered in xx')).toBeInTheDocument()
  })

  it('calls onResetToDefault when "Reset to default" is clicked', async () => {
    const onResetToDefault = vi.fn()
    renderEditor({ onResetToDefault })
    await userEvent.click(screen.getByRole('button', { name: 'Reset to default' }))
    expect(onResetToDefault).toHaveBeenCalledTimes(1)
  })
})

describe('stripUnsafePastedHtml — paste sanitisation (R6.4)', () => {
  it('removes <script> elements entirely', () => {
    const out = stripUnsafePastedHtml('<p>ok</p><script>alert(1)</script>')
    expect(out).not.toMatch(/<script/i)
    expect(out).toContain('ok')
  })

  it('removes <style>, <iframe>, <object>, <embed>, <link>, <meta>', () => {
    const out = stripUnsafePastedHtml(
      '<style>p{color:red}</style><iframe src="x"></iframe><object></object><embed><link><meta>',
    )
    expect(out).not.toMatch(/<style|<iframe|<object|<embed|<link|<meta/i)
  })

  it('strips on* event-handler attributes', () => {
    const out = stripUnsafePastedHtml('<p onclick="steal()">hi</p>')
    expect(out).not.toMatch(/onclick/i)
    expect(out).toContain('hi')
  })

  it('strips inline style attributes', () => {
    const out = stripUnsafePastedHtml('<p style="color:red">hi</p>')
    expect(out).not.toMatch(/style=/i)
  })

  it('removes javascript: and data: and file: URLs from href/src', () => {
    expect(stripUnsafePastedHtml('<a href="javascript:alert(1)">x</a>')).not.toMatch(/javascript:/i)
    expect(stripUnsafePastedHtml('<img src="data:text/html,evil">')).not.toMatch(/data:/i)
    expect(stripUnsafePastedHtml('<a href="file:///etc/passwd">x</a>')).not.toMatch(/file:/i)
  })

  it('preserves safe http/https links and text content', () => {
    const out = stripUnsafePastedHtml('<a href="https://example.com">link</a>')
    expect(out).toContain('href="https://example.com"')
    expect(out).toContain('link')
  })
})
