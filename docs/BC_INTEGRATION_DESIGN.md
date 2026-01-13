# Business Central Integration Design

## Executive Summary

Based on deep analysis of 888 real BC quotes and the product catalog, I've designed a two-path integration strategy to automatically create BC quotes from AI-parsed email requests.

---

## BC Quote Structure - Key Findings

### Quote Types Found

**Type 1: Pre-Configured Door Packages** (Simple Path)
- Only TX450 model has complete door SKUs (28 variations)
- SKU Format: `TX450-WWHH-03` (WW=width, HH=height)
- Example: `TX450-1010-03` = "10x10 TX450, WHITE, 3" TRACK" @ $2,118.41
- All base models are WHITE only

**Type 2: Component-Level Builds** (Complex Path)
- AL976, KANATA, PANORAMA, V130G models
- Custom TX450 configurations (non-white colors, powder coating)
- 15-20+ line items per door
- Includes: sections, glass kits, track, hardware, springs, shafts, seals, operators

---

## Product Catalog Structure

### Complete Catalog Overview

| Category | Prefix | Items | Examples |
|----------|--------|-------|----------|
| Panels/Sections | PN | 50+ | PN65-21000-1000, PN97-24300810-1002 |
| Glass Kits | GK | 50+ | GK15-10200-00, GK17-11600-00 |
| Track Systems | TR | 50+ | TR02-STDBM-1012, TR03-STDBM-14 |
| Hardware Kits | HK | 14 | HK01-00000-RC, HK03-00000-AL |
| Hardware Boxes | HW | 25 | HW12-14000-00, HW14-14000-00 |
| Shafts | SH | 17 | SH12-11010-00, SH11-11506-00 |
| Springs | SP | 50+ | SP11-21820-01 (LH), SP11-21820-02 (RH) |
| Seals/Plastics | PL | 50+ | PL11-12102-00, PL10-00146-00 |
| Operators | OP | 50+ | OP19-01099-00, OP21-01000-00 |
| Struts | FH | 50+ | FH17-00002-00, FH17-00018-00 |
| Aluminum Parts | AL | 46 | AL91-67400-01, AL91-67500-00 |

**Special Items:**
- `POWDERCOAT` - Custom powder coating charges
- `FREIGHT` - Shipping costs
- `CUSTOM` - Custom items/charges
- `WRAP` - Wrapping services

**Total Catalog:** 450+ distinct component items

---

## Required BC Quote Fields

### Minimum Required (100% populated in all quotes)
```
customerId / customerNumber / customerName
documentDate
dueDate
currencyCode (USD)
status (Draft, Sent, Accepted)
sellToAddressLine1, sellToCity, sellToState
billToAddressLine1, billToCity, billToState
shipToAddressLine1, shipToCity, shipToState
```

### Highly Recommended (95%+ populated)
```
email (98%)
phoneNumber (96%)
shipToContact (94%)
totalAmountExcludingTax
totalTaxAmount
totalAmountIncludingTax
```

### Optional but Common
```
externalDocumentNumber (56%) - Could use our quote request ID
salesperson (94%)
validUntilDate - Default to +60 days
```

---

## Integration Architecture

### Phase 1: Simple Path (TX450 Pre-Configured Doors)

**When to Use:**
- Door model = TX450
- Standard white color
- Standard lift (no custom configurations)

**Implementation:**
1. Parse email: "I need (2) TX450 doors, 10x10"
2. Map dimensions → SKU: `TX450-1010-03`
3. Fetch current price from BC items API
4. Create quote with single line item
5. Add glass kits if windows specified
6. Add operators if requested
7. Add FREIGHT line item

**Example Quote Generation:**
```python
customer_id = lookup_or_create_customer(parsed_data['customer'])
door_sku = f"TX450-{width:02d}{height:02d}-03"
item = bc_api.get_item(door_sku)

quote = bc_api.create_quote({
    'customerId': customer_id,
    'documentDate': today(),
    'dueDate': today(),
    'validUntilDate': today() + 60_days
})

bc_api.add_quote_line(quote.id, {
    'itemId': item.id,
    'quantity': parsed_data['quantity'],
    'unitPrice': item.unitPrice
})
```

### Phase 2: Complex Path (Component-Level Builds)

**When to Use:**
- AL976, KANATA, PANORAMA models
- Custom TX450 (powder coating, non-white)
- Special configurations

**Requirements:**
Need to build Bill of Materials (BOM) mapping:
- Door Model + Dimensions + Color → List of components with quantities
- Example: "AL976 10x12 Black" →
  - 5x PN97-24300820-1002 sections
  - 69x GK17-11600-00 glass kits
  - 2x SP12-00232-00 spring sets
  - etc.

