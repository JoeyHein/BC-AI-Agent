"""
Convert extracted high-lift drum .py files to JSON format for runtime loading.
Reads the Python dict files as text and converts to JSON.
"""
import json
import ast
import sys
import os
import re

def extract_data_from_py(filepath):
    """Extract the dict data from a _extracted.py file."""
    with open(filepath, 'r') as f:
        content = f.read()

    # Find the variable assignment: VAR_NAME = {
    match = re.search(r'(\w+_DATA)\s*=\s*(\{.+\})\s*$', content, re.DOTALL)
    if not match:
        print(f"Could not find DATA dict in {filepath}")
        return None, None

    var_name = match.group(1)
    dict_str = match.group(2)

    # Parse the dict using ast.literal_eval
    data = ast.literal_eval(dict_str)
    return var_name, data


def convert_drum(data, max_hl):
    """Convert drum data dict to JSON-serializable format."""
    all_heights = set()
    for hl_data in data.values():
        all_heights.update(hl_data.keys())

    # Convert keys to strings for JSON
    table = {}
    for hl, heights in sorted(data.items()):
        table[str(hl)] = {}
        for h, (multi, turns) in sorted(heights.items()):
            table[str(hl)][str(h)] = [multi, turns]

    return {
        "type": "high-lift",
        "min_height": min(all_heights),
        "max_height": max(all_heights),
        "max_hi_lift": max_hl,
        "table": table
    }


hl_dir = "backend/data/spring-calculator/drums/high-lift"

drums = [
    ("D400-54", 54),
    ("D525-54", 54),
    ("D575-120", 120),
    ("D6375-164", 164),
    ("D800-120", 120),
]

for name, max_hl in drums:
    py_path = os.path.join(hl_dir, f"{name}_extracted.py")
    if not os.path.exists(py_path):
        print(f"SKIP: {py_path} not found")
        continue

    var_name, data = extract_data_from_py(py_path)
    if data is None:
        continue

    result = convert_drum(data, max_hl)
    json_path = os.path.join(hl_dir, f"{name}.json")
    with open(json_path, 'w') as f:
        json.dump(result, f, indent=2)

    total_entries = sum(len(v) for v in data.values())
    print(f"{name}: {len(data)} HL rows, {total_entries} entries -> {json_path}")

print("\nDone!")
