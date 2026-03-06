"""
Extract high-lift drum multiplier tables from Canimex Cable Drum Catalog PDFs.
Handles continuation pages that have no HI-LIFT column (implicit row order).
"""
import fitz
import sys
import re
import json

sys.stdout.reconfigure(encoding='utf-8')


def load_pages(pdf_paths):
    """Load all pages from multiple PDFs."""
    pages = []
    for path in pdf_paths:
        doc = fitz.open(path)
        for i in range(doc.page_count):
            pages.append(doc[i].get_text())
        doc.close()
    return pages


def find_drum_pages(pages, drum_name):
    """Find page indices belonging to a drum's multiplier section."""
    drum_pages = []
    collecting = False
    other_drums = [d for d in ['D400-54', 'D525-54', 'D575-120', 'D6375-164', 'D800-120'] if d != drum_name]

    for i, text in enumerate(pages):
        if drum_name in text and 'MULTIPLIER' in text:
            collecting = True

        if collecting:
            # Stop at another drum's multiplier section
            if any(d in text and 'MULTIPLIER' in text for d in other_drums):
                collecting = False
                continue
            if 'VERTICAL-LIFT' in text or 'STATIONARY' in text or 'CLEVER PLUG' in text:
                collecting = False
                continue

            # Skip physical spec / illustration pages
            if 'PHYSICAL SPEC' in text or 'above illustrations' in text:
                continue

            drum_pages.append(i)

    return drum_pages


def parse_page(text, expected_hl_values):
    """Parse a single page of drum multiplier data.

    Args:
        text: Page text
        expected_hl_values: List of expected HI-LIFT values (e.g., [0, 3, 6, ..., 54])

    Returns:
        dict: {hl_value: {door_height: (multiplier, turns), ...}, ...}
    """
    lines = text.strip().split('\n')

    # 1. Extract door heights from header
    # Skip first line if it's just a page number (2-3 digits with no quotes)
    start_line = 0
    if lines and re.match(r'^\d{1,3}$', lines[0].strip()):
        start_line = 1

    door_heights = []
    for line in lines[start_line:20]:
        # Skip known non-height lines
        if 'DRUMS' in line or 'SPECIFICATION' in line or 'MULTIPLIER' in line or 'HIGH-LIFT' in line:
            continue
        # Match "96"" or bare "126" (some pages don't have quotes)
        matches = re.findall(r'(\d+)"', line)
        for val in matches:
            h = int(val)
            if 72 <= h <= 400:  # Min valid door height is 72"
                door_heights.append(h)
        if not matches:
            # Bare numbers on their own line
            m = re.match(r'^(\d{2,3})$', line.strip())
            if m:
                h = int(m.group(1))
                if 72 <= h <= 400:  # Min valid door height is 72"
                    door_heights.append(h)

    # Remove duplicates preserving order
    seen = set()
    unique = []
    for h in door_heights:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    door_heights = unique

    if not door_heights:
        return {}

    # 2. Determine if this page has HI-LIFT labels
    has_hl_column = any('HI-LIFT' in line or 'H.M.A' in line.upper() for line in lines[:30])

    # 3. Find where data starts (after headers)
    data_start = 0
    for i, line in enumerate(lines):
        if 'FACTOR' in line and i > 10:
            data_start = i + 1
            break

    if data_start == 0:
        # No FACTOR header found, try after TURNS
        for i, line in enumerate(lines):
            if i > 15 and re.match(r'^[\d.,]+$', line.strip()):
                data_start = i
                break

    # 4. Extract all numeric values from data area
    data_values = []
    for i in range(data_start, len(lines)):
        line = lines[i].strip()
        if line == '' or 'ZERO' in line or 'Over' in line or 'Between' in line or 'Under' in line:
            continue
        if 'DRUMS' in line or 'SPECIFICATION' in line:
            continue

        # Extract numbers and --- markers
        tokens = re.findall(r'[\d]+[.,]\d+|---+', line)
        for t in tokens:
            if '---' in t:
                data_values.append(None)
            else:
                data_values.append(float(t.replace(',', '.')))

    # 5. Parse data into rows
    num_heights = len(door_heights)

    if has_hl_column:
        # Each row: HL, HMA, REV, then (multi, turns, pitch) × num_heights
        values_per_row = 2 + (3 * num_heights)  # HMA + REV + triplets

        # But we need to also account for the HL value itself being on a separate line
        # Actually, the HL value might be mixed in. Let's find HL values in the data.

        # Re-scan: look for integer values that match expected HL values
        # The structure is: HL (int on own line), then HMA, REV, then data triplets

        result = {}
        idx = data_start
        hl_idx = 0

        while idx < len(lines) and hl_idx < len(expected_hl_values):
            line = lines[idx].strip()

            # Look for hi-lift value
            m = re.match(r'^(\d+)$', line)
            if m:
                hl = int(m.group(1))
                if hl in expected_hl_values or hl == expected_hl_values[hl_idx]:
                    # Collect numbers from following lines
                    nums = []
                    j = idx + 1
                    while j < len(lines) and len(nums) < 2 + 3 * num_heights:
                        next_line = lines[j].strip()
                        if next_line == '' or 'ZERO' in next_line or 'Over' in next_line:
                            break
                        # Check if next line is another HL value
                        m2 = re.match(r'^(\d+)$', next_line)
                        if m2 and int(m2.group(1)) in expected_hl_values and int(m2.group(1)) != hl:
                            break

                        tokens = re.findall(r'[\d]+[.,]\d+|---+', next_line)
                        for t in tokens:
                            if '---' in t:
                                nums.append(None)
                            else:
                                nums.append(float(t.replace(',', '.')))
                        j += 1

                    # Parse: skip HMA (idx 0) and REV (idx 1), then triplets
                    if len(nums) >= 2:
                        triplets = nums[2:]
                        result[hl] = {}
                        for h_idx in range(num_heights):
                            t_start = h_idx * 3
                            if t_start + 1 < len(triplets):
                                multi = triplets[t_start]
                                turns = triplets[t_start + 1]
                                if multi is not None and turns is not None:
                                    result[hl][door_heights[h_idx]] = (round(multi, 4), round(turns, 1))

                    hl_idx += 1
                    idx = j
                    continue

            idx += 1

        return result

    else:
        # Continuation page: no HL column. Data is just (multi, turns, pitch) × num_heights
        # for each HL row in order.
        values_per_row = 3 * num_heights

        result = {}
        idx = 0
        hl_idx = 0

        while idx + values_per_row <= len(data_values) and hl_idx < len(expected_hl_values):
            hl = expected_hl_values[hl_idx]
            row_data = data_values[idx:idx + values_per_row]

            result[hl] = {}
            for h_idx in range(num_heights):
                t_start = h_idx * 3
                multi = row_data[t_start]
                turns = row_data[t_start + 1]
                if multi is not None and turns is not None:
                    result[hl][door_heights[h_idx]] = (round(multi, 4), round(turns, 1))

            idx += values_per_row
            hl_idx += 1

        return result


