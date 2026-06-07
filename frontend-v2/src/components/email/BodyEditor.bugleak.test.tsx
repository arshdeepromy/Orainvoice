import { describe, it, expect } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import BodyEditor from './BodyEditor'
import type { SenderPreview } from './types'

/**
 * Exploratory bug-condition test — email-preview-body-mismatch, Task 6.1.
 *
 * This test mounts the REAL TipTap `BodyEditor` (NOT the lightweight textarea
 * stub used by `SendEmailModal.test.tsx`) and feeds it a full transactional
 * HTML *document* — the historical shape of the preview `body_html` field
 * (`<!DOCTYPE>…<head><title>{subject}</title></head><body>…</body></html>`).
 *
 * It demonstrates the ROOT CAUSE the bugfix addresses (bug condition 1.1,
 * Requirement 2.1): when a full document is handed to TipTap/ProseMirror, the
 * DOM parser walks the whole tree and surfaces the `<title>{subject}` text as
 * editable BODY content — so the subject line leaks into the editor as the
 * first visible paragraph, even though the sent email keeps the subject only
 * in `<title>`.
 *
 * The `SendEmailModal.test.tsx` suite stubs `./BodyEditor`, which hid this real
 * `useEditor` behaviour from CI; this test closes that gap. It asserts the
 * bug-producing behaviour of the raw input (a full document), proving WHY the
 * contract had to change so the editor binds to the chrome-free
 * `body_editable_html` fragment instead.
 *
 * **Validates: Requirements 2.1**
 */

const SENDER: SenderPreview = {
  from_email: 'billing@kerikerimotors.test',
  from_name: 'Kerikeri Motors',
  reply_to: null,
}

const SUBJECT = 'Invoice SPINV-0057 from SP Automotive'

/**
 * The `body_html` field the preview actually delivered to the editor before the
 * fix. It is the full transactional document AFTER `sanitise_email_html`, which
 * strips the disallowed `<!DOCTYPE>`/`<head>`/`<title>` tags but PRESERVES their
 * text (bleach `strip=True`). The result is the subject surviving as a BARE
 * leading text node ahead of the body `<div>` — exactly the string the editor
 * bound to (confirmed by the backend exploration test:
 * `body_html.strip().startswith(subject)`). When TipTap/ProseMirror parses this,
 * the leading bare text becomes the first editable paragraph → the subject leak.
 */
const SANITISED_BODY_HTML =
  `${SUBJECT}` +
  `<div style="max-width:640px;margin:0 auto">` +
  `<p>Hi Jane,</p>` +
  `<p>Your invoice is ready. You can view it online using the button below.</p>` +
  `<p>Kind regards,<br>SP Automotive</p>` +
  `</div>`

describe('BodyEditor (real TipTap) — full-document subject leak (bug exploration)', () => {
  it('surfaces the <title> subject as editable body text when fed a full document', async () => {
    const { container } = render(
      <BodyEditor
        valueHtml={SANITISED_BODY_HTML}
        defaultHtml={SANITISED_BODY_HTML}
        onChange={() => {}}
        onResetToDefault={() => {}}
        senderPreview={SENDER}
        locale="en"
      />,
    )

    // The real TipTap editor mounts into a `.tiptap.ProseMirror` contenteditable
    // (immediatelyRender:false ⇒ it appears after the mount effect, not the stub).
    await waitFor(() => {
      expect(container.querySelector('.tiptap.ProseMirror')).not.toBeNull()
    })
    const editor = container.querySelector('.tiptap.ProseMirror') as HTMLElement

    // BUG: ProseMirror pulled the leading subject text (the former <title>
    // content) into the editable body, so the subject line is now visible
    // editor content the customer's email never contains.
    await waitFor(() => {
      expect(editor.textContent ?? '').toContain(SUBJECT)
    })
  })
})
