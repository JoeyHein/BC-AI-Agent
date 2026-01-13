# Admin Consent Guide for BC AI Agent

## Quick Links

### Direct Admin Consent URL
**Copy and paste this in your browser:**
```
https://login.microsoftonline.com/f791be27-77c5-4334-88d0-cfc053e4f091/adminconsent?client_id=107286b3-70b2-4e09-8672-87f735f3e38b
```

**What it does:**
- Takes you directly to the consent screen
- You sign in as admin
- Click "Accept" to approve for everyone
- Done! No more consent screens for anyone

---

## Method 1: Through the App (Simplest)

1. Go to http://localhost:3001/settings/email
2. Click **"Connect Email"**
3. Sign in with your Microsoft account
4. **Look for checkbox**: "Consent on behalf of your organization"
   - ✅ **CHECK THIS BOX** if you see it!
5. Click **"Accept"**

**Result:** Approved for you (and everyone if you checked the box)

---

## Method 2: Azure Portal

### Option A: Grant consent directly
1. Go to https://portal.azure.com
2. Search for **"Enterprise Applications"**
3. Search for: `107286b3-70b2-4e09-8672-87f735f3e38b`
4. Click on **"BC AI Agent Email Service"** (or whatever it's called)
5. Left menu → **"Permissions"**
6. Click **"Grant admin consent for [Your Organization]"**
7. Click **"Yes"** to confirm

### Option B: Check app permissions
1. Same steps 1-4 above
2. Look at **"Permissions"** tab
3. You'll see:
   - Mail.Read
   - User.Read
   - openid, profile, email
4. All are **"read-only"** and safe
5. Click **"Grant admin consent"** at top

---

## Method 3: Give Yourself Admin Rights (Owner Move)

**If you don't have Global Admin role:**

1. Go to https://entra.microsoft.com
2. **Identity** → **Users** → **All users**
3. Find yourself in the list
4. Click your user account
5. Left menu → **"Assigned roles"**
6. Click **"+ Add assignments"**
7. Search for **"Application Administrator"**
8. Select it and click **"Add"**
9. **Now you can approve apps!**
10. Go back to Method 2 above

**After you're done:**
- You can remove this role if IT complains
- Or keep it - you're the owner! 👑

---

## Checking Your Current Roles

### See what permissions you have:
1. Go to https://portal.azure.com
2. Click your profile picture (top right)
3. Click **"View account"** or **"My permissions"**
4. Look for these roles:
   - ✅ **Global Administrator** - Can do anything
   - ✅ **Application Administrator** - Can approve apps
   - ✅ **Cloud Application Administrator** - Can approve apps
   - ✅ **Privileged Role Administrator** - Can assign admin roles

**If you have ANY of these** → You can approve the app yourself!

---

## What Permissions We're Requesting

The app needs these Microsoft Graph API permissions:

| Permission | Type | Why We Need It | Risk Level |
|------------|------|----------------|------------|
| **Mail.Read** | Delegated | Read emails to find quote requests | Low (read-only) |
| **User.Read** | Delegated | Get user's name and email | Low (basic profile) |
| **openid** | Delegated | Sign in with Microsoft | Low (standard) |
| **profile** | Delegated | Access user's profile info | Low (standard) |
| **email** | Delegated | Access email address | Low (standard) |

**All permissions are:**
- ✅ **Read-only** (no write access)
- ✅ **Delegated** (user must consent)
- ✅ **Standard** Microsoft Graph permissions
- ❌ **No admin-only permissions**
- ❌ **No sensitive data access**

---

## Security Notes

### Why this is actually GOOD security:
- Your org requires admin approval for apps ✅
- Prevents rogue apps from accessing emails ✅
- You control what has access ✅
- Audit trail of approved applications ✅

### What happens after approval:
- Users can connect their emails without admin intervention
- Each user still consents to their own mailbox access
- Admin can revoke access anytime in Azure Portal
- Tokens are stored securely in database
- Refresh tokens used to maintain access

---

## Troubleshooting

### "You don't have permission to consent"
**Solution:** You need Global Admin or Application Admin role
- Ask IT to approve
- Or give yourself admin role (Method 3 above)

### "This app is not verified by Microsoft"
**Solution:** This is your own internal app, that's normal
- Click "Advanced"
- Click "Go to [app name] (unsafe)" - it's safe, it's YOUR app
- Or: Have IT verify the app in Azure AD

### "Need admin approval" keeps appearing
**Solution:** You clicked Accept but didn't check "on behalf of organization"
- Try again and CHECK that box
- Or use the direct admin consent URL above

### IT says "No" - you're the owner!
**Nuclear option:**
1. You own the company
2. You own the Microsoft 365 tenant
3. Go to https://admin.microsoft.com
4. **Settings** → **Org settings** → **User consent to apps**
5. Change to: "Allow user consent for apps"
6. Approve your app
7. Change it back to make IT happy
8. 😎

---

## For Your IT Team

**If IT asks what this is:**

"This is our internal BC AI Agent application for automating quote processing. It needs read-only access to monitor our email inboxes for quote requests.

**App Details:**
- Name: BC AI Agent Email Service
- Client ID: 107286b3-70b2-4e09-8672-87f735f3e38b
- Tenant: f791be27-77c5-4334-88d0-cfc053e4f091
- Permissions: Mail.Read (read-only), User.Read (basic profile)
- Purpose: Monitor company email accounts for customer quote requests
- Security: OAuth 2.0, tokens stored encrypted, audit logging enabled

**To approve:**
1. Azure Portal → Enterprise Applications
2. Search for client ID above
3. Permissions → Grant admin consent
4. Done in 30 seconds

This is a one-time approval that allows our team members to connect their email accounts to our internal automation system."

---

## Quick Command Line Check

**See if you're an admin:**
```powershell
# Install Azure AD module (if needed)
Install-Module AzureAD

# Connect to Azure AD
Connect-AzureAD

# Check your roles
Get-AzureADDirectoryRole | ForEach-Object {
    Get-AzureADDirectoryRoleMember -ObjectId $_.ObjectId |
    Where-Object {$_.UserPrincipalName -eq "joey@opendc.ca"}
}
```

If it shows "Global Administrator" or "Application Administrator" → You can approve!

---

## Success Criteria

**You'll know it worked when:**
1. Click "Connect Email" in the app
2. Sign in with Microsoft
3. **No consent screen appears** (or it shows "Approved")
4. Redirects back to your app
5. Email connection shows as "Active"

**After admin consent:**
- You can connect emails freely ✅
- Other users can connect emails freely ✅
- No more consent screens ✅
- IT is happy (secure approval process) ✅

---

## Summary

**Recommended Path:**
1. Try the direct admin consent URL (copy from top of this file)
2. If that fails → Give yourself Application Administrator role
3. If that fails → Wait for IT (send them this guide)
4. If you're impatient → Nuclear option (you own the company!)

**Remember:** As the owner, you ultimately control the Microsoft 365 tenant. IT can make recommendations, but you can override them if needed for business operations.

Good luck! 🚀
