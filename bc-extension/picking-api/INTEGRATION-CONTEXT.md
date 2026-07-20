# Picking / Activity integration — developer context

Everything needed to work on the picking API and the per-order timing question.
Written against `Upwardor/Upwardor_BC_Repos` @ `b5f1ec1` (last upstream commit
2026-04-16), extension `Upwardor_repos` v1.0.0.49.

---

## 1. The `Source No.` question — what it should point at

`Activity Time Log` field 4 `"Source No."` (Code[20]) and field 5
`"Source Line No."` (Integer) have **no `TableRelation` at all**. Verified —
there is not a single `TableRelation` property anywhere in
`ActivityTimeLog.Table.al`.

They are a **discriminated union keyed by field 3 `"Source Type"`**:

```al
field(3; "Source Type"; Option)
{
    OptionMembers = "Sales Order","Production Order","Transfer Order",Other;
}
```

So the target table depends on the discriminant:

| `Source Type` | Ordinal | `Source No.` → | `Source Line No.` → |
|---|---|---|---|
| Sales Order | 0 | `Sales Header."No."` where `Document Type = Order` | `Sales Line."Line No."` |
| Production Order | 1 | `Production Order."No."` | `Prod. Order Line."Line No."` |
| Transfer Order | 2 | `Transfer Header."No."` | `Transfer Line."Line No."` |
| Other | 3 | *(free / unconstrained)* | *(free)* |

### Making that explicit in AL

A single `TableRelation` can't express this; the idiomatic BC form is a
conditional relation:

```al
field(4; "Source No."; Code[20])
{
    Caption = 'Source No.';
    TableRelation =
        if ("Source Type" = const("Sales Order")) "Sales Header"."No."
            where("Document Type" = const(Order))
        else if ("Source Type" = const("Production Order")) "Production Order"."No."
        else if ("Source Type" = const("Transfer Order")) "Transfer Header"."No.";
    DataClassification = CustomerContent;
}
```

### Worth knowing before committing to the Option

Standard BC models this same problem differently. `Warehouse Activity Line`,
`Reservation Entry` and friends store `"Source Type"` as an **Integer holding
the table ID** (36 = Sales Header, 5405 = Prod. Order Line, …) plus a
`"Source Subtype"` for document type. That extends to any new source without
touching the enum.

Two viable directions:

- **Keep the Option, add the conditional `TableRelation`.** Smaller change, no
  data migration. Fine if Sales/Production/Transfer really is the whole universe.
- **Move to the BC table-ID convention.** More extensible, matches how BC devs
  expect to read it. But existing rows already store `0` and `3`, so it needs an
  upgrade codeunit — `0` would have to become `36`, and `3` becomes ambiguous.

Recommendation: keep the Option. The extra generality isn't worth a data
migration on a live system unless there's a concrete fourth source type coming.

### An existing semantic bug to fix either way

Loading is logged as `Source Type = 3` ("Other"):

```al
// DigitalPickingList.Page.al:312
ActivityTimeMgmt.StartActivityWithEmployee(
    'LOADING', 3, '', 0, Rec."No.", LoaderNo, CopyStr(LoaderName, 1, 100));
```

Loading is work against **Sales Orders**, not "Other". `Activity Type` already
distinguishes `'PICKING'` from `'LOADING'`, so `Source Type` should be `0` for
both. As written, any future query filtering `Source Type = Sales Order` will
silently miss all loading work.

---

## 2. Why per-order timing was abandoned — and why it's now easy

The obsoleted fields on `Posted Picking Header` (11–14: `Picking Start`,
`Picking End`, `Picking Duration (Min.)`, `Picking Pause (Min.)`) are marked:

```al
ObsoleteState = Pending;
ObsoleteReason = 'Moved to Posted Picking Session table (70109)';
```

