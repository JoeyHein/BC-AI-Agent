# Current Sprint

> **Sprint Goal**: Door Configurator → Direct BC Integration (bypassing Upwardor)
> **Started**: 2026-01-22
> **Target Completion**: 2026-01-31
>
> **Pivot Note**: Upwardor Portal integration abandoned. Door Configuration Tool sends part numbers directly to BC.

---

## In Progress

(No tasks currently in progress - Sprint MVP Complete!)

---

## Blocked

(No blocked tasks)

---

## Completed This Sprint

### [TASK-014] Door Config -> BC End-to-End Testing
- **Status**: COMPLETE
- **Priority**: P1
- **Agent**: test
- **Completed**: 2026-01-23
- **Description**: Comprehensive testing of complete flow from door configuration to BC quote
- **Resolution**:
  - Created `scripts/test_door_config_to_bc.py` with 6 test cases
  - All tests passing:
    - [x] BC Part Number Mapper Direct Tests (5 verification tests)
    - [x] TX450 Commercial Door (9'x7' White)
    - [x] TX500 Commercial Door (12'x10' Steel Grey)
    - [x] KANATA Residential Door (16'x7' White Sheridan)
    - [x] Multi-Door Quote (2x 9'x7' + 1x 16'x8')
    - [x] Spring Calculator Integration
  - Part numbers verified: Springs, Panels, Tracks, Weather Strip, Shafts, Struts
  - Pre-configured door packages used for standard sizes (TX450-0907-01, etc.)
  - Note: AL976 aluminum doors DEFERRED (data exists but not MVP priority)

### [TASK-013] Audit & Complete Part Number Mappings
- **Status**: COMPLETE
- **Priority**: P1
- **Agent**: code
- **Completed**: 2026-01-23
- **Description**: Review existing part mappings and identify/build missing ones
- **Resolution**:
  - Audited `bc_part_number_mapper.py` - 976 lines of comprehensive mapping logic
  - **COMPLETE mappings:**
    - Springs: SP10, SP11, SP12 (26 wire sizes, 5 coil sizes)
    - Weather Strip: PL10 (8 lengths, 13 colors)
    - Astragal: 3", 4", 6.5"
    - Retainer: 1-3/4"
    - Tracks: TR02, TR03 (standard, vertical, LHR)
    - Shafts: SH11, SH12
    - Struts: FH17 (8 lengths)
    - Panels: TX450 (PN45, PN46), KANATA (PN60, PN61)
  - **DEFERRED mappings (data exists in bc_analysis):**
    - End Caps (FH10) - 22+ patterns
    - Aluminum Panels (PN10) - 100+ variations
    - CRAFT Panels - series codes needed
  - MVP coverage sufficient for TX450, TX500, KANATA doors

### [TASK-012] Remove Upwardor Dependency - Direct BC Integration
- **Status**: COMPLETE
- **Priority**: P0
- **Agent**: integration
- **Completed**: 2026-01-23
- **Description**: Pivot door configurator from Upwardor API to direct BC quote creation
- **Resolution**:
  - ✅ Removed Upwardor API imports and dependencies from `door_configurator.py`
  - ✅ Updated `/api/door-config/generate-quote` endpoint to create BC quotes directly
  - ✅ Uses `bc_client.create_sales_quote()` and `bc_client.add_quote_line()`
  - ✅ Uses existing `get_parts_for_door_config()` to get BC part numbers
  - ✅ Updated `/calculate-panels` and `/calculate-struts` with local calculations
  - ✅ Quote creation includes: customer, external doc number, all parts as line items
  - ✅ Returns BC quote number, parts summary, and line item count

### [TASK-005] Create Unit Test Suite for Spring Calculator
- **Status**: COMPLETE
- **Priority**: P1
- **Agent**: test
- **Completed**: 2026-01-23
- **Location**: `../../spring-calculator/`
- **Description**: Comprehensive tests for all spring calculation functions
- **Resolution**:
  - Created 114 passing tests across 3 test files
  - `core.test.ts` - Tests for IPPT, MIP, Active Coils, Spring Length, Weight, recommendations
  - `validation.test.ts` - 42 tests for all input validation functions
  - `canimex-fixtures.test.ts` - Regression tests using known Canimex catalog values
  - Achieved 100% line coverage on core.ts, 98% on validation.ts
  - Added CI-ready configuration with coverage thresholds (90%+ branches, 95%+ lines)
  - Added npm scripts: `test:ci`, `test:coverage`
  - Initial git commit created for spring-calculator repo

### [TASK-004] Integrate Email Learning System
- **Status**: COMPLETE
- **Priority**: P1
- **Completed**: 2026-01-23
- **Description**: Connect categorization learning service to email monitor for improved accuracy
- **Resolution**:
  - Learning system already existed in `email_categorization_service.py`
  - Backend endpoints already in place: `POST /{email_id}/mark-not-quote`, `GET /stats`
  - Frontend QuoteDetail.jsx already has "Not a Quote Request" button
  - Added `email_id` and `bc_quote_id` to QuoteResponse model for frontend access
  - Dashboard already displays AI Learning Progress panel with:
    - Accuracy Rate (correct categorizations / total verified)
    - False Positive Rate (incorrectly marked as quotes)
    - Learning Examples count (used to train AI)
  - Tip displayed when < 10 verified examples encouraging feedback
  - System learns from corrections and improves accuracy over time

