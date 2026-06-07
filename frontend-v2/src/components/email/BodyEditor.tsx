import { useCallback, useEffect, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import type { Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { cx } from '../ui/cx'
import type { SenderPreview } from './types'

/**
 * BodyEditor — the TipTap rich-text body editor for the Send Email composer.
 *
 * This is the ONLY module in frontend-v2 that imports TipTap. The parent
 * (`SendEmailModal`) `React.lazy()`-imports this module so the TipTap bundle is
 * code-split and only loaded when the composer opens (R6.1 / R28.4, ≤80 KB
 * gzipped). For that reason this file exposes a default export.
 *
 * Behaviour (design.md → "BodyEditor.tsx (TipTap wrapper)"):
 *   - Configured with ONLY `@tiptap/starter-kit`, `@tiptap/extension-link`, and
 *     `@tiptap/extension-underline` — no collaboration / yjs (R6.1, R28.4).
 *   - Toolbar: bold, italic, underline, bullet list, ordered list, link
 *     (insert/edit/remove), and "Reset to default" (R6.2). Reset calls
 *     `onResetToDefault` so the parent restores `defaultHtml` and clears
 *     `body_was_edited` (R6.3).
 *   - Keyboard shortcuts Ctrl/Cmd+B/I/U are provided by StarterKit + the
 *     underline extension (R27.2).
 *   - Every toolbar button is Tab-reachable and styled as a small ghost button
 *     (R24.7).
 *   - The paste handler strips style attributes, `<script>`, `<iframe>`, and
 *     `on*` event-handler attributes client-side before TipTap parses the HTML
 *     (R6.4). The server re-applies Body_Sanitiser as defence in depth.
 *   - Emits HTML (not Markdown) via `editor.getHTML()` through `onChange` (R6.5).
 *   - Read-only "Sender: {from_name} <{from_email}>" footer from `senderPreview`
 *     — informational, NOT a form field (R6.7, R9.2) — plus an informational
 *     "Default content rendered in {locale}" line (R3.10), both `font-mono`
 *     with `tnum` (R24.2).
 */

export interface BodyEditorProps {
  valueHtml: string
  defaultHtml: string
  onChange: (html: string) => void
  onResetToDefault: () => void
  senderPreview: SenderPreview
  locale: string
}

/** The two authoring modes the body editor supports. */
export type EditorMode = 'rich' | 'html'

/** Common locale codes → display names; falls back to the raw code (R3.10). */
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
 * client-side (R6.4). TipTap's schema already drops unknown nodes; this removes
 * the dangerous bits before they ever reach the parser. The server re-sanitises
 * as defence in depth.
 */
export function stripUnsafePastedHtml(html: string): string {
  if (typeof window === 'undefined' || typeof DOMParser === 'undefined') return html
  const doc = new DOMParser().parseFromString(html, 'text/html')

  // Remove disallowed elements entirely.
  doc.querySelectorAll('script, iframe, style, object, embed, link, meta').forEach(
    (el) => el.remove(),
  )

  // Strip dangerous attributes from everything that remains.
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
 * is defence-in-depth.
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
      className={cx(
        'grid h-[30px] min-w-[30px] place-items-center rounded-ctl px-[7px] text-[13px] leading-none',
        'transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent',
        isActive
          ? 'bg-accent-soft text-accent'
          : 'text-text hover:bg-black/5',
      )}
    >
      {children}
    </button>
  )
}

/**
 * Segmented Rich/HTML mode toggle (Tab-reachable real `<button>`s with
 * `aria-pressed`, styled consistently with `ToolbarButton`). Lives in the
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
      className="flex items-center gap-[2px] rounded-ctl bg-black/5 p-[2px]"
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
      className={cx(
        'grid h-[26px] place-items-center rounded-[5px] px-[9px] text-[12.5px] font-medium leading-none',
        'transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent',
        isActive
          ? 'bg-card text-accent shadow-sm'
          : 'text-muted hover:text-text',
      )}
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
    if (url === null) return // cancelled
    if (url.trim() === '') {
      editor.chain().focus().extendMarkRange('link').unsetLink().run()
      return
    }
    editor
      .chain()
      .focus()
      .extendMarkRange('link')
      .setLink({ href: url.trim() })
      .run()
  }, [editor])

  return (
    <div
      role="toolbar"
      aria-label="Text formatting"
      className="flex flex-wrap items-center gap-[3px] border-b border-border bg-canvas px-[6px] py-[5px]"
    >
      <ModeToggle mode={mode} onModeChange={onModeChange} />

      {mode === 'rich' && editor && (
        <>
          <span className="mx-[3px] h-[18px] w-px bg-border" aria-hidden="true" />

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

          <span className="mx-[3px] h-[18px] w-px bg-border" aria-hidden="true" />

          <ToolbarButton
            label="Bullet list"
            isActive={editor.isActive('bulletList')}
            onClick={() => editor.chain().focus().toggleBulletList().run()}
          >
            <BulletListIcon />
          </ToolbarButton>
          <ToolbarButton
            label="Numbered list"
            isActive={editor.isActive('orderedList')}
            onClick={() => editor.chain().focus().toggleOrderedList().run()}
          >
            <OrderedListIcon />
          </ToolbarButton>
          <ToolbarButton
            label="Link"
            isActive={editor.isActive('link')}
            onClick={setLink}
          >
            <LinkIcon />
          </ToolbarButton>
        </>
      )}

      <span className="ml-auto" />

      <button
        type="button"
        onClick={onResetToDefault}
        className="rounded-ctl px-[9px] py-[5px] text-[12.5px] font-medium text-muted transition-colors duration-150 hover:bg-black/5 hover:text-text focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        Reset to default
      </button>
    </div>
  )
}

function BulletListIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="h-[15px] w-[15px]"
    >
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
    </svg>
  )
}

function OrderedListIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="h-[15px] w-[15px]"
    >
      <path d="M10 6h11M10 12h11M10 18h11M4 4v4M4 8H3m1 0h1M3 18h2v-2H3.5m0 0H3m2 0v4H3" />
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
      className="h-[15px] w-[15px]"
    >
      <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
    </svg>
  )
}

export function BodyEditor({
  valueHtml,
  // `defaultHtml` is part of the contract (the parent restores it on
  // reset-to-default and clears `body_was_edited`); the editor itself only
  // needs `valueHtml` + `onResetToDefault`, so it is intentionally not read here.
  defaultHtml: _defaultHtml,
  onChange,
  onResetToDefault,
  senderPreview,
  locale,
}: BodyEditorProps) {
  // Authoring mode — rich WYSIWYG (default) or raw HTML. Both operate on the
  // same inner-body fragment (design.md → "dual-mode rich/HTML editing").
  const [mode, setMode] = useState<EditorMode>('rich')

  const editor = useEditor({
    // Create the editor in an effect, not during render. This is TipTap's
    // recommended setting for React and avoids the StrictMode / lazy-<Suspense>
    // lifecycle race where the editor is torn down (schema set to null) while a
    // render-phase read still references it — the source of the
    // "Cannot read properties of null (reading 'cached')" crash.
    immediatelyRender: false,
    extensions: [
      // TipTap 3.x StarterKit already bundles Link + Underline (and the list
      // extensions). Adding @tiptap/extension-link / -underline on top of it
      // registers duplicate 'link'/'underline' extensions, which crashes the
      // editor ("Cannot read properties of null (reading 'cached')"). Configure
      // Link through StarterKit instead and rely on its bundled Underline.
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
          'tiptap prose-sm max-w-none min-h-[180px] px-[12px] py-[10px] text-[13.5px] leading-relaxed text-text focus:outline-none',
      },
      // Strip unsafe markup from pasted HTML before TipTap parses it (R6.4).
      transformPastedHTML: (html) => stripUnsafePastedHtml(html),
    },
    onUpdate: ({ editor: ed }) => {
      onChange(ed.getHTML())
    },
  })

  // Sync the editor when `valueHtml` changes externally (reset-to-default,
  // initial preview load) without clobbering the cursor while the user types.
  // Guard against a destroyed editor: `useEditor` keeps a stable reference but
  // can tear down and recreate the underlying instance across renders (React
  // StrictMode double-invoke, lazy <Suspense> remount). On a destroyed editor
  // `editor.schema` is null, so calling getHTML()/setContent() throws
  // "Cannot read properties of null (reading 'cached')". `isDestroyed` (and the
  // editorView guard) keep us off that path. Only sync while Rich mode owns the
  // content — in HTML mode the textarea is the source of truth.
  useEffect(() => {
    if (!editor || editor.isDestroyed) return
    if (mode !== 'rich') return
    if (valueHtml !== editor.getHTML()) {
      editor.commands.setContent(valueHtml, { emitUpdate: false })
    }
    // `editor` identity is stable for the editor's lifetime; we only want to
    // react to external `valueHtml` changes here.
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
      const pasted = e.clipboardData?.getData('text/html') || e.clipboardData?.getData('text/plain') || ''
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
    <div className="flex flex-col gap-[7px]">
      <div className="overflow-hidden rounded-ctl border border-border bg-card">
        <Toolbar
          editor={editor}
          mode={mode}
          onModeChange={handleModeChange}
          onResetToDefault={onResetToDefault}
        />
        {mode === 'rich' ? (
          <EditorContent editor={editor} />
        ) : (
          <textarea
            value={valueHtml}
            onChange={handleTextareaChange}
            onPaste={handleTextareaPaste}
            aria-label="HTML source"
            spellCheck={false}
            className="block min-h-[180px] w-full resize-y border-0 bg-card px-[12px] py-[10px] font-mono text-[12.5px] leading-relaxed text-text focus:outline-none"
          />
        )}
      </div>

      {/* Informational locale line (R3.10) — read-only. */}
      <p className="font-mono text-[11.5px] tabular-nums text-muted-2">
        Default content rendered in {localeDisplayName(locale)}
      </p>

      {/* Read-only sender footer (R6.7, R9.2) — NOT a form field. */}
      <p className="font-mono text-[11.5px] tabular-nums text-muted">
        Sender: {senderPreview.from_name} &lt;{senderPreview.from_email}&gt;
      </p>
    </div>
  )
}

export default BodyEditor