**The structural reason:** a `Picker Session` covers a **customer batch** that
spans multiple Sales Orders. The picking screen (page 70110) is a `Sales Line`
list filtered by `"Sell-to Customer No."` — the picker walks the shelves and
picks lines from several orders interleaved. There is no moment where the
system can say "this picker is now working order SO-1234" for a contiguous
stretch of time. So per-order *duration* genuinely isn't well-defined at the
activity level. Abandoning it was a reasonable call.

**But the order context is not missing — it's discarded.** At the moment of a
pick, `Rec` on the picking screen *is* the Sales Line:

```al
// DigitalPickingCard.Page.al:716 (UpsertPickingEntry)
if not PickingEntry.Get(Rec."Document No.", Rec."Line No.") then begin
    PickingEntry."Sales Order No." := Rec."Document No.";
    PickingEntry."Sales Line No."  := Rec."Line No.";
```

The order number and line number are right there and already used as the key.
What is *not* recorded is **when**. `Picking Entry` has no timestamp field of
any kind (fields 1–15, verified — no DateTime, Date or Time field).

### Three options for per-order timing

**(a) One activity per order,** started/stopped on order transitions detected in
the `QtyPicked` `OnValidate` hook. Feasible — `Source No.` and `Source Line No.`
are free real estate (always `''`/`0` today), so **no schema change is strictly
required**. Costs: every customer-wide status loop and
`CompleteAllPickingActivities` (`DigitalPickingCard.Page.al:864-876`) has to
close N activities instead of one. Two real caveats:

- Time before the *first* keystroke on a new order lands on the previous order —
  walking time is misattributed, not lost.
- Row count multiplies by orders-per-batch. The hot query pattern everywhere is
  `SetRange("Activity Type"); SetRange("Customer No."); SetFilter(Status, …)`,
  which matches only the first two columns of key `ActivityLookup`. Add a key
  leading `"Activity Type", "Customer No.", "Source No.", "Status"` or these
  unfiltered `FindSet` loops degrade.

**(b) Stamp per-line pick times.** Add `"Picked At"; DateTime` to
`Picking Entry`, set it in the same `QtyPicked` `OnValidate` trigger
(`DigitalPickingCard.Page.al:129`) which *already* writes `Qty. Picked` and the
picker name. Carry it through `ArchiveAndCleanup` onto `Posted Picking Line`.

Per-order duration then becomes derivable (first → last line stamp for that
order), lines-per-hour becomes real, and the batch activity model is untouched.
**Recommended** — one trigger line plus one field on each of two tables, and it
records a measured fact rather than restructuring the timing model. It also
composes with (a) later rather than blocking it.

**(c) Infer from `Posted Picking Line` counts — NOT VIABLE.** Worth stating
plainly because it looks like the cheap option: `Posted Picking Line` carries
`Qty. Picked` and `Picker Name` but **no timestamps at all** (see the field copy
loop at `DigitalPickingList.Page.al:798-825`). All you could do is pro-rate
batch minutes by line count. That is an allocation, not a measurement, and it
would look like real per-order data downstream.

### If you do (b), also fix the call sites

With `Source No.` populated the activity log becomes genuinely per-document.
The two start call sites are the only ones that need changing:

| File:line | Call |
|---|---|
| `DigitalPickingList.Page.al:191` | `StartActivity('PICKING', 0, '', 0, Rec."No.", SessionEntryNo)` |
| `DigitalPickingList.Page.al:312` | `StartActivityWithEmployee('LOADING', 3, '', 0, Rec."No.", LoaderNo, …)` |

In both, `Rec."No."` is the **Customer** number (the page's source table is
`Customer`), passed as the `CustomerNo` parameter — args 3 and 4 are the
hardcoded `''` / `0`.

Note these are the *batch* activities, so a single `Source No.` can't represent
a multi-order batch. Populating them is only meaningful under option (a), where
activities are split per order. Under option (b): **leave `Source No.` blank for
batch-level PICKING / LOADING rows** and reserve it for future non-picking
activity types (production, install, service) where one activity really does map
to one document.

### Don't use `"Current Order No."` for this

