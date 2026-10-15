# Production schedule — SO, PO, and Upwardor ack

`OPENDC_Production_Schedule.xlsx` is still written by the scheduled job (`production_schedule_service.build_and_deliver`, scheduler `_production_schedule_job`). Each rebuild reads the current file back by **header name**, then overwrites it. A column that is not a known header is wiped. Pull from stock is a known header, so a hand-set Yes survives.

This does not download Upwardor's open-order email and it does not write to Business Central.

## Schedule columns

Schedule columns through Shipping Status are the box-in/box-out set, plus **In-house Build** (added 2026-10-08, between Emergency Build and Shipping Status). Fulfillment's dropdown is Buy Complete, Partial Build, Emergency Build. Read-back is by header name, so a file from before In-house Build still loads. On that older file, Buy Complete is the untouched default and an aluminum sales order is set to Partial Build. After the column exists, a Buy Complete a person left in place is kept. Emergency Build is always kept. The SO-PO Log sheet is not rebuilt from scratch.

**Partial Build** means the order has an aluminum section OpenDC builds in-house (Panorama `PN80`, V130G `PN10`, V230G `PN12`, AL976 `PN97`, Solalite `PN20`, AL-SWD `PN70`). Order Status still follows the Upwardor PO for the bought half. In-house Build starts at Not Started and uses the same list as Emergency Build (Not Started / In Production / Complete). The matching rule is `is_inhouse_aluminum_line` in `backend/app/services/production_schedule_service.py`.

| Column | Who fills it | What it means |
|---|---|---|
| Upwardor Ack # (S-ORD) | Rebuild, from `vendor_order_acks` | Acknowledgement numbers for the POs in Upwardor PO #. A split (`PO-000960(2)`) stays labeled and does not replace the primary number. |
| Upwardor Status | Rebuild | Confirmed / Revised / Cancelled from the ack. `Not acknowledged` when a PO has no ack number. `No Upwardor PO, no ack` when the SO still needs an Upwardor buy and has neither. |
| Recon Flag | Formula | `RED`, `MISSED`, `CHECK`, `OK`, or `OK - pull from stock` when Pull from stock is Yes. |
| Recon Note | Rebuild | `NOT ACKNOWLEDGED by Upwardor` or `MISSED, no PO, no ack`. |
| Pull from stock | Person, dropdown | `Yes` or blank. |

Operator-only and wrap-only sales orders are not flagged. Those lines are not bought from Upwardor.

## Flags and formatting

Evaluated on each open sales order, after Pull from stock is read back:

- **RED** — Upwardor PO # is filled and at least one of those POs has no ack number. The whole row is red fill `FFC7CE` and red bold text `9C0006`. The same PO is filled red on the Purchase Orders sheet.
- **MISSED** — the SO needs an Upwardor purchase, and it has no PO and no ack. Note is exactly `MISSED, no PO, no ack`. The row is orange fill `F8CBAD` with bold italic text `833C0B`.
- **CHECK** — an ack exists but it was cancelled, or an optional Upwardor open-order export does not list that S-ORD. Amber on the flag cell.
- **OK** — every PO on the row has an acknowledgement.
- **Pull from stock = Yes** — the formula shows `OK - pull from stock` and the red / orange row rules do not apply. The SO needs no PO and no ack. The note still describes the underlying gap, so Yes is an override a person can see. Clearing Yes shows the underlying flag again; the next rebuild reads the cell back, so the Yes is still there after the job runs.

The row rules are first in the conditional-format list, so they win over the existing Order Status / Shipping Status colors. Those column rules are unchanged.

## Upwardor Reconciliation sheet

Always written. Read-only (the job replaces it).

Without an export, it lists:

- every PO already shown in Upwardor PO # for an open SO
- stock POs that reference no sales order, when the vendor name contains `UPWARDOR` or is `UPW` (or the vendor name is blank)

Each row is RED when there is no ack number. A LiftMaster (or other non-Upwardor) stock PO is not listed.

With an export, pass the parsed rows as `upwardor_open_orders` on `build_workbook_bytes` (or on the dict `_build` reads). `parse_upwardor_open_order_export` reads Upwardor's workbook:

| Export column | Used for |
|---|---|
| Sales Order No. | S-ORD |
| Part No. / Description | kept on the parsed row for a later part-level diff |
| Qty. Ordered, remaining Qty, Qty. to Manufacture | section totals where Bulk = `SEC` |
| Bulk | `SEC` vs anything else |
| Customer Name | shown when we have no SO customer |

Matching is S-ORD → PO through the vendor acknowledgement. The export has no PO column. Results:

- **Matched** — ack links the S-ORD to an open PO
- **Matched - qty mismatch** — `PN*` quantity on that PO differs from Upwardor's SEC quantity
- **No OpenDC PO** — no acknowledgement links the S-ORD to a PO
- **Mismatch - closed/cancelled in BC** — the ack names a PO that is not open on an open sales order

POs whose S-ORD is missing from the export are CHECK (`Not on the Upwardor open-order list`). Part-suffix and glass-kit differences are not compared yet; the parsed `lines` are the place to add that.

Email ingest of the export is not implemented. A later job should parse the attachment and pass the rows in. Do not treat a parse error as an empty list — an empty list means Upwardor sent a real file with no open orders, and acknowledged POs would all be flagged CHECK.

## Verify without writing SharePoint or BC

Unit tests mock Graph and Business Central. They do not upload the workbook and they do not patch a purchase order.

```bash
cd backend && python -m pytest \
  tests/test_production_schedule_recon.py \
  tests/test_production_schedule_box_model.py \
  tests/test_production_schedule_po_log.py \
  tests/test_production_schedule_assignments.py \
  tests/test_vendor_ack_intake.py \
  -v --tb=short
```

What those tests cover:

- Existing schedule and Purchase Orders headers and dropdowns are still there.
- A PO with no ack is RED, on the schedule row and on the Purchase Orders sheet.
- An open SO that needs Upwardor goods, with no PO and no ack, is MISSED with the note `MISSED, no PO, no ack`.
- Pull from stock = Yes is read back by header name (even if the column is not in the usual position), is not counted as MISSED, and the flag formula's else-branch is still MISSED so clearing Yes shows it again.
- An archived SO's flag formula is rewritten for the archived row, not left pointing at the old schedule row.
- `build_and_deliver` downloads the configured path, merges Pull from stock, and uploads that same path. The test stubs download/upload and fails if a live Graph token or BC order call is made.
- The export parser groups S-ORDs, counts only `SEC` lines, and rejects a workbook that is not the export.
- The reconciliation sheet lists an unacknowledged stock PO and omits a non-Upwardor stock PO. With a parsed export it reports a section-qty mismatch and an S-ORD with no PO.

Do **not** use `generate_production_schedule.py --sharepoint` or call `build_and_deliver` against the production drive to preview this. Both overwrite `Production Schedule/OPENDC_Production_Schedule.xlsx`. `--local` still reads Business Central; it only avoids the SharePoint upload.

After review and deploy, the safe live check is: on a downloaded copy, set Pull from stock = Yes on one MISSED row, let the 04:30 / 12:30 / 16:30 job run, and confirm that Yes is still there and the row is not orange. Confirm a PO with no `vendor_order_acks` row is red. Leave `VENDOR_ACK_INTAKE_ENABLED` and `VENDOR_ACK_DRY_RUN` as they are for ack intake — this schedule change does not turn them on and does not write Vendor Order No.
