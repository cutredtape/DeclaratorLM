"""Compare two test corpus report folders (exclude broken decl_00000000)."""
from __future__ import annotations

import csv
import json
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List

EXCLUDE_DECL_ID = "00000000-0000-0000-0000-000000000000"

THEME_KEYWORDS = {
    "energy_wife": r"сонячн|енерг|альтенер|євроімекс|гідро",
    "dividends": r"дивіденд",
    "conflict": r"конфлікт",
    "children_assets": r"діт|син|дочк",
    "realty_valuation": r"нерухом|оцінк|вартість",
    "cash_fx": r"usd|eur|готів|валют",
    "vehicle_scheme": r"lexus|audi|q8|авто",
    "gift_other_income": r"подарун|інше|іншого",
}


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_summary(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_findings(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def filter_rows(rows: List[Dict[str, Any]], id_field: str = "declaration_id") -> List[Dict[str, Any]]:
    return [r for r in rows if r.get(id_field) != EXCLUDE_DECL_ID]


def theme_hits(text: str) -> Dict[str, bool]:
    t = (text or "").lower()
    return {k: bool(re.search(p, t, re.I)) for k, p in THEME_KEYWORDS.items()}


def analyze_run(name: str, base: Path) -> Dict[str, Any]:
    jsonl = filter_rows(load_jsonl(base / "analysis_results.jsonl"))
    summary = [r for r in load_summary(base / "report_summary.csv") if r["declaration_id"] != EXCLUDE_DECL_ID]
    findings_rows = [
        r
        for r in load_findings(base / "report_findings.csv")
        if r["declaration_id"] != EXCLUDE_DECL_ID
    ]

    n = len(jsonl)
    scores = []
    fc = []
    fa_lens = []
    rf_lens = []
    nv_lens = []
    payload_chars = []
    themes_per_decl: List[Dict[str, bool]] = []
    empty_fa = 0
    name_variants = set()

    for item in jsonl:
        a = item.get("analysis", {})
        scores.append(float(a.get("risk_score") or 0))
        findings = a.get("findings") or []
        fc.append(len(findings))
        fa = str(a.get("final_assessment") or "").strip()
        fa_lens.append(len(fa))
        if not fa:
            empty_fa += 1
        rf_lens.append(len(" | ".join(a.get("red_flags") or [])))
        nv_lens.append(len(" | ".join(a.get("needs_verification") or [])))
        payload_chars.append(item.get("context_snapshot", {}).get("payload_chars_sent") or 0)
        sp = a.get("subject_profile", {})
        name_variants.add(str(sp.get("declarant_full_name", "")).strip())
        blob = json.dumps(a, ensure_ascii=False)
        themes_per_decl.append(theme_hits(blob))

    # findings csv depth
    ev_lens = [len(r.get("evidence", "")) for r in findings_rows]
    rat_lens = [len(r.get("rationale", "")) for r in findings_rows]
    sev = [r.get("severity", "") for r in findings_rows]

    theme_coverage = {}
    for key in THEME_KEYWORDS:
        theme_coverage[key] = sum(1 for t in themes_per_decl if t.get(key)) / max(n, 1)

    risk_levels = [r.get("risk_level", "") for r in summary]

    return {
        "name": name,
        "path": str(base),
        "run_started": summary[0].get("run_started_at", "") if summary else "",
        "declarations": n,
        "risk_score_mean": round(statistics.mean(scores), 1) if scores else 0,
        "risk_score_median": round(statistics.median(scores), 1) if scores else 0,
        "risk_score_min": min(scores) if scores else 0,
        "risk_score_max": max(scores) if scores else 0,
        "critical_count": sum(1 for r in summary if r.get("risk_level") == "critical"),
        "high_count": sum(1 for r in summary if r.get("risk_level") == "high"),
        "low_count": sum(1 for r in summary if r.get("risk_level") == "low"),
        "findings_count_mean": round(statistics.mean(fc), 2) if fc else 0,
        "findings_count_total": sum(fc),
        "findings_csv_rows": len(findings_rows),
        "empty_final_assessment": empty_fa,
        "final_assessment_len_mean": round(statistics.mean(fa_lens), 0) if fa_lens else 0,
        "red_flags_len_mean": round(statistics.mean(rf_lens), 0) if rf_lens else 0,
        "needs_verification_len_mean": round(statistics.mean(nv_lens), 0) if nv_lens else 0,
        "payload_chars_mean": round(statistics.mean(payload_chars), 0) if payload_chars else 0,
        "evidence_len_mean": round(statistics.mean(ev_lens), 0) if ev_lens else 0,
        "rationale_len_mean": round(statistics.mean(rat_lens), 0) if rat_lens else 0,
        "severity_critical_pct": round(100 * sev.count("critical") / max(len(sev), 1), 1),
        "theme_coverage_pct": {k: round(100 * v, 1) for k, v in theme_coverage.items()},
        "name_variants": sorted(name_variants),
        "by_year": {
            str(item.get("context_snapshot", {}).get("declaration_year", "")): float(
                item.get("analysis", {}).get("risk_score") or 0
            )
            for item in jsonl
        },
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "deep_research"
    v23 = analyze_run("v2-3 compact", root / "Тестовий_10001 (v2-3 c)")
    v24 = analyze_run("v2-4 compact+raw", root / "Тестовий_10001 (v2-4 c+raw)")
    print(json.dumps({"v23": v23, "v24": v24}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