`Dashboard Picker Card."Current Order No."` looks like it answers "which order is
this picker on". It does not. `GetCurrentOrderForCustomer`
(`DashboardDataBuilder.Codeunit.al:500-515`) is a `FindFirst()` on key
`("Customer No.","Sales Order No.")` filtered to `Status::"In Progress"` — and
since `StartPicking` flips *every* order for the customer to `In Progress` in one
loop, all N orders qualify. It returns the **alphabetically-lowest order number
in the batch** and never changes during a session. The fallback at `:511-513`
drops the status filter entirely. It is a batch display label, not picker
location, and is not usable as a timing input.

---

## 3. Complete list of activity call sites

Every use of `Codeunit "Activity Time Management"` in the extension:

| File:line | Call |
|---|---|
| `DigitalPickingList.Page.al:191` | `StartActivity('PICKING', 0, '', 0, Rec."No.", SessionEntryNo)` |
| `DigitalPickingList.Page.al:312` | `StartActivityWithEmployee('LOADING', 3, '', 0, Rec."No.", LoaderNo, LoaderName)` |
| `DigitalPickingCard.Page.al:331` | `PauseActivity(ActivityEntryNo, PauseDialog.GetReason())` |
| `DigitalPickingCard.Page.al:361` | `ResumeActivity(ActivityEntryNo)` |
| `DigitalPickingCard.Page.al:874` | `CompleteActivity(ActivityTimeLog."Entry No.")` |
| `DigitalPickingCard.Page.al:932` | `CalcElapsedMinutes(...)` |
| `LoadingScreen.Page.al:147` | `PauseActivity(ActivityEntryNo, PauseDialog.GetReason())` |
| `LoadingScreen.Page.al:177` | `ResumeActivity(ActivityEntryNo)` |
| `LoadingScreen.Page.al:383` | `CompleteActivity(ActivityTimeLog."Entry No.")` |
| `LoadingScreen.Page.al:339` | `CalcElapsedMinutes(...)` |
| `DashboardDataBuilder.Codeunit.al:65` | `CalcElapsedMinutes(...)` |
| `src/API/ActivityTimeLog.API.al:137` | `CalcNetDuration(Rec)` *(new)* |

Only **two** start sites exist. `'PICKING'` and `'LOADING'` are the only
`Activity Type` values ever written, and `0` / `3` the only `Source Type`s.

### Codeunit 70107 public surface

```al
StartActivity(ActivityType: Code[20]; SourceType: Option; SourceNo: Code[20];
              SourceLineNo: Integer; CustomerNo: Code[20];
              PickerSessionEntryNo: Integer): Integer
StartActivityWithEmployee(ActivityType; SourceType; SourceNo; SourceLineNo;
              CustomerNo; EmployeeNo: Code[20]; EmployeeName: Text[100]): Integer
PauseActivity(ActivityEntryNo: Integer; Reason: Option)
ResumeActivity(ActivityEntryNo: Integer)
CompleteActivity(ActivityEntryNo: Integer)
CalcNetDuration(ActivityTimeLog: Record "Activity Time Log"): Decimal
CalcElapsedMinutes(ActivityEntryNo: Integer): Decimal
```

Time maths: durations are millisecond `DateTime` subtraction `/ 60000`.
`CalcNetDuration` = `(End - Start)/60000 - "Total Pause Minutes"`, substituting
`CurrentDateTime` when `End` is `0DT`, so it doubles as live elapsed. An open
pause is counted in real time.

---

## 4. Behaviour that constrains any reporting built on this

- **Managers and admins log no time.** PICKING starts only when
  `(not IsResuming) and (SessionEntryNo <> 0)`; manager sign-ins get `0`.
  Deliberate — it stops supervisors corrupting picker timers — but every labour
  total silently excludes them.
- **Loading is one row per customer**, guarded by an `IsEmpty()` check, so
  loading minutes can't be split across a crew.
