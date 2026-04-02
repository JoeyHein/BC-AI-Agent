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

| S.No | Quote | Bug | Status | Commit | Notes |
|------|-------|-----|--------|--------|-------|
| 29 | | TX450-20 given UDC option — only FLUSH available | DONE | `a5b7459` | Rulebook: 20G = FLUSH only |
| 29 | | Color restrictions not enforced (20G=white only, TX500=white+black) | DONE | `a5b7459` | Backend + frontend aligned |
| 28 | SQ-002319 | Put 4 struts on AL976 door with built-in strut | TODO | | Aluminum sections have built-in struts |
| 34 | SQ-002320 | Comment for window says "GK16" — should show dimensions | DONE | `1af650a` | Now shows dimensions (e.g. 24x12) |
| 32 | SQ-002320 | Multiple doors on one quote — no blank comment between | DONE | `a5b7459`, `ea3013d` | Admin + customer portal flows |
| 38 | | Defaults to cash sale instead of forcing customer selection | DONE | `a5b7459`, `ea3013d` | Button disabled, backend rejects |

## Tier 2: Easy Fixes (small logic changes)

| S.No | Quote | Bug | Status | Commit | Notes |
|------|-------|-----|--------|--------|-------|
| 6/21 | SQ-002319 | Freight not grouping into its own category | DONE | `310601d` | Output flag on freight line |
| 33 | SQ-002320 | Does not specify where in panel the window goes | DONE | `a938035` | Shows panel position (TOP/BOTTOM/N FROM TOP) |
| 19 | SQ-002319 | Does not specify glass pockets on AL doors; marks as flush | DONE | `0d4221f` | Glass pockets per section in comment |
| 24 | SQ-002319 | Portal showed 5 glass pockets — should be 6 by default | DONE | `4052ba1` | 18'2" doors now get 6 pockets |
| 7 | | Short windows on Flush doors appear as long in image | DONE | `a773216`, `c42731c` | Short panel windows + windowSize field |
| 20 | SQ-002319 | Does not add aluminum wrapping charge | DONE | `42923fe` | WRAPALU wrapping for all aluminum doors |
| 30 | | Missing items should refer customer to rep, not show price | DONE | (pending commit) | Shows "CONTACT REP FOR PRICING" |
| 37 | SQ-002320 | No top seal added for TX450-20 door | DONE | `12877af`, `0ddbbdc` | Optional upgrade toggle added |

## Tier 3: Medium Fixes (calculation logic)

| S.No | Quote | Bug | Status | Commit | Notes |
|------|-------|-----|--------|--------|-------|
| 35 | SQ-002320 | Used 2 shafts on 10x12 instead of 11'6" single | DONE | (pending commit) | Shaft lookup table from Upwardor Portal |
| 26 | SQ-002319 | Assigned (3) 6'6" shafts for 18' wide door | DONE | (pending commit) | Fixed: always 2 shafts, exact parts from table |
| 31 | SQ-002320 | Can't find HW box for 10x12 or 8x8 TX450-20 | DONE | `d47e02d`, `a4915d4` | HK03 for all commercial, all sizes mapped |
| 18 | SQ-002319 | Can't find hardware boxes for 18' wide doors | DONE | `d47e02d`, `a4915d4` | All sized HK kits mapped |
| 10 | | Only added 4 short windows to 16' wide door | TODO | | Formula vs rulebook max table |
| 22 | SQ-002319 | Used 6 spring config when 2 would have worked | TODO | | Spring over-selection |

## Tier 4: Complex Fixes (multi-file, investigation needed)

| S.No | Quote | Bug | Status | Commit | Notes |
|------|-------|-----|--------|--------|-------|
| 36 | SQ-002320 | TX450-20 weight incorrect (portal 389, actual 337) | TODO | | Weight calculation discrepancy |
| 25 | SQ-002319 | Weight calculated 498 by portal — actual 767 | DONE | `5151080`, `2bd41bc` | Proper aluminum weight calc |
| 27 | SQ-002319 | Put in 180 sqft glass (door 162, actual 125) | DONE | `5046242` | Uses actual window opening dimensions |
| 5 | | Assign retainer/window to panels for SO conversion | TODO | | Design decision: panel routing or remove BC rules |
| 9 | | Many window configs missing from BC (short super grey french oak) | TODO | | No valid combo matrix |
| 15 | | No polycarbonate option for AL976 | DONE | `c6438a7` | Polycarbonate glazing option added |
| 23 | SQ-002319 | AL-976 frames price very high | DONE | `5046242`, `3812182` | Fixed sqft calc + commercial tier margins |
| 19 | SQ-002319 | Glass pocket count not in aluminum quote output | DONE | `0d4221f` | Glass pockets per section in comment |

## Already Fixed (prior to this tracking)

| S.No | Bug | Fixed By |
|------|-----|----------|
| 3 | Universal cone part numbers (SP12-00231-01) | Commit `2e7038b` |
| 37 | Top seal conditional (width>=18' AND height>=10') | Commits `d2cfc58`, `12877af`, `0ddbbdc` |
| -- | Panel stamp V Groove / Micro Groove added | Commit `d2cfc58` |
| -- | 2" track blocked if height>14' or width>18' | Commit `d2cfc58` |
| -- | 16ga strut parts for 22', 24', 26' | Commit `d2cfc58` |
| -- | Weatherstrip PL11 format for commercial | Commit `d2cfc58` |
| -- | Bottom retainer series-specific parts | Commit `d2cfc58` |

---

## Summary

- **Total bugs**: 29
- **DONE**: 24
- **TODO**: 5
  - S.No 28 — Struts on AL976 (built-in)
  - S.No 10 — Only 4 short windows on 16' door
  - S.No 22 — Spring over-selection (6 vs 2)
  - S.No 36 — TX450-20 weight incorrect
  - S.No 5 — Retainer/window panel assignment for SO
  - S.No 9 — Missing window configs in BC
