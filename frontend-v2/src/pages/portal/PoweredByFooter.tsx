interface PoweredByData {
  platform_name: string
  logo_url: string | null
  signup_url: string | null
  website_url: string | null
  show_powered_by: boolean
}

interface PoweredByFooterProps {
  poweredBy?: PoweredByData | null
}

export function PoweredByFooter({ poweredBy }: PoweredByFooterProps) {
  if (!poweredBy || !poweredBy.show_powered_by) return null

  const linkUrl = poweredBy.signup_url
    ? `${poweredBy.signup_url}?utm_source=portal&utm_medium=web&utm_campaign=powered_by`
    : poweredBy.website_url

  return (
    <footer className="mt-8 border-t border-border pt-4 text-center text-xs text-muted-2">
      <p>
        Powered by{' '}
        {linkUrl ? (
          <a
            href={linkUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted hover:text-text underline"
          >
            {poweredBy.platform_name}
          </a>
        ) : (
          <span className="text-muted">{poweredBy.platform_name}</span>
        )}
      </p>
    </footer>
  )
}