- **`Picking Duration (Min.)` is labour-minutes**, summed across pickers.
  Wall-clock is `Picking End - Picking Start`. Two pickers × 30 min reads as 60.
- **Archive identity is a name string.** `Posted Picking Session."Pickers"` and
  `Posted Picking Line."Picker Name"` are `Text[250]` / `Text[100]` names, not
  `Employee No.` Joining to Employee is string matching, and the dedupe helper
  matches by `StrPos` substring — "Jo Smith" inside "Jo Smithers" is dropped.
  Only `Activity Time Log` carries a real `Employee No.`
- **Picker identity is unauthenticated free text** — a space-separated employee
  number string on page 70114, validated only against `Employee.Get()`. Anyone
  can type anyone's number. Fine for a warehouse floor; not fine as the identity
  layer for company-wide task assignment or anything payroll-adjacent.

---

## 5. Known defects (live in production)

| Where | Defect |
|---|---|
| `ArchiveAndCleanup` | `Posted Picking Header."Entry No."` assigned via `FindLast()+1` — race under concurrent posting. Should be `AutoIncrement`. |
| `Picking Archive Manager.LoadPickingQty` | Hard-gates on `Status = "Picking Completed"`. Simultaneous-load orders land in `Loaded` and **fail the action entirely**. |
| `ArchiveAndCleanup` | Shipment link matched on `Order No.` + `Posting Date = Today` — archive on a different day than posting and the link is lost. |
| `Posted Picking Line` | `Qty. Shipped`, `Discrepancy`, `Has Discrepancy` never assigned — permanently 0. |
| `Pause Reason Dialog` | `GetNotes()` is never called; pause notes are collected then discarded. |
| `BuildAlerts` | Scans open pauses with no index on `Pause End`, every 5 s per open dashboard. |
| `Dashboard Week Day` | `Pending Count` reads `Picking Selection`, deleted on post → structurally always 0 for past days. Not a valid historical series. |
| Alert thresholds | 40 / 90 / 30 minutes hardcoded, no setup table. |

---

## 6. Third-party coupling (Probiztech base extension)

Dependency: `businesscentral-repos_Upwardor` v1.0.0.165, publisher
*Probiztech Consultants Inc.*, id `42e09f83-1c26-49c5-b451-c939502e39da`.

Objects accessed by **raw numeric ID** via `RecordRef`/`FieldRef` — these break
silently if renumbered upstream:

| Reference | Used for |
|---|---|
| Table **60007** field **50013** | "Delivery Status" — set to 2 (Order Staged) on finish, restored on reopen |
| `Sales Line` field **50032** | Output Shelf No., written with `Modify(false)` |
| `Sales Line."Line No. 2"` | Copied to `Picking Entry."Line No. 2"`; source comments flag it as unverified |
| `Sales Header."Requested Delivery Date 1".."5"` | Ship date written to first empty slot |
| `Sales Header."External Customer"` | US customer name from Upwardor International |
| `Sales Header."NCR No."` | Exposed in query 70100 |

Delivery Status mapping (`DigitalPickingCard.DeliveryStatusToInt`):
`Not Ready`=0, `Ready to Pick`=1, `Order Staged`=2, `Order Shipped`=3,
`Order Invoiced`=4.

---

## 7. Repo facts

- **Access:** we have **read-only** access to `Upwardor/Upwardor_BC_Repos`.
  Pushes 403. Any AL change has to go through whoever owns write access.
- **Contributors:** Dickson Paniyadima, Sourav Patteri (+ Probiztech).
- **Activity:** 22 commits, Nov 2025 → Apr 2026. Stale since 2026-04-16.
- **No CI, no tests, no `.github/`.** `.gitignore` excludes `*.md`, which is why
  the repo has no documentation of any kind.
- **~7,300 lines of AL across 65 files.** `app.json`: runtime 15.0, target
  Cloud, platform 1.0.0.0, application 26.4.0.0, idRange 70100–79999.

---

## 8. Complete object inventory

