#!/usr/bin/env python3
"""Insert the captured logs into REPORT.md.

Run after the checks:
    ./scripts/verify.sh
    ./scripts/experiments.sh
    (cd orders_service && uv run pytest -v) 2>&1 | tee logs/unit_tests.log
    python3 scripts/fill_report.py

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
    "experiments": ROOT / "logs" / "experiments.log",
}


def main() -> int:
    text = REPORT.read_text(encoding="utf-8")
    missing = []
    for name, path in BLOCKS.items():
        if not path.exists():
            missing.append(path.relative_to(ROOT))
            continue
        content = path.read_text(encoding="utf-8", errors="replace").rstrip()
        block = f"<!-- BEGIN:{name} -->\n```text\n{content}\n```\n<!-- END:{name} -->"
        pattern = re.compile(rf"<!-- BEGIN:{name} -->.*?<!-- END:{name} -->", re.DOTALL)
        text, count = pattern.subn(lambda _m: block, text)
        if count == 0:
            print(f"warning: no marker for '{name}' in REPORT.md")
    REPORT.write_text(text, encoding="utf-8")
    for path in missing:
        print(f"note: {path} not found - that block was left unchanged")
    print("REPORT.md updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
