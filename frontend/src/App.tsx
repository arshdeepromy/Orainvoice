import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { InstallPromptBanner } from '@/components/pwa/InstallPromptBanner'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<div>WorkshopPro NZ</div>} />
      </Routes>
      <InstallPromptBanner />
    </BrowserRouter>
  )
}

export default App
