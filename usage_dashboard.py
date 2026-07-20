"""Aggregate usage statistics from analysis_results.jsonl for the UI dashboard."""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from report import (
    _as_dict,
    dedupe_by_latest,
    enrich_run_metadata,
    profile_value,
    read_jsonl,
    to_float,
    to_str_list,
    user_declarant_id_from_item,
)
from report_i18n import FINDING_TYPE_UK, RISK_LEVEL_UK

MANUAL_REVIEW_MINUTES = 10

RISK_LEVEL_ORDER = ("critical", "high", "medium", "low")
RISK_COLORS = {
    "critical": "#ef4444",
    "high": "#f97316",
    "medium": "#f59e0b",
    "low": "#22c55e",
}


def _normalize_risk_level(raw: Any) -> str:
    level = str(raw or "").strip().lower()
    if level in RISK_LEVEL_ORDER:
        return level
    return "low"


def _risk_score(item: Dict[str, Any]) -> float:
    analysis = _as_dict(item.get("analysis"))
    return to_float(analysis.get("risk_score"), 0.0)


def _declaration_year(item: Dict[str, Any]) -> int:
    y = profile_value(item, "declaration_year")
    if y:
        try:
            return int(float(y))
        except ValueError:
            pass
    return 0


def _model_label(item: Dict[str, Any]) -> str:
    run_meta = item.get("run_meta", {})
    if not isinstance(run_meta, dict):
        return ""
    mid = str(run_meta.get("model_id", "")).strip()
    if mid:
        slash = mid.rfind("/")
        if slash >= 0 and slash < len(mid) - 1:
            return mid[slash + 1 :]
        return mid
    full = str(run_meta.get("model", "")).strip()
    if not full:
        return ""
    paren = full.find(" (")
    return full[:paren] if paren > 0 else full


def _duration_sec(item: Dict[str, Any]) -> float:
    val = item.get("processing_duration_sec")
    if val is None:
        return 0.0
    return max(0.0, to_float(val, 0.0))


def _format_duration_hm(total_sec: float) -> Dict[str, Any]:
    sec = max(0, int(round(total_sec)))
    hours = sec // 3600
    minutes = (sec % 3600) // 60
    return {"hours": hours, "minutes": minutes, "total_sec": sec}


def _format_compact_count(n: int) -> str:
    if n >= 1000:
        val = n / 1000.0
        if val >= 10:
            return f"{int(round(val))}k"
        text = f"{val:.1f}".rstrip("0").rstrip(".")
        return f"{text}k"
    return str(n)


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def _parse_iso_utc(iso: str) -> Optional[datetime]:
    if not iso or not str(iso).strip():
        return None
    try:
        cleaned = str(iso).replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def format_session_time_label(finished_at_utc: str) -> str:
    dt = _parse_iso_utc(finished_at_utc)
    if dt is None:
        return ""
    local = dt.astimezone()
    now = datetime.now(local.tzinfo)
    day_diff = (now.date() - local.date()).days
    hm = local.strftime("%H:%M")
    if day_diff == 0:
        return f"сьогодні, {hm}"
    if day_diff == 1:
        return f"вчора, {hm}"
    return local.strftime("%d.%m.%Y, %H:%M")


def default_usage_aggregate() -> Dict[str, Any]:
    return {
        "total_wall_sec": 0,
        "sessions": [],
        "last_session": None,
    }


def normalize_usage_aggregate(raw: Any) -> Dict[str, Any]:
    base = default_usage_aggregate()
    if not isinstance(raw, dict):
        return base
    try:
        base["total_wall_sec"] = max(0, int(raw.get("total_wall_sec") or 0))
    except (TypeError, ValueError):
        base["total_wall_sec"] = 0
    sessions = raw.get("sessions")
    if isinstance(sessions, list):
        base["sessions"] = [s for s in sessions if isinstance(s, dict)][-50:]
    last = raw.get("last_session")
    if isinstance(last, dict):
        base["last_session"] = last
    return base


