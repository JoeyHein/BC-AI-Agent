# Staff Draft purchase-order review (Chief of Staff)

Ops / Grok Bot Chief of Staff can inventory unsent Business Central purchase
orders and check buy-complete rules using the existing BC API client
credentials (no interactive BC login). Source of truth is `purchaseOrders`
with `status eq 'Draft'`. The purchasing screen lists those Drafts and
can save an Outlook review draft for one of them; it is not a second
source of truth.

List, validate, and PDF download are **read-only**. They do not release,
email, send, or rewrite a PO. `POST .../review-draft` is the exception: it
saves an **unsent** Outlook message in joey@opendc.ca Drafts (BC PDF
attached, To: the vendor). It does not call sendMail. A human still sends.

After review, the finance email can still be drafted in Outlook from the
JSON; that is separate from the vendor review draft.

Customer-portal routes are unchanged.

## Auth

Staff **admin** JWT — `Authorization: Bearer <access_token>` (same as other
`/api/admin/purchasing/*` routes). Customer tokens are rejected (`403`).

## Endpoints

### List Draft POs with lines

```
GET /api/admin/purchasing/draft-pos
GET /api/admin/purchasing/draft-pos?number=PO-000962
```

| | |
|---|---|
| Success | `200` `{ count, purchase_orders: [...] }` |
| BC failure | `502` |
| Not signed in / not admin | `401` / `403` |

Each PO includes: number, vendor, status, order / posting / requested-receipt
dates, `external_document_number`, `sales_orders` (parsed from the external
doc plus comment/item descriptions), and lines (`item_number`, `description`,
`quantity`, `received_quantity`).

Lookup is always against **production** BC:

1. `purchaseOrders?$filter=status eq 'Draft'&$expand=purchaseOrderLines`
   (`BCClient.get_draft_purchase_orders_with_lines`)
2. Optional `?number=` is a case-insensitive filter on `number` after fetch

### Validate buy-complete rules

```
GET /api/admin/purchasing/draft-pos/validate
GET /api/admin/purchasing/draft-pos/{po_number}/validate
```

| | |
|---|---|
| All Draft POs | `200` `{ count, ok, issue_count, buy_complete_prefixes, companion_keywords, results }` |
| One Draft PO | `200` one result object (`ok`, `issues`, `buy_complete_parents`, …) |
| Missing PO | `404` |
| Exists but not Draft | `422` (already released / sent — do not treat as unsent) |

Rules (same lists as `purchasing_demand_service` / `so_po_generation_service`):

- **Buy-complete prefixes** — buy the finished item, do not explode the BOM:
  `HK`, `PN45-`, `PN46-`, `PN80-`, `TR02-`, `TR03-`, `SP12-`, `GK15-`, `GK16-`, `GK17-`
- **Panel companions** — when any `PN*` line is present, the PO must also
  carry description keywords `ASTRAGAL`, `RETAINER`, and `TOP SEAL` at full
  qty (not netted vs stock). Missing or zero-qty companions are flagged.
- **Exploded leftovers** — if a buy-complete parent is already on the PO,
  leftover-looking components are flagged (e.g. `FH*` with an `HK*` kit,
  `PN40-` cores with `PN45-`/`PN46-`, `TR10-`/`TR11-`/`TR12-` with `TR02-`/`TR03-`,
  `GL12*` / `AL*` with `GK15-17` or `PN80-`).

Issue `code`s: `missing_companion`, `companion_zero_qty`, `exploded_leftover`.

### Download one PO PDF (by number)

```
GET /api/admin/purchasing/draft-pos/{po_number}/pdf
```

| | |
|---|---|
| `{po_number}` | `PO-000962` (any case), bare digits (`962` → `PO-000962`), or the BC purchase-order GUID |
| Success | `200 application/pdf` with `Content-Disposition: attachment; filename="PO-000962.pdf"` |
| Missing PO | `404` |
| Bad identifier | `400` |
| Not signed in / not admin | `401` / `403` |

Lookup is always against **production** BC. Any status is allowed (Draft,
Open, Released) — unlike `/validate`, this is not limited to unsent Drafts:

1. `purchaseOrders?$filter=number eq 'PO-…'` (`BCClient.get_purchase_order_by_number`) — or `purchaseOrders({guid})` when a GUID is passed
2. `purchaseOrders({guid})/pdfDocument` then `mediaReadLink` (`BCClient.get_purchase_order_pdf`)

This download is **read-only**. It does not release, email, send, or rewrite
a PO. There is no bulk-PDF endpoint; CoS should loop this single-PO call (see
curl below). This is BC's built-in `pdfDocument` — the same report
`POST /api/admin/purchasing/generate-po` and
`POST /api/admin/purchasing/draft-pos/{po_number}/review-draft` attach to
the Outlook review draft.

