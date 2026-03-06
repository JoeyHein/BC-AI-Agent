"""
Extract standard-lift drum multiplier tables from Canimex Cable Drum Catalog Part1 PDF.
Each row: height_ft_in, height_inches, then values per column.
Columns vary per drum:
  D300-112: 10", 12", 15" radius + LHR (9 values: 10m, 10t, 12m, 12t, 15m, 15t, pitch, lhr_m, lhr_t)
  Others: 12", 15" radius + LHR (7 values: 12m, 12t, 15m, 15t, pitch, lhr_m, lhr_t)
"""
import fitz
import sys
import re
import json
import os

sys.stdout.reconfigure(encoding='utf-8')

pdf_path = 'backend/data/spring-calculator/reference/Cable-Drum-Catalog.pdf_Part1.pdf'
doc = fitz.open(pdf_path)


def get_page_lines(page_num):
    return doc[page_num].get_text().split('\n')


def parse_data_block(lines, start_idx, radii, max_height=None):
    """Parse a data block from the given starting line index.

    Args:
        lines: All lines from the page
        start_idx: Line index to start parsing data
        radii: List of radius values (e.g., [12, 15] or [10, 12, 15])
        max_height: Optional maximum door height to stop at

    Returns:
        dict: {radius: {height: (multi, turns)}, ..., "lhr": {height: (multi, turns)}}
    """
    result = {r: {} for r in radii}
    result["lhr"] = {}
    result["pitch"] = {}

    # Number of values per row: 2 per radius + pitch + 2 for LHR
    # e.g., [12, 15]: 12m, 12t, 15m, 15t, pitch, lhr_m, lhr_t = 7
    # e.g., [10, 12, 15]: 10m, 10t, 12m, 12t, 15m, 15t, pitch, lhr_m, lhr_t = 9
    values_per_row = len(radii) * 2 + 3  # +3 for pitch, lhr_multi, lhr_turns

    i = start_idx
    while i < len(lines):
        line = lines[i].strip()

        # Check for section breaks
        if 'TRACK RADIUS' in line or 'DRUMS SPECIFICATIONS' in line:
            # New section header — stop
            break
        if 'MULTIPLIER' in line and 'STANDARD' in line:
            break
        if 'CONTINUED' in line:
            break

        # Look for height line: "6'0''" or "10'0''" pattern
        # The special chars might be fancy quotes
        height_match = re.match(r"(\d+)\s*[\u2018\u2019'\u00b4`]+\s*(\d+)\s*[\u2018\u2019\"\u201c\u201d\u00b4`]+", line)
        if not height_match:
            i += 1
            continue

        feet = int(height_match.group(1))
        inches = int(height_match.group(2))
        door_height = feet * 12 + inches

        if max_height and door_height > max_height:
            break

        # Next line should be the height in inches
        i += 1
        if i >= len(lines):
            break
        inch_line = lines[i].strip()
        if not re.match(r'^\d{2,3}$', inch_line):
            continue
        height_verify = int(inch_line)
        if height_verify != door_height:
            print(f"  WARNING: height mismatch {door_height} vs {height_verify}", file=sys.stderr)
            door_height = height_verify

        # Collect the next values_per_row numeric values
        vals = []
        i += 1
        while i < len(lines) and len(vals) < values_per_row:
            val_line = lines[i].strip()
            if not val_line:
                i += 1
                continue
            # Is it a number?
            m = re.match(r'^(\d+[.,]\d+)$', val_line)
            if m:
                vals.append(float(m.group(1).replace(',', '.')))
                i += 1
                continue
            # Could also be just an integer (turns like "6" or "10")
            m = re.match(r'^(\d{1,3})(\.\d)?$', val_line)
            if m:
                vals.append(float(val_line.replace(',', '.')))
                i += 1
                continue
            # If it's not a number, stop collecting
            break

        if len(vals) < values_per_row:
            # Might have fewer values (some drums don't have LHR for all heights)
            pass

        # Map values to radii
        idx = 0
        for r in radii:
            if idx + 1 < len(vals):
                result[r][door_height] = (round(vals[idx], 4), round(vals[idx + 1], 1))
            idx += 2

        if idx < len(vals):
            result["pitch"][door_height] = round(vals[idx], 4)
            idx += 1

        if idx + 1 < len(vals):
            result["lhr"][door_height] = (round(vals[idx], 4), round(vals[idx + 1], 1))

    return result


