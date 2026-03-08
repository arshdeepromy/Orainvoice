import { Component } from 'react'
import type { ReactNode, ErrorInfo } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  isChunkError: boolean
  errorMessage: string | null
}

/**
 * Error boundary that specifically detects chunk load failures
 * (from React.lazy / dynamic imports) and renders a retry button
 * that reloads the page. For other errors it shows a generic message.
 */
export class ErrorBoundaryWithRetry extends Component<Props, State> {
  state: State = { hasError: false, isChunkError: false, errorMessage: null }

  static getDerivedStateFromError(error: Error): State {
    const isChunkError =
      error.name === 'ChunkLoadError' ||
      /loading chunk/i.test(error.message) ||
      /dynamically imported module/i.test(error.message) ||
      /failed to fetch/i.test(error.message)

    return {
      hasError: true,
      isChunkError,
      errorMessage: error.message,
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Log for debugging — could be wired to an error reporting service
    console.error('[ErrorBoundaryWithRetry]', error, info)
  }

  handleRetry = () => {
    window.location.reload()
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children
    }

    if (this.state.isChunkError) {
      return (
        <div
          data-testid="error-boundary-chunk"
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 32,
            gap: 16,
            fontFamily: 'sans-serif',
          }}
        >
          <p style={{ fontSize: 16, color: '#374151' }}>
            A new version is available or the page failed to load.
          </p>
          <button
            data-testid="error-boundary-retry"
            onClick={this.handleRetry}
            style={{
              padding: '10px 20px',
              fontSize: 14,
              fontWeight: 600,
              color: '#fff',
              backgroundColor: '#2563eb',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            Retry
          </button>
        </div>
      )
    }

    return (
      <div
        data-testid="error-boundary-generic"
        style={{ padding: 32, fontFamily: 'sans-serif' }}
      >
        <h2 style={{ color: '#dc2626' }}>Something went wrong</h2>
        <pre style={{ whiteSpace: 'pre-wrap', marginTop: 12, color: '#374151', fontSize: 13 }}>
          {this.state.errorMessage}
        </pre>
        <button
          data-testid="error-boundary-retry"
          onClick={this.handleRetry}
          style={{
            marginTop: 16,
            padding: '8px 16px',
            cursor: 'pointer',
          }}
        >
          Reload
        </button>
      </div>
    )
  }
}
