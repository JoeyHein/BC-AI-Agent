"""
Extract D575-120 high-lift drum multiplier table from two PDF files using pymupdf.
Outputs a Python dict: {hi_lift_inches: {door_height: (multiplier, turns), ...}, ...}
"""
import fitz
import json

pdf_part2 = "C:/Users/jhein/Downloads/Cable-Drum-Catalog.pdf_Part2.pdf"
pdf_part3 = "C:/Users/jhein/Downloads/Cable-Drum-Catalog.pdf_Part3.pdf"

def extract_tables_from_page(doc, page_idx):
    """Extract tables from a page using pymupdf's find_tables."""
    page = doc[page_idx]
    tabs = page.find_tables()
    results = []
    for tab in tabs.tables:
        data = tab.extract()
        results.append(data)
    return results

def clean_val(s):
    """Clean a cell value - handle European decimals and missing values."""
    if s is None:
        return None
    s = s.strip()
    if s in ('---', '----', '--', '-', '', 'None'):
        return None
    # Replace European decimal comma with period
    s = s.replace(',', '.')
    return s

def parse_float(s):
    """Parse a cleaned string to float."""
    s = clean_val(s)
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None

# Collect all data
# Format: {hi_lift_inches: {door_height: (multiplier, turns), ...}, ...}
all_data = {}

def process_page(table, door_heights, has_hilift_col):
    """
    Process a single page's table data.

    has_hilift_col: True if page has HI-LIFT, H.M.A., REV OF SPIRAL columns (left pages)
                    False if page only has door height data columns (right/continuation pages)
    door_heights: list of door height values in inches for this page
    """
    # Skip header rows (first 3 rows: door height inches, door height feet, column names)
    data_rows = table[3:]

    for row_idx, row in enumerate(data_rows):
        hi_lift = row_idx * 3  # 0, 3, 6, 9, ... 120

        if hi_lift > 120:
            break

        if hi_lift not in all_data:
            all_data[hi_lift] = {}

        for dh_idx, dh in enumerate(door_heights):
            if has_hilift_col:
                # Columns: HI-LIFT, H.M.A., REV_OF_SPIRAL, then groups of 3 (MULTI, TURNS, PITCH)
                multi_col = 3 + dh_idx * 3
                turns_col = 4 + dh_idx * 3
            else:
                # Columns: groups of 3 (MULTI, TURNS, PITCH) only
                multi_col = dh_idx * 3
                turns_col = 1 + dh_idx * 3

            if multi_col >= len(row) or turns_col >= len(row):
                continue

            multi = parse_float(row[multi_col])
            turns = parse_float(row[turns_col])

            if multi is not None and turns is not None:
                all_data[hi_lift][dh] = (multi, turns)


# ---- Part 2 ----
doc2 = fitz.open(pdf_part2)

# Page 17: D575-120 first page - door heights 72, 78, 84, 90 (has HI-LIFT col)
tables = extract_tables_from_page(doc2, 17)
process_page(tables[0], [72, 78, 84, 90], has_hilift_col=True)

# Page 18: continuation - door heights 96, 102, 108, 114, 120 (no HI-LIFT col)
tables = extract_tables_from_page(doc2, 18)
process_page(tables[0], [96, 102, 108, 114, 120], has_hilift_col=False)

# Page 19: D575-120 continued - door heights 126, 132, 138, 144 (has HI-LIFT col)
tables = extract_tables_from_page(doc2, 19)
process_page(tables[0], [126, 132, 138, 144], has_hilift_col=True)

# Page 20: continuation - door heights 150, 156, 162, 168, 174 (no HI-LIFT col)
tables = extract_tables_from_page(doc2, 20)
process_page(tables[0], [150, 156, 162, 168, 174], has_hilift_col=False)

doc2.close()

# ---- Part 3 ----
doc3 = fitz.open(pdf_part3)

# Page 0: door heights 180, 186, 192, 198 (has HI-LIFT col)
tables = extract_tables_from_page(doc3, 0)
process_page(tables[0], [180, 186, 192, 198], has_hilift_col=True)

# Page 1: door heights 204, 210, 216, 222, 228 (no HI-LIFT col)
tables = extract_tables_from_page(doc3, 1)
process_page(tables[0], [204, 210, 216, 222, 228], has_hilift_col=False)

# Page 2: door heights 234, 240, 246, 252 (has HI-LIFT col)
tables = extract_tables_from_page(doc3, 2)
process_page(tables[0], [234, 240, 246, 252], has_hilift_col=True)

# Page 3: door heights 258, 264 (no HI-LIFT col)
tables = extract_tables_from_page(doc3, 3)
process_page(tables[0], [258, 264], has_hilift_col=False)

doc3.close()

# ---- Output ----
# Print summary
total_entries = sum(len(v) for v in all_data.values())
print(f"Extracted {total_entries} entries across {len(all_data)} hi-lift values")

# Print the data as a Python dict
print("\n# Complete D575-120 data:")
for hl in sorted(all_data.keys()):
    entries = all_data[hl]
    if entries:
        parts = []
        for dh in sorted(entries.keys()):
            m, t = entries[dh]
            parts.append(f"{dh}: ({m}, {t})")
        print(f"  {hl}: {{{', '.join(parts)}}}")
    else:
        print(f"  {hl}: {{}}")

# Write to output file
output_path = "C:/Users/jhein/bc-ai-agent/backend/data/spring-calculator/drums/high-lift/D575-120_extracted.py"
with open(output_path, 'w') as f:
    f.write('"""\n')
    f.write('D575-120 High-Lift Drum Multiplier Table\n')
    f.write('Extracted from Canimex Cable Drum Catalog\n')
    f.write('Format: {hi_lift_inches: {door_height_inches: (multiplier, turns), ...}, ...}\n')
    f.write('"""\n\n')
    f.write('D575_120_HIGH_LIFT = {\n')

    for hl in sorted(all_data.keys()):
        entries = all_data[hl]
        if entries:
            f.write(f'    {hl}: {{\n')
            for dh in sorted(entries.keys()):
                m, t = entries[dh]
                f.write(f'        {dh}: ({m}, {t}),\n')
            f.write('    },\n')
        else:
            f.write(f'    {hl}: {{}},\n')

    f.write('}\n')

print(f"\nData written to {output_path}")