### [TASK-003] Add Multiple Email Accounts
- **Status**: COMPLETE
- **Priority**: P1
- **Completed**: 2026-01-23
- **Description**: Connect additional OPENDC email accounts for full coverage
- **Resolution**:
  - System already supported multiple accounts via EmailConnection model
  - Added monitoring status endpoint: `GET /api/email-connections/monitoring/status`
  - Added manual check triggers: `POST /monitoring/check-now` (all) and `POST /{id}/check-now` (single)
  - Shows health status (healthy/warning/critical), token expiration, last check time
  - Updated EmailSettings.jsx with:
    - Monitoring status panel with health indicator
    - "Check All Now" button to trigger immediate email check
    - Per-inbox "Check" button for individual testing
    - Warning display for token expiration and stale checks
  - To connect joey@opendc.ca and briand@opendc.ca: Go to Email Settings > Click "Connect Email" > Sign in with Microsoft credentials

### [TASK-010] Production Order Integration for Springs
- **Status**: COMPLETE
- **Priority**: P1
- **Completed**: 2026-01-23
- **Description**: Enable production orders to include spring specifications
- **Resolution**:
  - Added `item_type`, `specifications`, and inventory fields to ProductionOrder model
  - Created `create_production_orders()` method that converts quote items to production orders
  - Spring specs flow preserved: QuoteItem.item_metadata -> ProductionOrder.specifications
  - Full Canimex data retained: wire_diameter, coil_diameter, length, IPPT, MIP, turns, cycle_life, drum_model
  - Added `_check_and_allocate_inventory()` for spring stock checking via BC API
  - Created API endpoints: POST/GET `/{order_id}/production-orders`, GET `/{order_id}/spring-production-orders`
  - Added `update_production_status()` with auto-update of sales order when all production complete
  - Test script: `scripts/test_production_order_flow.py`