### Outlook review draft for an existing Draft PO

```
POST /api/admin/purchasing/draft-pos/{po_number}/review-draft
```

For a purchase order that is **already** in BC (hand-keyed, auto-po, or an
earlier generate-po that skipped the mailbox). Staff admin JWT. Body is
optional:

```json
{ "notes": "ship dock 2", "cc": ["buyer@opendc.ca"] }
```

`notes` and `cc` match generate-po. Omit them (empty body, or `{}`) when
you only want the standard subject and body.

| | |
|---|---|
| `{po_number}` | `PO-000962` (any case), bare digits (`962` → `PO-000962`), or the BC purchase-order GUID |
| Success | `200` JSON. `review_draft_created: true` when an unsent message is in Drafts. `email_sent` is always `false`. `emailed_to` is always `null`. |
| Draft, no vendor email | `200`. The draft is still saved, with no To address, and `draft_warning` is set. |
| BC PDF fetch fails | `200`. Nothing is saved in Outlook. `pdf_error` and `draft_error` are set. `review_draft_created` is `false`. |
| Graph save fails | `200`. The PO stays in BC unchanged. `draft_error` explains why. `pdf_source` is `bc` when the PDF downloaded. |
| Missing PO | `404` |
| Exists but not Draft | `422` (already released / sent — do not draft a vendor email for it) |
| Bad identifier | `400` |
| BC lookup failure | `502` |
| Not signed in / not admin | `401` / `403` |

What it does, same helpers as generate-po (`purchasing_po_service._save_review_draft`, `graph_client.create_draft_with_attachment`):

1. Resolve the PO (`number eq 'PO-…'` or `purchaseOrders({guid})`). Status must be `Draft`.
2. Download the BC report with `BCClient.get_purchase_order_pdf`. The homemade fpdf2 table is not attached.
3. Look up the vendor email on the BC vendor card (`vendorNumber`).
4. Save an **unsent** Outlook message with Graph createMessage:
   `POST /users/{NOTIFICATION_SENDER_EMAIL}/mailFolders/drafts/messages`.
   In production that mailbox is joey@opendc.ca. To: the BC vendor email.
   Subject `Purchase Order {number} — Open Distribution Company Inc.` and
   the same HTML body as generate-po. Attachment name `PO_{number}.pdf`.

**Not idempotent.** A second POST for the same PO creates another Drafts
message. That is intentional — Joey may want a fresh copy. Nothing is
stored to dedupe, and sendMail is never called. Check Sent after a test;
it should stay empty.

The purchasing screen (`/purchasing`) lists live Draft POs and has an
**Outlook review draft** button per row. It posts this endpoint with an
empty body. The confirm dialog states the message is not sent.

## Example curl

Login (staff portal user). Do not commit real passwords.

```bash
BASE="${PORTAL_BASE_URL:-https://portal.opendc.ca}"

TOKEN=$(curl -fsS -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${STAFF_EMAIL}\",\"password\":\"${STAFF_PASSWORD}\"}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  "$BASE/api/admin/purchasing/draft-pos" | python3 -m json.tool

curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  "$BASE/api/admin/purchasing/draft-pos/validate" | python3 -m json.tool

curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  "$BASE/api/admin/purchasing/draft-pos/PO-000962/validate" | python3 -m json.tool

PO=PO-000962
curl -fsS -o "${PO}.pdf" \
  -H "Authorization: Bearer ${TOKEN}" \
  "$BASE/api/admin/purchasing/draft-pos/${PO}/pdf"

file "${PO}.pdf"   # should report PDF document

# Bulk: no zip endpoint — loop the single-PO PDF call
for PO in PO-000961 PO-000962 PO-000963; do
  curl -fsS -o "${PO}.pdf" \
    -H "Authorization: Bearer ${TOKEN}" \
    "$BASE/api/admin/purchasing/draft-pos/${PO}/pdf"
done
```

If you already have a staff session token (portal `localStorage.authToken`):

```bash
curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  https://portal.opendc.ca/api/admin/purchasing/draft-pos

curl -fsS -o PO-000962.pdf \
  -H "Authorization: Bearer ${TOKEN}" \
  https://portal.opendc.ca/api/admin/purchasing/draft-pos/PO-000962/pdf
```

Review draft for a Draft that already exists. This **writes** an unsent
message in joey@opendc.ca Drafts. It does not send. Replace the PO number
with one you mean to review. A second call creates another draft.

```bash
PO=PO-000962   # a live Draft, not a released PO
curl -fsS -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}' \
  "$BASE/api/admin/purchasing/draft-pos/${PO}/review-draft" | python3 -m json.tool
```

## Verify

