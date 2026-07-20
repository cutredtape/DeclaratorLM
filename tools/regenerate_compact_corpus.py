#!/usr/bin/env python3
"""Regenerate compact_declaration.json snapshots from raw_declaration.json in ./compact."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import compact_declaration  # noqa: E402


def main() -> int:
    compact_root = ROOT / "compact"
    updated = 0
    for raw_path in sorted(compact_root.rglob("raw_declaration.json")):
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        compact = compact_declaration(raw, legacy_payload=False)
        out_path = raw_path.parent / "compact_declaration.json"
        out_path.write_text(
            json.dumps(compact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        updated += 1
        print(f"updated {out_path.relative_to(ROOT)}")
    print(f"done: {updated} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
