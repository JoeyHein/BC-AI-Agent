import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import doorOptions from '../door-options.json'
import './styles.css'

const OpenDCDesigner = {
  init({ container, quoteWebhook, dealerLocatorUrl } = {}) {
    const el = typeof container === 'string' ? document.querySelector(container) : container
    if (!el) {
      console.error('[OpenDC Designer] Container element not found:', container)
      return
    }
    const root = ReactDOM.createRoot(el)
    root.render(
      <App
        options={doorOptions}
        quoteWebhook={quoteWebhook || '/api/quote-requests'}
        dealerLocatorUrl={dealerLocatorUrl || '/find-a-dealer'}
      />
    )
    return root
  }
}

// Expose globally
window.OpenDCDesigner = OpenDCDesigner

export default OpenDCDesigner