### [TASK-011] BC Part Number Mapping and Memory Database
- **Status**: COMPLETE
- **Priority**: P0
- **Completed**: 2026-01-23
- **Description**: Deep analysis of BC part numbers and quotes to create memory database for door configurator
- **Resolution**:
  - Extracted 11,369 BC items, 891 quotes, 20,434 quote lines via API
  - Created `bc_part_number_mapper.py` with exact BC part number patterns:
    - Springs: SP11-{wire}{coil}-{wind} (e.g., SP11-23420-01 = 0.234" x 2" LH)
    - Panels: PN{series}-{height}{stamp}{color}-{width} (e.g., PN45-24400-0900)
    - Weather Strip: PL10-{length}203-{color} (e.g., PL10-07203-00)
    - Astragal: PL10-00005-{size} (01=3", 02=4", 03=6.5")
    - Retainer: PL10-00141-00 (1-3/4")
    - Winder Sets: SP12-00231-00 to SP12-00242-00
    - Tracks: TR02-STDBM-{height}{radius}
    - Shafts: SH12-1{width}10-00
    - Struts: FH17-{code}-00
  - Updated `part_number_service.py` to use real BC part numbers
  - Created memory database files in `data/bc_analysis/`
  - All tests passing - verified user example: TX450 9' white UDC

### [TASK-009] Add Spring Line Items to Quote Generation
- **Status**: COMPLETE
- **Priority**: P1
- **Completed**: 2026-01-23
- **Description**: Update quote generation service to include spring line items from calculator
- **Resolution**:
  - ✅ Added spring_calculator import to quote_service.py
  - ✅ Created `_generate_spring_item()` method with Canimex calculations
  - ✅ Added `_estimate_door_weight()` for weight from model + size
  - ✅ Added `_get_spring_price()` for wire/coil/length pricing
  - ✅ Spring items included in `_generate_door_items()` output
  - ✅ Full metadata: IPPT, MIP, turns, cycles, drum model, door weight
  - ✅ Tested: 2x TX450 9x7 doors → SP-234-2-27, 4 springs, $354.54

### [TASK-008] Connect Spring Calculator to Part Number Generation
- **Status**: COMPLETE
- **Priority**: P0
- **Completed**: 2026-01-22
- **Description**: Integrate spring calculator with part_number_service for accurate BC part numbers
- **Resolution**:
  - ✅ Added spring_calculator import to part_number_service.py
  - ✅ Added door_weight, target_cycles, spring_quantity to DoorConfiguration
  - ✅ Updated `_get_spring_parts()` to use Canimex calculator
  - ✅ Verified: 304 lbs + 12" radius → SP-250-2-29 (29.49" matches target 29.5")
  - ✅ Proper fallback to simplified rules if calculator fails
  - ✅ Detailed notes include IPPT, MIP, Turns, Cycles

### [TASK-007] Deep Dive into BC API - Learn Part Numbers and Functions
- **Status**: COMPLETE
- **Priority**: P0
- **Completed**: 2026-01-22
- **Description**: Explore BC API integration, understand part numbers and item structures
- **Resolution**:
  - ✅ OAuth 2.0 via MSAL with client credentials flow
  - ✅ Part number patterns documented:
    - Springs: SP-{WIRE_SIZE}-{ID}-{LENGTH} (e.g., SP-250-2-29)
    - Panels: PN-{SERIES}-{WIDTH_CODE}-{HEIGHT_CODE}-{COLOR}-{DESIGN}
    - Tracks: TR-V{THICKNESS}-{TYPE}-{LENGTH}, TR-H{THICKNESS}-{RADIUS}
    - Hardware: HK-SM/MD/LG/XL by door width
    - Glazing: GK-{SERIES}-{STYLE}-{GLAZING_TYPE}
  - ✅ Quote-to-order workflow: Email → QuoteRequest → BC Quote → Sales Order → Production → Shipment → Invoice
  - ✅ Database models: QuoteRequest, QuoteItem, SalesOrder, ProductionOrder, Shipment, Invoice
  - ✅ Key services: BCQuoteService, QuoteGenerationService, OrderLifecycleService, PartNumberService

### [TASK-002] Integrate Spring Calculator into Door Configurator
- **Status**: COMPLETE
- **Priority**: P0
- **Completed**: 2026-01-22
- **Description**: Replace simplified spring calculations with calibrated Canimex formulas
- **Resolution**:
  - ✅ Created `spring_calculator_service.py` with exact Canimex methodology
  - ✅ Ported all Canimex Appendix 2 divider values (38 wire sizes, 13 coil diameters)
  - ✅ Added drum multiplier tables (D400-96, D400-144)
  - ✅ Implemented: IPPT, MIP, Active Coils, Spring Length calculations
  - ✅ Updated `door_calculator_service.py` to use new spring module
  - ✅ Verified: 304 lbs door → 29.49" spring (matches target 29.5")
  - ✅ Part number generation: SP-250-2-29

### [TASK-001] Complete Spring Calculator Calibration
- **Status**: COMPLETE
- **Priority**: P0
- **Completed**: 2026-01-22
- **Description**: Finalize divider values with exact Canimex Appendix 2 data
- **Resolution**:
  - ✅ Updated dividers.json with ALL exact Canimex Appendix 2 values (38 wire sizes, 13 coil diameters)
  - ✅ Updated dead coil factors with exact Factor 1 and Factor 2 values
  - ✅ Added extrapolated 0.1875" x 2.0" = 312.7 divider for non-Canimex suppliers
  - ✅ Updated CoilDiameter type to include all Canimex sizes
  - ✅ Verified: 0.250" x 2.0" calculates to 29.49" (matches target 29.5")
  - ✅ All 23 unit tests passing

### [TASK-000] Fix Spring Calculation Formulas
- **Status**: COMPLETE
- **Priority**: P0
- **Completed**: 2026-01-22
- **Description**: Formula implementations were inverted (smaller wire = longer spring)
- **Resolution**:
  - ✅ Fixed MIP: `(IPPT × Turns) / SpringQty`
  - ✅ Fixed Active Coils: `(SpringQty × Divider) / IPPT`
  - ✅ Scaled divider values ~93x
  - ✅ Fixed dead coil factors
  - ✅ Direction now correct

---

## Sprint Metrics

| Metric | Value |
|--------|-------|
| Tasks Started | 14 |
| Tasks Completed | 14 |
| Tasks Blocked | 0 |
| Questions Asked | 2 (both answered) |

**SPRINT MVP COMPLETE!**
- Pivoted from Upwardor integration to direct BC integration
- Door Configurator now sends part numbers directly to BC
- All tests passing (6/6 test cases)
- Part number mappings verified against real BC data

---

## Quick Reference

### Project Locations
- **Main Backend**: `C:\Users\jhein\bc-ai-agent\backend`
- **Main Frontend**: `C:\Users\jhein\bc-ai-agent\frontend`
- **Spring Calculator**: `C:\Users\jhein\spring-calculator`
- **Agent Config**: `C:\Users\jhein\bc-ai-agent\opendc-agent`

### Running Services
- Backend: http://localhost:8000 (FastAPI)
- Frontend: http://localhost:3001 (React)
- API Docs: http://localhost:8000/docs

### Priority Levels
- **P0**: Critical - blocking everything
- **P1**: High - needed this sprint
- **P2**: Medium - nice to have
- **P3**: Low - can wait

### Status Values
- `NOT_STARTED` - Ready to begin
- `IN_PROGRESS` - Actively working
- `BLOCKED` - Waiting on something
- `IN_REVIEW` - Needs verification
- `COMPLETE` - Done and verified