def append_usage_session(
    existing: Dict[str, Any],
    *,
    finished_at_utc: str,
    wall_sec: float,
    declarations_ok: int,
    critical_count: int,
    model_label: str,
) -> Dict[str, Any]:
    agg = normalize_usage_aggregate(existing)
    wall_i = max(0, int(round(wall_sec)))
    session = {
        "finished_at_utc": finished_at_utc,
        "wall_sec": wall_i,
        "declarations_ok": max(0, declarations_ok),
        "critical_count": max(0, critical_count),
        "model_label": str(model_label or "").strip(),
    }
    agg["total_wall_sec"] = int(agg.get("total_wall_sec") or 0) + wall_i
    sessions = list(agg.get("sessions") or [])
    sessions.append(session)
    agg["sessions"] = sessions[-50:]
    agg["last_session"] = session
    return agg


def _load_rows(jsonl_path: Path, *, no_dedupe: bool) -> tuple[List[Dict[str, Any]], bool]:
    if not jsonl_path.is_file():
        return [], False
    raw = read_jsonl(jsonl_path)
    if not raw:
        return [], True
    raw = enrich_run_metadata(raw)
    rows = raw if no_dedupe else dedupe_by_latest(raw)
    return rows, True


def aggregate_dashboard(
    jsonl_path: Path,
    *,
    no_dedupe: bool = False,
    usage_aggregate: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    agg = normalize_usage_aggregate(usage_aggregate)
    rows, file_exists = _load_rows(jsonl_path, no_dedupe=no_dedupe)

    mtime_iso = ""
    if jsonl_path.is_file():
        try:
            ts = jsonl_path.stat().st_mtime
            mtime_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except OSError:
            pass

    empty = not rows
    n = len(rows)

    person_ids: set[str] = set()
    risk_counts = {k: 0 for k in RISK_LEVEL_ORDER}
    scores: List[float] = []
    red_flags_total = 0
    decls_with_flags = 0
    finding_type_counts: Dict[str, int] = {}
    model_counts: Dict[str, int] = {}
    year_counts: Dict[int, int] = {}
    duration_jsonl = 0.0

    highest: Optional[Dict[str, Any]] = None
    highest_score = -1.0

    for item in rows:
        uid = user_declarant_id_from_item(item)
        if uid:
            person_ids.add(uid)

        analysis = _as_dict(item.get("analysis"))
        level = _normalize_risk_level(analysis.get("risk_level"))
        risk_counts[level] = risk_counts.get(level, 0) + 1

        score = _risk_score(item)
        scores.append(score)

        flags = to_str_list(analysis.get("red_flags"))
        red_flags_total += len(flags)
        if flags:
            decls_with_flags += 1

        findings = analysis.get("findings", [])
        findings_count = 0
        if isinstance(findings, list):
            findings_count = len(findings)
            for f in findings:
                if not isinstance(f, dict):
                    continue
                ftype = str(f.get("type", "other")).strip() or "other"
                finding_type_counts[ftype] = finding_type_counts.get(ftype, 0) + 1

        ml = _model_label(item)
        if ml:
            model_counts[ml] = model_counts.get(ml, 0) + 1

        year = _declaration_year(item)
        if year > 0:
            year_counts[year] = year_counts.get(year, 0) + 1

        duration_jsonl += _duration_sec(item)

        if score > highest_score:
            highest_score = score
            pos = profile_value(item, "position")
            workplace = profile_value(item, "workplace")
            highest = {
                "declarant_full_name": profile_value(item, "declarant_full_name"),
                "position": pos,
                "workplace": workplace,
                "declaration_year": year,
                "risk_score": int(round(score)),
                "red_flags_count": len(flags),
                "findings_count": findings_count,
            }

    total_analysis_sec = duration_jsonl
    if total_analysis_sec <= 0:
        total_analysis_sec = float(agg.get("total_wall_sec") or 0)

    avg_sec = (total_analysis_sec / n) if n > 0 else 0.0
    time_saved_sec = n * MANUAL_REVIEW_MINUTES * 60

    risk_distribution = []
    for level in RISK_LEVEL_ORDER:
        count = risk_counts.get(level, 0)
        pct = round(100.0 * count / n, 1) if n else 0.0
        risk_distribution.append(
            {
                "level": level,
                "label": RISK_LEVEL_UK[level],
                "count": count,
                "pct": pct,
                "color": RISK_COLORS[level],
            }
        )

    finding_types_sorted = sorted(
        finding_type_counts.items(), key=lambda x: (-x[1], x[0])
    )[:4]
    max_ft = finding_types_sorted[0][1] if finding_types_sorted else 1
    finding_types = [
        {
            "type": t,
            "label": FINDING_TYPE_UK.get(t, t.replace("_", " ")),
            "count": c,
            "count_label": _format_compact_count(c),
            "bar_pct": round(100.0 * c / max_ft, 1) if max_ft else 0,
        }
        for t, c in finding_types_sorted
    ]

    models_sorted = sorted(model_counts.items(), key=lambda x: (-x[1], x[0]))[:6]
    max_model = models_sorted[0][1] if models_sorted else 1
    models = [
        {
            "name": name,
            "count": cnt,
            "bar_pct": round(100.0 * cnt / max_model, 1) if max_model else 0,
        }
        for name, cnt in models_sorted
    ]

    years_hist: List[Dict[str, Any]] = []
    if year_counts:
        ymin = min(year_counts)
        ymax = max(year_counts)
        for y in range(ymin, ymax + 1):
            cnt = year_counts.get(y, 0)
            years_hist.append(
                {
                    "year": y,
                    "label": f"'{str(y)[-2:]}",
                    "count": cnt,
                }
            )
        max_y = max((h["count"] for h in years_hist), default=1) or 1
        for h in years_hist:
            h["bar_pct"] = round(100.0 * h["count"] / max_y, 1) if max_y else 0

    peak_year = 0
    if year_counts:
        peak_year = max(year_counts.items(), key=lambda x: (x[1], x[0]))[0]

    last_session_raw = agg.get("last_session")
    last_session = None
    if isinstance(last_session_raw, dict):
        last_session = {
            "declarations_ok": int(last_session_raw.get("declarations_ok") or 0),
            "critical_count": int(last_session_raw.get("critical_count") or 0),
            "model_label": str(last_session_raw.get("model_label") or "").strip(),
            "time_label": format_session_time_label(
                str(last_session_raw.get("finished_at_utc") or "")
            ),
        }

    return {
        "ok": True,
        "empty": empty,
        "file_exists": file_exists,
        "source_path": str(jsonl_path),
        "source_basename": jsonl_path.name,
        "source_mtime_utc": mtime_iso,
        "manual_review_minutes": MANUAL_REVIEW_MINUTES,
        "totals": {
            "declarations": n,
            "persons": len(person_ids),
            "red_flags": red_flags_total,
            "declarations_with_red_flags": decls_with_flags,
            "declarations_with_red_flags_pct": round(
                100.0 * decls_with_flags / n, 1
            )
            if n
            else 0.0,
            "avg_risk_score": round(sum(scores) / n, 1) if n else 0.0,
            "median_risk_score": round(_median(scores), 1),
            "peak_year": peak_year,
            "analysis_time": _format_duration_hm(total_analysis_sec),
            "avg_analysis_sec": round(avg_sec, 1),
            "time_saved": _format_duration_hm(time_saved_sec),
        },
        "risk_distribution": risk_distribution,
        "finding_types": finding_types,
        "highest_risk": highest,
        "models": models,
        "years": years_hist,
        "last_session": last_session,
    }