68 objects across 69 AL files. Includes the 5 new files in `src/API/`.

### Tables (15)

| ID | Name | File |
|---|---|---|
| 70100 | `"Picking Entry"` | `src/Digital Picking/PickingEntry.Table.al` |
| 70101 | `"Picking Selection"` | `src/Digital Picking/PickingSelection.Table.al` |
| 70102 | `"Picking Line Selection"` | `src/Digital Picking/PickingLineSelection.Table.al` |
| 70103 | `"Posted Picking Header"` | `src/Digital Picking/Posted Picking/PostedPickingHeader.Table.al` |
| 70104 | `"Posted Picking Line"` | `src/Digital Picking/Posted Picking/PostedPickingLine.Table.al` |
| 70105 | `"Activity Time Log"` | `src/Digital Picking/Activity Tracker/ActivityTimeLog.Table.al` |
| 70106 | `"Activity Pause Log"` | `src/Digital Picking/Activity Tracker/ActivityPauseLog.Table.al` |
| 70107 | `"Loading Entry"` | `src/Digital Picking/LoadingEntry.Table.al` |
| 70108 | `"Picker Session"` | `src/Digital Picking/PickerSession.Table.al` |
| 70109 | `"Posted Picking Session"` | `src/Digital Picking/Posted Picking/PostedPickingSession.Table.al` |
| 70110 | `"Dashboard Picker Card"` | `src/Dashboard/DashboardPickerCard.Table.al` |
| 70111 | `"Dashboard Queue Item"` | `src/Dashboard/DashboardQueueItem.Table.al` |
| 70112 | `"Dashboard Alert"` | `src/Dashboard/DashboardAlert.Table.al` |
| 70113 | `"Dashboard Completed Item"` | `src/Dashboard/DashboardCompletedItem.Table.al` |
| 70114 | `"Dashboard Week Day"` | `src/Dashboard/DashboardWeekDay.Table.al` |

70110-70114 are **temporary** tables used only as dashboard transport.

### Pages (29)

| ID | Name |
|---|---|
| 70109 | `"Digital Picking List"` |
| 70110 | `"Digital Picking Screen"` - file is `DigitalPickingCard.Page.al` |
| 70111 | `"Digital Picking Subform"` |
| 70112 | `"Picking Order Selection"` |
| 70113 | `"Picking Line Subform"` |
| 70114 | `"Picker Sign In"` |
| 70115 | `"Posted Picking List"` |
| 70116 | `"Posted Picking Sheet"` |
| 70117 | `"Posted Picking Lines"` |
| 70118 | `"Picking By Lines"` - file is `PickingByLines_PageExt.al` but declares a **page**, not a pageextension |
| 70119 | `"Pick Ship Date Dialog"` |
| 70120 | `"Loading Screen"` |
| 70121 | `"Pause Reason Dialog"` |
| 70122 | `"Posted Picking Sessions"` |
| 70123 | `"Posted Picking Session Card"` |
| 70124 | `"Posted Picking Session Orders"` |
| 70125 | `"Posted Picking Shipment"` |
| 70126 | `"Picking Date Dialog"` |
| 70130 | `"Picking Dashboard"` |
| 70131 | `"Activity History"` |
| 70132 | `"Pause History"` |
| 70133 | `"Session Activity Details"` |
| 70134 | `"Upwardor API Activity Log"` **(new)** |
| 70135 | `"Upwardor API Pause Log"` **(new)** |
| 70136 | `"Upwardor API Picking Queue"` **(new)** |
| 70137 | `"Upwardor API Picker Session"` **(new)** |
| 70138 | `"Upwardor API Posted Session"` **(new)** |
| 70139 | `"Upwardor API Posted Header"` **(new)** |
| 70140 | `"Upwardor API Posted Line"` **(new)** |

### Codeunits (7)

