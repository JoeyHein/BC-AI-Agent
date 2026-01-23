# Business Central API Configuration

## Authentication

### OAuth 2.0 Client Credentials Flow

```
TOKEN ENDPOINT:
https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token

REQUIRED PARAMETERS:
├── grant_type: client_credentials
├── client_id: {your_client_id}
├── client_secret: {your_client_secret}
└── scope: https://api.businesscentral.dynamics.com/.default
```

### Environment Variables
```bash
BC_TENANT_ID=         # Azure AD Tenant ID
BC_CLIENT_ID=         # App Registration Client ID
BC_CLIENT_SECRET=     # App Registration Secret
BC_ENVIRONMENT=       # production | sandbox
BC_COMPANY_ID=        # BC Company ID (GUID)
BC_COMPANY_NAME=      # BC Company Name (for reference)
```

## API Endpoints

### Base URLs
```
STANDARD API (v2.0):
https://api.businesscentral.dynamics.com/v2.0/{tenant_id}/{environment}/api/v2.0

CUSTOM API:
https://api.businesscentral.dynamics.com/v2.0/{tenant_id}/{environment}/api/{publisher}/{group}/{version}

ODATA:
https://api.businesscentral.dynamics.com/v2.0/{tenant_id}/{environment}/ODataV4
```

### Common Endpoints

| Resource | Endpoint | Methods |
|----------|----------|---------|
| Companies | `/companies` | GET |
| Customers | `/companies({id})/customers` | GET, POST, PATCH, DELETE |
| Items | `/companies({id})/items` | GET, POST, PATCH, DELETE |
| Sales Orders | `/companies({id})/salesOrders` | GET, POST, PATCH, DELETE |
| Sales Order Lines | `/companies({id})/salesOrderLines` | GET, POST, PATCH, DELETE |
| Vendors | `/companies({id})/vendors` | GET, POST, PATCH, DELETE |
| Purchase Orders | `/companies({id})/purchaseOrders` | GET, POST, PATCH, DELETE |
| Inventory | `/companies({id})/itemLedgerEntries` | GET |

### Query Parameters

```
FILTERING:
$filter=displayName eq 'Acme Corp'
$filter=amount gt 1000 and status eq 'Open'
$filter=contains(displayName, 'Acme')

SORTING:
$orderby=displayName asc
$orderby=createdDate desc

PAGINATION:
$top=100
$skip=200

SELECTING FIELDS:
$select=id,displayName,email

EXPANDING RELATIONS:
$expand=salesOrderLines
```

## Common Payloads

### Create Customer
```json
{
  "displayName": "Acme Corporation",
  "type": "Company",
  "addressLine1": "123 Main St",
  "city": "Medicine Hat",
  "state": "AB",
  "postalCode": "T1A 1A1",
  "country": "CA",
  "email": "contact@acme.com",
  "phoneNumber": "403-555-1234"
}
```

### Create Sales Order
```json
{
  "customerId": "customer-guid-here",
  "customerNumber": "C00001",
  "orderDate": "2024-01-15",
  "requestedDeliveryDate": "2024-01-30",
  "externalDocumentNumber": "PO-12345",
  "salesOrderLines": [
    {
      "itemId": "item-guid-here",
      "quantity": 10,
      "unitPrice": 99.99
    }
  ]
}
```

### Create Item
```json
{
  "number": "ITEM-001",
  "displayName": "Garage Door Panel - White",
  "type": "Inventory",
  "unitPrice": 150.00,
  "unitCost": 75.00,
  "inventory": 100,
  "baseUnitOfMeasure": "EA"
}
```

## Error Handling

### Common Error Codes
| Code | Meaning | Action |
|------|---------|--------|
| 400 | Bad Request | Check payload format |
| 401 | Unauthorized | Refresh token |
| 403 | Forbidden | Check permissions |
| 404 | Not Found | Verify resource ID |
| 409 | Conflict | Check ETag for updates |
| 429 | Rate Limited | Implement backoff |
| 500 | Server Error | Retry with backoff |

### Error Response Format
```json
{
  "error": {
    "code": "BadRequest",
    "message": "The field 'quantity' must be a positive number.",
    "target": "quantity",
    "details": [
      {
        "code": "InvalidValue",
        "message": "Value '-5' is not valid for field 'quantity'"
      }
    ]
  }
}
```

## Rate Limits

```
LIMITS:
├── 600 API calls per minute per user
├── 6,000 API calls per minute per tenant
├── Batch requests count as single call
└── OData queries count against limits

BEST PRACTICES:
├── Use $select to minimize payload
├── Use $filter to reduce results
├── Batch related operations
├── Implement exponential backoff
└── Cache frequently accessed data
```

## Known Issues & Workarounds

### Modal Dialog Blocking (OPENDC-specific)
**Issue**: Some BC operations trigger modal dialogs that block API calls
**Workaround**: 
- Use background sessions in AL code
- Implement ConfirmHandler/MessageHandler
- Set GuiAllowed = false in codeunits

### Permission Errors
**Issue**: Custom extension APIs return 403
**Workaround**:
- Verify permission sets include custom objects
- Check entitlements for SaaS deployment
- Ensure indirect permissions are granted

### Pagination with Filters
**Issue**: $skip doesn't work with some filters
**Workaround**:
- Use @odata.nextLink for pagination
- Store last ID and filter with `id gt '{lastId}'`

## Testing Endpoints

### Sandbox Environment
```
BASE: https://api.businesscentral.dynamics.com/v2.0/{tenant}/sandbox/api/v2.0

NOTES:
├── Use for all development/testing
├── Data can be reset
├── No production impact
└── Same API behavior as production
```

### Health Check Endpoint
```bash
# Verify connectivity
curl -X GET \
  "https://api.businesscentral.dynamics.com/v2.0/{tenant}/{env}/api/v2.0/companies" \
  -H "Authorization: Bearer {token}"
```