1. `GET /api/admin/purchasing/draft-pos` and pick a known Draft (status Draft).
2. `POST /api/admin/purchasing/draft-pos/{that-number}/review-draft` with a staff admin JWT. Or use **Outlook review draft** on `/purchasing`.
3. In joey@opendc.ca Outlook, open **Drafts**. The new message is To the BC vendor email, subject `Purchase Order {number} — Open Distribution Company Inc.`, body the same as a generate-po review draft, and the attachment is the BC purchase-order PDF (same report as `GET .../pdf`).
4. **Sent** does not contain that message. Do not click Send while checking.
5. POST again. A second draft appears in Drafts. Sent is still empty.

## Outlook review draft (`generate-po`)

`POST /api/admin/purchasing/generate-po` creates the Draft PO in BC. It does
**not** email the vendor. There is no send-to-vendor flag.

When `create_review_draft` is true (the default, including the purchasing
screen), the API then:

1. Downloads the BC report with `BCClient.get_purchase_order_pdf` (same
   `pdfDocument` as the GET above). The homemade fpdf2 table is not attached.
2. Saves an **unsent** Outlook message with Graph createMessage:
   `POST /users/{NOTIFICATION_SENDER_EMAIL}/mailFolders/drafts/messages`.
   In production that mailbox is joey@opendc.ca. The draft is pre-addressed
   To: the BC vendor email, with the PO subject/body and the BC PDF attached,
   so a person can open Drafts and hit Send.

| | |
|---|---|
| Default | `create_review_draft` omitted or `true` — save the Outlook draft, do not send |
| PO only | `create_review_draft: false` — no `pdfDocument` call and no Graph. Download the Draft with the GET above and compare it to BC Print. |
| Old flag | `send_email` is a deprecated alias for `create_review_draft`. It does **not** send. `create_review_draft` wins if both are set. |
| BC PDF fetch fails | The PO create still succeeds. Nothing is saved in Outlook. Response includes `pdf_error` and `draft_error` (the purchasing screen shows them). |
| Graph save fails | The PO stays in BC. `draft_error` explains why. `email_sent` is always `false`. |
| Vendor has no email | The draft is still saved, with no To address, and `draft_warning` is set. |

Do not click Send on that draft while checking layout, and do not aim a test
at a real vendor address unless you intend to leave a draft in Drafts.

The same Outlook draft, for a PO that already exists, is
`POST /api/admin/purchasing/draft-pos/{po_number}/review-draft` (above).
generate-po creates the PO; review-draft does not.

## Complete sales order → Draft PO

Staff purchasing can turn one sales order into a complete Upwardor (or other
vendor) Draft PO. Line selection is `build_upwardor_po` in `mode="complete"`
(`so_po_generation_service`). This screen does not reimplement buy-complete,
netting, or the operator/wrapping skip list.

Complete mode copies purchasable SO lines at full quantity, grouped under
the same door-header comments as the sales order. It skips:

- `OP*` — operators, bought direct from the manufacturer
- `WRAP*` — wrapping, done in-house
- non-stock charges already excluded by the service (`FREIGHT`, and the
  rest of `NON_STOCK_ITEMS`)

It does not net against stock and does not explode BOMs.

### Preview (no write)

```
GET /api/admin/purchasing/so-complete-po/preview?so_number=SO-001299
GET /api/admin/purchasing/so-complete-po/preview?so_number=1299&vendor_no=UPW&vendor_name=UPWARDOR
```

| | |
|---|---|
| `so_number` | `SO-001299` (any case) or bare digits (`1299` → `SO-001299`) |
| Vendor | Optional. Defaults `UPW` / `UPWARDOR`. Preview does not create a PO, so the vendor is only echoed. |
| Success | `200` JSON. `dry_run` is true. `bc_po_number` is null. `doors` are the door groups (label + lines with `quantity`). `skipped` lists `OP*` / `WRAP*` with `quantity` and `reason`. `lines` is the flat item list. `item_line_count` is how many Item lines the create would write. |
| Unknown SO | `404` |
| Bad number | `400` |
| BC failure | `502` |
| Not signed in / not admin | `401` / `403` |

Does not call `create_purchase_order` and does not call Graph.

### Create the Draft

```
POST /api/admin/purchasing/so-complete-po
```

```json
{
  "so_number": "SO-001299",
  "vendor_no": "UPW",
  "vendor_name": "UPWARDOR",
  "create_review_draft": false
}
```