**This requires:**
1. Reverse-engineer BOMs from existing BC quotes
2. Create product configuration rules
3. Build BOM calculation engine

**Deferred to later:** This is complex and requires detailed product knowledge

---

## Recommended Implementation Plan

### Step 1: Customer Lookup/Creation
```python
def get_or_create_customer(email_data):
    # Search BC for existing customer by email or name
    customer = bc_api.search_customers(email=email_data['email'])

    if customer:
        return customer.id

    # Create new customer in BC
    customer = bc_api.create_customer({
        'name': email_data['company_name'],
        'email': email_data['email'],
        'phoneNumber': email_data['phone'],
        'address': email_data['address']
    })

    return customer.id
```

### Step 2: TX450 Quote Generator
```python
def generate_tx450_quote(quote_request_id, parsed_data):
    # Get or create customer
    customer_id = get_or_create_customer(parsed_data['customer'])

    # Create BC quote header
    bc_quote = bc_api.create_quote({
        'customerId': customer_id,
        'customerNumber': customer['number'],
        'customerName': customer['name'],
        'documentDate': date.today().isoformat(),
        'dueDate': date.today().isoformat(),
        'validUntilDate': (date.today() + timedelta(days=60)).isoformat(),
        'email': parsed_data['customer']['email'],
        'phoneNumber': parsed_data['customer']['phone'],
        'sellToAddressLine1': parsed_data['customer']['address']['line1'],
        'sellToCity': parsed_data['customer']['address']['city'],
        'sellToState': parsed_data['customer']['address']['state'],
        'externalDocumentNumber': f'AI-QUOTE-{quote_request_id}'
    })

    # Add line items for each door
    for door in parsed_data['doors']:
        # Map to TX450 SKU
        width = int(door['width_ft'])
        height = int(door['height_ft'])
        sku = f"TX450-{width:02d}{height:02d}-03"

        # Fetch item from BC
        item = bc_api.get_item_by_number(sku)

        if not item:
            raise ValueError(f"Door size {width}x{height} not available")

        # Add comment line describing the door
        bc_api.create_quote_line(bc_quote['id'], {
            'lineType': 'Comment',
            'description': f"({door['quantity']}) {width}x{height} TX450, {door.get('color', 'WHITE')}, 3\" HW, STD LIFT"
        })

        # Add door line item
        bc_api.create_quote_line(bc_quote['id'], {
            'lineType': 'Item',
            'itemId': item['id'],
            'quantity': door['quantity'],
            'unitPrice': item['unitPrice']
        })

        # Add glass kits if windows specified
        if door.get('windows'):
            glass_kit = bc_api.get_item_by_number('GK16-23205-00')  # Standard TX450 glass
            window_qty = door['quantity'] * door['windows']['count']

            bc_api.create_quote_line(bc_quote['id'], {
                'lineType': 'Item',
                'itemId': glass_kit['id'],
                'quantity': window_qty,
                'unitPrice': glass_kit['unitPrice']
            })

        # Add operators if specified
        if door.get('operator'):
            operator = bc_api.get_item_by_number('OP19-01099-00')  # LiftMaster standard

            bc_api.create_quote_line(bc_quote['id'], {
                'lineType': 'Item',
                'itemId': operator['id'],
                'quantity': door['quantity'],
                'unitPrice': operator['unitPrice']
            })

    # Add freight
    freight_item = bc_api.get_item_by_number('FREIGHT')
    bc_api.create_quote_line(bc_quote['id'], {
        'lineType': 'Item',
        'itemId': freight_item['id'],
        'quantity': 1,
        'unitPrice': calculate_freight(parsed_data)
    })

    return bc_quote
```

### Step 3: Dashboard Integration

Update frontend `QuoteDetail.jsx`:
```javascript
const generateBCQuoteMutation = useMutation({
  mutationFn: () => quotesApi.generateBCQuote(id),
  onSuccess: (response) => {
    alert(`BC Quote ${response.bc_quote_number} created successfully!`)
    // Optionally open BC quote in new tab
    window.open(response.bc_quote_url, '_blank')
  },
})
```

