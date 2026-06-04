/**
 * ImageBlock — responsive `<img>` with lazy loading, required alt text,
 * and `srcset` assembled from Media_Asset WebP variants.
 *
 * Puck naming: the on-disk component name is `ImageBlock` so it does
 * not collide with Puck's own `Image` export, but the Puck config key
 * in `puckConfig.ts` will be `Image` (matching the design doc).
 */
import type { ComponentConfig } from '@puckeditor/core'

/** Width/URL pair used to build the `srcset` attribute. */
export interface ImageVariant {
  width: number
  url: string
}

export interface ImageBlockProps {
  src: string
  alt: string
  decorative: boolean
  variants: ImageVariant[]
  caption: string
  width: 'narrow' | 'wide' | 'full'
  rounded: boolean
}

const WIDTH_CLASSES: Record<ImageBlockProps['width'], string> = {
  narrow: 'max-w-md',
  wide: 'max-w-3xl',
  full: 'max-w-full',
}

export const ImageBlockComponent: ComponentConfig<ImageBlockProps> = {
  label: 'Image',
  fields: {
    src: { type: 'text', label: 'Image URL (fallback)' },
    alt: {
      type: 'text',
      label: 'Alt text (required unless marked decorative)',
    },
    decorative: {
      type: 'radio',
      label: 'Decorative image',
      options: [
        { label: 'No — describes content', value: false },
        { label: 'Yes — purely decorative', value: true },
      ],
    },
    variants: {
      type: 'array',
      label: 'Responsive variants (width + URL)',
      arrayFields: {
        width: { type: 'number', label: 'Width (px)', min: 1 },
        url: { type: 'text', label: 'Variant URL' },
      },
      defaultItemProps: { width: 960, url: '' },
      getItemSummary: (item) => `${item.width}px`,
    },
    caption: { type: 'text', label: 'Caption (optional)' },
    width: {
      type: 'select',
      label: 'Max width',
      options: [
        { label: 'Narrow', value: 'narrow' },
        { label: 'Wide', value: 'wide' },
        { label: 'Full width', value: 'full' },
      ],
    },
    rounded: {
      type: 'radio',
      label: 'Rounded corners',
      options: [
        { label: 'Yes', value: true },
        { label: 'No', value: false },
      ],
    },
  },
  defaultProps: {
    src: '',
    alt: '',
    decorative: false,
    variants: [],
    caption: '',
    width: 'wide',
    rounded: true,
  },
  render: ({ src, alt, decorative, variants, caption, width, rounded }) => {
    const safeVariants = variants ?? []
    const srcSet =
      safeVariants.length > 0
        ? safeVariants
            .filter((v) => v.url && v.width > 0)
            .map((v) => `${v.url} ${v.width}w`)
            .join(', ')
        : undefined
    const sizes = srcSet
      ? '(min-width: 1280px) 1280px, (min-width: 960px) 960px, 100vw'
      : undefined
    const effectiveAlt = decorative ? '' : (alt ?? '')
    const ariaRole = decorative ? 'presentation' : undefined
    const widthClass = WIDTH_CLASSES[width] ?? WIDTH_CLASSES.wide
    const roundedClass = rounded ? 'rounded-xl' : ''

    if (!src && safeVariants.length === 0) {
      // Placeholder for editor — never renders on public output because
      // a page without a URL fails SEO anyway.
      return (
        <div className={`mx-auto ${widthClass} rounded-xl border border-dashed border-gray-300 bg-gray-50 p-12 text-center text-sm text-gray-500`}>
          No image selected — choose one from the Media Library.
        </div>
      )
    }

    return (
      <figure className={`mx-auto ${widthClass}`}>
        <img
          src={src || safeVariants[safeVariants.length - 1]?.url || ''}
          srcSet={srcSet}
          sizes={sizes}
          alt={effectiveAlt}
          role={ariaRole}
          loading="lazy"
          decoding="async"
          className={`block h-auto w-full ${roundedClass}`}
        />
        {caption ? (
          <figcaption className="mt-2 text-center text-sm text-gray-500">{caption}</figcaption>
        ) : null}
      </figure>
    )
  },
}
