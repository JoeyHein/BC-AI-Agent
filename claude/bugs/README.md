# Bug Tracker

Last updated: 2026-04-02

## Status Legend
- **TODO** — Not started
- **IN PROGRESS** — Currently being worked on
- **DONE** — Fixed and committed
- **WONTFIX** — Decided not to fix
- **DEFERRED** — Needs more info or blocked

---

## Tier 1: Low-Hanging Fruit (config/data fixes)

| S.No | Quote | Bug | Status | Commit | Files | Notes |
|------|-------|-----|--------|--------|-------|-------|
| 29 | | TX450-20 given UDC option — only FLUSH available | IN PROGRESS | | `door_configurator.py` | Rulebook: 20G = FLUSH only |
| 29 | | Color restrictions not enforced (20G=white only, TX500=white+black) | IN PROGRESS | | `door_configurator.py` | Rulebook DIFF #2 |
| 28 | SQ-002319 | Put 4 struts on AL976 door with built-in strut | TODO | | `part_number_service.py` | Aluminum sections have built-in struts |
| 34 | SQ-002320 | Comment for window says "GK16" — should show dimensions (24x12) | TODO | | `part_number_service.py` | Customer-facing description |
| 32 | SQ-002320 | Multiple doors on one quote — no blank comment between | TODO | | `quote_service.py` | Also add separator before freight |
| 38 | | Defaults to cash sale instead of forcing customer selection | TODO | | Frontend | UI default issue |

## Tier 2: Easy Fixes (small logic changes)

| S.No | Quote | Bug | Status | Commit | Files | Notes |
|------|-------|-----|--------|--------|-------|-------|
| 6 | | Freight not grouping into its own category | TODO | | `quote_service.py`, `bc_quote_service.py` | Also reported as #21 |
| 21 | SQ-002319 | Does not group freight by itself | TODO | | `quote_service.py`, `bc_quote_service.py` | Duplicate of #6 |
| 33 | SQ-002320 | Does not specify where in panel the window goes | TODO | | `part_number_service.py` | windowSection not output to BC |
| 19 | SQ-002319 | Does not specify glass pockets on AL doors; marks as flush | TODO | | `quote_service.py`, `part_number_service.py` | Aluminum comment line wrong |
| 24 | SQ-002319 | Portal showed 5 glass pockets — should be 6 by default | TODO | | `DoorPreview.jsx` | Pane count mapping wrong for 16' |
| 7 | | Short windows on Flush doors appear as long in image | TODO | | `DoorPreview.jsx` | FLUSH skips window sizing logic |
| 20 | SQ-002319 | Does not add aluminum wrapping charge | TODO | | `part_number_service.py` | No wrapping line item generated |
| 30 | | Missing items should refer customer to rep, not show price | TODO | | `bc_quote_service.py` | Missing item handling |
| 37 | SQ-002320 | No top seal added for TX450-20 door | DONE | `12877af`, `0ddbbdc` | `part_number_service.py` | Fixed — optional upgrade toggle |

## Tier 3: Medium Fixes (calculation logic)

| S.No | Quote | Bug | Status | Commit | Files | Notes |
|------|-------|-----|--------|--------|-------|-------|
| 35 | SQ-002320 | Used 2 shafts on 10x12 instead of 11'6" single | TODO | | `door_calculator_service.py`, `part_number_service.py` | Shaft formula vs rulebook table |
| 26 | SQ-002319 | Assigned (3) 6'6" shafts for 18' wide door | TODO | | `door_calculator_service.py` | width_minimum or spring count issue |
| 31 | SQ-002320 | Can't find HW box for 10x12 or 8x8 TX450-20 | TODO | | `bc_part_number_mapper.py` | Old part number format |
| 18 | SQ-002319 | Can't find hardware boxes for 18' wide doors | TODO | | `bc_part_number_mapper.py` | HK lookup edge case |
| 10 | | Only added 4 short windows to 16' wide door | TODO | | `door_configurator.py` | Formula vs rulebook max table |
| 22 | SQ-002319 | Used 6 spring config when 2 would have worked | TODO | | `door_calculator_service.py` | Spring over-selection |

## Tier 4: Complex Fixes (multi-file, investigation needed)

| S.No | Quote | Bug | Status | Commit | Files | Notes |
|------|-------|-----|--------|--------|-------|-------|
| 36 | SQ-002320 | TX450-20 weight incorrect (portal 389, actual 337) | TODO | | `door_calculator_service.py` | Weight calculation discrepancy |
| 25 | SQ-002319 | Weight calculated 498 by portal — actual 767 | TODO | | `door_calculator_service.py` | Under-calculated, missing components? |
| 27 | SQ-002319 | Put in 180 sqft glass (door 162, actual 125) | TODO | | `part_number_service.py` | Uses full panel area not glass area |
| 5 | | Assign retainer/window to panels for SO conversion | TODO | | `part_number_service.py` | Design decision: panel routing or remove BC rules |
| 9 | | Many window configs missing from BC (short super grey french oak) | TODO | | `door_configurator.py`, BC | No valid combo matrix |
| 15 | | No polycarbonate option for AL976 | TODO | | `part_number_service.py` | Hardcoded to PANORAMA/SOLALITE only |
| 19 | SQ-002319 | Glass pocket count not in aluminum quote output | TODO | | `part_number_service.py` | Calculated internally, not returned |
| 23 | SQ-002319 | AL-976 frames price very high | TODO | | BC pricing / `part_number_service.py` | Likely sqft miscalculation (see #27) |

## Already Fixed

| S.No | Bug | Fixed By |
|------|-----|----------|
| 3 | Universal cone part numbers (SP12-00231-01) | Commit `2e7038b` — already uses universal parts |
| 37 | Top seal conditional (width>=18' AND height>=10') | Commits `d2cfc58`, `12877af`, `0ddbbdc` |
| -- | Panel stamp V Groove / Micro Groove added | Commit `d2cfc58` |
| -- | 2" track blocked if height>14' or width>18' | Commit `d2cfc58` |
| -- | 16ga strut parts for 22', 24', 26' | Commit `d2cfc58` |
| -- | Weatherstrip PL11 format for commercial | Commit `d2cfc58` |
| -- | Bottom retainer series-specific parts | Commit `d2cfc58` |