| ID | Name |
|---|---|
| 70100 | `BlockShippingHandler` |
| 70101 | `CODShipmentWarning` |
| 70102 | `"Picking Slip COD Check"` |
| 70105 | `"Picking Archive Manager"` |
| 70106 | `"Picking Permissions"` |
| 70107 | `"Activity Time Management"` |
| 70108 | `"Dashboard Data Builder"` |

### Page extensions (11)

70100 `SalesOrderShipmentExt` - 70101 `CustomerListExt` - 70102 `SalesOrderShipmentListExt` -
70103 `CustomerCardExt` - 70104 `PostedSalesShipmentLinesExt` - 70105 `"Sales Lines Ext"` -
70106 `"Production Order Line List"` - 70107 `PostedPurchaseInvoiceExt` -
70108 `"Sales Order SubForm PageExt"` - 70109 `"Sales Order PageExt"` - 70110 `ItemCardExt`

### Table extensions (4) and the fields they add

| Ext ID | Extends | Field | Name | Type | FlowField |
|---|---|---|---|---|---|
| 70100 `CustomerExt` | Customer | 70100 | `"Block Shipping"` | Boolean | No |
| 70100 `CustomerExt` | Customer | 70102 | `"Allow B2C Quoting"` | Boolean | No |
| 70102 `"Customer Picking Ext"` | Customer | 70101 | `"Has Active Picking"` | Boolean | **Yes** - `exist("Picking Selection" where("Customer No."=field("No.")))` |
| 70101 `"Sales Line Ext"` | Sales Line | 70100 | `"Available Inventory"` | Decimal | **Yes** - `Sum("Item Ledger Entry"."Remaining Quantity" where("Item No."=field("No.")))` |
| 70110 `ItemExt` | Item | 70110 | `"Description (French)"` | Text[100] | No |

**Maintenance hazard:** Customer field numbers are interleaved across two
different tableextension objects - 70100 owns fields 70100 and 70102, while
70102 owns field 70101. Easy to collide when adding a field.

`"Sales Line Ext"` (70101) also lives inside `src/Page Extensions/SalesOrder_SubForm_PageExt.al`,
sharing a file with pageextension 70108.

### Queries (3), permission sets (3), control add-ins (2)

Queries 70100 `"Sales Order List"` - 70101 `"Items Unit of Measure"` - 70102 `"Inv By Location"`
- all `UsageCategory = ReportsAndAnalysis`, in-client only, **not** API-exposed.

Permission sets 70100 `"Picking System"` - 70101 `"Picking Mgr"` - 70102 `"Picking API Read"` (new).

Control add-ins `"Live Timer"` and `"Picking Dashboard Renderer"` - no object IDs in AL.

No reports, xmlports, enums, profiles or entitlements exist.

### Free IDs (range 70100-79999)

| Type | Used | Free |
|---|---|---|
| table | 70100-70114 | **70115+** |
| tableextension | 70100, 70101, 70102, 70110 | 70103-70109, **70111+** |
| page | 70109-70126, 70130-70140 | 70100-70108, 70127-70129, **70141+** |
| pageextension | 70100-70110 | **70111+** |
| codeunit | 70100-70102, 70105-70108 | **70103, 70104**, **70109+** |
| query | 70100-70102 | **70103+** |
| permissionset | 70100-70102 | **70103+** |

Codeunits 70103 and 70104 are free - likely deleted objects. Re-check before
reusing, in case they exist in a deployed version and would collide on upgrade.

---

## 9. Third-party coupling - exact call sites

### Raw numeric access (no compile-time check - fails silently at runtime)

All in `src/Digital Picking/DigitalPickingCard.Page.al` (page 70110):

