import { useCallback, useEffect, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import type { Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import type { SenderPreview } from './types'

/**
 * MobileBodyEditor — TipTap rich-text body editor for the mobile Send Email sheet.
 *
 * This is the ONLY module in the mobile app that imports TipTap. The parent
 * (`SendEmailSheet`) `React.lazy()`-imports it so the TipTap bundle is code-split
 * and only loaded when the composer opens (R6.1 / R12.1). For that reason this
 * file exposes a default export.
 *
 * It mirrors the web `BodyEditor` (same StarterKit + link + underline extensions,
 * same client-side paste sanitisation, emits HTML via `getHTML()`), but with a
 * mobile-optimised layout: a larger touch-target toolbar and an editor surface
 * that fills the available space so the body occupies ≥ 50 % of the viewport
 * (R12.2 / R12.3). The server re-applies the Body_Sanitiser as defence in depth.
 *
 * Like the web editor it supports a dual authoring mode — rich WYSIWYG (default)
 * and a raw-HTML `<textarea>` — so power users can author or paste full styled
 * HTML email templates. Both modes operate on the same inner-body fragment
 * (design.md → "dual-mode rich/HTML editing").
 */

export interface MobileBodyEditorProps {
  valueHtml: string
  defaultHtml: string
  onChange: (html: string) => void
  onResetToDefault: () => void
  senderPreview: SenderPreview
  locale: string
}

/** The two authoring modes the body editor supports. */
export type EditorMode = 'rich' | 'html'

const LOCALE_DISPLAY_NAMES: Record<string, string> = {
  en: 'English',
  'en-us': 'English (US)',
  'en-gb': 'English (UK)',
  'en-nz': 'English (NZ)',
  'en-au': 'English (Australia)',
  mi: 'Māori',
  fr: 'French',
  de: 'German',
  es: 'Spanish',
  it: 'Italian',
  nl: 'Dutch',
  pt: 'Portuguese',
  zh: 'Chinese',
  ja: 'Japanese',
  ko: 'Korean',
}

function localeDisplayName(locale: string): string {
  if (!locale) return locale
  return LOCALE_DISPLAY_NAMES[locale.toLowerCase()] ?? locale
}

/**
 * Strip styles / scripts / iframes / event-handler attributes from pasted HTML
 * client-side. TipTap's schema already drops unknown nodes; this removes the
 * dangerous bits before they reach the parser. The server re-sanitises as
 * defence in depth.
 */
export function stripUnsafePastedHtml(html: string): string {
  if (typeof window === 'undefined' || typeof DOMParser === 'undefined') return html
  const doc = new DOMParser().parseFromString(html, 'text/html')

  doc
    .querySelectorAll('script, iframe, style, object, embed, link, meta')
    .forEach((el) => el.remove())

  doc.querySelectorAll('*').forEach((el) => {
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase()
      const value = attr.value.toLowerCase().replace(/\s+/g, '')
      if (
        name.startsWith('on') ||
        name === 'style' ||
        ((name === 'href' || name === 'src') &&
          (value.startsWith('javascript:') ||
            value.startsWith('data:') ||
            value.startsWith('file:')))
      ) {
        el.removeAttribute(attr.name)
      }
    }
  })

  return doc.body.innerHTML
}

/**
 * Reduce a pasted full HTML *document* to its inner body fragment (R: dual-mode
 * paste hardening, bugfix Requirement 2.1). When the HTML-mode textarea receives
 * a complete document — anything carrying `<!DOCTYPE>`, `<html>`, `<head>`,
 * `<title>`, or `<body>` chrome — we extract `body.innerHTML` so the document
 * head/title text can never re-leak into the editable body (the very defect this
 * bugfix addresses). Partial fragments (e.g. a bare `<table>…</table>` paste) are
 * returned UNCHANGED so legitimate styled-template pastes survive intact. The
 * server `sanitise_email_html` allowlist remains the authoritative defence; this
 * is defence-in-depth and mirrors the web `BodyEditor` helper exactly.
 */
export function stripFullDocumentChrome(html: string): string {
  if (typeof html !== 'string' || html === '') return html

  // Only act on full documents. A partial fragment must pass through verbatim.
  const isFullDocument = /<!doctype|<html[\s>]|<head[\s>]|<title[\s>]|<body[\s>]/i.test(html)
  if (!isFullDocument) return html

  if (typeof window === 'undefined' || typeof DOMParser === 'undefined') {
    // Non-DOM environment fallback: regex-strip the document chrome.
    return html
      .replace(/<!doctype[^>]*>/gi, '')
      .replace(/<title[^>]*>[\s\S]*?<\/title>/gi, '')
      .replace(/<\/?(?:html|head|body)[^>]*>/gi, '')
      .replace(/<meta[^>]*>/gi, '')
      .trim()
  }

  const doc = new DOMParser().parseFromString(html, 'text/html')
  return doc.body ? doc.body.innerHTML : html
}

interface ToolbarButtonProps {
  label: string
  onClick: () => void
  isActive?: boolean
  children: React.ReactNode
}

function ToolbarButton({ label, onClick, isActive = false, children }: ToolbarButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={isActive}
      title={label}
      className={`grid min-h-[44px] min-w-[44px] place-items-center rounded-lg text-base leading-none transition-colors ${
        isActive
          ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
          : 'text-gray-700 active:bg-gray-100 dark:text-gray-200 dark:active:bg-gray-700'
      }`}
    >
      {children}
    </button>
  )
}

