# GNB Doors (Manitoba) — Custom Escalating Margin Grid

GNB Manitoba is on a **volume-discount escalating margin curve** rather than a
flat tier. The bigger the quote, the lower the gross margin (and the bigger the
discount off list).

- **BC customer**: GNB Doors (Manitoba), Winnipeg MB
- **Account ID (portal)**: 52
- **BC customer ID**: `318ad8fb-4003-f011-9346-0022483d305e`
- **Profile key in code**: `GNB_MANITOBA`
- **Match rule**: any BC customer name containing "GNB" (case-insensitive)

## How the curve works

Every line in the quote is first priced at a **base 30 % gross margin**. The
total of those base-priced lines is then run through the curve below to get a
**target GM %** for the whole quote. Each line price is then multiplied by:

```
multiplier = (1 − base_GM%/100) / (1 − target_GM%/100)
            = (1 − 0.30)        / (1 − target_GM%/100)
```

So all lines on the quote get the same percentage discount — the discount is
chosen by total quote size.

## Breakpoints

Below $10k → no discount (full 30 % GM). Above $180k → floor at 9.5 % GM.
Between breakpoints, the target GM is **linearly interpolated**.

| Quote total (@ 30 % GM) | Target GM | Effective discount off list |
|------------------------:|----------:|----------------------------:|
| < $10,000               | 30.00 %   | 0.00 %                      |
| $10,000                 | 26.00 %   | 5.41 %                      |
| $16,000                 | 23.00 %   | 9.09 %                      |
| $38,000                 | 18.50 %   | 14.11 %                     |
| $180,000                |  9.50 %   | 22.65 %                     |
| > $180,000              |  9.50 %   | 22.65 % (floor)             |

## Sample quote totals along the curve

| Quote @ 30 % GM | Target GM | Multiplier | Discount | Adjusted total |
|----------------:|----------:|-----------:|---------:|---------------:|
| $5,000          | 30.00 %   | 1.0000     | 0.00 %   | $5,000         |
| $9,999          | 30.00 %   | 1.0000     | 0.00 %   | $9,999         |
| $10,000         | 26.00 %   | 0.9459     | 5.41 %   | $9,459         |
| $12,000         | 25.00 %   | 0.9333     | 6.67 %   | $11,200        |
| $16,000         | 23.00 %   | 0.9091     | 9.09 %   | $14,545        |
| $25,000         | 21.16 %   | 0.8879     | 11.21 %  | $22,197        |
| $38,000         | 18.50 %   | 0.8589     | 14.11 %  | $32,638        |
| $75,000         | 16.15 %   | 0.8349     | 16.51 %  | $62,615        |
| $120,000        | 13.30 %   | 0.8074     | 19.26 %  | $96,889        |
| $180,000        |  9.50 %   | 0.7735     | 22.65 %  | $139,227       |
| $250,000        |  9.50 %   | 0.7735     | 22.65 %  | $193,370       |

(Numbers generated from the live `EscalatingMarginProfile.calculate()` —
match what the portal applies on the quote.)

## How this interacts with the standard pricing grid

GNB Manitoba **does not use the Platinum / Gold / Silver / Bronze grid**. The
escalating curve replaces the tier margin entirely. The other parts of the
standard pricing pipeline still apply:

1. `unitCost` is pulled live from BC.
2. **Cost adjustments** still apply (Tariff +50 %, Glazing +20 %, Garage Openers
   +10 %, Freight +7 %, others 0 %).
3. **Spring waste factor** (+15 % on `SPRI` items) still applies.
4. Each line is then priced at **30 % GM**.
5. Quote total is summed, the curve picks a target GM, and the multiplier is
   applied to every line.

## Where this lives in code

- `backend/app/services/escalating_margin_service.py` — profile, breakpoints,
  curve math
- `ESCALATING_PROFILES["GNB_MANITOBA"]` — the configured breakpoints
- Customer match: any BC customer name containing "GNB" routes to this profile

To change the curve, edit the `breakpoints=[…]` list at
`escalating_margin_service.py:131` and redeploy.
