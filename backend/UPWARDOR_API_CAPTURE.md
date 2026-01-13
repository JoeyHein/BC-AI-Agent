# Upwardor Portal API Capture Guide

## What We Have So Far

✅ **Login Endpoint**
- URL: `POST http://195.35.8.196:6100/user/login`
- Body: `{"email": "...", "password": "..."}`
- Response: Contains `access_token` and user data

✅ **User Detail Endpoint**
- URL: `GET http://195.35.8.196:6100/admin/user/detail?id=...`
- Headers: `Authorization: Bearer {token}`
- Response: User and company details

## What We Still Need

We need to capture the following API endpoints to complete the integration:

### 1. Door Products/Catalog Listing 🔍 **PRIORITY**
**What to do:**
1. After logging in to the portal at http://195.35.8.196:8100
2. Navigate to where you can see a list of door products or door models
3. Look in Network tab (F12) for XHR/Fetch requests
4. Look for endpoints like:
   - `/api/products`
   - `/api/doors`
   - `/api/catalog`
   - `/admin/products/list`
   - `/door/list`

**What to capture:**
- Full URL
- Request method (GET/POST)
- Request headers (especially Authorization)
- Response body (the list of products)

### 2. Door Configuration Options 🔍 **PRIORITY**
**What to do:**
1. Click on a specific door model or start configuring a door
2. Look for API calls that load:
   - Available sizes
   - Glass options
   - Hardware options
   - Color/finish options
   - Any other configuration choices

**What to capture:**
- Endpoint URL for each option type
- Request/response format

### 3. Pricing Calculation 🔍 **PRIORITY**
**What to do:**
1. Configure a door with specific options
2. Look for an API call that calculates/returns the price
3. This might happen:
   - When you select options (real-time pricing)
   - When you click "Get Quote" or similar button
   - When you finalize the configuration

**What to capture:**
- Pricing endpoint URL
- What data you send (door config)
- What pricing data comes back

### 4. Quote Creation (if available) 🔍 **OPTIONAL**
**What to do:**
1. If the portal lets you create/save quotes, try that
2. Capture the API call

**What to capture:**
- Quote creation endpoint
- Required fields
- Response format

## How to Capture Network Traffic

1. **Open the portal**: http://195.35.8.196:8100
2. **Open Developer Tools**: Press F12
3. **Go to Network tab**
4. **Clear existing requests**: Click the "Clear" button (🚫 icon)
5. **Filter to XHR/Fetch**: Click the "Fetch/XHR" button to show only API calls
6. **Perform the action**: Navigate/configure doors/get pricing
7. **Click on the API call** in the Network tab
8. **Take screenshots** of:
   - Headers tab (full URL, request method, request headers)
   - Payload tab (request body if it's a POST)
   - Response tab (response body)

## Example - What Good Captures Look Like

For each endpoint, I need:

```
✅ GOOD CAPTURE:
Endpoint: GET http://195.35.8.196:6100/api/doors/list
Headers:
  Authorization: Bearer eyJhbGc...
  Content-Type: application/json
Response:
  {
    "doors": [
      {"id": 1, "name": "Model A", "type": "overhead"},
      {"id": 2, "name": "Model B", "type": "sectional"}
    ]
  }
```

## Next Steps

Once you capture these endpoints:
1. Share screenshots (or just type out the details if easier)
2. I'll add them to the `upwardor_service.py` client
3. We'll integrate door validation and pricing into the quote workflow
4. The AI will be able to validate customer requests against actual Upwardor products

## Questions?

If you're not sure where to find something in the portal, just share:
- A screenshot of the portal interface
- What sections/menus are available
- I'll guide you to the right place
