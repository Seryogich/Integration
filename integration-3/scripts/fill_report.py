#!/usr/bin/env python3
"""Insert the captured logs into REPORT.md.

    python scripts/verify.py --with-docker --restart-experiment     # writes logs/verify.log
    (cd orders_service && uv run pytest -v) > logs/unit_tests.log   # or copy the output by hand
    python scripts/fill_report.py

Every block  <!-- BEGIN:name --> ... <!-- END:name -->  in REPORT.md is replaced by the
content of logs/<file> in a fenced code block. Running the script again refreshes the blocks.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "REPORT.md"
BLOCKS = {
    "unit_tests": ROOT / "logs" / "unit_tests.log",
    "verify": ROOT / "logs" / "verify.log",
}


def read_log(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1251"):  # PowerShell redirection may produce UTF-16
        try:
            return raw.decode(enc).rstrip()
        except UnicodeError:
            continue
    return raw.decode("utf-8", errors="replace").rstrip()


def main() -> int:
    text = REPORT.read_text(encoding="utf-8")
    for name, path in BLOCKS.items():
        if not path.exists():
            print(f"note: {path.relative_to(ROOT)} not found - block '{name}' left unchanged")
            continue
        block = f"<!-- BEGIN:{name} -->\n```text\n{read_log(path)}\n```\n<!-- END:{name} -->"
        pattern = re.compile(rf"<!-- BEGIN:{name} -->.*?<!-- END:{name} -->", re.DOTALL)
        text, count = pattern.subn(lambda _m: block, text)
        if count == 0:
            print(f"warning: no marker for '{name}' in REPORT.md")
    REPORT.write_text(text, encoding="utf-8")
    print("REPORT.md updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
