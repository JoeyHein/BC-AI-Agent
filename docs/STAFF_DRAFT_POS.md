# Staff Draft purchase-order review (Chief of Staff)

Ops / Grok Bot Chief of Staff can inventory unsent Business Central purchase
orders and check buy-complete rules using the existing BC API client
credentials (no interactive BC login). Source of truth is `purchaseOrders`
with `status eq 'Draft'` — the portal `/purchasing` UI does not list live
Draft POs.

These endpoints are **read-only**. They do not release, email, send, or
rewrite a PO. After review, draft the finance email in Outlook from the
JSON; a human still sends the PO from BC.

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

This is **read-only**. It does not release, email, send, or rewrite a PO.
There is no bulk-PDF endpoint; CoS should loop this single-PO call (see
curl below). This is BC's built-in `pdfDocument`, not the portal-rendered
fpdf2 attachment from `POST /api/admin/purchasing/generate-po`.

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

## Related (do not use for CoS Draft-PO inventory)

- `GET /api/admin/purchasing/requirements` — demand netted vs stock/open POs; not a Draft-PO list.
- `GET /api/admin/purchasing/so-po-links` — tool-created POs only (`POAgentLog`); misses hand-keyed BC Drafts.
- `POST /api/admin/purchasing/generate-po` / `auto-po/run` — writes Draft POs; not for review. The PDF it emails is a portal fpdf2 render, not BC `pdfDocument`.
