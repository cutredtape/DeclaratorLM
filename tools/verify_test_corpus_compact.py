#!/usr/bin/env python3
"""Verify compact v2 interpretation on Тестовий declaration corpus."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import as_list, compact_declaration  # noqa: E402

PERSON_ID_RE = re.compile(r"Особа id=")

RAW_DIRS = [
    ROOT / "deep_research" / "Тестовий_10001",
    ROOT / "deep_research" / "Тестовий_10001 (v2-1)",
    ROOT / "deep_research" / "Тестовий аудит",
]


def collect_raw_paths() -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for base in RAW_DIRS:
        if not base.exists():
            continue
        for pattern in ("decl_*.json", "*/raw_declaration.json"):
            for path in sorted(base.glob(pattern)):
                key = path.stem if path.name.startswith("decl_") else path.parent.name
                if key in seen:
                    continue
                seen.add(key)
                paths.append(path)
    return paths


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    errors: list[str] = []
    stats = {
        "declarations": 0,
        "person_id_labels": 0,
        "corporate_missing_name": 0,
        "corporate_missing_owners": 0,
        "income_raw_person": 0,
        "unknown_type": 0,
        "bad_j_holders": 0,
        "raw_extras_unresolved_person": 0,
    }

    for raw_path in collect_raw_paths():
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        decl_id = raw.get("id") or raw_path.stem
        stats["declarations"] += 1

        compact = compact_declaration(raw, legacy_payload=False)
        blob = json.dumps(compact, ensure_ascii=False)

        if PERSON_ID_RE.search(blob):
            stats["person_id_labels"] += 1
            errors.append(f"{decl_id}: contains «Особа id=»")

        if compact.get("step_0_interpreted", {}).get("declaration_type_label") == "Невідомий тип":
            stats["unknown_type"] += 1
            errors.append(f"{decl_id}: declaration_type_label is «Невідомий тип»")

        raw_cr = as_list(raw.get("data", {}).get("step_9", {}).get("data"))
        compact_cr = compact.get("corporate_rights") or []
        for ri, ci in zip(raw_cr, compact_cr):
            raw_name = str(ri.get("name") or ri.get("company_name_beneficial_owner") or "").strip()
            if raw_name and not ci.get("company_name"):
                stats["corporate_missing_name"] += 1
                errors.append(f"{decl_id}: corporate_rights missing company_name for {raw_name[:50]!r}")
            if ri.get("person") and not ci.get("owners"):
                stats["corporate_missing_owners"] += 1
                errors.append(f"{decl_id}: corporate_rights missing owners for person={ri.get('person')}")

        for inc in compact.get("incomes") or []:
            pwc = inc.get("person_who_care")
            if isinstance(pwc, list):
                for entry in pwc:
                    if isinstance(entry, dict) and entry.get("person"):
                        stats["income_raw_person"] += 1
                        errors.append(f"{decl_id}: income person_who_care still raw dict")

        for sec in ("real_estate", "vehicles", "cash_assets", "unfinished_construction"):
            for it in compact.get(sec) or []:
                for owner in it.get("owners_or_users") or []:
                    if "id=j" in str(owner) or re.search(r"Особа id=[a-z]$", str(owner)):
                        stats["bad_j_holders"] += 1
                        errors.append(f"{decl_id}: bad holder in {sec}: {owner}")

        extras = compact.get("raw_extras") or {}
        for step_key, payload in extras.items():
            items: list = []
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict):
                for value in payload.values():
                    if isinstance(value, list):
                        items.extend(value)
            for item in items:
                if not isinstance(item, dict):
                    continue
                person = item.get("person")
                if person is not None and str(person).strip() and not item.get("person_resolved"):
                    stats["raw_extras_unresolved_person"] += 1
                    errors.append(f"{decl_id}: {step_key} person without person_resolved")

    print(f"Declarations checked: {stats['declarations']}")
    print(f"  person_id labels: {stats['person_id_labels']}")
    print(f"  unknown type: {stats['unknown_type']}")
    print(f"  corporate missing name: {stats['corporate_missing_name']}")
    print(f"  corporate missing owners: {stats['corporate_missing_owners']}")
    print(f"  income raw person_who_care: {stats['income_raw_person']}")
    print(f"  bad j holders: {stats['bad_j_holders']}")
    print(f"  raw_extras unresolved person: {stats['raw_extras_unresolved_person']}")

    if errors:
        print("\nFAILURES (first 15):")
        for err in errors[:15]:
            print(f"  - {err}")
        if len(errors) > 15:
            print(f"  ... and {len(errors) - 15} more")
        return 1

    print("\nOK: all test corpus compact checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
