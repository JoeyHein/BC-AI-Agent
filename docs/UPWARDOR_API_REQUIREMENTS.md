# Upwardor API Requirements

## Current Status

**Portal URL**: http://195.35.8.196:8100/
**API Backend**: http://195.35.8.196:6100/
**Access**: We can login via web interface
**Need**: Direct API access (authentication tokens, endpoints, request/response formats)

## What We've Discovered So Far

### API Endpoints Identified
From network capture during login:
- `POST http://195.35.8.196:6100/user/login` - User authentication
- `GET http://195.35.8.196:6100/admin/user/detail?id={encrypted_id}` - User details
- WebSocket connections via socket.io (real-time updates)

### Authentication Method
- Appears to use session-based auth or JWT tokens
- User ID is encrypted in URL parameters (AES encryption with salt)
- Cookies or localStorage might contain auth tokens

## What We Need From API Code/Documentation

### 1. Authentication
```
How to authenticate programmatically:
- Endpoint: POST /user/login
- Request body format: { email: string, password: string }
- Response format: { token: string, user: {...} }
- Token usage: Headers? Cookies? How to include in subsequent requests?
- Token expiration: How long? How to refresh?
```

### 2. Door Series / Product Catalog
```
Get list of available door series:
- Endpoint: GET /products/series or similar
- Response: Array of series (TX 450, KANATA, AL976, PANORAMA, etc.)
- For each series:
  - ID
  - Name
  - Type (Residential/Commercial)
  - Available configurations
  - Pre-configured packages (if any)
```

### 3. Configuration Options
```
For a given door series, get available options:
- Door types (Residential, Commercial)
- Panel widths (90, 96, 108, 120, 144, 192 inches, etc.)
- Panel heights (D7'0, D7'6, D8'0, D9'0, D10'0, etc.)
- Stamp patterns (SKML, UDC GROOVE, RIBBED, FLUSH, etc.)
- Colors (WHITE, ALMOND, SANDSTONE, BRONZE, etc.)
- Window types
- Track types
- Hardware options
```

### 4. Quote Creation
```
Create a quote programmatically:
- Endpoint: POST /quotes or /quotes/create
- Request body: Configuration object
- Response: Quote ID, line items, pricing

Example request body we need to construct:
{
  "doorType": "Residential",
  "series": "TX 450",
  "numberOfPanels": 2,
  "panelWidth": 108,
  "panelHeight": "D7'0",
  "stampPattern": "RIBBED",
  "color": "WHITE",
  "components": {
    "tracks": true,
    "trackType": "STANDARD LIFT BRACKET MOUNT",
    "shafts": true,
    "springs": true,
    "struts": true,
    "hardwareKits": true,
    "weatherStripping": true
  }
}
```

### 5. Part Number Lookup
```
Get part numbers for components:
- Given a configuration, what are the exact SKU/part numbers?
- TX450-WWHH-03 format decoder
- Individual component part numbers
```

### 6. Quote Validation
```
Validate a configuration before creating quote:
- Endpoint: POST /quotes/validate
- Check if configuration is valid
- Return errors if incompatible options selected
- Suggest alternatives if needed
```

### 7. Pricing (if available)
```
Get pricing for a configuration:
- Base price
- Component prices
- Total quote amount
- Discounts/markup rules
```

## Integration Plan

### Once We Have API Access:

#### Phase 1: Learn Configuration Options
1. Call product catalog API to get all series/options
2. Store in our database for reference
3. Build validation rules based on dependencies
4. Create mapping from email descriptions → API parameters

#### Phase 2: Quote Generation
1. Parse email quote request (already working)
2. Map parsed data to API format
3. Call Upwardor API to create quote
4. Store Upwardor quote ID in our database
5. Link to BC quote if needed

#### Phase 3: Validation & Feedback Loop
1. Validate email parsing against Upwardor API
2. Check if suggested configuration is valid
3. Learn from failures to improve parsing
4. Provide feedback to user if configuration incomplete

## API Code Examples We Need

### Example 1: Authentication
```javascript
// How to login and get token
const response = await fetch('http://195.35.8.196:6100/user/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    email: 'opentest@yopmail.com',
    password: 'Welcome@123'
  })
});

const { token } = await response.json();
// How to use this token?
```

### Example 2: Get Product Options
```javascript
// Get available door series
const series = await fetch('http://195.35.8.196:6100/products/series', {
  headers: {
    'Authorization': `Bearer ${token}` // Or how is auth done?
  }
});

// Get options for a specific series
const options = await fetch('http://195.35.8.196:6100/products/TX450/options', {
  headers: { 'Authorization': `Bearer ${token}` }
});
```

### Example 3: Create Quote
```javascript
// Create a quote via API
const quote = await fetch('http://195.35.8.196:6100/quotes', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    // What fields go here?
    doorType: 'Residential',
    series: 'TX 450',
    // ... rest of configuration
  })
});

const quoteData = await quote.json();
// Response format?
```

## Questions for API Provider

1. **Authentication**: What authentication method does the API use? (JWT, OAuth, API keys?)

2. **Rate Limiting**: Are there rate limits on API calls?

3. **Documentation**: Is there OpenAPI/Swagger documentation available?

4. **Environments**: Is there a test/sandbox environment?

5. **Webhooks**: Can we receive notifications when quotes are updated?

6. **Batch Operations**: Can we create multiple quotes in one request?

7. **Error Handling**: What error codes/formats are returned?

8. **Data Format**: Are all requests/responses JSON?

9. **CORS**: If calling from browser, is CORS enabled?

10. **Support**: Who to contact for API issues?

## Alternative: API Code Reverse Engineering

If we can't get official documentation, we can:

1. **Use browser DevTools** to capture all network requests while using portal
2. **Copy as cURL** and convert to Python requests
3. **Extract authentication tokens** from successful requests
4. **Replicate request format** in our code
5. **Test and iterate** until we understand the API

## Benefits of Direct API Access

### vs Browser Automation (Selenium)
- ✅ **100x faster** - API calls vs full page loads
- ✅ **More reliable** - No UI changes breaking automation
- ✅ **Better error handling** - Structured API errors vs parsing HTML
- ✅ **Easier to maintain** - API contracts vs DOM selectors
- ✅ **Scalable** - Can handle many requests in parallel

### For Our Use Case
- ✅ **Validate email parsing** - Check if configuration is possible
- ✅ **Learn part numbers** - Store exact SKUs in our database
- ✅ **Auto-complete quotes** - Fill missing fields with defaults
- ✅ **Price estimation** - If API provides pricing
- ✅ **Integration with BC** - Bridge between email → Upwardor → BC

## Next Steps

**Immediate** (if API code provided):
1. Review authentication method
2. Test login endpoint
3. Explore product catalog endpoints
4. Test quote creation
5. Build Python integration module

**Short Term**:
1. Create `app/integrations/upwardor/client.py` - API client
2. Add configuration validation
3. Integrate with email parsing
4. Store Upwardor catalog in database

**Long Term**:
1. Auto-generate BC quotes from Upwardor quotes
2. Sync part numbers and pricing
3. Handle quote updates/changes
4. Build quote comparison tool (Email parsed vs Upwardor vs BC)

---

**Status**: Waiting for API code/documentation from Upwardor provider
**Last Updated**: 2026-01-06
