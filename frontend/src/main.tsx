import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import { registerServiceWorker } from './registerSW'

// Handle chunk load failures (stale assets after frontend rebuild).
// When a lazy-loaded chunk 404s, auto-reload once to pick up the new index.html.
window.addEventListener('unhandledrejection', (event) => {
  const msg = String(event.reason?.message || event.reason || '')
  if (
    msg.includes('Failed to fetch dynamically imported module') ||
    msg.includes('Loading chunk') ||
    msg.includes('Loading CSS chunk')
  ) {
    // Only auto-reload once to avoid infinite loops
    const key = '_chunk_reload'
    if (!sessionStorage.getItem(key)) {
      sessionStorage.setItem(key, '1')
      window.location.reload()
    }
  }
})
// Clear the reload flag on successful load
sessionStorage.removeItem('_chunk_reload')

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

registerServiceWorker()