def extract_drum(pages, drum_name, max_hl):
    """Extract complete drum data."""
    page_indices = find_drum_pages(pages, drum_name)
    print(f"\n{drum_name}: Found {len(page_indices)} pages", file=sys.stderr)

    # Generate expected HL values (0 to max_hl in 3" increments)
    expected_hl = list(range(0, max_hl + 1, 3))

    all_data = {}  # hl -> {height: (multi, turns)}

    for pi in page_indices:
        text = pages[pi]
        page_data = parse_page(text, expected_hl)

        for hl, heights in page_data.items():
            if hl not in all_data:
                all_data[hl] = {}
            all_data[hl].update(heights)

        # Show what we got
        if page_data:
            heights_found = set()
            for hl_data in page_data.values():
                heights_found.update(hl_data.keys())
            print(f"  Page {pi}: {len(page_data)} HL rows, heights: {sorted(heights_found)}", file=sys.stderr)

    # Summary
    hl_keys = sorted(all_data.keys())
    print(f"  Total: {len(hl_keys)} HL rows", file=sys.stderr)
    if hl_keys:
        # Check completeness
        expected_set = set(expected_hl)
        actual_set = set(hl_keys)
        missing = expected_set - actual_set
        if missing:
            print(f"  MISSING HL values: {sorted(missing)}", file=sys.stderr)
        # Show height coverage for first and last HL
        for hl in [hl_keys[0], hl_keys[-1]]:
            print(f"  HL={hl}: {sorted(all_data[hl].keys())}", file=sys.stderr)

    return all_data


def write_output(drum_name, data, max_hl):
    """Write extracted data as Python file."""
    outpath = f'backend/data/spring-calculator/drums/high-lift/{drum_name}_extracted.py'
    with open(outpath, 'w') as f:
        f.write(f"# {drum_name} High-Lift Drum Multiplier Table\n")
        f.write(f"# Extracted from Canimex Cable Drum Catalog\n")
        f.write(f"# Format: hi_lift_inches -> {{door_height_inches: (multiplier, turns)}}\n")
        f.write(f"# HL range: 0 to {max_hl} in 3\" increments\n\n")

        var_name = drum_name.replace('-', '_')
        f.write(f"{var_name}_DATA = {{\n")
        for hl in sorted(data.keys()):
            heights = data[hl]
            items = sorted(heights.items())
            f.write(f"    {hl}: {{")
            for k, (door_h, (m, t)) in enumerate(items):
                if k > 0:
                    f.write(", ")
                f.write(f"{door_h}: ({m}, {t})")
            f.write("},\n")
        f.write("}\n")

    print(f"  Written to {outpath}", file=sys.stderr)


# Main
pdf_paths = [
    'C:/Users/jhein/Downloads/Cable-Drum-Catalog.pdf_Part2.pdf',
    'C:/Users/jhein/Downloads/Cable-Drum-Catalog.pdf_Part3.pdf',
    'C:/Users/jhein/Downloads/Cable-Drum-Catalog.pdf_Part4.pdf',
]

pages = load_pages(pdf_paths)
print(f"Loaded {len(pages)} pages total", file=sys.stderr)

drums = [
    ('D400-54', 54),
    ('D525-54', 54),
    ('D575-120', 120),
    ('D6375-164', 164),
    ('D800-120', 120),
]

for drum_name, max_hl in drums:
    data = extract_drum(pages, drum_name, max_hl)
    write_output(drum_name, data, max_hl)

print("\nDone!", file=sys.stderr)
