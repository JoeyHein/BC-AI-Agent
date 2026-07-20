# Picking API pages — BC extension handoff

Read-only AL API pages exposing the Digital Picking time-and-motion data so the
OPENDC portal (and later, scheduling/task tooling) can read it.

**These files are not deployed yet.** They need to be merged into
`Upwardor/Upwardor_BC_Repos` and shipped by whoever builds that extension
(Probiztech / Dickson / Sourav). We have read-only access to that repo, which is
why the source is staged here.

## Why this exists

The picking extension had **zero external read path**. No API pages, no
published web services. The three existing `Query` objects are
`UsageCategory = ReportsAndAnalysis` (in-client only) and cover inventory and
sales orders — nothing from the picking or activity tables.

So who picked what, how long it took, and why they paused was trapped inside the
BC web client.

## What's here

| Object | Entity set | Purpose |
|---|---|---|
| page 70134 | `activityTimeLogs` | Labour minutes per employee, pause-adjusted |
| page 70135 | `activityPauseLogs` | Downtime with reason codes |
| page 70136 | `pickingQueue` | Live queue state |
| page 70137 | `pickerSessions` | Who is signed in now |
| page 70138 | `postedPickingSessions` | Durable throughput history |
| page 70139 | `postedPickingHeaders` | Per-order archive |
| page 70140 | `postedPickingLines` | Per-line picker/loader attribution |
| permissionset 70102 | `Picking API Read` | R/X only, for the integration account |

All pages are read-only (`Editable/Insert/Modify/Delete = false`,
`DataAccessIntent = ReadOnly`). Object IDs 70134–70140 were free at time of
writing (70109–70133 were in use); **re-check before merging** in case the
extension has moved on.

Base URL: `.../api/upwardor/picking/v1.0` — note this is *not* `api/v2.0`.

## Not yet verified

**The AL has not been compiled.** No AL toolchain was available where it was
written, and it has not been built against the Probiztech base extension
(`businesscentral-repos_Upwardor`). Treat it as a reviewed draft, not
production-ready — it needs a build before merge.

## Deliberate omissions

- **`Posted Picking Header` fields 11–14** (`Picking Start/End/Duration/Pause`)
  are `ObsoleteState = Pending` — that timing moved to `Posted Picking Session`.
  Not exposed.
- **`Posted Picking Line`**: `Qty. Shipped`, `Discrepancy`, `Order Comments` are
  never populated by `ArchiveAndCleanup`. Exposing them would ship permanent
  zeros that look like real data.
- **`Picker Session`**: `User Security ID` and `Session ID` are internal.

## Consumer gotchas

- `activityTimeLogs.elapsedMinutes` is computed live for Active/Paused rows only
  (`Net Duration Minutes` isn't stamped until `CompleteActivity`). Completed rows
  return the stored value, which avoids an N+1 pause-log scan per row.
- `postedPickingSessions.pickingDurationMinutes` is **labour-minutes** summed
  across pickers, not wall-clock. Wall-clock is `pickingEnd - pickingStart`.
  Two pickers × 30 min reads as 60. This is the easiest thing here to get wrong.
- `sourceNo` / `sourceLineNo` are exposed but the AL call sites currently write
  `''` / `0`, so timing attributes to a **customer batch**, not a sales order or
  line. Per-order cycle time is not derivable today.
- Managers and admins **log no time at all** — activities only start when
  `SessionEntryNo <> 0`, and manager sign-ins get `0`. Labour totals exclude
  supervisors by design.
- Loading creates **one activity row per customer** regardless of crew size, so
  loading minutes can't be split between loaders.

## Consumed by

- `backend/app/integrations/bc/client.py` — `get_activity_time_logs()`,
  `get_posted_picking_sessions()`, etc. Returns `[]` and logs a clear warning on
  404 rather than raising, so the portal degrades gracefully until deploy.
- `backend/app/services/picking_activity_service.py` — aggregation into
  per-employee labour, downtime by reason, throughput, live floor state.
- `backend/tests/test_picking_activity_service.py` — 11 tests, all mocked.

Once deployed, `picking_activity_service` starts returning `available: True`
with no code change needed on our side.
