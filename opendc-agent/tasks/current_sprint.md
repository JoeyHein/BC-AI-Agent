# Current Sprint

> **Sprint Goal**: Complete Phase 1 Foundation - Spring Calculator + Quote Workflow Enhancement
> **Started**: 2026-01-22
> **Target Completion**: 2026-01-31

---

## In Progress

### [TASK-010] Production Order Integration for Springs
- **Status**: NOT_STARTED
- **Priority**: P1
- **Agent**: integration
- **Description**: Enable production orders to include spring specifications
- **Location**: `backend/app/services/order_lifecycle_service.py`
- **Acceptance Criteria**:
  - [ ] Production orders include spring item details
  - [ ] Spring specs flow from quote → sales order → production
  - [ ] Inventory allocation considers spring stock

---

## Ready for Work

### [TASK-003] Add Multiple Email Accounts
- **Status**: NOT_STARTED
- **Priority**: P1
- **Agent**: integration
- **Description**: Connect additional OPENDC email accounts for full coverage
- **Acceptance Criteria**:
  - [ ] joey@opendc.ca connected
  - [ ] briand@opendc.ca connected
  - [ ] Additional emails TBD connected
  - [ ] All monitored for quote requests

### [TASK-004] Integrate Email Learning System
- **Status**: NOT_STARTED
- **Priority**: P1
- **Agent**: code
- **Description**: Connect categorization learning service to email monitor for improved accuracy
- **Acceptance Criteria**:
  - [ ] "Not a Quote Request" button in UI
  - [ ] Feedback stored and used for learning
  - [ ] Categorization accuracy improves over time
  - [ ] Stats visible on dashboard
- **Notes**: Code exists in `services/categorization_service.py`, needs integration

### [TASK-005] Create Unit Test Suite for Spring Calculator
- **Status**: NOT_STARTED
- **Priority**: P1
- **Agent**: test
- **Location**: `../../spring-calculator/`
- **Description**: Comprehensive tests for all spring calculation functions
- **Acceptance Criteria**:
  - [ ] Tests for IPPT, MIP, Active Coils, Spring Length
  - [ ] Test fixtures with known Canimex examples
  - [ ] 100% coverage on core calculations
  - [ ] CI-ready test configuration

---

## Blocked

### [TASK-006] BC Quote Line Items
- **Status**: BLOCKED
- **Priority**: P2
- **Agent**: integration
- **Blocked By**: Upwardor integration needed for product codes
- **Description**: Auto-populate BC quote line items from parsed door specs
- **Notes**: Currently quotes created without lines, manager adds manually

---

## Completed This Sprint

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
| Tasks Started | 7 |
| Tasks Completed | 7 |
| Tasks Blocked | 1 |
| Questions Asked | 2 (both answered) |

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
