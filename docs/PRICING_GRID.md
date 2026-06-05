# OPENDC Pricing Grid (Garaga / Upwardor)

Source of truth for how the portal converts BC `unitCost` into customer-facing
selling prices. Numbers below reflect **production settings** (pulled from
`AppSettings` on portal.opendc.ca, 2026-05-01).

## Formula

```
adjusted_cost  = unitCost × (1 + costAdjustment%/100)
selling_price  = adjusted_cost / (1 - margin%/100)
```

- `unitCost` comes from BC (live, cached 1 hour).
- `costAdjustment%` is a per-BC-posting-group uplift (see table below).
- `margin%` is a gross margin set by the customer's **tier** and the **door type**.
- Margin is gross (selling price ÷ margin = profit), not markup.

Example: residential Gold tier, item with `unitCost = $100`, posting group `RESI`
(0% adjustment): `100 × 1.00 / (1 − 0.30) = $142.86`.

---

## Tier × Door-Type Margin Grid

All values are gross-margin percentages.

| Door Type   | Platinum | Unlisted | Gold | Silver | Bronze | Retail |
|-------------|---------:|---------:|-----:|-------:|-------:|-------:|
| Residential |   25 %   |   20 %   | 30 % |  35 %  |  40 %  |  50 %  |
| Commercial  |   27 %   |   24 %   | 30 % |  33 %  |  36 %  |  42 %  |
| Aluminium   |   45 %   |   40 %   | 48 % |  51 %  |  55 %  |  65 %  |
| Glazing     |   55 %   |   50 %   | 60 % |  64 %  |  66 %  |  73 %  |

**Tier definitions (informal):**
- **Platinum** — top dealer, best pricing.
- **Unlisted** — internal / cost-plus-minimal accounts.
- **Gold / Silver / Bronze** — standard dealer tiers (dealers placed by volume).
- **Retail** — homeowners, walk-ins, anyone without a dealer account.

---

## Cost Adjustments by BC Posting Group

These uplifts are applied to `unitCost` **before** the margin formula. They cover
freight, tariff, vendor surcharges, and category-level markup.

| Posting Group | Description                       | Adjustment |
|---------------|-----------------------------------|-----------:|
| RESI          | Panels (Residential)              |     0 %    |
| COMM          | Panels (Commercial)               |     0 %    |
| ALUM          | Aluminum                          |     0 %    |
| HARD          | Hardware                          |     0 %    |
| TRAC          | Tracks                            |     0 %    |
| SPRI          | Springs                           |     0 %    |
| OPER          | Operators                         |     0 %    |
| GO            | Garage Openers                    |    10 %    |
| GLAZ          | Glazing / Windows                 |    20 %    |
| PLAS          | Plastics / Weather Stripping      |     0 %    |
| ACS           | Accessories                       |     0 %    |
| UPCW          | UPCW                              |     0 %    |
| CONS          | Consumables                       |     0 %    |
| MISC          | Miscellaneous                     |     0 %    |
| SAMP          | Samples                           |     0 %    |
| LABR          | Labour                            |     0 %    |
| FREIGHT       | Freight                           |     7 %    |
| TARIFF        | Tariff                            |    50 %    |

---

## Special Routing Rules

These override the door-type margin lookup for specific part categories:

- **GK17 glazing kits** (any door) → priced at **glazing margins** (not
  the host door's residential/commercial tier).
- **PN10 / PN12 V130G frames** (any door) → priced at **glazing margins**.
- **Aluminum doors** + hardware/tracks/springs/operators/plastics/accessories
  (`HARD / TRAC / SPRI / OPER / PLAS / ACS`) → priced at the customer's
  **commercial tier**, not aluminium.
- **Springs** (`SPRI` posting group or `SP11…` part numbers) — a 15 % waste
  factor is added to `unitCost` before the formula. Springs are cut to length
  on the floor; 15 % covers offcut/scrap.

## Per-Prefix Margin Overrides

The portal supports per-part-number-prefix margin overrides
(`pricing_prefix_margins` setting). **Currently none are configured in
production** — this is a tool for one-off product overrides if needed.

## BC Price Group → Portal Tier Mapping

The portal can auto-assign a customer to a portal tier based on their BC price
group code (`bc_group_tier_mapping` setting). **Currently no mappings are
configured in production** — tiers are assigned manually per customer in the
admin portal.

## Fallbacks

- If `unitCost` is 0 or missing → portal **does not** override BC's price; BC
  uses its own list price for the line. Logged as a warning.
- If a customer's tier is missing/unknown/legacy → falls back to **Retail**.
- Margin is hard-capped at 99 % (safety guard).

---

## Where this lives in code

- `backend/app/services/pricing_service.py` — formulas, tier lookup, cache
- `backend/app/db/models.py::AppSettings` — overrides storage
- Admin UI: **Settings → Pricing** (edit margins, cost adjustments, BC group
  mapping, per-prefix overrides)
