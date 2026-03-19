import { Component } from 'react'
import type { ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** Where to show the error — 'page' keeps layout intact, 'app' is full-screen */
  level?: 'page' | 'app'
  /** Optional name for logging which boundary caught the error */
  name?: string
}

interface State {
  error: Error | null
}

/**
 * Reusable error boundary that catches render errors and shows a
 * human-readable fallback instead of a blank screen.
 *
 * Use `level="page"` (default) around individual routes so the sidebar
 * and navigation stay visible when a single page crashes.
 *
 * Use `level="app"` at the top level as a last resort.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    const label = this.props.name ?? 'unknown'
    console.error(`[ErrorBoundary:${label}]`, error, info.componentStack)

    // Auto-reload once for chunk load failures (stale assets after rebuild)
    const msg = error.message || ''
    if (
      msg.includes('Failed to fetch dynamically imported module') ||
      msg.includes('Loading chunk') ||
      msg.includes('Loading CSS chunk')
    ) {
      const key = '_eb_chunk_reload'
      if (!sessionStorage.getItem(key)) {
        sessionStorage.setItem(key, '1')
        window.location.reload()
        return
      }
    }
    sessionStorage.removeItem('_eb_chunk_reload')
  }

  private handleReset = () => {
    this.setState({ error: null })
  }

  private handleReload = () => {
    window.location.reload()
  }

  render() {
    if (!this.state.error) return this.props.children

    const { level = 'page' } = this.props
    const msg = this.state.error.message || 'An unexpected error occurred'

    if (level === 'app') {
      return (
        <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
          <div className="w-full max-w-lg rounded-xl bg-white p-8 shadow-lg text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-100">
              <svg className="h-7 w-7 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h1 className="text-xl font-semibold text-gray-900">Something went wrong</h1>
            <p className="mt-2 text-sm text-gray-600">
              The application hit an unexpected error. This has been logged.
            </p>
            <details className="mt-4 text-left">
              <summary className="cursor-pointer text-sm text-gray-500 hover:text-gray-700">
                Technical details
              </summary>
              <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-gray-100 p-3 text-xs text-gray-700 whitespace-pre-wrap">
                {msg}
              </pre>
            </details>
            <div className="mt-6 flex justify-center gap-3">
              <button
                onClick={this.handleReload}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                Reload page
              </button>
            </div>
          </div>
        </div>
      )
    }

    // Page-level: keeps sidebar/nav intact, only the content area shows the error
    return (
      <div className="flex flex-col items-center justify-center py-16 px-4">
        <div className="w-full max-w-md text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-100">
            <svg className="h-6 w-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-gray-900">This page couldn't load</h2>
          <p className="mt-1 text-sm text-gray-600">
            Something went wrong loading this page. The rest of the app is fine — you can navigate away or try again.
          </p>
          <details className="mt-3 text-left">
            <summary className="cursor-pointer text-sm text-gray-500 hover:text-gray-700">
              Technical details
            </summary>
            <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-gray-100 p-3 text-xs text-gray-700 whitespace-pre-wrap">
              {msg}
            </pre>
          </details>
          <div className="mt-5 flex justify-center gap-3">
            <button
              onClick={this.handleReset}
              className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              Try again
            </button>
            <button
              onClick={() => window.history.back()}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              Go back
            </button>
          </div>
        </div>
      </div>
    )
  }
}
