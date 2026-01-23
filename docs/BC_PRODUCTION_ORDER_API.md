# Business Central Production Order API Access

## Current State (Sandbox_Internal Environment)

### Order Lifecycle - API Availability

| Step | API Method | Status | Notes |
|------|-----------|--------|-------|
| Create Quote | `POST salesQuotes` | ⚠️ Blocked* | Open DC: Table 50005 permission |
| Create Order | `POST salesOrders` | ✅ Working | All companies |
| Add Line Items | `POST salesOrderLines` | ✅ Working | All companies |
| Set Delivery Date | `PATCH salesOrders` | ✅ Working | All companies |
| Convert Quote→Order | `Microsoft.NAV.makeOrder` | ✅ Working | CRONUS only |
| Ship & Invoice | `Microsoft.NAV.shipAndInvoice` | ❌ Blocked | Page 50502 dialog |
| Post Invoice | `Microsoft.NAV.post` | ❌ Blocked | Page 50502 dialog |

*Open Distribution Company has custom extension "businesscentral_Open DC" requiring Table 50005 Read permission on Azure AD Application.

### Custom Extension Blocking Issues

The BC Sandbox_Internal environment has custom extensions that show modal dialogs during posting operations. These dialogs cannot work via API.

**Page 50502 - Posting Date Dialog** blocks:
- `Microsoft.NAV.shipAndInvoice` action
- `Microsoft.NAV.post` action

**Fix Required**: BC Admin must either:
1. Disable/remove the custom extension for API operations
2. Modify extension to skip dialogs when called from API context
3. Use a different BC environment without these extensions

### Available via API
- **Production BOMs** (ODataV4): `ProductionBomLines`, `Production_BOM_Excel`
- **Items with BOMs**: Full item master with BOM references
- **Sales Orders**: Full CRUD (but not shipping/invoicing)

### NOT Available via Standard API
- Production Orders (Table 5405)
- Production Order Lines (Table 5406)
- Released Production Orders (Page 99000831)
- Firm Planned Production Orders (Page 99000813)

---

## Solution Options

### Option 1: Publish BC Web Service (Quickest)

1. **In Business Central**, search for "Web Services"
2. Add the following web services:

| Object Type | Object ID | Service Name | Published |
|-------------|-----------|--------------|-----------|
| Page | 99000831 | ReleasedProductionOrders | Yes |
| Page | 99000813 | FirmPlannedProdOrders | Yes |
| Page | 99000829 | ProductionOrders | Yes |
| Page | 5510 | ProductionOrderLines | Yes |

3. **Access via ODataV4**:
```
https://api.businesscentral.dynamics.com/v2.0/{tenant}/{environment}/ODataV4/Company('Open Distribution Company Inc.')/ReleasedProductionOrders
```

---

### Option 2: Create AL Extension (Recommended for Full Control)

Create a custom API page to expose production orders:

```al
// ProductionOrderAPI.al
page 50100 "Production Order API"
{
    APIGroup = 'opendc';
    APIPublisher = 'opendc';
    APIVersion = 'v1.0';
    EntityName = 'productionOrder';
    EntitySetName = 'productionOrders';
    PageType = API;
    SourceTable = "Production Order";
    DelayedInsert = true;
    ODataKeyFields = SystemId;

    layout
    {
        area(Content)
        {
            repeater(Records)
            {
                field(id; Rec.SystemId) { Caption = 'id'; }
                field(status; Rec.Status) { Caption = 'status'; }
                field(number; Rec."No.") { Caption = 'number'; }
                field(description; Rec.Description) { Caption = 'description'; }
                field(sourceType; Rec."Source Type") { Caption = 'sourceType'; }
                field(sourceNo; Rec."Source No.") { Caption = 'sourceNo'; }
                field(quantity; Rec.Quantity) { Caption = 'quantity'; }
                field(dueDate; Rec."Due Date") { Caption = 'dueDate'; }
                field(startingDate; Rec."Starting Date") { Caption = 'startingDate'; }
                field(endingDate; Rec."Ending Date") { Caption = 'endingDate'; }
                field(finishedDate; Rec."Finished Date") { Caption = 'finishedDate'; }
            }
        }
    }

    [ServiceEnabled]
    procedure Release()
    var
        ProdOrderStatusMgt: Codeunit "Prod. Order Status Management";
    begin
        ProdOrderStatusMgt.ChangeStatusOnProdOrder(Rec, Rec.Status::Released, Rec."Due Date", false);
    end;

    [ServiceEnabled]
    procedure Finish()
    var
        ProdOrderStatusMgt: Codeunit "Prod. Order Status Management";
    begin
        ProdOrderStatusMgt.ChangeStatusOnProdOrder(Rec, Rec.Status::Finished, Rec."Due Date", false);
    end;
}
```

**Deploy the extension**, then access via:
```
https://api.businesscentral.dynamics.com/v2.0/{tenant}/{environment}/api/opendc/v1.0/companies({companyId})/productionOrders
```

---

### Option 3: Use Existing Actions + Planning

Even without direct Production Order API, you can:

1. **Create Sales Order** (existing API)
2. **Let BC Planning create Production Orders** (configured in BC)
3. **Query Production BOMs** to understand what will be produced

This is the "pull" model where BC's MRP creates production orders automatically.

---

## HAR File Capture (Browser Method)

To capture the actual API calls BC makes for production orders:

1. Open BC Web Client in Chrome/Edge
2. Open Developer Tools (F12) → Network tab
3. Navigate to Production Orders
4. Perform actions (create, release, finish)
5. Right-click in Network tab → "Save all as HAR with content"

The HAR file will show the actual OData calls BC makes internally.

---

## Python Client Implementation

Once web services are published, update the BC client:

```python
# Add to app/integrations/bc/client.py

def get_production_orders(self, company_name: str = "Open Distribution Company Inc.",
                         status: str = None, top: int = 100) -> List[Dict]:
    """Get production orders via ODataV4 web service"""
    import urllib.parse
    encoded = urllib.parse.quote(company_name)

    endpoint = f"ODataV4/Company('{encoded}')/ReleasedProductionOrders"
    if status:
        endpoint += f"?$filter=Status eq '{status}'&$top={top}"
    else:
        endpoint += f"?$top={top}"

    # Note: ODataV4 uses different base URL pattern
    url = f"{self.base_url.replace('/api/v2.0', '')}/{endpoint}"
    return self._make_odata_request("GET", url)

def create_production_order(self, item_no: str, quantity: int, due_date: str,
                           company_name: str = "Open Distribution Company Inc.") -> Dict:
    """Create a production order via ODataV4"""
    # Requires web service to be published
    pass

def release_production_order(self, prod_order_no: str) -> Dict:
    """Release a production order"""
    # Call Release bound action
    pass
```

---

## Next Steps

1. **BC Admin Task**: Publish web services for Production Order pages (Option 1)
2. **Developer Task**: Update BC client to use ODataV4 for production orders
3. **Test**: Query production orders and verify data structure
4. **Integrate**: Add production order sync to scheduler service

---

## References

- [BC Production Order Tables](https://learn.microsoft.com/en-us/dynamics365/business-central/design-details-table-structure)
- [Publishing Web Services](https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-publish-web-service)
- [Custom API Pages](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/developer/devenv-develop-custom-api)
