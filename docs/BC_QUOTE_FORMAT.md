# BC Quote Line Format Specification

> **Version**: 1.0
> **Last Updated**: 2026-01-23
> **Source**: OPENDC Business Rules

## Quote Structure

Every door quote in Business Central follows a standardized line format:

### Multi-Door Quotes

For quotes with multiple doors, each door section begins with a **Comment line** describing the door configuration. This comment line has the "Output" checkbox checked in BC.

```
[Comment] (1) 10x9 TX450, WHITE, UDC, 2" HW, STD LIFT
  - Panel lines
  - Retainer
  - Astragal
  - etc.

[Comment] (2) 16x8 KANATA, WALNUT, SHERIDAN XL, 2" HW, STD LIFT
  - Panel lines
  - Retainer
  - etc.
```

---

## Line Item Ordering (Standardized)

Lines must appear in this exact order for each door:

| Order | Category | Description |
|-------|----------|-------------|
| 1 | **Comment** | Door description (lineType: Comment) |
| 2 | **Panels** | Door panels/sections |
| 3 | **Retainer** | Top/bottom retainer |
| 4 | **Astragal** | Bottom rubber seal |
| 5 | **Struts** | Reinforcing struts |
| 6 | **Windows** | Window sections (if applicable) |
| 7 | **Track** | Standard track assembly |
| 8 | **High Lift Track** | Additional track (if high lift) |
| 9 | **Hardware Box** | Hardware kit |
| 10 | **Springs** | Torsion springs, winders, accessories |
| 11 | **Weather Seal** | Perimeter weather stripping |
| 12 | **Accessories** | Pusher springs, bumper springs, etc. |

---

## Panel Part Number Rules

### Complete Door Panels

Panel part numbers follow the format: `PN{series}-{height}{stamp}{color}-{width}`

| Model | Width ≤ 16' | Width > 16' | Notes |
|-------|-------------|-------------|-------|
| **KANATA** | PN65 | PN65 | Residential, same for all widths |
| **CRAFT** | PN95 | PN95 | Residential, same for all widths |
| **TX450** | PN45 | PN46 | Commercial, SEC/DEC based on width |
| **TX500** | PN55 | PN56 | Commercial, SEC/DEC based on width |
| **TX380** | PN35 | N/A | Commercial, max width 16' |

### Part Number Components

```
PN45-24400-0900
│  │  ││││  ││││
│  │  ││││  └┴┴┴── Width: FFII format (09'00" = 9 feet)
│  │  │││└──────── Color: 00=White, 05=Black, 10=New Brown, etc.
│  │  ││└───────── Stamp: 0=Standard, 4=UDC
│  │  └┴────────── Height: 21" or 24"
│  └────────────── Series: 35/45/46/55/56/65/95
└───────────────── Prefix: PN (Panel)
```

### Color Codes

| Code | Color |
|------|-------|
| 00 | White |
| 01 | Brown |
| 02 | Almond |
| 04 | Sandtone |
| 05 | Black |
| 06 | Bronze |
| 10 | New Brown |
| 20 | Steel Grey |
| 25 | Iron Ore |
| 30 | New Almond |
| 40 | Hazelwood |
| 51 | Walnut |
| 55 | English Chestnut |

---

## Door Description Format (Comment Line)

```
({qty}) {width}'x{height}' {series}, {color}, {design}, {track_size}" HW, {lift_type}
```

Examples:
- `(1) 10x9 TX450, WHITE, UDC, 2" HW, STD LIFT`
- `(2) 16x7 KANATA, WALNUT, SHERIDAN XL, 2" HW, STD LIFT`
- `(1) 20x12 TX500, BLACK, FLUSH, 3" HW, HIGH LIFT`

---

## Future Enhancement: Upsell Feature

**PLANNED**: Add upsell suggestions in the door configuration tool:
- Premium hardware upgrades
- Extended cycle spring options
- Window additions
- Insulation upgrades
- Opener packages

*Note: Implement after core quote generation is complete.*

---

## Implementation Notes

### BC API Field Mapping

When adding lines to BC via API:

```python
# Comment line
{
    "lineType": "Comment",
    "description": "(1) 10x9 TX450, WHITE, UDC, 2\" HW, STD LIFT"
}

# Item line
{
    "lineType": "Item",
    "lineObjectNumber": "PN45-24400-0900",
    "description": "TX450 SECTION, 9' X 24\", UDC, WHITE",
    "quantity": 4
}
```

### Ordering in Code

The `format_for_quote()` method must output lines in the specified order:
1. Comment first (door description)
2. Panels
3. Retainer
4. Astragal
5. Struts
6. Windows
7. Track
8. Hardware
9. Springs
10. Weather seal
11. Accessories
