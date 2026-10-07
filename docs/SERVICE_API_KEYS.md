# Service keys for the automation

The hourly jobs were signing in as a staff person. That login expires, and when it does the job stops. A service key is a separate password for the automation. It stays valid until you revoke it. You can also give it an end date if you want one.

Only an admin can create or revoke a key. The key is not a full staff login.

## Create a key

1. Log in at [portal.opendc.ca](https://portal.opendc.ca).
2. Open **Settings**.
3. Open the **Service keys** tab (admins only).
4. Type a name you will recognize, such as `Hourly PO check`.
5. Leave **Expires** blank unless you want the key to stop on its own.
6. Click **Create key**.
7. Copy the key immediately and put it where the automation keeps secrets.

The portal shows the full key **once**. It stores only a scrambled copy. If you lose the key, revoke it and create a new one. There is no way to look the old one up.

The automation sends the key on each request, either as:

```
Authorization: Bearer osk_live_...
```

or as a header:

```
X-API-Key: osk_live_...
```

Use one or the other. If both are sent, the Authorization header is the one that counts.

## Revoke a key

1. Settings → **Service keys**.
2. Click **Revoke** on that key and confirm.

The next request that uses the key is rejected. You do not need to restart anything. Revoking does not affect staff logins.

To rotate: revoke the old key, create a new one, and update the automation.

## What the key can do

A new key is limited to the automation’s work:

- Read sales orders
- Read inventory and catalog items
- Read purchasing requirements and which sales orders already have a purchase order
- List and validate Draft purchase orders, including the PDF
- Read and edit Draft PO lines (change, add, delete a line, reorder, normalize order)
- Create a Draft purchase order with **send_email set to false** (this does not email the vendor and does not save an Outlook draft)
- Save an unsent Outlook review draft for a Draft PO that already exists
- Read quotes and quote reviews
- List vendor acknowledgements and run the vendor-acknowledgement check

## What the key cannot do

Anything not in the list above is refused. That includes:

- Creating or deleting users, or changing passwords
- Changing settings (pricing, springs, freight, and the rest)
- Approving or rejecting quotes, or creating quotes in Business Central
- Shipping orders, posting invoices, or converting quotes to orders
- Releasing or deleting a Business Central document
- Sending email
- Creating a purchase order that also saves an Outlook draft. That call must set `send_email` to false. Saving a draft is a separate step (`review-draft`) and does not send mail.

A person’s login is unchanged. Staff still sign in with email and password, and that token still expires the way it does today.

## Activity log

Settings → Service keys → **Recent activity** shows each call: the key’s name, the address it called, and the time. Use this to see what the automation did. The log never contains the key itself.

## The “Automation” user

The first time a key is used, the portal adds a user named **Automation** (`automation@keys.opendc.internal`). That row is how the existing staff checks recognize the key. It cannot sign in with a password. Leave it alone. To stop the jobs, revoke the key.

## After this is deployed

You do not run a database command by hand. A normal deploy starts the backend with `alembic upgrade head`, which creates the new tables before the app serves traffic. `scripts/deploy.sh` does not run the migration itself (a second run at the same time can collide). After deploy, create the key in Settings and give it to the automation.