| | |
|---|---|
| `create_review_draft` | Optional. Default `true`. `false` creates the BC Draft only: no `pdfDocument` call and no Graph. |
| `notes`, `cc` | Optional. Same Outlook draft extras as generate-po. Ignored when `create_review_draft` is false. |
| PO created | `200`. `created` is true. `bc_po_number` is the new Draft. `email_sent` is always `false`. `emailed_to` is always `null`. |
| Nothing to order | `200`. `created` is false. `note` explains why (operators, wrapping, or service lines only). No PO, no PDF, no Graph. |
| Review draft saved | `200`. `review_draft_created` is true. `review_mailbox` is `NOTIFICATION_SENDER_EMAIL` (production: joey@opendc.ca). `draft_to` is the BC vendor email. |
| Draft, no vendor email | `200`. The draft is still saved, with no To address, and `draft_warning` is set. |
| BC PDF fetch fails | `200`. The PO stays in BC. Nothing is saved in Outlook. `pdf_error` and `draft_error` are set. |
| Graph save fails | `200`. The PO stays in BC. `draft_error` explains why. `pdf_source` is `bc` when the PDF downloaded. |
| Unknown SO | `404` |
| Bad number | `400` |
| BC create failure | `502` |
| Not signed in / not admin | `401` / `403` |

What create does:

1. `build_upwardor_po(so_number, vendor_no, vendor_name, dry_run=False, mode="complete")` — one new BC Draft, door comments, full quantities.
2. When `create_review_draft` is true and a PO number came back: `purchasing_po_service._save_review_draft` (same helper as generate-po and `POST .../draft-pos/{po}/review-draft`). Graph `createMessage` in Drafts. No `sendMail`.

**Not idempotent.** A second POST for the same sales order creates another Draft PO (and, when the flag is true, another Outlook draft). Check Sent after a test; it should stay empty. Do not click Send.

The purchasing screen (`/purchasing`) has a **Complete sales order** card: type or pick an SO, Preview, then Create Draft PO. The checkbox defaults to on and posts `create_review_draft`.

### Verify

Use a staff admin JWT. Do not click Send. Each create writes a real Draft in production BC, so pick an SO you mean to draft (or stop after preview).

1. Preview. `GET /api/admin/purchasing/so-complete-po/preview?so_number=SO-00xxxx`. Confirm `doors` (or flat `lines`), `skipped` contains the `OP*` and `WRAP*` lines with quantities, and `bc_po_number` is null. Business Central has no new PO.
2. Create without a mailbox write. `POST /api/admin/purchasing/so-complete-po` with `"create_review_draft": false`. Confirm `created` is true, `email_sent` is false, and `review_draft_created` is false. The new number is a Draft in BC. joey@opendc.ca Drafts and Sent are unchanged.
3. Create with the review draft. POST again with `"create_review_draft": true` (or omit it — that is the default; it creates a **second** PO). In joey@opendc.ca Outlook, open **Drafts**. The new message is To the BC vendor email, subject `Purchase Order {number} — Open Distribution Company Inc.`, and the attachment is the BC purchase-order PDF. **Sent** does not contain that message.
4. On `/purchasing`, the same three steps are Preview, then Create Draft PO with the checkbox off, then (for a PO you mean to review) with the checkbox on.

```bash
BASE="${PORTAL_BASE_URL:-https://portal.opendc.ca}"
SO=SO-001299   # replace with an order you intend to preview

curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  "$BASE/api/admin/purchasing/so-complete-po/preview?so_number=${SO}" \
  | python3 -m json.tool

# Draft in BC only. No Outlook message.
curl -fsS -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"so_number\":\"${SO}\",\"create_review_draft\":false}" \
  "$BASE/api/admin/purchasing/so-complete-po" | python3 -m json.tool

# Second Draft, plus an unsent Outlook review draft. Do not click Send.
curl -fsS -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"so_number\":\"${SO}\",\"create_review_draft\":true}" \
  "$BASE/api/admin/purchasing/so-complete-po" | python3 -m json.tool
```

## Related (do not use for CoS Draft-PO inventory)

- `GET /api/admin/purchasing/requirements` — demand netted vs stock/open POs; not a Draft-PO list.
- `GET /api/admin/purchasing/so-po-links` — tool-created POs only (`POAgentLog`); misses hand-keyed BC Drafts.
- `POST /api/admin/purchasing/generate-po` / `auto-po/run` — writes Draft POs; not for CoS inventory. `generate-po` can also save an unsent Outlook review draft with the BC PDF. It does not email the vendor. `auto-po/run` drafts in BC and does not email. For a Draft that already exists, use `POST /draft-pos/{po_number}/review-draft` instead of generate-po.
- `GET /api/admin/purchasing/so-complete-po/preview` and `POST /api/admin/purchasing/so-complete-po` — preview or create one complete Draft PO from a sales order (`build_upwardor_po`, mode complete). Preview does not write. POST creates a new Draft and, by default, an unsent Outlook review draft. Not a Draft-PO inventory.