Add API endpoint in `app/api/feedback.py`:
```python
@router.post("/{quote_id}/generate-bc-quote")
def generate_bc_quote(quote_id: int, db: Session = Depends(get_db)):
    """Generate quote in Business Central from approved AI parse"""
    from app.services.bc_integration_service import BCIntegrationService

    bc_service = BCIntegrationService(db)
    bc_quote = bc_service.generate_quote(quote_id)

    return {
        'bc_quote_id': bc_quote['id'],
        'bc_quote_number': bc_quote['number'],
        'bc_quote_url': f"https://businesscentral.dynamics.com/quote/{bc_quote['id']}"
    }
```

---

## Data Flow

```
Email Received
    ↓
AI Parse → QuoteRequest (DB)
    ↓
User Reviews in Dashboard
    ↓
User Approves → Status = "approved"
    ↓
[NEW] User clicks "Create BC Quote"
    ↓
BC Integration Service:
  1. Get/Create Customer in BC
  2. Create BC Quote Header
  3. Add Comment Lines (door descriptions)
  4. Add Item Lines (products)
  5. Calculate totals
    ↓
BC Quote Created → Store BC quote ID in QuoteRequest
    ↓
User can open BC quote directly from dashboard
```

---

## Customer Matching Strategy

### Search Hierarchy
1. **Exact email match** - Most reliable
2. **Company name fuzzy match** - Handle variations
3. **Phone number match** - Secondary identifier
4. **Create new customer** - If no match found

### Implementation
```python
def find_customer_in_bc(email, company_name, phone):
    # Try email first
    customer = bc_api.search_customers(filter=f"email eq '{email}'")
    if customer:
        return customer[0]

    # Try exact company name
    customer = bc_api.search_customers(filter=f"name eq '{company_name}'")
    if customer:
        return customer[0]

    # Try phone number
    if phone:
        customer = bc_api.search_customers(filter=f"phoneNumber eq '{phone}'")
        if customer:
            return customer[0]

    # No match - will create new
    return None
```

---

## Error Handling

### Common Errors
1. **Door size not available** - TX450-1234-03 doesn't exist
   - Solution: Show error to user with available sizes

2. **Customer already exists** - Email match but different name
   - Solution: Show match to user, ask to confirm or create new

3. **BC API authentication failure**
   - Solution: Refresh OAuth token, retry once

4. **Invalid address** - BC requires valid state code
   - Solution: Validate and normalize addresses before sending

### Error Recovery
```python
try:
    bc_quote = generate_bc_quote(quote_request_id)
except DoorSizeNotAvailable as e:
    return {
        'success': False,
        'error': f"Door size {e.size} not available",
        'available_sizes': get_available_tx450_sizes()
    }
except CustomerDuplicateEmail as e:
    return {
        'success': False,
        'error': 'Customer with this email exists',
        'existing_customer': e.customer,
        'action_required': 'confirm_or_create_new'
    }
```

---

## Testing Strategy

### Phase 1: TX450 Simple Path Testing

1. **Test with approved AI parse**
   - Verify customer lookup
   - Verify quote creation
   - Verify line items
   - Verify pricing matches BC catalog

2. **Test customer scenarios**
   - New customer (doesn't exist in BC)
   - Existing customer (exact email match)
   - Similar customer (fuzzy name match)

3. **Test door configurations**
   - Single door
   - Multiple doors (different sizes)
   - Doors with windows
   - Doors with operators

4. **Test error cases**
   - Invalid door size
   - BC API down
   - Authentication failure
   - Missing customer data

---

## Success Metrics

### Phase 1 Goals
- ✅ Successfully create BC quotes for TX450 doors
- ✅ 90%+ customer matching accuracy
- ✅ Pricing matches BC catalog exactly
- ✅ Quote totals calculate correctly

### Phase 2 Goals (Future)
- Component-level BOM builds for all door models
- Custom configurations (powder coating, special glass)
- Automated approval for high-confidence parses (>95%)

---

## Next Steps

1. ✅ **Complete** - BC API authentication and exploration
2. ✅ **Complete** - Product catalog analysis
3. **NEXT** - Build BC Integration Service
   - Customer lookup/creation
   - Quote header creation
   - Line item generation
   - TX450 simple path implementation
4. **Then** - Add "Create BC Quote" button to dashboard
5. **Then** - Test with real approved parses
6. **Then** - Deploy to production
7. **Later** - Phase 2: Component-level builds

---

## File Structure

```
backend/
  app/
    services/
      bc_integration_service.py  # NEW - BC quote generation
      bc_api_client.py           # NEW - BC API wrapper
    api/
      feedback.py                # ADD - /generate-bc-quote endpoint

frontend/
  src/
    components/
      QuoteDetail.jsx            # ADD - "Create BC Quote" button
    api/
      client.js                  # ADD - generateBCQuote() method
```
