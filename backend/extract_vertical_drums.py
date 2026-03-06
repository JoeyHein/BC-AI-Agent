"""
Extract vertical-lift drum multiplier tables from Canimex Cable Drum Catalog Part4 PDF.
Page 13 (index 13): D850-132 + D1100-216 combined table
Page 14 (index 14): D1350-336 table

Each row: door_height_ft_in, door_height_inches, HMA (inch), REV_OF_DRUM (turns), TURNS_ON_SPRING (turns)
Multiplier = HMA / TURNS_ON_SPRING (per Canimex formula: Turns = HMA / Multiplier)

Note: Page 13 has both D850-132 and D1100-216 drums sharing the same table.
  - Section 1 (heights 0-129): applies to both drums
  - Section 2 (heights 132-218): D1100-216 only (D850-132 maxes out at 132)
"""
import fitz
import sys
import re
import json
import os

sys.stdout.reconfigure(encoding='utf-8')

pdf_path = 'backend/data/spring-calculator/reference/Cable-Drum-Catalog.pdf_Part4.pdf'
doc = fitz.open(pdf_path)


def parse_vl_data(lines, start_idx, max_height=None):
    """Parse VL data rows from page lines.

    Each data row spans 5 lines:
      1. Height ft/in (e.g., "6'0''")
      2. Height inches (e.g., "72")
      3. HMA value (comma decimal, e.g., "3,225")
      4. REV of drum (comma decimal)
      5. TURNS on spring (comma decimal)

    Returns list of (height, hma, rev, turns) tuples.
    """
    entries = []
    i = start_idx
    while i < len(lines):
        line = lines[i].strip()

        # Stop at section breaks
        if 'DOOR HEIGHT' in line or 'DRUMS SPECIFICATIONS' in line:
            break
        if 'MULTIPLIER' in line:
            break

        # Look for height line: "6'0''" pattern
        height_match = re.match(
            r"(\d+)\s*[\u2018\u2019'\u00b4`]+\s*(\d+)\s*[\u2018\u2019'\"\u201c\u201d\u00b4`]+",
            line
        )
        if not height_match:
            i += 1
            continue

        feet = int(height_match.group(1))
        inches = int(height_match.group(2))
        door_height = feet * 12 + inches

        if max_height and door_height > max_height:
            break

        # Next line should be height in inches
        i += 1
        if i >= len(lines):
            break
        inch_line = lines[i].strip()
        if not re.match(r'^\d{1,3}$', inch_line):
            continue
        height_verify = int(inch_line)
        if height_verify != door_height:
            print(f"  WARNING: height mismatch {door_height} vs {height_verify}", file=sys.stderr)
            door_height = height_verify

        # Collect 3 numeric values: HMA, REV, TURNS
        vals = []
        i += 1
        while i < len(lines) and len(vals) < 3:
            val_line = lines[i].strip()
            if not val_line:
                i += 1
                continue
            # European decimal: comma -> dot
            m = re.match(r'^(\d+[.,]\d+)$', val_line)
            if m:
                vals.append(float(m.group(1).replace(',', '.')))
                i += 1
                continue
            # Integer value
            m = re.match(r'^(\d{1,3})(\.\d)?$', val_line)
            if m:
                vals.append(float(val_line.replace(',', '.')))
                i += 1
                continue
            break

        if len(vals) == 3:
            hma, rev, turns = vals
            entries.append((door_height, hma, rev, turns))
        else:
            print(f"  WARNING: height {door_height} only got {len(vals)} values: {vals}",
                  file=sys.stderr)

    return entries


def find_section_starts(lines):
    """Find where data sections start (after header rows)."""
    starts = []
    for i, line in enumerate(lines):
        if 'TURNS ON' in line and i > 3:
            data_start = i + 1
            # Skip remaining header lines: SPRING, (FT), (IN), (INCH), (TURNS), etc.
            while data_start < len(lines):
                s = lines[data_start].strip()
                if s in ['SPRING', ''] or s.startswith('('):
                    data_start += 1
                else:
                    break
            starts.append(data_start)
    return starts


# ---- Page 13: D850-132 + D1100-216 ----
print("Extracting VL drums from Part4 page 13...", file=sys.stderr)
lines_p13 = doc[13].get_text().split('\n')
section_starts = find_section_starts(lines_p13)
print(f"  Found {len(section_starts)} section(s) starting at lines: {section_starts}",
      file=sys.stderr)