/**
 * Segmented Rich/HTML mode toggle — Tab-reachable real `<button>`s with
 * `aria-pressed`, ≥44px touch targets and dark-mode variants. Lives in the
 * toolbar so it is always reachable regardless of the active mode.
 */
function ModeToggle({
  mode,
  onModeChange,
}: {
  mode: EditorMode
  onModeChange: (mode: EditorMode) => void
}) {
  return (
    <div
      role="group"
      aria-label="Editor mode"
      className="flex items-center gap-0.5 rounded-lg bg-gray-200 p-0.5 dark:bg-gray-700"
    >
      <ModeToggleButton
        label="Rich text"
        isActive={mode === 'rich'}
        onClick={() => onModeChange('rich')}
      />
      <ModeToggleButton
        label="HTML"
        isActive={mode === 'html'}
        onClick={() => onModeChange('html')}
      />
    </div>
  )
}

function ModeToggleButton({
  label,
  isActive,
  onClick,
}: {
  label: string
  isActive: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={isActive}
      title={label}
      className={`grid min-h-[44px] place-items-center rounded-md px-3 text-sm font-medium leading-none transition-colors ${
        isActive
          ? 'bg-white text-blue-700 shadow-sm dark:bg-gray-900 dark:text-blue-300'
          : 'text-gray-500 active:text-gray-700 dark:text-gray-400 dark:active:text-gray-200'
      }`}
    >
      {label}
    </button>
  )
}

