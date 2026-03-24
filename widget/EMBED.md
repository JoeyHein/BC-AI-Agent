# OPENDC Door Designer Widget — Embed Instructions

## Quick Start

Add the widget to any webpage with two lines:

```html
<div id="door-designer"></div>
<script src="https://your-cdn.com/opendc-door-designer.iife.js"></script>
<script>
  OpenDCDesigner.init({
    container: '#door-designer',
    quoteWebhook: 'https://portal.opendc.ca/api/quote-requests',
    dealerLocatorUrl: 'https://opendc.ca/find-a-dealer'
  });
</script>
```

## Build

```bash
cd widget
npm install
npm run build
```

This produces `dist/opendc-door-designer.iife.js` — a single self-contained file with React bundled in.

## Development

```bash
npm run dev
```

Opens a local dev server at `http://localhost:5173` with hot reload.

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `container` | `string` or `Element` | (required) | CSS selector or DOM element to mount into |
| `quoteWebhook` | `string` | `/api/quote-requests` | URL to POST quote form submissions |
| `dealerLocatorUrl` | `string` | `/find-a-dealer` | URL for "Find a Dealer" button |

## Quote Webhook Payload

When a user submits the quote form, the widget POSTs JSON:

```json
{
  "name": "Jane Smith",
  "email": "jane@example.com",
  "phone": "555-0123",
  "postalCode": "V6B 1A1",
  "notes": "Looking for a 16x8 door for my new build",
  "configuration": {
    "family": "Kanata Collection",
    "familyId": "kanata",
    "design": "Sheridan XL",
    "designId": "SHXL",
    "color": "Iron Ore",
    "colorId": "IRON_ORE",
    "windows": "Stockton Arched",
    "windowId": "STOCKTON_ARCHED",
    "glassType": null,
    "glassId": null
  },
  "timestamp": "2026-03-24T12:00:00.000Z"
}
```

## Styling

The widget uses CSS custom properties scoped under `.odc-widget`. You can override them:

```css
.odc-widget {
  --odc-accent: #your-brand-color;
  --odc-bg: #your-background;
}
```

## Browser Support

Modern browsers (Chrome 80+, Firefox 80+, Safari 14+, Edge 80+). No IE11 support.

## Size

The built bundle is approximately 80-100KB gzipped (includes React 18).
