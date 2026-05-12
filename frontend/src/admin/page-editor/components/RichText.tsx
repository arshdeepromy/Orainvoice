/**
 * RichText — paragraph text supporting bold, italic and hyperlinks.
 *
 * The HTML is sanitised server-side on save (see app/modules/page_editor/
 * sanitiser.py — allowed tags: strong, em, a[href target rel], br, p).
 * Because sanitisation happens server-side, we trust the HTML at render
 * time and use `dangerouslySetInnerHTML`. Never bypass the server
 * sanitiser when producing this content.
 */
import type { ComponentConfig } from '@puckeditor/core'

export interface RichTextProps {
  html: string
  align: 'left' | 'center' | 'right'
  size: 'sm' | 'base' | 'lg'
}

const ALIGN_CLASSES: Record<RichTextProps['align'], string> = {
  left: 'text-left',
  center: 'text-center',
  right: 'text-right',
}

const SIZE_CLASSES: Record<RichTextProps['size'], string> = {
  sm: 'text-sm',
  base: 'text-base',
  lg: 'text-lg',
}

export const RichTextComponent: ComponentConfig<RichTextProps> = {
  label: 'Rich Text',
  fields: {
    html: {
      type: 'textarea',
      label: 'HTML content',
      placeholder:
        '<p>Paragraph with <strong>bold</strong>, <em>italic</em>, and <a href="/signup">links</a>.</p>',
    },
    align: {
      type: 'radio',
      label: 'Align',
      options: [
        { label: 'Left', value: 'left' },
        { label: 'Centre', value: 'center' },
        { label: 'Right', value: 'right' },
      ],
    },
    size: {
      type: 'select',
      label: 'Size',
      options: [
        { label: 'Small', value: 'sm' },
        { label: 'Base', value: 'base' },
        { label: 'Large', value: 'lg' },
      ],
    },
  },
  defaultProps: {
    html: '<p>Replace this with your own copy. You can include <strong>bold</strong> and <em>italic</em> text, and <a href="/">links</a>.</p>',
    align: 'left',
    size: 'base',
  },
  render: ({ html, align, size }) => {
    const alignClass = ALIGN_CLASSES[align] ?? ALIGN_CLASSES.left
    const sizeClass = SIZE_CLASSES[size] ?? SIZE_CLASSES.base
    return (
      <div
        className={`rich-text space-y-4 leading-relaxed text-gray-700 ${sizeClass} ${alignClass}`}
        // The HTML is sanitised server-side using a strict allow-list
        // (strong, em, a, br, p). See requirements section 2.4–2.5.
        dangerouslySetInnerHTML={{ __html: html ?? '' }}
      />
    )
  },
}
