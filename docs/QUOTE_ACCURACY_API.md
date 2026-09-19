# Internal Quote Accuracy API

Read-only lookup of a production Business Central sales quote (header + lines) for post-quote accuracy checks against portal/AI drafts.

This is the path Joey chose instead of browser sign-in or pasted exports. It is **not** the supplier `X-Service-AI-Key` surface (`/api/external/*`) and **not** the JWT admin quote-review UI.

## Endpoint

```
GET /api/internal/sales-quotes/{quote_number}
```

Production base URL: `https://portal.opendc.ca`

| Item | Value |
| --- | --- |
| Auth | Header `X-API-Key: <QUOTE_ACCURACY_API_KEY>` |
| Quote number | `SQ-003058`, `sq-3058`, or `3058` (normalized to `SQ-######`) |
| Query | `line_skip` (default `0`), `line_limit` (default `200`, max `500`) |
| Reads | BC company from server env (`BC_COMPANY_ID`). Callers cannot pass a company id. |
| Writes | None. No create, update, approve, convert, or send. |

### Success (`200`)

```json
{
  "ok": true,
  "data": {
    "quote": {
      "id": "<bc-guid>",
      "number": "SQ-003058",
      "status": "Draft",
      "customerNumber": "C000123",
      "customerName": "Example Ltd",
      "documentDate": "2026-05-01",
      "validUntilDate": "2026-06-01",
      "discountAmount": 0,
      "totalAmountExcludingTax": 1234.56,
      "totalTaxAmount": 61.73,
      "totalAmountIncludingTax": 1296.29
    },
    "lines": [
      {
        "sequence": 10000,
        "lineType": "Comment",
        "itemNumber": "",
        "description": "(1) 10x9 TX450, WHITE, UDC, 2\" HW, STD LIFT",
        "quantity": 0,
        "unitPrice": 0,
        "flags": ["comment"]
      },
      {
        "sequence": 20000,
        "lineType": "Item",
        "itemNumber": "PN45-24400-1000",
        "lineObjectNumber": "PN45-24400-1000",
        "description": "TX450 24\" WHITE",
        "quantity": 4,
        "unitPrice": 120.00,
        "discountPercent": 0,
        "discountAmount": 0,
        "amountExcludingTax": 480.00,
        "taxCode": "GST",
        "taxPercent": 5,
        "totalTaxAmount": 24.00,
        "amountIncludingTax": 504.00,
        "dimensionSetLines": [
          { "code": "AREA", "valueCode": "AB", "displayName": "Area", "valueDisplayName": "Alberta" }
        ],
        "flags": ["tax"]
      }
    ],
    "lineCount": 42,
    "lineSkip": 0,
    "lineLimit": 200,
    "hasMore": false
  }
}
```

Comment lines carry door dimensions/options in `description` / `description2`. Freight usually appears as an item line (`flags` includes `freight`). Tax is on the header (`totalTaxAmount`) and per line when BC populates tax fields. `dimensionSetLines` is included when BC returns them; the server falls back to lines-only if `$expand` is unsupported.

To page remaining lines: repeat the same GET with `line_skip=<previous lineSkip + lineLimit>` while `hasMore` is true. The server follows BC `@odata.nextLink` before slicing the page.

### Errors

| HTTP | `error.code` | When |
| --- | --- | --- |
| 401 | — | Missing or wrong `X-API-Key` (same message either way) |
| 400 | `INVALID_REQUEST` | Quote number is not `SQ-` + digits |
| 404 | `NOT_FOUND` | No quote with that document number in the configured BC company |
| 422 | — | `line_skip` / `line_limit` outside allowed range |
| 502 | `UPSTREAM_ERROR` | Business Central lookup failed (`retryable: true`) |
| 503 | — | `QUOTE_ACCURACY_API_KEY` is not set on the server |

Trace header: send `X-Request-ID`; it is echoed on the response.

Audit: application logs record quote number, HTTP status, line counts, and request id. The existing call-log table stores method, path, status, latency, and the **first 12 characters** of the API key. The full key, customer email/phone, and line payloads are not written to the audit log.

## After merge / deploy (Joey)

Do **not** commit the key. The GitHub Actions deploy does not mint it.

1. Generate a key:
   ```bash
   python3 -c "import secrets; print('qak_' + secrets.token_urlsafe(32))"
   ```
2. SSH to the production droplet and add this line to `/opt/bc-ai-agent/.env` (or the env file compose already uses):
   ```
   QUOTE_ACCURACY_API_KEY=qak_REPLACE_ME
   ```
3. Recreate the backend so it picks up the env var:
   ```bash
   ssh root@159.203.3.173 "cd /opt/bc-ai-agent && docker compose up -d --force-recreate backend"
   ```
4. Confirm unset vs set: a request without a key returns **503** before the env is present, **401** after.

No BC credential changes. The portal already uses production `BC_TENANT_ID` / `BC_CLIENT_ID` / `BC_CLIENT_SECRET` / `BC_COMPANY_ID`. Do not mint or rotate supplier `X-Service-AI-Key` rows for this.

## Sample curl (placeholders)

```bash
curl -sS -H "X-API-Key: $QUOTE_ACCURACY_API_KEY" \
  -H "X-Request-ID: qa-$(date +%s)" \
  "https://portal.opendc.ca/api/internal/sales-quotes/SQ-003058"
```

Next page:

```bash
curl -sS -H "X-API-Key: $QUOTE_ACCURACY_API_KEY" \
  "https://portal.opendc.ca/api/internal/sales-quotes/SQ-003058?line_skip=200&line_limit=200"
```

Local:

```bash
curl -sS -H "X-API-Key: $QUOTE_ACCURACY_API_KEY" \
  "http://localhost:8000/api/internal/sales-quotes/3058"
```

Cursor can call the same URL with the `X-API-Key` header; do not paste production keys into chats or commit them.
