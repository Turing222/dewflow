import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

import { initI18n } from './lib/i18n.ts'

const renderApp = () => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

initI18n()
  .then(renderApp)
  .catch((err) => {
    console.error('Failed to initialize i18n:', err);
    renderApp();
  });
