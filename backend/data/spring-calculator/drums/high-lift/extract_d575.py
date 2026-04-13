"""
Extract D575-120 high-lift drum multiplier table from two PDF files using pymupdf.
"""
import fitz
import json
import re

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

# Process Part2 pages for D575-120
print("Processing Part 2...")
doc2 = fitz.open(pdf_part2)

# Page 17 (pdf page 38): D575-120 first page - door heights 72, 78, 84, 90
# This page has HI-LIFT column + H.M.A. + REV OF SPIRAL + then 4 door heights
tables = extract_tables_from_page(doc2, 17)
print(f"Part2 Page 17: {len(tables)} tables found")
for t_idx, table in enumerate(tables):
    print(f"  Table {t_idx}: {len(table)} rows x {len(table[0]) if table else 0} cols")
    if table:
        # Print first few rows to understand structure
        for r in table[:6]:
            print(f"    {r}")
        print("    ...")
        for r in table[-3:]:
            print(f"    {r}")

# Page 18 (pdf page 39): continuation - door heights 96, 102, 108, 114, 120
tables = extract_tables_from_page(doc2, 18)
print(f"\nPart2 Page 18: {len(tables)} tables found")
for t_idx, table in enumerate(tables):
    print(f"  Table {t_idx}: {len(table)} rows x {len(table[0]) if table else 0} cols")
    if table:
        for r in table[:6]:
            print(f"    {r}")
        print("    ...")
        for r in table[-3:]:
            print(f"    {r}")

# Page 19 (pdf page 40): D575-120 continued - door heights 126, 132, 138, 144
tables = extract_tables_from_page(doc2, 19)
print(f"\nPart2 Page 19: {len(tables)} tables found")
for t_idx, table in enumerate(tables):
    print(f"  Table {t_idx}: {len(table)} rows x {len(table[0]) if table else 0} cols")
    if table:
        for r in table[:6]:
            print(f"    {r}")
        print("    ...")

# Page 20 (pdf page 41): door heights 150, 156, 162, 168, 174
tables = extract_tables_from_page(doc2, 20)
print(f"\nPart2 Page 20: {len(tables)} tables found")
for t_idx, table in enumerate(tables):
    print(f"  Table {t_idx}: {len(table)} rows x {len(table[0]) if table else 0} cols")
    if table:
        for r in table[:6]:
            print(f"    {r}")
        print("    ...")

doc2.close()

# Process Part3 pages for D575-120
print("\n\nProcessing Part 3...")
doc3 = fitz.open(pdf_part3)

# Page 0 (pdf page 42): door heights 180, 186, 192, 198
tables = extract_tables_from_page(doc3, 0)
print(f"Part3 Page 0: {len(tables)} tables found")
for t_idx, table in enumerate(tables):
    print(f"  Table {t_idx}: {len(table)} rows x {len(table[0]) if table else 0} cols")
    if table:
        for r in table[:6]:
            print(f"    {r}")
        print("    ...")

# Page 1 (pdf page 43): door heights 204, 210, 216, 222, 228
tables = extract_tables_from_page(doc3, 1)
print(f"\nPart3 Page 1: {len(tables)} tables found")
for t_idx, table in enumerate(tables):
    print(f"  Table {t_idx}: {len(table)} rows x {len(table[0]) if table else 0} cols")
    if table:
        for r in table[:6]:
            print(f"    {r}")
        print("    ...")

# Page 2 (pdf page 44): door heights 234, 240, 246, 252
tables = extract_tables_from_page(doc3, 2)
print(f"\nPart3 Page 2: {len(tables)} tables found")
for t_idx, table in enumerate(tables):
    print(f"  Table {t_idx}: {len(table)} rows x {len(table[0]) if table else 0} cols")
    if table:
        for r in table[:6]:
            print(f"    {r}")
        print("    ...")

# Page 3 (pdf page 45): door heights 258, 264
tables = extract_tables_from_page(doc3, 3)
print(f"\nPart3 Page 3: {len(tables)} tables found")
for t_idx, table in enumerate(tables):
    print(f"  Table {t_idx}: {len(table)} rows x {len(table[0]) if table else 0} cols")
    if table:
        for r in table[:6]:
            print(f"    {r}")
        print("    ...")
        for r in table[-5:]:
            print(f"    {r}")

doc3.close()
