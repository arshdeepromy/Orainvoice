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
    <footer className="mt-8 border-t border-gray-200 pt-4 text-center text-xs text-gray-400">
      <p>
        Powered by{' '}
        {linkUrl ? (
          <a
            href={linkUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-gray-500 hover:text-gray-700 underline"
          >
            {poweredBy.platform_name}
          </a>
        ) : (
          <span className="text-gray-500">{poweredBy.platform_name}</span>
        )}
      </p>
    </footer>
  )
}
