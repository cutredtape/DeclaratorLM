"""Build time-series chart data for deep-research dossier mode."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from report import _as_dict, dedupe_by_latest, profile_value, read_jsonl, to_float, to_str_list
from usage_dashboard import _declaration_year, _risk_score

_FOLDER_UID_RE = re.compile(r"_(\d+)$")

# Declaration type codes (main.DECLARATION_TYPE_MAP): only these enter dossier charts.
_DOSSIER_CHART_TYPE_CODES = frozenset({"1", "2"})  # Annual; Before dismissal


def is_deep_research_dir(input_dir: Path, base_dir: Path) -> bool:
    try:
        root = (base_dir / "deep_research").resolve()
        return input_dir.resolve().is_relative_to(root)
    except (OSError, ValueError):
        return False


def _user_id_from_folder(dir_path: Path) -> Optional[int]:
    m = _FOLDER_UID_RE.search(dir_path.name)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _person_from_compact(compact: Dict[str, Any]) -> Dict[str, str]:
    meta = _as_dict(compact.get("meta"))
    decl = _as_dict(meta.get("declarant"))
    parts = [
        str(decl.get("lastname", "")).strip(),
        str(decl.get("firstname", "")).strip(),
        str(decl.get("middlename", "")).strip(),
    ]
    name = " ".join(p for p in parts if p)
    return {
        "name": name,
        "position": str(decl.get("work_post", "")).strip(),
        "workplace": str(decl.get("work_place", "")).strip(),
    }


def _land_count(compact: Dict[str, Any]) -> int:
    real_estate = compact.get("real_estate")
    if not isinstance(real_estate, list):
        real_estate = []
    land = 0
    for item in real_estate:
        if not isinstance(item, dict):
            continue
        ot = str(item.get("objectType") or "").lower()
        if "land" in ot or "земл" in ot:
            land += 1
    if land == 0:
        unfinished = compact.get("unfinished_construction")
        if isinstance(unfinished, list):
            land = len(unfinished)
    return land


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _financials_from_compact(compact: Dict[str, Any]) -> Dict[str, Any]:
    qt = _as_dict(compact.get("quick_totals"))
    income = _optional_float(qt.get("income_total_uah_estimated"))
    liab = _optional_float(qt.get("liabilities_total_estimated"))
    cash = _optional_float(qt.get("cash_assets_total_estimated")) or 0.0
    realty = _optional_float(qt.get("realty_declared_cost_total_estimated")) or 0.0
    vehicle = _optional_float(qt.get("vehicle_declared_cost_total_estimated")) or 0.0
    assets_sum = cash + realty + vehicle
    assets: Optional[float] = assets_sum if assets_sum > 0 else None
    if assets is None and (cash or realty or vehicle):
        assets = 0.0
    return {
        "income": income,
        "assets": assets,
        "liab": liab,
        "realty": len(compact.get("real_estate") or []),
        "autos": len(compact.get("vehicles") or []),
        "land": _land_count(compact),
    }


def _year_from_compact(compact: Dict[str, Any]) -> int:
    meta = _as_dict(compact.get("meta"))
    yr = meta.get("declaration_year")
    try:
        return int(yr) if yr is not None else 0
    except (TypeError, ValueError):
        return 0


def _analysis_metrics(item: Dict[str, Any]) -> Dict[str, Any]:
    analysis = _as_dict(item.get("analysis"))
    findings = analysis.get("findings", [])
    finds = len(findings) if isinstance(findings, list) else 0
    flags = len(to_str_list(analysis.get("red_flags")))
    return {
        "risk": int(round(_risk_score(item))),
        "finds": finds,
        "flags": flags,
        "risk_level": str(analysis.get("risk_level", "")).strip().lower() or "low",
    }


def _declaration_type_code_from_compact(compact: Dict[str, Any]) -> str:
    from main import _declaration_type_fields_from_compact

    code, _ = _declaration_type_fields_from_compact(compact)
    return str(code or "").strip()


def _include_in_dossier_charts(compact: Dict[str, Any]) -> bool:
    return _declaration_type_code_from_compact(compact) in _DOSSIER_CHART_TYPE_CODES


def _load_errors_by_source(errors_path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if errors_path is None or not errors_path.is_file():
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for row in read_jsonl(errors_path):
        if not isinstance(row, dict):
            continue
        src = str(row.get("source_file", "")).strip()
        if src:
            out[src] = row
    return out


def build_dossier_chart_series(
    input_dir: Path,
    output_jsonl: Path,
    *,
    base_dir: Path,
    errors_jsonl: Optional[Path] = None,
    no_dedupe: bool = False,
) -> Dict[str, Any]:
    """Aggregate per-declaration metrics for dossier charts."""
    if not is_deep_research_dir(input_dir, base_dir):
        return {
            "ok": False,
            "error": "input_dir не всередині deep_research",
        }

    from main import compact_declaration, sort_declaration_files_chronologically

    if not input_dir.is_dir():
        return {"ok": False, "error": "Каталог досьє не знайдено"}

    files = sort_declaration_files_chronologically(list(input_dir.glob("decl_*.json")))
    if not files:
        return {
            "ok": True,
            "person": {"name": "", "position": "", "workplace": "", "user_declarant_id": None},
            "years": [],
            "records": [],
            "processed_count": 0,
            "planned_total": 0,
            "avg_duration_sec": 0.0,
        }

    raw_rows: List[Dict[str, Any]] = []
    if output_jsonl.is_file():
        raw_rows = read_jsonl(output_jsonl)
    rows = raw_rows if no_dedupe else dedupe_by_latest(raw_rows)
    by_source: Dict[str, Dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        src = str(item.get("source_file", "")).strip()
        if src:
            by_source[src] = item

    errors_by_source = _load_errors_by_source(errors_jsonl)

    records: List[Dict[str, Any]] = []
    person: Dict[str, Any] = {"name": "", "position": "", "workplace": "", "user_declarant_id": None}
    durations: List[float] = []

    folder_uid = _user_id_from_folder(input_dir)

    for path in files:
        source_file = path.name
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        compact = compact_declaration(raw)
        if not _include_in_dossier_charts(compact):
            continue

        decl_type_code = _declaration_type_code_from_compact(compact)
        fin = _financials_from_compact(compact)
        year = _year_from_compact(compact)

        jsonl_item = by_source.get(source_file)
        if jsonl_item:
            yr_jsonl = _declaration_year(jsonl_item)
            if yr_jsonl > 0:
                year = yr_jsonl

        status = "pending"
        risk: Optional[int] = None
        finds = 0
        flags = 0
        risk_level = "low"

        if jsonl_item:
            status = "analyzed"
            metrics = _analysis_metrics(jsonl_item)
            risk = metrics["risk"]
            finds = metrics["finds"]
            flags = metrics["flags"]
            risk_level = metrics["risk_level"]
            dur = to_float(jsonl_item.get("processing_duration_sec"), 0.0)
            if dur > 0:
                durations.append(dur)
            if not person.get("name"):
                person = {
                    "name": profile_value(jsonl_item, "declarant_full_name"),
                    "position": profile_value(jsonl_item, "position"),
                    "workplace": profile_value(jsonl_item, "workplace"),
                    "user_declarant_id": jsonl_item.get("user_declarant_id") or folder_uid,
                }
        elif source_file in errors_by_source:
            status = "error"

        if not person.get("name"):
            p_compact = _person_from_compact(compact)
            if p_compact["name"]:
                person = {**p_compact, "user_declarant_id": raw.get("user_declarant_id") or folder_uid}

        records.append(
            {
                "year": year,
                "declaration_type_code": decl_type_code,
                "source_file": source_file,
                "status": status,
                "risk": risk,
                "finds": finds,
                "flags": flags,
                "risk_level": risk_level,
                "income": fin["income"],
                "assets": fin["assets"],
                "liab": fin["liab"],
                "realty": fin["realty"],
                "autos": fin["autos"],
                "land": fin["land"],
            }
        )

    if not person.get("user_declarant_id") and folder_uid is not None:
        person["user_declarant_id"] = folder_uid

    years = sorted({int(r["year"]) for r in records if int(r.get("year") or 0) > 0})
    processed_count = sum(1 for r in records if r.get("status") == "analyzed")
    avg_duration = (
        sum(max(0.0, d) for d in durations) / len(durations) if durations else 0.0
    )

    return {
        "ok": True,
        "person": person,
        "years": years,
        "records": records,
        "processed_count": processed_count,
        "planned_total": len(records),
        "avg_duration_sec": round(avg_duration, 2),
    }
