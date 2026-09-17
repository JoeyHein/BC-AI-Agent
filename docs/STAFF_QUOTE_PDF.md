# Staff BC sales-quote PDF (by SQ number)

Ops / Chief-of-Staff agents can fetch a Business Central sales-quote PDF by
SQ number using the existing BC API client credentials (no interactive BC
login). The bytes are suitable for attaching to Outlook mail as `Quote_SQ-….pdf`.

Customer-portal PDF (`GET /api/customer/portal/bc-quotes/{guid}/pdf`) is
unchanged and still requires a customer JWT plus ownership of that quote.

## Endpoint

```
GET /api/admin/quotes/by-number/{sq_number}/pdf
```

| | |
|---|---|
| Auth | Staff **admin** JWT — `Authorization: Bearer <access_token>` (same as other `/api/admin/quotes` routes). Customer tokens are rejected. |
| `{sq_number}` | `SQ-003132` (any case), bare digits (`3132` → `SQ-003132`), or the BC quote GUID |
| Success | `200 application/pdf` with `Content-Disposition: attachment; filename="Quote_SQ-003132.pdf"` |
| Missing quote | `404` |
| Bad identifier | `400` |
| Not signed in / not admin | `401` / `403` |

Lookup is always against **production** BC:

1. `salesQuotes?$filter=number eq 'SQ-…'` (`BCClient.get_sales_quote_by_number`) — or `salesQuotes({guid})` when a GUID is passed
2. `salesQuotes({guid})/pdfDocument` then `mediaReadLink` (`BCClient.get_quote_pdf`)

This does **not** require a `saved_quote_configs` row. DoorConfigurator
generate-quote stores `bc_quote_id` (GUID) and `bc_quote_number` (`SQ-…`)
on the generate-quote response / quote snapshot; customer drafts additionally
persist both columns. Staff configurator quotes that never became a customer
saved-quote still resolve by SQ number in BC.

## Example curl

Login (staff portal user). Do not commit real passwords.

```bash
BASE="${PORTAL_BASE_URL:-https://portal.opendc.ca}"

TOKEN=$(curl -fsS -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${STAFF_EMAIL}\",\"password\":\"${STAFF_PASSWORD}\"}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

SQ=SQ-003132
curl -fsS -o "Quote_${SQ}.pdf" \
  -H "Authorization: Bearer ${TOKEN}" \
  "$BASE/api/admin/quotes/by-number/${SQ}/pdf"

file "Quote_${SQ}.pdf"   # should report PDF document
```

If you already have a staff session token (portal `localStorage.authToken`):

```bash
curl -fsS -o Quote_SQ-003132.pdf \
  -H "Authorization: Bearer ${TOKEN}" \
  https://portal.opendc.ca/api/admin/quotes/by-number/SQ-003132/pdf
```

## UI

Staff Quotes search (`/quotes`) and Door Configurator (after generate) expose
a **Download PDF** button that hits the same endpoint.

## Related (do not use for CoS SQ quotes)

- `GET /api/quotes/{QuoteRequest.id}/pdf` — integer email-review RFQ id only; `bc_quote_id` on that table is the SQ *number*, not a GUID, and it is not DoorConfigurator.
- `GET /api/customer/portal/bc-quotes/{bc_guid}/pdf` — customer JWT + must own the quote.