| Line | Target | Action |
|---|---|---|
| 210-213 | Sales Line **field 50032** (Output Shelf No.) | Writes via FieldRef, `Modify(false)` - skips validation triggers |
| 455 | **Table 60007** (Calendar Sales Header 2) | `CalHeaderRef.Open(60007)` - finish-picking path |
| 456-457 | 60007 **field 1** (Document Type) | `SetRange(1)` - Order ordinal hardcoded |
| 458-459 | 60007 **field 3** (No.) | `SetRange(PickingSelection."Sales Order No.")` |
| 461-464 | 60007 **field 50013** (Delivery Status) | Saves prior value, writes `2` (Order Staged) |
| 508 | **Table 60007** | Second `Open(60007)` - reopen/undo path |
| 509-512 | 60007 fields 1, 3 | Same filters |
| 514-515 | 60007 **field 50013** | Restores via `DeliveryStatusToInt(...)` |
| 641-644 | Sales Line **field 50032** | Reads shelf in `OnAfterGetRecord` - every row fetch |

Delivery Status ordinals are duplicated in `DeliveryStatusToInt`:
`Not Ready`=0, `Ready to Pick`=1, `Order Staged`=2, `Order Shipped`=3, `Order Invoiced`=4.

### Name-bound external fields (compile-time coupling to Probiztech)

| File:line | Field |
|---|---|
| `Queries/_Sales Order List_.Query.al:30` | Sales Header `"NCR No."` |
| `PickingByLines_PageExt.al:265-295` | `"Requested Delivery Date 1".."5"` - 5-slot ladder, silently no-ops if all full |
| `PickingOrderSelection.Page.al:220-250` | Same 5-slot ladder, **duplicated logic** |
| `PickingByLines_PageExt.al:354` | `"External Customer"` |
| `SalesOrderShipmentList.PageExt.al:7` | `"External Customer"` |
| `_SalesOrderShipmentExt_.PageExt.al:13-25` | `"External Document No."`, `"External Sales Order"`, `"External Customer No"` (**no trailing period**), `"External Customer"` |
| `PickingLineSubform.Page.al:58`, `PickingByLines_PageExt.al:55`, `DigitalPickingCard.Page.al:76` | `"Line No. 2"` |
| `DigitalPickingList.Page.al:566, 574` | `SalesLine."Line No. 2"` - both carry the comment `// Verify field name matches Probiztech extension` |

### Event subscriptions

| File:line | Subscription |
|---|---|
| `BlockShipping.CodeUnit.al:3` | `Codeunit "Sales-Post"`, `OnBeforePostSalesDoc` |
| `BlockShippingTerms.CodeUnit.al:3` | `Codeunit "Sales-Post"`, `OnBeforePostSalesDoc` - **second subscriber on the same event, ordering undefined** |
| `CodPickSlipWarning.CodeUnit.al:3` | `Page "Sales Order"`, `OnBeforeActionEvent`, action `Pick Instruction` |
| `CodPickSlipWarning.CodeUnit.al:12` | `Page "Sales Order Shipment"`, `OnBeforeActionEvent`, action `Picking` |

Both `OnBeforeActionEvent` subscriptions bind to **action names** on
Probiztech-extended pages. Renaming an action upstream breaks the COD warnings
silently - it still compiles.

---

## 10. Suggested sequence

1. **Ship the API pages** (`bc-extension/picking-api/`). Compile them first -
   they have never been built. Unblocks all portal-side reporting with no
   behaviour change to the picking flow.
2. **Fix `Source Type = 3` on the LOADING call site** (`DigitalPickingList.Page.al:312`)
   to `0`. One character, and nothing reads the field today, so it is free to fix
   now and expensive to fix once something depends on it.
3. **Add the conditional `TableRelation`** to `"Source No."` so the union is
   self-documenting.
4. **Add `"Picked At"` to `Picking Entry` + `Posted Picking Line`** (option b),
   stamped in `QtyPicked` `OnValidate`. This is what makes per-order and
   per-line timing real.
5. **Then** decide on per-order activities (option a), with actual pick-time data
   in hand to validate against.

Independently of the above: `Posted Picking Header."Entry No."` should become
`AutoIncrement` (it is the only entry-no in the module that isn't - `Activity
Time Log."Entry No."` already is), and `LoadPickingQty` should accept `Loaded`
status so simultaneous-load orders stop failing.
