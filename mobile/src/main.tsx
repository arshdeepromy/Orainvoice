import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Capacitor } from '@capacitor/core'
import { capacitorInit } from '@/native/capacitor-init'
import App from './App'
import './index.css'

// On native Capacitor, the app is served from root (/).
// On web (behind nginx reverse proxy), it's served from /mobile/.
const basename = Capacitor.isNativePlatform() ? '/' : '/mobile'

// Initialise native Capacitor features before rendering.
// On web this is a no-op and resolves immediately.
capacitorInit().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <BrowserRouter basename={basename}>
        <App />
      </BrowserRouter>
    </StrictMode>,
  )
})
