# Business Central OData Web Services Setup Guide

This guide explains how to publish the required OData web services in Business Central to enable full production order integration with the OPENDC AI Agent.

## Important: Azure AD App Permissions

For the backend to access OData endpoints, the Azure AD app registration needs proper permissions:

### Option 1: Add OData Permissions to Existing App
1. Go to Azure Portal > Azure Active Directory > App registrations
2. Find the BC AI Agent app (Client ID: `e95810a7-0f6f-462b-9fc2-e60aa04a7bb8`)
3. Go to **API permissions**
4. Add permission: **Dynamics 365 Business Central** > **Delegated permissions** > `Financials.ReadWrite.All`
5. Grant admin consent

### Option 2: Register App in BC for OData Access
1. In Business Central, search for **Microsoft Entra Applications**
2. Add new entry for the app:
   - Client ID: `e95810a7-0f6f-462b-9fc2-e60aa04a7bb8`
   - Description: BC AI Agent
   - State: Enabled
3. Assign user permissions to the app (SUPER or specific permission sets)

---

## Required Web Services

To enable production order management from the AI Agent, publish these pages as OData web services:

| Page ID | Page Name | Service Name | Purpose |
|---------|-----------|--------------|---------|
| 5405 | Released Production Orders | `ReleasedProductionOrders` | View/manage production orders |
| 99000818 | Prod. Order Components | `ProdOrderComponents` | View components needed |
| 99000754 | Work Centers | `WorkCenters` | View capacity/scheduling |
| 99000789 | Prod. Order Routing | `ProdOrderRouting` | View routing operations |

## Step-by-Step Setup in Business Central

### Step 1: Open Web Services Page
1. In Business Central, click the **Search** icon (magnifying glass)
2. Search for **"Web Services"**
3. Click on **Web Services** to open the list

### Step 2: Add Released Production Orders
1. Click **+ New** to add a new line
2. Fill in the fields:
   - **Object Type**: `Page`
   - **Object ID**: `5405`
   - **Object Name**: (auto-fills) `Released Production Orders`
   - **Service Name**: `ReleasedProductionOrders`
   - **Published**: ✓ (check this box)
3. The OData URL will be auto-generated

### Step 3: Add Prod. Order Components
1. Click **+ New** to add a new line
2. Fill in the fields:
   - **Object Type**: `Page`
   - **Object ID**: `99000818`
   - **Object Name**: (auto-fills) `Prod. Order Components`
   - **Service Name**: `ProdOrderComponents`
   - **Published**: ✓ (check this box)

### Step 4: Add Work Centers
1. Click **+ New** to add a new line
2. Fill in the fields:
   - **Object Type**: `Page`
   - **Object ID**: `99000754`
   - **Object Name**: (auto-fills) `Work Centers`
   - **Service Name**: `WorkCenters`
   - **Published**: ✓ (check this box)

### Step 5: Add Prod. Order Routing (Optional)
1. Click **+ New** to add a new line
2. Fill in the fields:
   - **Object Type**: `Page`
   - **Object ID**: `99000789`
   - **Object Name**: (auto-fills) `Prod. Order Routing`
   - **Service Name**: `ProdOrderRouting`
   - **Published**: ✓ (check this box)

### Step 6: Verify Publication
After adding all services, your Web Services list should look like:

| Object Type | Object ID | Service Name | Published |
|-------------|-----------|--------------|-----------|
| Page | 5405 | ReleasedProductionOrders | Yes |
| Page | 99000818 | ProdOrderComponents | Yes |
| Page | 99000754 | WorkCenters | Yes |
| Page | 99000789 | ProdOrderRouting | Yes |

## Testing the Web Services

### OData Endpoint URLs
Once published, the services are available at:

```
Base URL: https://api.businesscentral.dynamics.com/v2.0/{tenant_id}/{environment}/ODataV4

Production Orders:
https://api.businesscentral.dynamics.com/v2.0/{tenant_id}/{environment}/ODataV4/Company('OPENDC')/ReleasedProductionOrders

Work Centers:
https://api.businesscentral.dynamics.com/v2.0/{tenant_id}/{environment}/ODataV4/Company('OPENDC')/WorkCenters
```

For OPENDC sandbox:
```
Tenant ID: f791be27-77c5-4334-88d0-cfc053e4f091
Environment: Sandbox_Internal
Company: OPENDC
```

### Test URL
```
https://api.businesscentral.dynamics.com/v2.0/f791be27-77c5-4334-88d0-cfc053e4f091/Sandbox_Internal/ODataV4/Company('OPENDC')/ReleasedProductionOrders?$top=5
```

## After Configuration

Once these services are published:

1. **Notify the development team** - We'll update the AI Agent to use these endpoints
2. **Test access** - Run the provided test script to verify connectivity
3. **Enable integration** - We'll flip the `PRODUCTION_API_AVAILABLE` flag to `True`

## Additional Pages (Optional)

If you want more production visibility, consider also publishing:

| Page ID | Page Name | Purpose |
|---------|-----------|---------|
| 5406 | Firm Planned Prod. Orders | Planning stage orders |
| 5407 | Finished Production Orders | Completed orders |
| 99000831 | Capacity Ledger Entries | Track production time |
| 99000760 | Work Center Load | Capacity utilization |

## Troubleshooting

### "Page not found" Error
- Verify the Object ID is correct
- Check that the page exists in your BC version
- Ensure you have proper licensing for manufacturing module

### "Access Denied" Error
- The Azure AD app registration needs proper permissions
- User must have BC manufacturing permissions
- Check that the app is registered in BC (Users > Microsoft Entra Applications)

### "Company not found" Error
- Verify company name is exactly 'OPENDC' (case-sensitive)
- Try URL encoding: `Company('OPENDC')` or `Company%28%27OPENDC%27%29`

## Contact

For issues with this setup, contact:
- BC Admin / IT Team for BC configuration
- Development Team for integration issues
