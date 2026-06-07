import { describe, it, expect, vi, beforeAll } from 'vitest'
import { useState } from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BodyEditor, stripFullDocumentChrome } from './BodyEditor'
import type { SenderPreview } from './types'

/**
 * jsdom does not implement the layout APIs ProseMirror calls while applying an
 * edit transaction (`elementFromPoint`, `Range/Element.getClientRects`,
 * `getBoundingClientRect`). Without these, typing into the real TipTap editor
 * throws mid-transaction and `onUpdate` never fires. Polyfilling them with
 * inert stubs lets the WYSIWYG edit path run to completion so we can assert the
 * `onChange` contract in Rich mode. This is the documented jsdom/TipTap
 * limitation noted in the spec (Task 6.4).
 */
beforeAll(() => {
  if (!document.elementFromPoint) {
    document.elementFromPoint = () => null
  }
  const emptyRectList = () =>
    Object.assign([], { item: () => null }) as unknown as DOMRectList
  if (!Element.prototype.getClientRects) {
    Element.prototype.getClientRects = emptyRectList as unknown as () => DOMRectList
  }
  if (!Range.prototype.getClientRects) {
    Range.prototype.getClientRects = emptyRectList as unknown as () => DOMRectList
  }
  if (!Range.prototype.getBoundingClientRect) {
    // @ts-expect-error jsdom stub
    Range.prototype.getBoundingClientRect = () => ({
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      width: 0,
      height: 0,
    })
  }
})

/**
 * BodyEditor dual-mode tests — email-preview-body-mismatch, Task 6.4.
 *
 * Exercises the REAL TipTap `BodyEditor` (not the textarea stub) for the
 * dual-mode (rich ↔ HTML) capability added by this bugfix:
 *
 *   - Property 6 — Rich↔HTML round-trip preserves the inner-body fragment: the
 *     HTML-mode textarea shows `editor.getHTML()`, and toggling Rich→HTML→Rich→HTML
 *     reproduces the same fragment.
 *   - HTML-mode paste of a FULL document degrades to its body fragment before it
 *     reaches `onChange` (the `stripFullDocumentChrome` hardening, Requirement 2.1).
 *   - `body_was_edited` flips in BOTH modes — editing diverges the emitted value
 *     from the default fragment via `onChange` (the parent's `handleBodyChange`
 *     uses exactly this signal).
 *   - Reset-to-default restores the fragment in the active mode.
 *
 * The editor is *controlled* by its parent (`valueHtml` is the source of truth,
 * `onChange` emits), so these tests wrap it in a small stateful `Harness` that
 * mirrors how `SendEmailModal` drives it.
 */

const SENDER: SenderPreview = {
  from_name: 'Kerikeri Motors',
  from_email: 'billing@kerikerimotors.test',
  reply_to: null,
}

const FRAGMENT = '<p>Hi Jane,</p><p>Your invoice is ready.</p>'

/** Last argument passed to an onChange spy (avoids Array.prototype.at for lib compat). */
function lastEmitted(spy: ReturnType<typeof vi.fn>): string {
  const calls = spy.mock.calls
  return calls[calls.length - 1][0] as string
}

function Harness({
  initial = FRAGMENT,
  onChangeSpy,
}: {
  initial?: string
  onChangeSpy?: (html: string) => void
}) {
  const [html, setHtml] = useState(initial)
  return (
    <BodyEditor
      valueHtml={html}
      defaultHtml={initial}
      onChange={(next) => {
        onChangeSpy?.(next)
        setHtml(next)
      }}
      // Mirror the modal: reset restores the default fragment.
      onResetToDefault={() => setHtml(initial)}
      senderPreview={SENDER}
      locale="en"
    />
  )
}

/** Wait for the real TipTap editor (immediatelyRender:false ⇒ appears post-mount). */
async function waitForEditor() {
  await waitFor(() => {
    expect(document.querySelector('.tiptap.ProseMirror')).not.toBeNull()
  })
}

describe('BodyEditor dual-mode — Rich↔HTML round-trip (Property 6)', () => {
  it('shows editor.getHTML() in HTML mode and preserves the fragment across toggles', async () => {
    render(<Harness initial={FRAGMENT} />)
    await waitForEditor()

    // Rich → HTML: textarea reflects the serialised fragment exactly.
    await userEvent.click(screen.getByRole('button', { name: 'HTML' }))
    const textarea = screen.getByLabelText('HTML source') as HTMLTextAreaElement
    expect(textarea).toHaveValue(FRAGMENT)

    // HTML → Rich: the WYSIWYG editor re-renders with the same content.
    await userEvent.click(screen.getByRole('button', { name: 'Rich text' }))
    await waitForEditor()
    expect((document.querySelector('.tiptap.ProseMirror') as HTMLElement).textContent).toContain(
      'Your invoice is ready.',
    )

    // Rich → HTML again: the fragment is byte-identical (no drift).
    await userEvent.click(screen.getByRole('button', { name: 'HTML' }))
    expect(screen.getByLabelText('HTML source')).toHaveValue(FRAGMENT)
  })

  it('does not leak the subject/chrome — the fragment never contains <title>/<head>', async () => {
    render(<Harness initial={FRAGMENT} />)
    await waitForEditor()
    await userEvent.click(screen.getByRole('button', { name: 'HTML' }))
    const value = (screen.getByLabelText('HTML source') as HTMLTextAreaElement).value
    expect(value).not.toMatch(/<!doctype|<head|<title|<html|<body/i)
  })
})