function Toolbar({
  editor,
  mode,
  onModeChange,
  onResetToDefault,
}: {
  editor: Editor | null
  mode: EditorMode
  onModeChange: (mode: EditorMode) => void
  onResetToDefault: () => void
}) {
  const setLink = useCallback(() => {
    if (!editor) return
    const previous = editor.getAttributes('link').href as string | undefined
    const url = window.prompt('Link URL (leave blank to remove)', previous ?? '')
    if (url === null) return
    if (url.trim() === '') {
      editor.chain().focus().extendMarkRange('link').unsetLink().run()
      return
    }
    editor.chain().focus().extendMarkRange('link').setLink({ href: url.trim() }).run()
  }, [editor])

  return (
    <div
      role="toolbar"
      aria-label="Text formatting"
      className="flex flex-wrap items-center gap-1 border-b border-gray-200 bg-gray-50 px-1 py-1 dark:border-gray-700 dark:bg-gray-900"
    >
      <ModeToggle mode={mode} onModeChange={onModeChange} />

      {mode === 'rich' && editor && (
        <>
          <span className="mx-1 h-5 w-px bg-gray-300 dark:bg-gray-600" aria-hidden="true" />

          <ToolbarButton
            label="Bold"
            isActive={editor.isActive('bold')}
            onClick={() => editor.chain().focus().toggleBold().run()}
          >
            <span className="font-bold">B</span>
          </ToolbarButton>
          <ToolbarButton
            label="Italic"
            isActive={editor.isActive('italic')}
            onClick={() => editor.chain().focus().toggleItalic().run()}
          >
            <span className="italic">I</span>
          </ToolbarButton>
          <ToolbarButton
            label="Underline"
            isActive={editor.isActive('underline')}
            onClick={() => editor.chain().focus().toggleUnderline().run()}
          >
            <span className="underline">U</span>
          </ToolbarButton>

          <span className="mx-1 h-5 w-px bg-gray-300 dark:bg-gray-600" aria-hidden="true" />

          <ToolbarButton
            label="Bullet list"
            isActive={editor.isActive('bulletList')}
            onClick={() => editor.chain().focus().toggleBulletList().run()}
          >
            <ListIcon ordered={false} />
          </ToolbarButton>
          <ToolbarButton
            label="Numbered list"
            isActive={editor.isActive('orderedList')}
            onClick={() => editor.chain().focus().toggleOrderedList().run()}
          >
            <ListIcon ordered />
          </ToolbarButton>
          <ToolbarButton label="Link" isActive={editor.isActive('link')} onClick={setLink}>
            <LinkIcon />
          </ToolbarButton>
        </>
      )}

      <button
        type="button"
        onClick={onResetToDefault}
        className="ml-auto min-h-[44px] rounded-lg px-3 text-sm font-medium text-gray-500 active:bg-gray-100 dark:text-gray-400 dark:active:bg-gray-700"
      >
        Reset
      </button>
    </div>
  )
}

function ListIcon({ ordered }: { ordered: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="h-[17px] w-[17px]"
    >
      {ordered ? (
        <path d="M10 6h11M10 12h11M10 18h11M4 4v4M4 8H3m1 0h1M3 18h2v-2H3.5m0 0H3m2 0v4H3" />
      ) : (
        <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
      )}
    </svg>
  )
}

function LinkIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="h-[17px] w-[17px]"
    >
      <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
    </svg>
  )
}

