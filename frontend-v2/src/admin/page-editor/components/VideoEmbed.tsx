/**
 * VideoEmbed — YouTube/Vimeo → `<iframe loading="lazy">`;
 *              direct MP4    → `<video>` with poster frame.
 */
import type { ComponentConfig } from '@puckeditor/core'

export interface VideoEmbedProps {
  url: string
  title: string
  poster: string
  aspect: '16/9' | '4/3' | '1/1'
}

type Provider =
  | { kind: 'youtube'; embedUrl: string }
  | { kind: 'vimeo'; embedUrl: string }
  | { kind: 'mp4'; src: string }
  | { kind: 'unknown' }

const ASPECT_CLASSES: Record<VideoEmbedProps['aspect'], string> = {
  '16/9': 'aspect-video',
  '4/3': 'aspect-[4/3]',
  '1/1': 'aspect-square',
}

/**
 * Parse the supplied URL and figure out which renderer to use.
 *
 * Supported patterns:
 * - https://www.youtube.com/watch?v=ID
 * - https://youtu.be/ID
 * - https://www.youtube.com/embed/ID
 * - https://vimeo.com/ID
 * - https://player.vimeo.com/video/ID
 * - Any URL ending in .mp4 (case-insensitive)
 */
function detectProvider(rawUrl: string): Provider {
  const url = (rawUrl ?? '').trim()
  if (!url) return { kind: 'unknown' }

  // MP4 direct
  if (/\.mp4(\?.*)?$/i.test(url)) {
    return { kind: 'mp4', src: url }
  }

  // YouTube
  const youtubeMatch =
    url.match(/youtube\.com\/watch\?v=([A-Za-z0-9_-]{6,})/i) ||
    url.match(/youtu\.be\/([A-Za-z0-9_-]{6,})/i) ||
    url.match(/youtube\.com\/embed\/([A-Za-z0-9_-]{6,})/i)
  if (youtubeMatch) {
    return { kind: 'youtube', embedUrl: `https://www.youtube.com/embed/${youtubeMatch[1]}` }
  }

  // Vimeo
  const vimeoMatch =
    url.match(/vimeo\.com\/(\d+)/i) || url.match(/player\.vimeo\.com\/video\/(\d+)/i)
  if (vimeoMatch) {
    return { kind: 'vimeo', embedUrl: `https://player.vimeo.com/video/${vimeoMatch[1]}` }
  }

  return { kind: 'unknown' }
}

export const VideoEmbedComponent: ComponentConfig<VideoEmbedProps> = {
  label: 'Video Embed',
  fields: {
    url: {
      type: 'text',
      label: 'Video URL (YouTube, Vimeo, or .mp4)',
    },
    title: {
      type: 'text',
      label: 'Accessible title',
      placeholder: 'e.g. OraInvoice product walkthrough',
    },
    poster: {
      type: 'text',
      label: 'Poster image URL (MP4 only)',
    },
    aspect: {
      type: 'select',
      label: 'Aspect ratio',
      options: [
        { label: '16:9 (widescreen)', value: '16/9' },
        { label: '4:3', value: '4/3' },
        { label: '1:1 (square)', value: '1/1' },
      ],
    },
  },
  defaultProps: {
    url: '',
    title: 'Video',
    poster: '',
    aspect: '16/9',
  },
  render: ({ url, title, poster, aspect }) => {
    const provider = detectProvider(url)
    const aspectClass = ASPECT_CLASSES[aspect] ?? ASPECT_CLASSES['16/9']

    if (provider.kind === 'unknown') {
      return (
        <div
          className={`mx-auto max-w-3xl rounded-xl border border-dashed border-gray-300 bg-gray-50 p-8 text-center text-sm text-gray-500 ${aspectClass}`}
        >
          Unsupported or empty video URL — paste a YouTube, Vimeo, or .mp4 link.
        </div>
      )
    }

    if (provider.kind === 'mp4') {
      return (
        <div className={`mx-auto max-w-3xl overflow-hidden rounded-xl bg-black ${aspectClass}`}>
          <video
            className="h-full w-full"
            controls
            preload="none"
            // `loading="lazy"` is defined in the HTML spec for <video>
            // elements under the same semantics as <iframe> — only
            // relevant browsers will honour it, others will ignore it.
            // We cast because React's lib.dom.d.ts hasn't caught up in
            // some versions.
            {...({ loading: 'lazy' } as { loading: 'lazy' })}
            poster={poster || undefined}
            aria-label={title || 'Video'}
          >
            <source src={provider.src} type="video/mp4" />
            Your browser does not support HTML5 video.
          </video>
        </div>
      )
    }

    return (
      <div className={`mx-auto max-w-3xl overflow-hidden rounded-xl bg-black ${aspectClass}`}>
        <iframe
          src={provider.embedUrl}
          title={title || 'Embedded video'}
          loading="lazy"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
          allowFullScreen
          className="h-full w-full border-0"
        />
      </div>
    )
  },
}
