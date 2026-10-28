import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { finishConsentPopup } from './lib/mailPopup'
import './styles/global.css'

const root = createRoot(document.getElementById('root')!)
if (finishConsentPopup()) {
  // window.close() is refused for a window the browser no longer counts as
  // opened by script (Google's opener policy can do that): say where to go.
  root.render(
    <main className="flex min-h-dvh items-center justify-center p-6 text-center">
      <p className="text-lg">
        {new URLSearchParams(window.location.search).get('mail') === 'connected'
          ? 'Your Gmail is connected. You can close this window.'
          : 'Connecting your Gmail did not work. Close this window and try again.'}
      </p>
    </main>,
  )
} else {
  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}
