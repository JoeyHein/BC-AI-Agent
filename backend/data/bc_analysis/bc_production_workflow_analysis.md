# BC Production Workflow Analysis for OPENDC

## Executive Summary

This document outlines the Business Central production workflow and the integration strategy for OPENDC's door manufacturing system. The key finding is that **Production Orders are NOT available in the standard BC v2.0 API** and require custom API exposure.

## Current BC Integration Status

### Available in Standard v2.0 API
- Items (with inventory levels)
- Customers
- Vendors
- Sales Quotes
- Sales Orders
- Sales Invoices
- Sales Shipments
- Purchase Orders
- Item Ledger Entries
- Locations (Warehouses)
- Item Categories

### NOT Available in Standard v2.0 API (Requires Custom Exposure)
- Production Orders
- Production Order Lines
- Production Order Components
- Production BOMs
- Routings
- Work Centers
- Machine Centers
- Capacity Ledger Entries
- Planning Worksheets

## BC Production Order Workflow

### 1. Production Order Types (Statuses)
1. **Simulated** - Test scenarios without affecting inventory
2. **Planned** - Created automatically by MRP based on demand forecasts
3. **Firm Planned** - Committed for execution but not released
4. **Released** - Active production on shop floor
5. **Finished** - Completed, inventory updated

### 2. Key Production Entities

#### Production Order Header
- No., Description, Status
- Source Type, Source No. (Item being produced)
- Quantity, Due Date
- Starting/Ending Date/Time
- Routing No., Production BOM No.

#### Production Order Lines
- Line No., Item No., Description
- Quantity, Due Date
- Routing No., Production BOM No.
- Location Code

#### Production Order Components
- Line No., Item No., Description
- Quantity Per, Expected Quantity
- Remaining Quantity, Consumed Quantity
- Location Code, Bin Code

#### Routings
- Routing No., Description
- Operations (sequence of steps)
- Work Center, Machine Center
- Run Time, Setup Time

#### Work Centers
- No., Name, Capacity
- Unit of Measure, Efficiency
- Calendar Code

### 3. Material Consumption Methods
- **Forward Flushing** - Materials consumed at production start
- **Backward Flushing** - Materials consumed when order finished
- **Manual** - Explicit consumption posting required
- **Pick + Forward/Backward** - Warehouse pick required

### 4. Output Recording
- Manual posting via Output Journal
- Forward posting (automatic at release)
- Backward posting (automatic at finish)

## Integration Strategy for OPENDC

### Phase 1: Inventory Visibility (Can Start Now)

The Items API already provides inventory levels. We can:
1. Check item availability before order confirmation
2. Track stock levels for components
3. View item ledger entries for movement history

```
GET /companies({id})/items?$filter=number eq 'HK02-16080-RC'
Response includes: inventory (qty on hand)
```

### Phase 2: Production Order Access (Requires BC Work)

**Option A: OData Web Services (Recommended)**
- BC Admin publishes Production Order page as OData service
- Endpoint: `/ODataV4/Company('OPENDC')/Production_Orders`
- Pros: Quick to implement, no AL development
- Cons: Limited filtering, read-only for complex operations

**Option B: Custom API Page (Best Long-term)**
- Create AL extension with API page for Production Orders
- Full CRUD operations, custom actions
- Example endpoint: `/api/opendc/manufacturing/v1.0/productionOrders`
- Pros: Full control, proper REST design
- Cons: Requires BC developer

**Option C: Power Automate Middleware**
- Use Power Automate flows to create production orders
- HTTP trigger receives request, creates order in BC
- Pros: No BC development, quick setup
- Cons: Additional cost, latency, maintenance

### Phase 3: Automatic Scheduling

Once production orders are accessible:
1. **Backward Scheduling** - Calculate start date from due date
2. **Work Center Capacity** - Check available capacity
3. **Component Availability** - Verify all parts available
4. **Queue Management** - Prioritize by due date

## Recommended Implementation Path

### Immediate Actions (This Week)
1. Implement inventory checking service using existing Items API
2. Create inventory availability endpoint for quote/order validation
3. Design the production order service interface (ready for when BC exposes it)

### BC Admin Actions Required
1. Publish "Released Production Orders" page as OData web service
2. Publish "Prod. Order Components" page as OData web service
3. Publish "Work Centers" page as OData web service
4. Test API access with current OAuth credentials

### Future Development
1. Create custom API pages in BC for full CRUD
2. Implement automatic scheduling algorithm
3. Build production calendar UI

## API Endpoint Design (Future)

### Check Inventory Availability
```
POST /api/inventory/check-availability
{
    "items": [
        {"itemNumber": "HK02-16080-RC", "quantity": 5},
        {"itemNumber": "SP-1408-SS", "quantity": 10}
    ],
    "requiredDate": "2024-02-15"
}
Response:
{
    "available": false,
    "shortages": [
        {"itemNumber": "HK02-16080-RC", "required": 5, "available": 2, "shortfall": 3}
    ],
    "productionRequired": [
        {"itemNumber": "HK02-16080-RC", "quantity": 3, "leadTime": 5}
    ]
}
```

### Create Production Order (Future - requires BC exposure)
```
POST /api/production/orders
{
    "itemNumber": "HK02-16080-RC",
    "quantity": 3,
    "dueDate": "2024-02-15",
    "salesOrderNumber": "SO-001234",
    "priority": "high"
}
```

### Get Production Schedule (Future)
```
GET /api/production/schedule?startDate=2024-02-01&endDate=2024-02-28
Response:
{
    "orders": [...],
    "capacity": {...},
    "bottlenecks": [...]
}
```

## Data Flow Diagram

```
[Customer Portal] --> [Quote/Order] --> [OPENDC AI Agent]
                                              |
                                              v
                                    [Inventory Check Service]
                                              |
                      +------------------+----+----+------------------+
                      |                  |         |                  |
                      v                  v         v                  v
              [Items Available?]   [On Production?]  [Need to Produce?]
                      |                  |                   |
                      v                  v                   v
              [Reserve Stock]    [Link to PO]      [Create Prod Order]
                                                           |
                                                           v
                                                   [Schedule Production]
                                                           |
                                                           v
                                                    [Production Calendar]
```

## References

- [About Production Orders - Microsoft Learn](https://learn.microsoft.com/en-us/dynamics365/business-central/production-about-production-orders)
- [Configure Production Processes - Microsoft Learn](https://learn.microsoft.com/en-us/dynamics365/business-central/production-configure-production-processes)
- [Developing Custom APIs - Microsoft Learn](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/developer/devenv-develop-custom-api)
- [OData Web Services - Microsoft Learn](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/webservices/odata-web-services)
