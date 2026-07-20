#!/usr/bin/env python3
"""Validate compact v2: size savings + protected data coverage vs legacy payload."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import compact_declaration  # noqa: E402


PROTECTED_FRAGMENTS = (
    "workPlace",
    "workPost",
    "sizeIncome",
    "costDate",
    "cost_date_assessment",
    "establishment_ua_company_name",
    "establishment_ua_company_code",
    "person_open_account",
    "sources",
)


def collect_strings(obj, out: list[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            collect_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_strings(v, out)
    elif obj is not None and not isinstance(obj, (bool, int, float)):
        s = str(obj).strip()
        if s and s not in {"[Конфіденційна інформація]", "[Не застосовується]"}:
            out.append(s)


def main() -> int:
    compact_root = ROOT / "compact"
    errors: list[str] = []
    total_legacy = 0
    total_v2 = 0
    unknown_type_before = 0
    unknown_type_after = 0
    fin_inst_count = 0

    for raw_path in sorted(compact_root.rglob("raw_declaration.json")):
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        decl_id = str(raw.get("id") or raw_path.parent.name)
        legacy = compact_declaration(raw, legacy_payload=True)
        v2 = compact_declaration(raw, legacy_payload=False)

        legacy_s = json.dumps(legacy, ensure_ascii=False)
        v2_s = json.dumps(v2, ensure_ascii=False)
        total_legacy += len(legacy_s)
        total_v2 += len(v2_s)

        if legacy.get("step_0_interpreted", {}).get("declaration_type_label") == "Невідомий тип":
            unknown_type_before += 1
        if v2.get("step_0_interpreted", {}).get("declaration_type_label") == "Невідомий тип":
            unknown_type_after += 1

        fin = v2.get("financial_institutions") or []
        if fin:
            fin_inst_count += 1
            payload17 = (legacy.get("all_nonempty_steps_payload") or {}).get("step_17") or []
            legacy_names = {
                str(x.get("establishment_ua_company_name", "")).strip()
                for x in payload17
                if isinstance(x, dict)
            }
            v2_names = {
                str(x.get("establishment_ua_company_name", "")).strip()
                for x in fin
                if isinstance(x, dict)
            }
            missing = legacy_names - v2_names - {""}
            if missing:
                errors.append(f"{decl_id}: missing bank names in financial_institutions: {missing}")

        if "all_nonempty_steps_payload" in v2:
            errors.append(f"{decl_id}: v2 must not include legacy payload unless flag set")

        payload = legacy.get("all_nonempty_steps_payload") or {}
        legacy_text: list[str] = []
        collect_strings(payload, legacy_text)
        v2_text: list[str] = []
        collect_strings({k: v for k, v in v2.items() if k != "steps_context"}, v2_text)
        legacy_blob = "\n".join(legacy_text)

        for frag in PROTECTED_FRAGMENTS:
            if frag in legacy_blob and frag not in v2_s and not any(frag in t for t in v2_text):
                # workPlace/workPost may be renamed to work_place/work_post in meta
                if frag in {"workPlace", "workPost"}:
                    alt = "work_place" if frag == "workPlace" else "work_post"
                    if alt in v2_s:
                        continue
                errors.append(f"{decl_id}: protected fragment '{frag}' may be missing in v2")

        nonempty = set((legacy.get("steps_context") or {}).get("nonempty_steps") or [])
        covered = {
            f"step_{n}"
            for n in (0, 1, 2, 3, 4, 6, 9, 11, 12, 13, 14, 15, 17)
        }
        extras = set((v2.get("raw_extras") or {}).keys())
        uncovered = nonempty - covered
        if uncovered != extras:
            errors.append(
                f"{decl_id}: raw_extras mismatch uncovered={sorted(uncovered)} extras={sorted(extras)}"
            )

    n = max(1, len(list(compact_root.rglob("raw_declaration.json"))))
    savings = 100 * (1 - total_v2 / max(total_legacy, 1))
    print(f"declarations: {n}")
    print(f"avg legacy chars: {total_legacy // n:,}")
    print(f"avg v2 chars: {total_v2 // n:,}")
    print(f"savings: {savings:.1f}%")
    print(f"unknown type before/after: {unknown_type_before}/{unknown_type_after}")
    print(f"declarations with financial_institutions: {fin_inst_count}/{n}")

    if errors:
        print("\nERRORS:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("\nOK: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
