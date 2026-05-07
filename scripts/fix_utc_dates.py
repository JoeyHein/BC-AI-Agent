"""One-shot: convert `new Date(<expr>).toLocaleString/DateString/TimeString(...)`
calls to formatDateTime/formatDate/formatTime helpers from utils/datetime.js,
preserving args and adding the import to each file that gets touched.

Skips `new Date()` (no argument) since those are 'now' and don't need UTC parse.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend" / "src"
PATTERN = re.compile(
    r"new Date\(\s*([^)\s][^)]*?)\s*\)\.toLocale(String|DateString|TimeString)\((.*?)\)",
    re.DOTALL,
)
HELPER_FOR = {
    "String": "formatDateTime",
    "DateString": "formatDate",
    "TimeString": "formatTime",
}

def relative_import_path(file_path: Path) -> str:
    rel = Path("utils/datetime")
    src = file_path.parent.relative_to(ROOT)
    depth = len(src.parts)
    prefix = "../" * depth if depth else "./"
    return prefix + str(rel).replace("\\", "/")

def transform(src: str, file_path: Path):
    used = set()
    def sub(m):
        expr, kind, args = m.group(1), m.group(2), m.group(3).strip()
        helper = HELPER_FOR[kind]
        used.add(helper)
        if args:
            return f"{helper}({expr}, {args})"
        return f"{helper}({expr})"
    new_src, n = PATTERN.subn(sub, src)
    if n == 0:
        return src, 0, set()

    # Add import. Look for an existing import from utils/datetime; if present,
    # merge. Otherwise append after the last import line at the top of the file.
    if used:
        existing = re.search(
            r"^import \{([^}]*)\} from ['\"][^'\"]*utils/datetime['\"]",
            new_src,
            re.MULTILINE,
        )
        if existing:
            current = {x.strip() for x in existing.group(1).split(",") if x.strip()}
            merged = sorted(current | used)
            new_src = (
                new_src[: existing.start()]
                + f"import {{ {', '.join(merged)} }} from '{relative_import_path(file_path)}'"
                + new_src[existing.end() :]
            )
        else:
            import_line = (
                f"import {{ {', '.join(sorted(used))} }} "
                f"from '{relative_import_path(file_path)}'"
            )
            # Insert after the last contiguous import line at file top
            lines = new_src.split("\n")
            last_import = -1
            for i, line in enumerate(lines):
                if line.startswith("import ") or line.startswith("import("):
                    last_import = i
                elif last_import >= 0 and line.strip() and not line.startswith("//"):
                    break
            if last_import >= 0:
                lines.insert(last_import + 1, import_line)
            else:
                lines.insert(0, import_line)
            new_src = "\n".join(lines)
    return new_src, n, used


def main():
    total = 0
    files = sorted(ROOT.rglob("*.jsx")) + sorted(ROOT.rglob("*.js"))
    for f in files:
        # Don't touch the helper itself or drawingExport (uses `new Date()` for "now")
        if f.name == "datetime.js":
            continue
        try:
            src = f.read_text(encoding="utf-8")
        except Exception:
            continue
        new_src, n, used = transform(src, f)
        if n > 0:
            f.write_text(new_src, encoding="utf-8")
            total += n
            rel = f.relative_to(ROOT)
            print(f"  {rel}: {n} replaced ({', '.join(sorted(used))})")
    print(f"\nTotal: {total} replacements")


if __name__ == "__main__":
    main()
