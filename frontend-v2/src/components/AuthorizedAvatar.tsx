/**
 * AuthorizedAvatar — fetches a JWT-protected image through axios and renders
 * it with a graceful initials fallback. Wraps `useAuthorizedImage` for
 * single-image consumers (avatar circles in tables / drawers / cards).
 *
 * The platform's `/api/v2/uploads/...` route is protected by the JWT
 * middleware. Plain `<img src>` requests don't carry the bearer token, so
 * encrypted-at-rest staff photos / clock photos / etc. render as broken-link
 * 401s. This wrapper does an authenticated axios fetch in the background and
 * swaps the bitmap into a blob URL once it lands.
 *
 * While the fetch is in-flight (or if it fails), the component shows the
 * caller-supplied initials so the row never renders an empty square.
 */

import useAuthorizedImage from '@/hooks/useAuthorizedImage'

interface AuthorizedAvatarProps {
  src: string | null | undefined
  initials: string
  /** Tailwind classes for the wrapper square — caller controls size + shape. */
  className?: string
  /** Tailwind classes for the initials fallback (font size, colour). */
  fallbackClassName?: string
  /** Accessibility label. Optional — empty default since avatars are usually
   *  paired with a visible name elsewhere in the row. */
  alt?: string
}

export default function AuthorizedAvatar({
  src,
  initials,
  className = 'h-10 w-10 shrink-0 rounded-full border border-border bg-canvas',
  fallbackClassName = 'text-xs font-semibold uppercase text-muted-2',
  alt = '',
}: AuthorizedAvatarProps) {
  const { src: resolved } = useAuthorizedImage(src)

  if (resolved) {
    return (
      <img src={resolved} alt={alt} className={`${className} object-cover`} />
    )
  }

  return (
    <span
      className={`${className} inline-flex items-center justify-center`}
      aria-hidden={alt ? undefined : true}
      aria-label={alt || undefined}
    >
      <span className={fallbackClassName}>{initials || '?'}</span>
    </span>
  )
}
