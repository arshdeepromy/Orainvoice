import { useEffect, type ReactNode } from 'react'
import { LandingHeader, LandingFooter } from '@/components/public'
import { resetH1Counter } from '@/admin/page-editor/components'

interface PageShellProps {
  children: ReactNode
}

/**
 * Wraps Puck `<Render>` output with the public site chrome (header + footer)
 * and a `public-page` document class toggle so global CSS can target rendered
 * public pages. Also resets the single-H1 counter at render start so the
 * enforcement logic in `HeadingComponent` starts fresh for each render tree.
 *
 * Requirements: 7.1, 14.6
 */
export function PageShell({ children }: PageShellProps) {
  // Toggle `public-page` class on <html> while a public page is mounted.
  useEffect(() => {
    document.documentElement.classList.add('public-page')
    return () => {
      document.documentElement.classList.remove('public-page')
    }
  }, [])

  // Reset the H1 counter at the start of each render pass so the single-H1
  // rule is evaluated fresh for the Puck Render tree below. `resetH1Counter`
  // is idempotent and cheap, so running it during render is safe.
  resetH1Counter()

  return (
    <>
      <LandingHeader />
      <main className="pt-16">{children}</main>
      <LandingFooter />
    </>
  )
}

export default PageShell
