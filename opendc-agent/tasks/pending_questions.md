# Pending Questions

> Questions collected during autonomous execution.
> When 5+ questions accumulate OR work is blocked, present to user.

---

## Current Questions

*No pending questions*

---

## Answered Questions

### Q1: Canimex Appendix 2 Exact Divider Values
**Context**: Current divider values produce 0.1875" → 11.28" (expected ~7.75") and 0.250" → 25.78" at 350 lbs. The 0.250" result matches ~29.5" at 300 lbs, but 0.1875" is consistently off. Need exact values from Canimex catalog to calibrate.
**Answer**: User provided Cable-Drum-Catalog.pdf_Part5.pdf page 96 (Appendix 2)
**Resolution**:
- Updated dividers.json with ALL exact Canimex Appendix 2 values (38 wire sizes, 13 coil diameters)
- 0.1875" x 2.0" does NOT exist in Canimex - only 1.75" coil available
- Added extrapolated 0.1875" x 2.0" = 312.7 divider for non-Canimex suppliers
- Verified: 0.250" x 2.0" calculates to 29.49" (matches target 29.5")

### Q2: Test Case Door Specifications
**Context**: You mentioned 0.1875" x 2" = 7.75" at 0 cycles. What door configuration produces this?
**Answer**: 304 lbs (not 350), 192" wide x 84" tall, 12" radius tracks, target .250x2x29.5", 2 springs
**Resolution**: Updated test case parameters, verified calculation matches target exactly

---

## Response Format

Reply with: "Q1: A, Q2: B" or provide custom answers