def extract_drum(page_nums, drum_name, radii, start_height=None, max_height=None):
    """Extract a drum across one or more pages."""
    print(f"\n{drum_name}: pages {page_nums}", file=sys.stderr)

    all_data = {r: {} for r in radii}
    all_data["lhr"] = {}
    all_data["pitch"] = {}

    for pn in page_nums:
        lines = get_page_lines(pn)

        # Find data start: after the header rows
        data_start = 0
        for i, line in enumerate(lines):
            if 'TURNS ON' in line and i > 5:
                data_start = i + 1
                # Check if next line is also a header part (e.g., "SPRING")
                while data_start < len(lines) and lines[data_start].strip() in ['SPRING', '']:
                    data_start += 1
                break

        if data_start == 0:
            print(f"  Page {pn}: no data start found", file=sys.stderr)
            continue

        print(f"  Page {pn}: data starts at line {data_start}", file=sys.stderr)

        page_data = parse_data_block(lines, data_start, radii, max_height)

        for r in radii:
            all_data[r].update(page_data[r])
        all_data["lhr"].update(page_data["lhr"])
        all_data["pitch"].update(page_data["pitch"])

    # Summary
    for r in radii:
        heights = sorted(all_data[r].keys())
        if heights:
            print(f"  {r}\" radius: {len(heights)} heights ({heights[0]}-{heights[-1]})", file=sys.stderr)
    lhr_heights = sorted(all_data["lhr"].keys())
    if lhr_heights:
        print(f"  LHR: {len(lhr_heights)} heights ({lhr_heights[0]}-{lhr_heights[-1]})", file=sys.stderr)

    return all_data


# Page 14 has TWO drums split by a second header block.
# Handle D400-96 (top half) and D400-123 (bottom half) specially.
def extract_page14():
    lines = get_page_lines(14)

    # Find first data block (D400-96)
    data_start1 = 0
    header_count = 0
    for i, line in enumerate(lines):
        if 'TURNS ON SPRING' in line:
            header_count += 1
            if header_count == 1:
                data_start1 = i + 1

    # Find second header block (D400-123)
    data_start2 = 0
    header_count = 0
    for i, line in enumerate(lines):
        if 'TURNS ON SPRING' in line:
            header_count += 1
            if header_count == 2:
                data_start2 = i + 1

    print(f"\nD400-96: page 14 (data starts at {data_start1})", file=sys.stderr)
    d96_data = parse_data_block(lines, data_start1, [12, 15], max_height=98)

    print(f"\nD400-123: page 14 (data starts at {data_start2})", file=sys.stderr)
    d123_data = parse_data_block(lines, data_start2, [12, 15], max_height=125)

    for name, data in [("D400-96", d96_data), ("D400-123", d123_data)]:
        for r in [12, 15]:
            heights = sorted(data[r].keys())
            if heights:
                print(f"  {name} {r}\" radius: {len(heights)} heights ({heights[0]}-{heights[-1]})", file=sys.stderr)
        lhr_heights = sorted(data["lhr"].keys())
        if lhr_heights:
            print(f"  {name} LHR: {len(lhr_heights)} heights ({lhr_heights[0]}-{lhr_heights[-1]})", file=sys.stderr)

    return d96_data, d123_data


# Extract all drums
drums = {}

# D300-112 (page 12) — has 10", 12", 15" radius
drums["D300-112"] = extract_drum([12], "D300-112", [10, 12, 15])

# D300-144 (page 13)
drums["D300-144"] = extract_drum([13], "D300-144", [12, 15])

# D400-96 and D400-123 (page 14 — split)
d96, d123 = extract_page14()
drums["D400-96"] = d96
drums["D400-123"] = d123

# D400-144 (page 15)
drums["D400-144"] = extract_drum([15], "D400-144", [12, 15])

# D525-216 (pages 16-17)
drums["D525-216"] = extract_drum([16, 17], "D525-216", [12, 15])

# D800-384 (pages 18-20)
drums["D800-384"] = extract_drum([18, 19, 20], "D800-384", [12, 15])


# Write JSON output files
out_dir = "backend/data/spring-calculator/drums/standard-lift"
os.makedirs(out_dir, exist_ok=True)

for name, data in drums.items():
    # Determine radii from data
    radii = [r for r in data.keys() if isinstance(r, int) and data[r]]

    # Build JSON structure
    table = {}
    # Get all heights
    all_heights = set()
    for r in radii:
        all_heights.update(data[r].keys())
    all_heights = sorted(all_heights)

    for h in all_heights:
        table[str(h)] = {}
        for r in radii:
            if h in data[r]:
                multi, turns = data[r][h]
                table[str(h)][str(r)] = [multi, turns]
        if h in data.get("lhr", {}):
            multi, turns = data["lhr"][h]
            table[str(h)]["lhr"] = [multi, turns]
        if h in data.get("pitch", {}):
            table[str(h)]["pitch_factor"] = data["pitch"][h]

    result = {
        "type": "standard-lift",
        "min_height": min(all_heights) if all_heights else 0,
        "max_height": max(all_heights) if all_heights else 0,
        "radii": radii,
        "table": table
    }

    outpath = os.path.join(out_dir, f"{name}.json")
    with open(outpath, 'w') as f:
        json.dump(result, f, indent=2)

    total = sum(len(v) - (1 if 'pitch_factor' in v else 0) for v in table.values())
    print(f"\n{name}: {len(all_heights)} heights, {total} entries -> {outpath}", file=sys.stderr)

doc.close()
print("\nDone!", file=sys.stderr)
