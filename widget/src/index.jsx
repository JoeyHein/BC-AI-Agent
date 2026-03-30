import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import doorOptions from '../door-options.json'
import css from './styles.css?inline'

const OpenDCDesigner = {
  _injectCSS() {
    if (document.getElementById('odc-widget-styles')) return
    const style = document.createElement('style')
    style.id = 'odc-widget-styles'
    style.textContent = css
    document.head.appendChild(style)
  },
  init({ container, quoteWebhook, dealerLocatorUrl } = {}) {
    this._injectCSS()
    const el = typeof container === 'string' ? document.querySelector(container) : container
    if (!el) {
      console.error('[OpenDC Designer] Container element not found:', container)
      return
    }
    const root = ReactDOM.createRoot(el)
    root.render(
      <App
        options={doorOptions}
        quoteWebhook={quoteWebhook || '/api/public/quote-request'}
        dealerLocatorUrl={dealerLocatorUrl || '/find-a-dealer'}
      />
    )
    return root
  }
}

// Expose globally
window.OpenDCDesigner = OpenDCDesigner

export default OpenDCDesigner