# Section 1: D850-132 range (heights 0-129)
section1 = parse_vl_data(lines_p13, section_starts[0], max_height=131)
print(f"  Section 1: {len(section1)} entries "
      f"({section1[0][0]}-{section1[-1][0]}\")", file=sys.stderr)

# Section 2: D1100-216 continuation (heights 132+)
section2 = []
if len(section_starts) > 1:
    section2 = parse_vl_data(lines_p13, section_starts[1])
    print(f"  Section 2: {len(section2)} entries "
          f"({section2[0][0]}-{section2[-1][0]}\")", file=sys.stderr)

# ---- Page 14: D1350-336 ----
print("\nExtracting D1350-336 from Part4 page 14...", file=sys.stderr)
lines_p14 = doc[14].get_text().split('\n')
section_starts_p14 = find_section_starts(lines_p14)
print(f"  Found section start at line: {section_starts_p14}", file=sys.stderr)

section3 = parse_vl_data(lines_p14, section_starts_p14[0])
print(f"  D1350-336: {len(section3)} entries "
      f"({section3[0][0]}-{section3[-1][0]}\")", file=sys.stderr)

doc.close()


# ---- Build drum data ----
def build_multiplier_table(entries):
    """Convert (height, hma, rev, turns) tuples to multiplierTable format."""
    table = []
    for height, hma, rev, turns in entries:
        if turns > 0:
            multiplier = round(hma / turns, 4)
        else:
            multiplier = 0
        table.append({
            "doorHeight": height,
            "multiplier": multiplier,
            "turns": round(turns, 1)
        })
    return table


# D850-132: section 1 only (heights 0-129)
d850_table = build_multiplier_table(section1)

# D1100-216: section 1 + section 2 (heights 0-218)
d1100_entries = section1 + section2
d1100_table = build_multiplier_table(d1100_entries)

# D1350-336: section 3 (heights 216-331)
d1350_table = build_multiplier_table(section3)

# ---- Write JSON files ----
out_dir = "backend/data/spring-calculator/drums/vertical-lift"
os.makedirs(out_dir, exist_ok=True)

drums = {
    "D850-132": {
        "model": "D850-132",
        "type": "vertical-lift",
        "minDoorHeight": d850_table[0]["doorHeight"],
        "maxDoorHeight": d850_table[-1]["doorHeight"],
        "multiplierTable": d850_table
    },
    "D1100-216": {
        "model": "D1100-216",
        "type": "vertical-lift",
        "minDoorHeight": d1100_entries[0][0],
        "maxDoorHeight": d1100_entries[-1][0],
        "multiplierTable": d1100_table
    },
    "D1350-336": {
        "model": "D1350-336",
        "type": "vertical-lift",
        "minDoorHeight": section3[0][0],
        "maxDoorHeight": section3[-1][0],
        "multiplierTable": d1350_table
    }
}

for name, data in drums.items():
    outpath = os.path.join(out_dir, f"{name}.json")
    with open(outpath, 'w') as f:
        json.dump(data, f, indent=2)
    n = len(data["multiplierTable"])
    h_min = data["minDoorHeight"]
    h_max = data["maxDoorHeight"]
    print(f"\n{name}: {n} entries ({h_min}-{h_max}\") -> {outpath}", file=sys.stderr)

# ---- Verify against Canimex example ----
print("\n--- Verification ---", file=sys.stderr)
# Example from Part5 page 8: D1100-216 at 165", multiplier=0.3750, turns=12.4
for entry in d1100_table:
    if entry["doorHeight"] == 165:
        print(f"D1100-216 at 165\": mult={entry['multiplier']}, turns={entry['turns']}", file=sys.stderr)
        print(f"  Canimex example: mult=0.3750, turns=12.4", file=sys.stderr)
        diff = abs(entry['multiplier'] - 0.3750)
        print(f"  Difference: {diff:.4f} ({diff/0.3750*100:.2f}%)", file=sys.stderr)
        break

# Also check D850-132 at 72"
for entry in d850_table:
    if entry["doorHeight"] == 72:
        print(f"D850-132 at 72\": mult={entry['multiplier']}, turns={entry['turns']}", file=sys.stderr)
        # HMA=3.225, TURNS=8.6, expected mult=3.225/8.6=0.375
        print(f"  Expected: mult=0.3750, turns=8.6", file=sys.stderr)
        break

print("\nDone!", file=sys.stderr)