describe('BodyEditor dual-mode — HTML paste degrades a full document (Requirement 2.1)', () => {
  // The exported helper is the authoritative, deterministic unit under test.
  it('stripFullDocumentChrome reduces a full document to its body fragment', () => {
    const fullDoc =
      '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">' +
      '<title>Invoice SPINV-0057 from SP Automotive</title></head>' +
      '<body><div><p>Hi Jane,</p><p>Your invoice is ready.</p></div></body></html>'
    const out = stripFullDocumentChrome(fullDoc)
    expect(out).not.toMatch(/<!doctype|<head|<title|<html|<body/i)
    expect(out).not.toContain('Invoice SPINV-0057 from SP Automotive')
    expect(out).toContain('Hi Jane,')
    expect(out).toContain('Your invoice is ready.')
  })

  it('stripFullDocumentChrome passes a partial fragment through unchanged', () => {
    const fragment = '<table><tr><td>Styled button</td></tr></table>'
    expect(stripFullDocumentChrome(fragment)).toBe(fragment)
  })

  it('a full-document paste into the HTML textarea reaches onChange as a body fragment', async () => {
    const onChangeSpy = vi.fn()
    render(<Harness initial="<p></p>" onChangeSpy={onChangeSpy} />)
    await waitForEditor()
    await userEvent.click(screen.getByRole('button', { name: 'HTML' }))
    const textarea = screen.getByLabelText('HTML source')

    const fullDoc =
      '<!DOCTYPE html><html><head><title>LEAKED SUBJECT</title></head>' +
      '<body><div><p>Pasted body</p></div></body></html>'
    fireEvent.paste(textarea, {
      clipboardData: {
        getData: (type: string) => (type === 'text/html' ? fullDoc : ''),
      },
    })

    await waitFor(() => expect(onChangeSpy).toHaveBeenCalled())
    const emitted = lastEmitted(onChangeSpy)
    expect(emitted).not.toMatch(/<!doctype|<head|<title|<html|<body/i)
    expect(emitted).not.toContain('LEAKED SUBJECT')
    expect(emitted).toContain('Pasted body')
  })
})

describe('BodyEditor dual-mode — body_was_edited flips in both modes', () => {
  it('HTML-mode editing emits a value that diverges from the default fragment', async () => {
    const onChangeSpy = vi.fn()
    render(<Harness initial={FRAGMENT} onChangeSpy={onChangeSpy} />)
    await waitForEditor()

    await userEvent.click(screen.getByRole('button', { name: 'HTML' }))
    const textarea = screen.getByLabelText('HTML source')
    await userEvent.clear(textarea)
    await userEvent.type(textarea, '<p>Edited in HTML mode</p>')

    await waitFor(() => expect(onChangeSpy).toHaveBeenCalled())
    const emitted = lastEmitted(onChangeSpy)
    expect(emitted).not.toBe(FRAGMENT)
    expect(emitted).toContain('Edited in HTML mode')
  })

  it('Rich-mode editing emits a value that diverges from the default fragment', async () => {
    const onChangeSpy = vi.fn()
    render(<Harness initial={FRAGMENT} onChangeSpy={onChangeSpy} />)
    await waitForEditor()

    const pm = document.querySelector('.tiptap.ProseMirror') as HTMLElement
    await userEvent.click(pm)
    await userEvent.type(pm, 'Z')

    await waitFor(() => {
      expect(onChangeSpy).toHaveBeenCalled()
      const emitted = lastEmitted(onChangeSpy)
      expect(emitted).not.toBe(FRAGMENT)
    })
  })
})

describe('BodyEditor dual-mode — reset restores the fragment in the active mode', () => {
  it('reset-to-default restores the original fragment while in HTML mode', async () => {
    render(<Harness initial={FRAGMENT} />)
    await waitForEditor()

    await userEvent.click(screen.getByRole('button', { name: 'HTML' }))
    const textarea = screen.getByLabelText('HTML source')
    await userEvent.clear(textarea)
    await userEvent.type(textarea, '<p>throwaway</p>')
    expect(textarea).toHaveValue('<p>throwaway</p>')

    // Reset restores the default fragment (the parent re-seeds valueHtml).
    await userEvent.click(screen.getByRole('button', { name: 'Reset to default' }))
    expect(screen.getByLabelText('HTML source')).toHaveValue(FRAGMENT)
  })
})