export function MobileBodyEditor({
  valueHtml,
  defaultHtml: _defaultHtml,
  onChange,
  onResetToDefault,
  senderPreview,
  locale,
}: MobileBodyEditorProps) {
  // Authoring mode — rich WYSIWYG (default) or raw HTML. Both operate on the
  // same inner-body fragment (design.md → "dual-mode rich/HTML editing").
  const [mode, setMode] = useState<EditorMode>('rich')

  const editor = useEditor({
    // Create the editor in an effect (TipTap's recommended React setting) to
    // avoid the StrictMode / lazy-<Suspense> race where a torn-down editor
    // (schema=null) is read during render → "reading 'cached'" crash.
    immediatelyRender: false,
    extensions: [
      // TipTap 3.x StarterKit already bundles Link + Underline; adding the
      // standalone extensions registers duplicates and crashes the editor
      // ("Cannot read properties of null (reading 'cached')"). Configure Link
      // via StarterKit and rely on its bundled Underline.
      StarterKit.configure({
        link: {
          openOnClick: false,
          autolink: true,
          protocols: ['http', 'https', 'mailto'],
        },
      }),
    ],
    content: valueHtml,
    editorProps: {
      attributes: {
        class:
          'tiptap prose-sm max-w-none min-h-[40vh] px-3 py-3 text-base leading-relaxed text-gray-900 dark:text-gray-100 focus:outline-none',
      },
      transformPastedHTML: (html) => stripUnsafePastedHtml(html),
    },
    onUpdate: ({ editor: ed }) => {
      onChange(ed.getHTML())
    },
  })

  // Sync when `valueHtml` changes externally (reset-to-default / preview load)
  // without clobbering the cursor while the user types. Guard against a
  // destroyed editor (schema=null after teardown) to avoid the "reading
  // 'cached'" crash. Only sync while Rich mode owns the content — in HTML mode
  // the textarea is the source of truth.
  useEffect(() => {
    if (!editor || editor.isDestroyed) return
    if (mode !== 'rich') return
    if (valueHtml !== editor.getHTML()) {
      editor.commands.setContent(valueHtml, { emitUpdate: false })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valueHtml, editor, mode])

  // Switch authoring modes, seeding the destination from the current source so
  // the fragment round-trips. Rich→HTML seeds the textarea from the editor's
  // serialised HTML; HTML→Rich pushes the raw HTML back into TipTap without
  // emitting an update (the value is already in sync via `onChange`).
  const handleModeChange = useCallback(
    (next: EditorMode) => {
      if (next === mode) return
      if (editor && !editor.isDestroyed) {
        if (next === 'html') {
          // Rich → HTML: make sure the textarea reflects the editor exactly.
          const html = editor.getHTML()
          if (html !== valueHtml) onChange(html)
        } else {
          // HTML → Rich: re-render the raw HTML into the WYSIWYG editor.
          editor.commands.setContent(valueHtml, { emitUpdate: false })
        }
      }
      setMode(next)
    },
    [mode, editor, valueHtml, onChange],
  )

  // HTML-mode textarea edits flow through the same `onChange` contract the
  // editor uses, so the parent's `body_was_edited` logic works in both modes.
  const handleTextareaChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      onChange(e.target.value)
    },
    [onChange],
  )

  // Harden HTML-mode paste against a full-document re-leak: if the pasted text
  // is a complete HTML document, reduce it to its body fragment before it ever
  // reaches `onChange`, so document head/title chrome cannot re-introduce the
  // subject-leak this bugfix removes (Requirement 2.1). Partial-HTML pastes are
  // inserted unchanged. The server `sanitise_email_html` is the authoritative
  // defence; this is defence-in-depth.
  const handleTextareaPaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const pasted =
        e.clipboardData?.getData('text/html') || e.clipboardData?.getData('text/plain') || ''
      const stripped = stripFullDocumentChrome(pasted)
      // Only intercept when we actually reduced a full document; otherwise let
      // the browser handle the normal paste (preserves undo + caret behaviour).
      if (stripped === pasted) return

      e.preventDefault()
      const target = e.currentTarget
      const start = target.selectionStart ?? target.value.length
      const end = target.selectionEnd ?? target.value.length
      const next = target.value.slice(0, start) + stripped + target.value.slice(end)
      onChange(next)
      // Restore the caret to just after the inserted fragment on the next tick,
      // once React has flushed the controlled value.
      const caret = start + stripped.length
      requestAnimationFrame(() => {
        if (!target.isConnected) return
        target.setSelectionRange(caret, caret)
      })
    },
    [onChange],
  )

  return (
    <div className="flex flex-col gap-2">
      <div className="flex min-h-[50vh] flex-col overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
        <Toolbar
          editor={editor}
          mode={mode}
          onModeChange={handleModeChange}
          onResetToDefault={onResetToDefault}
        />
        {mode === 'rich' ? (
          <div className="flex-1 overflow-y-auto">
            <EditorContent editor={editor} />
          </div>
        ) : (
          <textarea
            value={valueHtml}
            onChange={handleTextareaChange}
            onPaste={handleTextareaPaste}
            aria-label="HTML source"
            spellCheck={false}
            className="block min-h-[40vh] w-full flex-1 resize-y border-0 bg-white px-3 py-3 font-mono text-sm leading-relaxed text-gray-900 focus:outline-none dark:bg-gray-800 dark:text-gray-100"
          />
        )}
      </div>

      {/* Informational locale line (R3.10) — read-only. */}
      <p className="font-mono text-xs tabular-nums text-gray-400 dark:text-gray-500">
        Default content rendered in {localeDisplayName(locale)}
      </p>

      {/* Read-only sender footer (R6.7 / R9.2) — NOT a form field. */}
      <p className="font-mono text-xs tabular-nums text-gray-500 dark:text-gray-400">
        Sender: {senderPreview.from_name} &lt;{senderPreview.from_email}&gt;
      </p>
    </div>
  )
}

export default MobileBodyEditor
