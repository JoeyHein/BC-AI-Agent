# BC Permission Fix Required

## Issue
The API cannot create sales quotes or orders in the **Open Distribution Company** due to a missing permission on a custom table.

**Error:**
```
Sorry, the current permissions prevented the action.
(TableData 50005 Unscheduled Lines Read: businesscentral_Open DC)
```

## Root Cause
The custom extension **"businesscentral_Open DC"** by ProBizTech added Table 50005 (Unscheduled Lines). When creating sales documents, BC triggers this table but the API application doesn't have Read permission on it.

## Fix (BC Admin)

### Option 1: Add Permission to Existing Permission Set

1. In BC, search for **"Permission Sets"**
2. Find the permission set assigned to the API application (likely "D365 AUTOMATION" or custom)
3. Click **Permissions**
4. Add new line:
   - **Object Type**: Table Data
   - **Object ID**: 50005
   - **Object Name**: Unscheduled Lines (or leave blank)
   - **Read Permission**: Yes
   - **Insert Permission**: Yes (optional)
   - **Modify Permission**: Yes (optional)
   - **Delete Permission**: No

### Option 2: Create New Permission Set

1. In BC, search for **"Permission Sets"**
2. Click **New**
3. Enter:
   - **Permission Set**: `OPENDC-API`
   - **Name**: Open DC API Access
4. Click **Permissions**
5. Add:
   - Table Data 50005 - Read: Yes
   - Any other custom tables from the extension

Then assign this permission set to the API application.

### Option 3: Grant via Extension (Long-term)

Have ProBizTech update the extension to:
1. Include an API permission set
2. Auto-grant permissions when the extension is installed

## Verification

After fixing, test with:
```bash
cd backend
python -c "
from app.integrations.bc.client import bc_client
# Create a test quote
result = bc_client.create_sales_quote({
    'customerNumber': 'ABES',
    'externalDocumentNumber': 'API-TEST'
})
print(result)
"
```

## Working Companies

Currently, **CRONUS Canada, Inc.** works for full order lifecycle testing because it doesn't have the custom extension.

## Summary

| Company | Status | Issue |
|---------|--------|-------|
| CRONUS Canada, Inc. | Working | Full API access |
| Open Distribution Company | Blocked | Table 50005 permission |
| My Company | Blocked | Same extension issue |
