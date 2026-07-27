"""Generate the summary/findings CSVs and the interactive HTML report from analysis_results.jsonl."""
import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from report_i18n import (
    RISK_LEVEL_FILTER_ORDER,
    RISK_LEVEL_UK,
    risk_level_css_class,
    severity_sort_rank,
    translate_finding_type,
    translate_profile_field,
    translate_risk_level,
    translate_severity,
)


def to_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _as_dict(value: Any) -> Dict[str, Any]:
    """Return value if it's a dict, else an empty dict.

    JSONL rows where `analysis` is `null` (or any non-dict) used to crash with
    `AttributeError: 'NoneType' object has no attribute 'get'` because
    `dict.get(key, default)` returns the stored `None`, not the default.
    """
    return value if isinstance(value, dict) else {}


def to_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                print(f"Skip invalid JSONL line {line_no}.")
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def dedupe_by_latest(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Deduplicate by (declaration_id, model) so different models are kept as
    # separate rows. Within the same model, the latest JSONL entry wins.
    latest: Dict[str, Dict[str, Any]] = {}
    for item in rows:
        declaration_id = str(item.get("declaration_id", "")).strip()
        if not declaration_id:
            declaration_id = str(item.get("source_file", "")).strip()
        model = str(item.get("run_meta", {}).get("model", "")).strip()
        key = f"{declaration_id}||{model}"
        latest[key] = item
    return list(latest.values())


def enrich_run_metadata(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # First pass: collect all (started_at, run_id) pairs that have a real date,
    # then assign run_seq in chronological order so newer runs get higher numbers.
    dated_keys: List[tuple] = []
    for item in rows:
        run_meta = item.get("run_meta", {})
        if not isinstance(run_meta, dict):
            continue
        run_id = str(run_meta.get("run_id", "")).strip()
        started_at = str(run_meta.get("started_at_utc", "")).strip()
        run_key = run_id or started_at
        if run_key and (run_key, started_at) not in dated_keys:
            dated_keys.append((run_key, started_at))

    # Sort by date ascending so run_seq=1 is the earliest real run.
    dated_keys.sort(key=lambda x: x[1])
    run_order: Dict[str, int] = {key: i + 1 for i, (key, _) in enumerate(dated_keys)}

    legacy_seq = 0  # rows without run_meta keep seq=0

    for item in rows:
        run_meta = item.get("run_meta", {})
        if not isinstance(run_meta, dict):
            run_meta = {}
        run_id = str(run_meta.get("run_id", "")).strip()
        started_at = str(run_meta.get("started_at_utc", "")).strip()
        run_key = run_id or started_at
        run_seq = run_order.get(run_key, legacy_seq)
        run_meta["run_seq"] = run_seq
        run_meta["started_at_utc"] = started_at
        item["run_meta"] = run_meta
    return rows


def format_user_declarant_id(val: Any) -> str:
    if val is None or val == "":
        return ""
    if isinstance(val, bool):
        return ""
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        if val != val:
            return ""
        iv = int(val)
        return str(iv) if float(iv) == val else str(val).strip()
    return str(val).strip()


def user_declarant_id_from_item(item: Dict[str, Any]) -> str:
    top = format_user_declarant_id(item.get("user_declarant_id"))
    if top:
        return top
    analysis = _as_dict(item.get("analysis"))
    profile = analysis.get("subject_profile", {})
    if isinstance(profile, dict):
        return format_user_declarant_id(profile.get("user_declarant_id"))
    return ""


def profile_value(item: Dict[str, Any], field: str) -> str:
    analysis = _as_dict(item.get("analysis"))
    profile = analysis.get("subject_profile", {})
    if isinstance(profile, dict):
        value = str(profile.get(field, "")).strip()
        if value:
            return value
    context = item.get("context_snapshot", {})
    if isinstance(context, dict):
        return str(context.get(field, "")).strip()
    return ""


_DEEP_RESEARCH_ROOT = Path(__file__).resolve().parent / "deep_research"


def is_dossier_report_input(input_path: Path) -> bool:
    """Whether this is a JSONL report from a deep research session (dossier mode)."""
    try:
        return input_path.resolve().is_relative_to(_DEEP_RESEARCH_ROOT.resolve())
    except (OSError, ValueError):
        return False


def _declaration_date_sort_key(date_raw: Any) -> str:
    if not isinstance(date_raw, str) or not date_raw.strip():
        return ""
    ds = date_raw.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ds).isoformat()
    except ValueError:
        return date_raw.strip()


def _declaration_date_from_source_file(decl_dir: Path, source_file: str) -> str:
    name = source_file.strip()
    if not name:
        return ""
    decl_path = decl_dir / name
    if not decl_path.is_file():
        return ""
    try:
        raw = json.loads(decl_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return ""
    if isinstance(raw, dict):
        return _declaration_date_sort_key(raw.get("date"))
    return ""


def dossier_chronological_sort_key(
    item: Dict[str, Any], *, decl_dir: Optional[Path] = None
) -> Tuple[int, str, str]:
    """Oldest -> newest (same as sort_declaration_files_chronologically in main.py)."""
    yr_s = profile_value(item, "declaration_year")
    try:
        year = int(yr_s) if str(yr_s).strip() else 0
    except (TypeError, ValueError):
        year = 0
    date_key = ""
    if decl_dir is not None:
        date_key = _declaration_date_from_source_file(
            decl_dir, str(item.get("source_file", ""))
        )
    return (year, date_key, str(item.get("source_file", "")))


def sort_rows_dossier_chronological(
    rows: List[Dict[str, Any]], input_path: Path
) -> List[Dict[str, Any]]:
    decl_dir = input_path.parent if is_dossier_report_input(input_path) else None
    return sorted(
        rows,
        key=lambda item: dossier_chronological_sort_key(item, decl_dir=decl_dir),
    )


def _fmt_date(iso: str) -> str:
    """Convert UTC ISO timestamp to local time 'YYYY-MM-DD HH:MM' for display."""
    if not iso or iso in {"NONE", "EMPTY", "None"}:
        return ""
    try:
        cleaned = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local_dt = dt.astimezone()
        return local_dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso[:16].replace("T", " ")


def build_summary_rows(
    rows: List[Dict[str, Any]], *, dossier_chronological: bool = False
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in rows:
        analysis = _as_dict(item.get("analysis"))
        findings = analysis.get("findings", [])
        run_meta = item.get("run_meta", {})
        row = {
            "run_seq": run_meta.get("run_seq", 0),
            "model": run_meta.get("model", ""),
            "run_started_at": _fmt_date(str(run_meta.get("started_at_utc", ""))),
            "source_file": item.get("source_file", ""),
            "declaration_id": item.get("declaration_id", ""),
            "user_declarant_id": user_declarant_id_from_item(item),
            "declarant_full_name": profile_value(item, "declarant_full_name"),
            "position": profile_value(item, "position"),
            "workplace": profile_value(item, "workplace"),
            "declaration_year": profile_value(item, "declaration_year"),
            "declaration_type_code": profile_value(item, "declaration_type_code"),
            "declaration_type_label": profile_value(item, "declaration_type_label"),
            "risk_score": analysis.get("risk_score", ""),
            "risk_level": translate_risk_level(analysis.get("risk_level", "")),
            "findings_count": len(findings) if isinstance(findings, list) else 0,
            "red_flags": " | ".join(to_str_list(analysis.get("red_flags"))),
            "needs_verification": " | ".join(
                to_str_list(analysis.get("needs_verification"))
            ),
            "final_assessment": analysis.get("final_assessment", ""),
        }
        result.append(row)
    if dossier_chronological:

        def _summary_year_key(row: Dict[str, Any]) -> int:
            y = row.get("declaration_year", "")
            if isinstance(y, int):
                return y
            s = str(y).strip()
            try:
                return int(s) if s else 0
            except ValueError:
                return 0

        return sorted(
            result,
            key=lambda x: (_summary_year_key(x), str(x.get("source_file", ""))),
        )
    return sorted(
        result,
        key=lambda x: (
            to_float(x.get("risk_score"), default=0.0),
            str(x.get("run_started_at", "")),
        ),
        reverse=True,
    )


_SEVERITY_CLASS = {
    "critical": "sev-critical",
    "high": "sev-high",
    "medium": "sev-medium",
    "low": "sev-low",
}


def _ul_from_list(items: Any, css_class: str = "rich-ul") -> str:
    """Safe <ul> from a list or scalar. Empty -> ''. """
    if items is None:
        return ""
    if not isinstance(items, list):
        s = str(items).strip()
        return f'<ul class="{css_class}"><li>{html_escape(s)}</li></ul>' if s else ""
    lis: List[str] = []
    for it in items:
        s = str(it).strip()
        if s:
            lis.append(f"<li>{html_escape(s)}</li>")
    return f'<ul class="{css_class}">{"".join(lis)}</ul>' if lis else ""


def _chips_from_list(items: Any) -> str:
    if not isinstance(items, list):
        s = str(items).strip() if items is not None else ""
        return f'<span class="chip">{html_escape(s)}</span>' if s else ""
    chips: List[str] = []
    for it in items:
        s = str(it).strip()
        if s:
            chips.append(f'<span class="chip">{html_escape(s)}</span>')
    return "".join(chips)


def _render_findings_html(findings: List[Any]) -> str:
    """Finding cards: severity pill, title, rationale, collapsible details."""
    if not findings:
        return ""
    cards: List[str] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        sev_raw = str(f.get("severity", "") or "").strip().lower()
        sev_cls = _SEVERITY_CLASS.get(sev_raw, "sev-other")
        sev_label = translate_severity(sev_raw) or "—"
        title = str(f.get("title", "") or "").strip()
        ftype = str(f.get("type", "") or "").strip()
        ftype_disp = translate_finding_type(ftype) if ftype else ""
        conf = f.get("confidence", None)
        try:
            conf_val = float(conf) if conf is not None and conf != "" else None
        except (TypeError, ValueError):
            conf_val = None
        conf_badge = (
            f'<span class="badge">впевн. {conf_val:.2f}</span>' if conf_val is not None else ""
        )
        type_badge = (
            f'<span class="badge">{html_escape(ftype_disp)}</span>' if ftype_disp else ""
        )
        rationale = str(f.get("rationale", "") or "").strip()
        evidence_html = _ul_from_list(f.get("evidence"), "rich-ul")
        persons_html = _chips_from_list(f.get("involved_persons"))
        assets_html = _ul_from_list(f.get("related_assets_or_income"), "rich-ul")

        details_inner_parts: List[str] = []
        if evidence_html:
            details_inner_parts.append(
                f'<div class="kv"><b>Докази</b>{evidence_html}</div>'
            )
        if persons_html:
            details_inner_parts.append(
                f'<div class="kv"><b>Особи</b><div class="chips">{persons_html}</div></div>'
            )
        if assets_html:
            details_inner_parts.append(
                f'<div class="kv"><b>Активи / дохід</b>{assets_html}</div>'
            )
        details_block = ""
        if details_inner_parts:
            open_attr = " open" if sev_raw == "critical" else ""
            details_block = (
                f'<details class="finding-more"{open_attr}>'
                '<summary>Докази та зв’язки</summary>'
                f'{"".join(details_inner_parts)}'
                "</details>"
            )

        rationale_html = (
            f'<p class="rationale">{html_escape(rationale)}</p>' if rationale else ""
        )
        title_html = (
            f'<span class="title">{html_escape(title)}</span>'
            if title
            else '<span class="title muted">(без заголовка)</span>'
        )
        badges = "".join([type_badge, conf_badge])
        cards.append(
            f'<article class="finding {sev_cls}">'
            "<header>"
            f'<span class="sev-pill {sev_cls}">{html_escape(sev_label)}</span>'
            f"{title_html}"
            f'<span class="badges">{badges}</span>'
            "</header>"
            f"{rationale_html}"
            f"{details_block}"
            "</article>"
        )
    return "".join(cards)


def _render_family_assets_html(val: Any) -> str:
    """List of "persons with asset examples"."""
    if val is None:
        return ""
    if not isinstance(val, list):
        s = str(val).strip()
        return f'<div class="fam-plain">{html_escape(s)}</div>' if s else ""
    items: List[str] = []
    for it in val:
        if isinstance(it, dict):
            person = str(it.get("person", "") or "").strip()
            ac = it.get("asset_count", "")
            ac_str = "" if ac in ("", None) else str(ac)
            examples = it.get("asset_examples", [])
            ex_html = _ul_from_list(examples, "rich-ul")
            head_parts: List[str] = []
            if person:
                head_parts.append(f"<b>{html_escape(person)}</b>")
            if ac_str:
                head_parts.append(f'<span class="muted">n={html_escape(ac_str)}</span>')
            head = '<span class="fam-head">' + " · ".join(head_parts) + "</span>" if head_parts else ""
            if head or ex_html:
                items.append(f"<li>{head}{ex_html}</li>")
        else:
            s = str(it).strip()
            if s:
                items.append(f"<li>{html_escape(s)}</li>")
    return f'<ul class="fam-list">{"".join(items)}</ul>' if items else ""


def _render_subject_profile_html(profile: Any, exclude_keys: Tuple[str, ...]) -> str:
    """`<dl>` of subject_profile fields, excluding duplicates already shown in other columns."""
    if not isinstance(profile, dict) or not profile:
        return ""
    rows: List[str] = []
    for k, v in profile.items():
        if k in exclude_keys:
            continue
        if v in (None, "", [], {}):
            continue
        if isinstance(v, list):
            val_html = _ul_from_list(v, "rich-ul")
        elif isinstance(v, dict):
            val_html = (
                "<code>" + html_escape(json.dumps(v, ensure_ascii=False)) + "</code>"
            )
        else:
            val_html = html_escape(str(v))
        label = translate_profile_field(k)
        rows.append(
            f'<div class="dl-row"><dt>{html_escape(label)}</dt><dd>{val_html}</dd></div>'
        )
    return f'<dl class="profile-dl">{"".join(rows)}</dl>' if rows else ""


def _render_clear_facts_html(facts: Any) -> str:
    return _ul_from_list(facts, "rich-ul clear-facts-ul")


def build_findings_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in rows:
        analysis = _as_dict(item.get("analysis"))
        findings = analysis.get("findings", [])
        if not isinstance(findings, list):
            continue
        run_meta = item.get("run_meta", {})
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            sev_raw = finding.get("severity", "")
            result.append(
                {
                    "run_seq": run_meta.get("run_seq", 0),
                    "model": run_meta.get("model", ""),
                    "run_started_at": _fmt_date(str(run_meta.get("started_at_utc", ""))),
                    "source_file": item.get("source_file", ""),
                    "declaration_id": item.get("declaration_id", ""),
                    "user_declarant_id": user_declarant_id_from_item(item),
                    "declarant_full_name": profile_value(item, "declarant_full_name"),
                    "position": profile_value(item, "position"),
                    "workplace": profile_value(item, "workplace"),
                    "risk_score": analysis.get("risk_score", ""),
                    "risk_level": translate_risk_level(analysis.get("risk_level", "")),
                    "finding_title": finding.get("title", ""),
                    "finding_type": translate_finding_type(finding.get("type", "")),
                    "severity": translate_severity(sev_raw),
                    "confidence": finding.get("confidence", ""),
                    "evidence": " | ".join(to_str_list(finding.get("evidence"))),
                    "rationale": finding.get("rationale", ""),
                    "_sev_rank": severity_sort_rank(sev_raw),
                }
            )
    result.sort(
        key=lambda x: (
            to_float(x.get("risk_score"), default=0.0),
            int(x.get("_sev_rank", 0)),
        ),
        reverse=True,
    )
    for row in result:
        row.pop("_sev_rank", None)
    return result


def write_csv(path: Path, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def html_escape(text: Any) -> str:
    value = str(text)
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def nazk_public_declaration_url(declaration_id: str) -> str:
    """URL of the declaration card on public.nazk.gov.ua (expects a UUID)."""
    d = str(declaration_id or "").strip()
    if not d or len(d) < 8:
        return ""
    if not re.fullmatch(r"[0-9a-fA-F-]+", d):
        return ""
    return f"https://public.nazk.gov.ua/documents/{d}"


def _build_stats_block(rows: List[Dict[str, Any]]) -> str:
    total = len(rows)
    scores = [
        to_float(r.get("risk_score"), default=0.0)
        for r in rows
        if r.get("risk_score") not in (None, "")
    ]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    level_counts: Dict[str, int] = {}
    for r in rows:
        lv = str(r.get("risk_level", "unknown")).lower()
        level_counts[lv] = level_counts.get(lv, 0) + 1

    level_order = ["critical", "high", "medium", "low"]
    level_colors = {
        "critical": "#dc2626",
        "high": "#ea580c",
        "medium": "#2563eb",
        "low": "#16a34a",
    }
    badges = ""
    for lv in level_order:
        cnt = level_counts.get(lv, 0)
        color = level_colors.get(lv, "#555")
        lv_uk = translate_risk_level(lv)
        badges += (
            f'<span style="background:{color};color:#fff;padding:3px 10px;'
            f'border-radius:4px;margin-right:6px;font-weight:600">'
            f'{html_escape(lv_uk)}: {cnt}</span>'
        )
    for lv, cnt in level_counts.items():
        if lv not in level_order:
            badges += (
                f'<span style="background:#555;color:#fff;padding:3px 10px;'
                f'border-radius:4px;margin-right:6px">'
                f'{html_escape(translate_risk_level(lv))}: {int(cnt)}</span>'
            )
    return (
        f'<div class="stats-block">'
        f'<span class="stat-item">Всього декларацій: <strong>{total}</strong></span>'
        f'<span class="stat-item">Середній бал ризику: <strong>{avg_score}</strong></span>'
        f'<span class="stat-item">{badges}</span>'
        f'</div>'
    )


def _stats_rows_from_jsonl_items(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flat risk_score / risk_level rows for _build_stats_block from raw JSONL items."""
    out: List[Dict[str, Any]] = []
    for item in rows:
        a = _as_dict(item.get("analysis"))
        out.append({"risk_score": a.get("risk_score", ""), "risk_level": a.get("risk_level", "")})
    return out


def _position_workplace_cell(item: Dict[str, Any]) -> str:
    pos = profile_value(item, "position")
    wp = profile_value(item, "workplace")
    if pos and wp:
        return f"{pos} — {wp}"
    return pos or wp or ""


def _detail_panel_inner_html(item: Dict[str, Any], row_key: str, decl_raw: str) -> str:
    """Two-column expand panel: findings, flags, profile; family, check, conclusion, meta."""
    analysis = _as_dict(item.get("analysis"))
    findings_raw = analysis.get("findings", [])
    findings_list = findings_raw if isinstance(findings_raw, list) else []
    findings_html = _render_findings_html(findings_list)

    profile = analysis.get("subject_profile", {})
    profile_html = ""
    if isinstance(profile, dict):
        profile_html = _render_subject_profile_html(
            profile,
            exclude_keys=(
                "declaration_id",
                "declarant_full_name",
                "declaration_year",
                "declaration_type_code",
                "declaration_type_label",
            ),
        )

    fam_html = _render_family_assets_html(analysis.get("family_assets_overview"))
    clear_html = _render_clear_facts_html(analysis.get("clear_facts"))

    red_html = _ul_from_list(analysis.get("red_flags"), "rich-ul red-flags-ul")
    needs_html = _ul_from_list(analysis.get("needs_verification"), "rich-ul")
    final_txt = str(analysis.get("final_assessment", "") or "").strip()
    risk_lv = str(analysis.get("risk_level", "") or "").strip().lower()

    findings_block = (
        f'<div class="detail-section">{findings_html}</div>'
        if findings_html.strip()
        else '<p class="muted">Знахідок AI для цього запису немає.</p>'
    )
    red_block = (
        f'<div class="detail-section"><h4 class="detail-h">Червоні прапорці</h4>{red_html}</div>'
        if red_html
        else ""
    )
    # If there are no finding cards but profile fields exist — show them immediately (not only under a collapsed summary).
    profile_open = ""
    if profile_html.strip() and not findings_html.strip():
        profile_open = " open"
    profile_block = (
        f'<details class="detail-meta-sub"{profile_open}><summary>Додаткові поля профілю</summary>{profile_html}</details>'
        if profile_html.strip()
        else ""
    )

    fam_block = (
        f'<div class="detail-section"><h4 class="detail-h">Сім’я та активи</h4>{fam_html}</div>'
        if fam_html.strip()
        else '<div class="detail-section"><h4 class="detail-h">Сім’я та активи</h4><p class="muted">—</p></div>'
    )
    needs_block = (
        f'<div class="detail-section"><h4 class="detail-h">Потребує перевірки</h4>{needs_html}</div>'
        if needs_html
        else '<div class="detail-section"><h4 class="detail-h">Потребує перевірки</h4><p class="muted">—</p></div>'
    )
    clear_block = ""
    if clear_html.strip():
        clear_block = f'<div class="detail-section"><h4 class="detail-h">Узгоджені факти</h4>{clear_html}</div>'

    if final_txt:
        conclusion_body = f'<div class="conclusion-text">{html_escape(final_txt)}</div>'
    else:
        conclusion_body = (
            '<p class="muted">Текстовий висновок моделі відсутній — '
            "див. таблицю зверху та поля профілю зліва.</p>"
        )
    risk_ru = html_escape(translate_risk_level(risk_lv)) if risk_lv else "—"
    risk_cls_line = risk_level_css_class(risk_lv)
    conclusion = (
        f'<div class="conclusion-box"><h4 class="detail-h">Висновок</h4>'
        f"{conclusion_body}"
        f'<div class="conclusion-risk rl-{risk_cls_line}">Ризик: <strong>{risk_ru}</strong></div></div>'
    )

    src = html_escape(str(item.get("source_file", "")))
    decl_esc = html_escape(decl_raw)
    udecl = html_escape(str(user_declarant_id_from_item(item)))
    decl_type_code = profile_value(item, "declaration_type_code")
    decl_type_label = profile_value(item, "declaration_type_label")
    if decl_type_label:
        decl_type_disp = html_escape(decl_type_label)
        if decl_type_code:
            decl_type_disp += f' <span class="meta-muted">({html_escape(decl_type_code)})</span>'
    elif decl_type_code:
        decl_type_disp = html_escape(decl_type_code)
    else:
        decl_type_disp = '<span class="meta-muted">—</span>'
    nazk_href = nazk_public_declaration_url(decl_raw)
    if nazk_href:
        nazk_row = (
            f'<div><strong>НАЗК:</strong> '
            f'<a class="meta-nazk" href="{html_escape(nazk_href)}" '
            'target="_blank" rel="noopener noreferrer">[сайт НАЗК]</a></div>'
        )
    else:
        nazk_row = '<div><strong>НАЗК:</strong> <span class="meta-muted">—</span></div>'

    meta = (
        f'<details class="meta-details detail-meta-top"><summary>Технічні деталі</summary>'
        f'<label class="mark-label"><input type="checkbox" class="mark-cb" data-key="{row_key}" /> Позначити рядок</label>'
        f'<div><strong>source_file:</strong> <span class="meta-mono">{src or "—"}</span></div>'
        f'<div><strong>declaration_id:</strong> <span class="meta-mono">{decl_esc or "—"}</span></div>'
        f'<div><strong>user_declarant_id:</strong> <span class="meta-mono">{udecl or "—"}</span></div>'
        f'<div><strong>Тип декларації:</strong> {decl_type_disp}</div>'
        f"{nazk_row}</details>"
    )

    left = (
        f'<div class="detail-col detail-col-left">'
        f'<h3 class="detail-h detail-h-main">Знахідки AI</h3>{findings_block}{red_block}{profile_block}</div>'
    )
    right = (
        f'<div class="detail-col detail-col-right">{fam_block}{needs_block}{clear_block}{conclusion}{meta}</div>'
    )
    return f'<div class="detail-panel">{left}{right}</div>'


# Master-row column headers for the HTML report (master-detail).
_HTML_MAIN_HEADER_LABELS: List[str] = [
    "#",
    "ПІБ декларанта",
    "Посада / установа",
    "Рік",
    "Модель",
    "Бал",
    "Ризик",
    "Знах.",
    "",
]

# Declaration-type filter in the HTML report (value = declaration_type_code on the row data-*).
_HTML_DECL_TYPE_FILTER_OPTIONS: List[Tuple[str, str]] = [
    ("", "Показати усі декларації"),
    ("1", "Річні декларації"),
    ("changes", "Декларації змін"),
    ("2", "Декларації перед звільненням"),
]


def _html_decl_type_filter_options() -> str:
    return "".join(
        f'<option value="{html_escape(code)}">{html_escape(label)}</option>'
        for code, label in _HTML_DECL_TYPE_FILTER_OPTIONS
    )


def _html_risk_filter_options() -> str:
    parts = ['<option value="">Всі рівні ризику</option>']
    for code in RISK_LEVEL_FILTER_ORDER:
        label = RISK_LEVEL_UK.get(code, code)
        parts.append(
            f'<option value="{html_escape(code)}">{html_escape(label)}</option>'
        )
    return "".join(parts)


def write_filterable_html(
    path: Path,
    rows: List[Dict[str, Any]],
    error_rows: Optional[List[Dict[str, Any]]] = None,
    *,
    dossier_chronological: bool = False,
) -> None:
    """Single HTML report: master-row + expanded detail (fields from analysis)."""
    main_col_count = len(_HTML_MAIN_HEADER_LABELS)
    # Master-row column indices for JS (0-based).
    col_name = 1
    col_pos = 2
    col_year = 3
    col_model = 4
    col_score = 5
    col_level = 6
    col_find = 7

    row_html_parts: List[str] = []
    for idx, item in enumerate(rows):
        run_meta = item.get("run_meta", {})
        if not isinstance(run_meta, dict):
            run_meta = {}
        model = str(run_meta.get("model", "")).strip()
        run_started_raw = str(run_meta.get("started_at_utc", "")).strip()
        run_started_display = _fmt_date(run_started_raw)
        is_legacy = not model and not run_started_raw
        tr_class = " legacy-row" if is_legacy else ""

        decl_raw = str(item.get("declaration_id", "")).strip()
        row_key = html_escape(
            f"{decl_raw}|{run_started_display}" if decl_raw else str(item.get("source_file", ""))
        )
        row_id = str(idx)

        analysis = _as_dict(item.get("analysis"))
        findings = analysis.get("findings", [])
        n_find = len(findings) if isinstance(findings, list) else 0

        name = profile_value(item, "declarant_full_name")
        year = profile_value(item, "declaration_year")
        pos_wp = _position_workplace_cell(item)
        score_raw = analysis.get("risk_score", "")
        score_str = str(score_raw).strip() if score_raw not in (None, "") else ""
        risk_lv = str(analysis.get("risk_level", "") or "").strip().lower()
        risk_cls = risk_level_css_class(risk_lv)

        name_cell = (
            f'<td class="legacy-cell">(немає у старих даних)</td>'
            if not name
            else f"<td>{html_escape(name)}</td>"
        )
        pos_cell = f"<td>{html_escape(pos_wp) if pos_wp else '—'}</td>"
        year_cell = f"<td>{html_escape(year) if year else '—'}</td>"
        if not model:
            model_cell = '<td class="legacy-cell" title="Старий запис без метаданих">(без моделі)</td>'
        else:
            model_cell = f"<td>{html_escape(model)}</td>"

        score_disp = html_escape(score_str) if score_str else "—"
        score_cell = (
            f'<td class="td-score"><span class="score-pill score-pill-{risk_cls}">{score_disp}</span></td>'
        )
        risk_disp = html_escape(translate_risk_level(risk_lv)) if risk_lv else "—"
        risk_cell = f'<td class="rl-{html_escape(risk_cls)}"><span class="risk-badge">{risk_disp}</span></td>'
        find_cell = f'<td class="td-fcount"><span class="fcircle">{n_find}</span></td>'
        expand_cell = (
            f'<td class="td-expand"><button type="button" class="row-expand-btn" '
            f'aria-expanded="false" data-row-id="{row_id}" aria-label="Розгорнути рядок">▼</button></td>'
        )

        detail_inner = _detail_panel_inner_html(item, row_key, decl_raw)
        run_sort_esc = html_escape(run_started_raw)

        decl_type_code_attr = html_escape(profile_value(item, "declaration_type_code"))
        source_file_attr = html_escape(str(item.get("source_file", "")))
        main_tr = (
            f'<tr class="row-main{tr_class}" data-key="{row_key}" data-row-id="{row_id}" '
            f'data-run-started="{run_sort_esc}" '
            f'data-source-file="{source_file_attr}" '
            f'data-risk-level="{html_escape(risk_lv)}" '
            f'data-declaration-type-code="{decl_type_code_attr}">'
            f'<td class="col-idx"></td>{name_cell}{pos_cell}{year_cell}{model_cell}'
            f"{score_cell}{risk_cell}{find_cell}{expand_cell}</tr>"
        )
        detail_tr = (
            f'<tr class="row-detail{tr_class}" data-row-id="{row_id}" hidden>'
            f'<td colspan="{main_col_count}" class="td-detail">{detail_inner}</td></tr>'
        )
        row_html_parts.append(main_tr + detail_tr)

    stats_html = _build_stats_block(_stats_rows_from_jsonl_items(rows))
    errors_html = _build_errors_html(error_rows or [])

    header_ths_list: List[str] = []
    for i, lab in enumerate(_HTML_MAIN_HEADER_LABELS):
        if i == 0 or i == main_col_count - 1:
            header_ths_list.append(f'<th data-col="{i}" class="th-nosort">{html_escape(lab)}</th>')
        else:
            header_ths_list.append(
                f'<th data-col="{i}" class="sortable">{html_escape(lab)} <span class="sort-arrow"></span></th>'
            )
    header_ths = "".join(header_ths_list)

    col_labels_js = ", ".join(json.dumps(lab, ensure_ascii=False) for lab in _HTML_MAIN_HEADER_LABELS)
    decl_type_filter_opts = _html_decl_type_filter_options()
    risk_filter_opts = _html_risk_filter_options()

    if dossier_chronological:
        sort_hint_html = (
            "Фільтри та сортування локально в браузері. Розгорніть рядок для повного аналізу. "
            "Режим досьє: за замовчуванням <strong>від найстарішої декларації до найновішої</strong> "
            "(рік, потім дата з файлу декларації)."
        )
        default_sort_js = "sortPairsByDeclarationYear();"
    else:
        sort_hint_html = (
            "Фільтри та сортування локально в браузері. Розгорніть рядок для повного аналізу. "
            "За замовчуванням сортування за датою запуску: <strong>новіші зверху</strong>, "
            "тож останній рядок таблиці — найраніший запуск (не обов’язково останній рядок у JSONL)."
        )
        default_sort_js = "sortPairsByRunStarted();"

    html = f"""<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <title>ДеклараторLM — Звіт</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ font-family: "Segoe UI", Arial, sans-serif; margin: 16px; color: #1a1a1a; background: #fafafa; }}
    h2 {{ margin-bottom: 4px; }}
    .stats-block {{
      display: flex; flex-wrap: wrap; align-items: center; gap: 12px;
      background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
      padding: 10px 14px; margin-bottom: 14px;
    }}
    .stat-item {{ font-size: 14px; color: #444; }}
    .filters {{
      display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px;
      background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
      padding: 10px 14px;
    }}
    .filters input, .filters select {{
      padding: 5px 8px; border: 1px solid #cbd5e1; border-radius: 4px;
      font-size: 13px; min-width: 140px;
    }}
    .filters select#declType {{ min-width: 240px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 12.5px; background: #fff; }}
    th, td {{ border: 1px solid #e2e8f0; padding: 5px 7px; vertical-align: middle; }}
    th {{
      position: sticky; top: 0; background: #f1f5f9; font-size: 12px;
      white-space: nowrap; cursor: pointer; user-select: none;
    }}
    th.th-nosort {{ cursor: default; }}
    th.th-nosort:hover {{ background: #f1f5f9; }}
    th:hover {{ background: #e2e8f0; }}
    .sort-arrow {{ font-size: 10px; color: #94a3b8; }}
    th.asc .sort-arrow::after {{ content: " ▲"; color: #3b82f6; }}
    th.desc .sort-arrow::after {{ content: " ▼"; color: #3b82f6; }}
    tbody tr.row-main:nth-child(4n+1) {{ background: #f8fafc; }}
    tbody tr.row-main:nth-child(4n+3) {{ background: #fff; }}
    tr.row-detail {{ background: #f1f5f9; }}
    tr.row-marked, tr.row-marked + tr.row-detail {{ background: #fdf6ee !important; }}
    tr.row-marked:hover {{ background: #faeeda !important; }}
    .rl-critical {{ background: #fee2e2; color: #991b1b; font-weight: 700; text-align: center; }}
    .rl-high     {{ background: #ffedd5; color: #9a3412; font-weight: 600; text-align: center; }}
    .rl-medium   {{ background: #dbeafe; color: #1e40af; text-align: center; }}
    .rl-low      {{ background: #dcfce7; color: #166534; text-align: center; }}
    .rl-unknown  {{ background: #f1f5f9; color: #475569; text-align: center; }}
    .small {{ color: #666; margin-bottom: 8px; font-size: 13px; }}
    td.td-score {{ text-align: center; }}
    .score-pill {{
      display: inline-flex; align-items: center; justify-content: center;
      min-width: 2.1rem; height: 2.1rem; border-radius: 50%;
      font-weight: 700; font-size: 13px;
    }}
    .score-pill-critical {{ background: #fecaca; color: #7f1d1d; }}
    .score-pill-high     {{ background: #fed7aa; color: #9a3412; }}
    .score-pill-medium   {{ background: #bfdbfe; color: #1e3a8a; }}
    .score-pill-low      {{ background: #bbf7d0; color: #14532d; }}
    .score-pill-unknown  {{ background: #e2e8f0; color: #334155; }}
    .risk-badge {{ font-weight: 600; text-transform: lowercase; }}
    .fcircle {{
      display: inline-flex; align-items: center; justify-content: center;
      min-width: 1.5rem; height: 1.5rem; border-radius: 50%;
      background: #e2e8f0; color: #334155; font-size: 11px; font-weight: 700;
    }}
    .row-expand-btn {{
      border: 1px solid #cbd5e1; background: #fff; border-radius: 6px;
      padding: 2px 8px; cursor: pointer; font-size: 11px; color: #475569;
    }}
    .row-expand-btn:hover {{ background: #f1f5f9; }}
    tr.row-main.is-open .row-expand-btn {{ background: #e0f2fe; border-color: #7dd3fc; }}
    .td-detail {{ padding: 0 !important; border-top: none; vertical-align: top; }}
    .detail-panel {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 14px 20px;
      padding: 14px 16px; background: #f8fafc;
    }}
    @media (max-width: 960px) {{ .detail-panel {{ grid-template-columns: 1fr; }} }}
    .detail-col {{ min-width: 0; }}
    .detail-h {{ margin: 0 0 8px 0; font-size: 13px; color: #0f172a; }}
    .detail-h-main {{ font-size: 14px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }}
    .detail-section {{ margin-bottom: 12px; }}
    .red-flags-ul li {{ color: #b91c1c; }}
    .conclusion-box {{
      background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
      padding: 10px 12px; margin-top: 8px;
    }}
    .conclusion-text {{ white-space: pre-wrap; word-break: break-word; color: #1e293b; margin-bottom: 8px; }}
    .conclusion-risk {{ font-size: 13px; }}
    .detail-meta-sub {{ margin-top: 10px; font-size: 12px; }}
    .detail-meta-top {{ margin-top: 12px; }}
    .muted {{ color: #94a3b8; }}
    .rich-ul {{ margin: 4px 0 0 0; padding-left: 18px; }}
    .rich-ul li {{ margin: 2px 0; }}
    .clear-facts-ul {{ margin-top: 0; }}
    .finding {{
      border: 1px solid #e2e8f0; border-left-width: 4px;
      border-radius: 8px;
      padding: 10px 12px; margin-bottom: 8px;
      background: #fff;
    }}
    .finding:last-child {{ margin-bottom: 0; }}
    .finding.sev-critical {{ border-left-color: #dc2626; border-color: #fecaca; }}
    .finding.sev-high     {{ border-left-color: #ea580c; border-color: #fed7aa; }}
    .finding.sev-medium   {{ border-left-color: #d97706; border-color: #fde68a; }}
    .finding.sev-low      {{ border-left-color: #22c55e; border-color: #bbf7d0; }}
    .finding.sev-other    {{ border-left-color: #94a3b8; border-color: #e5e7eb; }}
    .finding header {{
      display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 8px;
      margin-bottom: 4px;
    }}
    .finding .title {{ font-weight: 600; color: #0f172a; flex: 1 1 auto; min-width: 0; }}
    .finding .badges {{ display: inline-flex; gap: 4px; flex-wrap: wrap; }}
    .badge {{
      display: inline-block; padding: 1px 7px; border-radius: 999px;
      background: #fff; color: #334155; font-size: 11px; line-height: 1.6;
      border: 1px solid #e2e8f0; white-space: nowrap;
    }}
    .sev-pill {{
      display: inline-block; padding: 2px 9px; border-radius: 999px;
      font-size: 10px; font-weight: 700; letter-spacing: .04em;
      text-transform: uppercase; line-height: 1.65;
      white-space: nowrap; border: 1px solid transparent;
    }}
    .sev-pill.sev-critical {{ background: #fecaca; color: #7f1d1d; border-color: #f87171; }}
    .sev-pill.sev-high     {{ background: #fed7aa; color: #9a3412; border-color: #fb923c; }}
    .sev-pill.sev-medium   {{ background: #fde68a; color: #92400e; border-color: #fbbf24; }}
    .sev-pill.sev-low      {{ background: #dcfce7; color: #14532d; border-color: #86efac; }}
    .sev-pill.sev-other    {{ background: #f1f5f9; color: #475569; border-color: #cbd5e1; }}
    .finding .rationale {{
      margin: 6px 0 8px 0; color: #1e293b;
      white-space: pre-wrap; word-break: break-word;
    }}
    .finding-more > summary {{
      cursor: pointer; font-size: 12px; color: #475569; user-select: none;
      list-style: revert;
    }}
    .finding-more[open] > summary {{ margin-bottom: 4px; }}
    .finding-more .kv {{ margin: 4px 0; }}
    .finding-more .kv > b {{ display: block; font-size: 11px; color: #64748b; font-weight: 600; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }}
    .chip {{
      display: inline-block; padding: 1px 7px; border-radius: 999px;
      background: #eef2ff; color: #3730a3; font-size: 11px; line-height: 1.6;
      border: 1px solid #c7d2fe;
    }}
    .profile-dl {{ margin: 0; }}
    .profile-dl .dl-row {{
      display: grid; grid-template-columns: minmax(90px, 30%) 1fr;
      gap: 4px 10px; padding: 2px 0;
      border-bottom: 1px dashed #eef2f7;
    }}
    .profile-dl .dl-row:last-child {{ border-bottom: 0; }}
    .profile-dl dt {{ color: #64748b; font-size: 11px; align-self: start; }}
    .profile-dl dd {{ margin: 0; color: #0f172a; word-break: break-word; }}
    .fam-list {{ margin: 0; padding-left: 18px; }}
    .fam-list > li {{ margin-bottom: 6px; }}
    .fam-list > li:last-child {{ margin-bottom: 0; }}
    .fam-head {{ display: inline-block; }}
    .fam-plain {{ color: #1f2937; }}
    .legacy-row {{ opacity: 0.7; }}
    .legacy-cell {{ color: #aaa; font-style: italic; font-size: 11px; }}
    .meta-cell {{ min-width: 180px; }}
    .meta-details summary {{
      cursor: pointer; color: #334155; font-weight: 600; user-select: none;
    }}
    .meta-details[open] summary {{ margin-bottom: 6px; }}
    .meta-details > div {{ margin-bottom: 3px; line-height: 1.35; }}
    .meta-mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }}
    .meta-details a.meta-nazk {{ color: #2563eb; font-weight: 600; font-size: 12px; text-decoration: underline; }}
    .meta-details a.meta-nazk:hover {{ color: #1d4ed8; }}
    .meta-muted {{ color: #94a3b8; }}
    .mark-label {{
      display: flex; align-items: center; gap: 5px;
      font-size: 12px; color: #64748b; cursor: pointer;
      margin-bottom: 6px; user-select: none;
    }}
    .mark-label input {{ cursor: pointer; accent-color: #d97706; }}
    .errors-section {{
      background: #fff7ed; border: 1px solid #fed7aa; border-radius: 8px;
      padding: 10px 14px; margin-bottom: 14px;
    }}
    .errors-section summary {{
      cursor: pointer; font-weight: 600; color: #9a3412; font-size: 14px; user-select: none;
    }}
    .err-badge {{
      background: #ea580c; color: #fff; border-radius: 4px;
      padding: 1px 8px; font-size: 12px; margin-left: 8px;
    }}
    .err-run {{ margin-top: 10px; border-left: 3px solid #fdba74; padding-left: 10px; }}
    .err-run-header {{ display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; margin-bottom: 4px; }}
    .err-model {{ font-weight: 700; font-size: 13px; color: #1e293b; }}
    .err-date {{ font-size: 12px; color: #64748b; }}
    .err-count {{ font-size: 12px; color: #dc2626; }}
    .err-list {{ margin: 2px 0 4px 0; padding-left: 18px; }}
    .col-vis-panel {{
      background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
      padding: 8px 14px; margin-bottom: 10px;
    }}
    .col-vis-panel > summary {{
      cursor: pointer; font-weight: 600; color: #334155; user-select: none; font-size: 13px;
    }}
    .col-vis-panel[open] > summary {{ margin-bottom: 8px; }}
    .col-toggles {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .col-btn {{
      padding: 3px 10px; border-radius: 4px; border: 1px solid #cbd5e1;
      background: #f1f5f9; color: #334155; font-size: 12px;
      cursor: pointer; user-select: none; transition: background .12s, color .12s;
    }}
    .col-btn:hover {{ background: #e2e8f0; }}
    .col-btn.off {{
      background: #f1f5f9; color: #94a3b8; text-decoration: line-through; border-color: #e2e8f0;
    }}
    .col-reset-btn {{
      padding: 3px 10px; border-radius: 4px; border: 1px solid #bfdbfe;
      background: #eff6ff; color: #2563eb; font-size: 12px; cursor: pointer;
    }}
    .col-reset-btn:hover {{ background: #dbeafe; }}
  </style>
  <style id="col-hide"></style>
</head>
<body>
  <h2>ДеклараторLM — Зведена таблиця</h2>
  <div class="small">{sort_hint_html}</div>
  {stats_html}
  {errors_html}
  <div class="filters">
    <input id="q" placeholder="Пошук (ПІБ, посада, знахідки, висновок…)" />
    <input id="modelFilter" placeholder="Фільтр за моделлю" />
    <select id="risk">
      {risk_filter_opts}
    </select>
    <input id="position" placeholder="Фільтр за посадою" />
    <input id="workplace" placeholder="Фільтр за місцем роботи" />
    <input id="yearMin" type="number" min="0" max="3000" placeholder="рік ≥" />
    <input id="scoreMin" type="number" min="0" max="100" placeholder="бал ≥" />
    <select id="declType" title="Фільтр за типом декларації (код з JSONL)">
      {decl_type_filter_opts}
    </select>
  </div>
  <details class="col-vis-panel">
    <summary>Стовпці <span style="font-weight:400;color:#64748b;font-size:12px">(натисніть, щоб приховати/показати)</span></summary>
    <div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px;">
      <div class="col-toggles" id="colToggles"></div>
      <button class="col-reset-btn" id="colVisReset">Показати всі</button>
    </div>
  </details>
  <table id="tbl">
    <thead><tr>{header_ths}</tr></thead>
    <tbody>
      {"".join(row_html_parts)}
    </tbody>
  </table>
  <script>
    const COL_NAME = {col_name};
    const COL_POS = {col_pos};
    const COL_YEAR = {col_year};
    const COL_MODEL = {col_model};
    const COL_SCORE = {col_score};
    const COL_LEVEL = {col_level};
    const COL_FIND = {col_find};

    function getRowPairs() {{
      const mains = Array.from(document.querySelectorAll('#tbl tbody tr.row-main'));
      return mains.map((main) => ({{ main, detail: main.nextElementSibling }}));
    }}

    function pairText(pair) {{
      return (pair.main.textContent + String.fromCharCode(10) + (pair.detail?.textContent || '')).toLowerCase();
    }}

    const q           = document.getElementById('q');
    const modelFilter = document.getElementById('modelFilter');
    const riskEl      = document.getElementById('risk');
    const posEl       = document.getElementById('position');
    const workEl      = document.getElementById('workplace');
    const yearMin     = document.getElementById('yearMin');
    const scoreMin    = document.getElementById('scoreMin');
    const declTypeEl  = document.getElementById('declType');

    function applyFilters() {{
      const qv  = q.value.toLowerCase().trim();
      const mv  = modelFilter.value.toLowerCase().trim();
      const rv  = riskEl.value.toLowerCase().trim();
      const pv  = posEl.value.toLowerCase().trim();
      const wv  = workEl.value.toLowerCase().trim();
      const yv  = Number(yearMin.value || 0);
      const sv  = Number(scoreMin.value || 0);
      const typeFilter = (declTypeEl?.value || '').trim();
      for (const {{ main, detail }} of getRowPairs()) {{
        if (!detail || !detail.classList.contains('row-detail')) continue;
        const cells = main.querySelectorAll('td');
        const text  = pairText({{ main, detail }});
        const model = (cells[COL_MODEL]?.textContent || '').toLowerCase().trim();
        const riskLevel = (main.dataset.riskLevel || '').toLowerCase().trim();
        const posWork = (cells[COL_POS]?.textContent || '').toLowerCase();
        const yearTxt = (cells[COL_YEAR]?.textContent || '').trim();
        const yearNum = Number(yearTxt || 0);
        const score = Number(cells[COL_SCORE]?.textContent || 0);
        const typeCode = (main.dataset.declarationTypeCode || '').trim();
        const typeOk = !typeFilter || typeCode === typeFilter;
        const ok = (!qv || text.includes(qv))
          && (!mv || model.includes(mv))
          && (!rv || riskLevel === rv)
          && (!pv || posWork.includes(pv))
          && (!wv || posWork.includes(wv))
          && (!yv || yearNum >= yv)
          && (score >= sv)
          && typeOk;
        const disp = ok ? '' : 'none';
        main.style.display = disp;
        detail.style.display = disp;
      }}
      renumberVisible();
    }}

    [q, modelFilter, riskEl, posEl, workEl, yearMin, scoreMin].forEach((el) =>
      el.addEventListener('input', applyFilters)
    );
    if (declTypeEl) declTypeEl.addEventListener('change', applyFilters);

    let sortCol = -1;
    let sortAsc = false;

    function cellTextMain(row, col) {{
      return (row.querySelectorAll('td')[col]?.textContent || '').trim();
    }}

    function sortPairsByColumn(col) {{
      const tbody = document.querySelector('#tbl tbody');
      let pairs = getRowPairs().filter((p) => p.detail);
      if (sortCol === col) {{
        sortAsc = !sortAsc;
      }} else {{
        sortCol = col;
        sortAsc = false;
      }}
      pairs.sort((a, b) => {{
        let av = cellTextMain(a.main, col);
        let bv = cellTextMain(b.main, col);
        const an = Number(av);
        const bn = Number(bv);
        let cmp;
        if (!isNaN(an) && !isNaN(bn)) {{
          cmp = an - bn;
        }} else {{
          cmp = av.localeCompare(bv, 'uk');
        }}
        return sortAsc ? cmp : -cmp;
      }});
      pairs.forEach(({{ main, detail }}) => {{
        tbody.appendChild(main);
        tbody.appendChild(detail);
      }});
      document.querySelectorAll('#tbl th').forEach((th, i) => {{
        th.classList.remove('asc', 'desc');
        if (i === sortCol) th.classList.add(sortAsc ? 'asc' : 'desc');
      }});
      renumberVisible();
    }}

    function sortPairsByRunStarted() {{
      const tbody = document.querySelector('#tbl tbody');
      const pairs = getRowPairs().filter((p) => p.detail);
      pairs.sort((a, b) => {{
        const av = a.main.dataset.runStarted || '';
        const bv = b.main.dataset.runStarted || '';
        return bv.localeCompare(av);
      }});
      pairs.forEach(({{ main, detail }}) => {{
        tbody.appendChild(main);
        tbody.appendChild(detail);
      }});
      sortCol = -1;
      sortAsc = false;
      document.querySelectorAll('#tbl th').forEach((th) => th.classList.remove('asc', 'desc'));
      renumberVisible();
    }}

    function sortPairsByDeclarationYear() {{
      const tbody = document.querySelector('#tbl tbody');
      const pairs = getRowPairs().filter((p) => p.detail);
      pairs.sort((a, b) => {{
        const ay = Number(cellTextMain(a.main, COL_YEAR));
        const by = Number(cellTextMain(b.main, COL_YEAR));
        const an = !isNaN(ay) ? ay : 0;
        const bn = !isNaN(by) ? by : 0;
        if (an !== bn) return an - bn;
        const asf = a.main.dataset.sourceFile || '';
        const bsf = b.main.dataset.sourceFile || '';
        return asf.localeCompare(bsf, 'uk');
      }});
      pairs.forEach(({{ main, detail }}) => {{
        tbody.appendChild(main);
        tbody.appendChild(detail);
      }});
      sortCol = COL_YEAR;
      sortAsc = true;
      document.querySelectorAll('#tbl th').forEach((th, i) => {{
        th.classList.remove('asc', 'desc');
        if (i === COL_YEAR) th.classList.add('asc');
      }});
      renumberVisible();
    }}

    document.querySelectorAll('#tbl th.sortable').forEach((th) => {{
      th.addEventListener('click', () => sortPairsByColumn(Number(th.dataset.col)));
    }});

    {default_sort_js}

    function renumberVisible() {{
      let n = 0;
      for (const {{ main }} of getRowPairs()) {{
        if (main.style.display === 'none') continue;
        n += 1;
        const idxCell = main.querySelector('.col-idx');
        if (idxCell) idxCell.textContent = String(n);
      }}
    }}

    document.querySelector('#tbl tbody').addEventListener('click', (e) => {{
      const btn = e.target.closest('.row-expand-btn');
      if (!btn) return;
      const id = btn.dataset.rowId;
      const main = btn.closest('tr.row-main');
      const detail = main?.nextElementSibling;
      if (!detail || !detail.classList.contains('row-detail')) return;
      const open = detail.hasAttribute('hidden');
      if (open) {{
        detail.removeAttribute('hidden');
        btn.setAttribute('aria-expanded', 'true');
        btn.textContent = '▲';
        main.classList.add('is-open');
      }} else {{
        detail.setAttribute('hidden', '');
        btn.setAttribute('aria-expanded', 'false');
        btn.textContent = '▼';
        main.classList.remove('is-open');
      }}
    }});

    const COL_LABELS = [{col_labels_js}];
    const COL_LS_KEY = 'dlm_hidden_cols_v2';

    function getHiddenCols() {{
      try {{ return JSON.parse(localStorage.getItem(COL_LS_KEY) || '[]'); }}
      catch {{ return []; }}
    }}

    function applyColVisCSS(hidden) {{
      let css = '';
      for (const idx of hidden) {{
        css += `#tbl thead th:nth-child(${{idx + 1}}), #tbl tbody tr.row-main td:nth-child(${{idx + 1}}) {{ display: none }}\\n`;
      }}
      document.getElementById('col-hide').textContent = css;
    }}

    function renderColButtons() {{
      const hidden = getHiddenCols();
      const container = document.getElementById('colToggles');
      container.innerHTML = '';
      COL_LABELS.forEach((label, idx) => {{
        const btn = document.createElement('button');
        const isHidden = hidden.includes(idx);
        btn.className = 'col-btn' + (isHidden ? ' off' : '');
        btn.textContent = label || '…';
        btn.title = isHidden ? 'Показати стовпець' : 'Приховати стовпець';
        btn.addEventListener('click', () => {{
          const h = getHiddenCols();
          const pos = h.indexOf(idx);
          if (pos === -1) h.push(idx); else h.splice(pos, 1);
          localStorage.setItem(COL_LS_KEY, JSON.stringify(h));
          applyColVisCSS(h);
          renderColButtons();
        }});
        container.appendChild(btn);
      }});
    }}

    document.getElementById('colVisReset').addEventListener('click', () => {{
      localStorage.removeItem(COL_LS_KEY);
      applyColVisCSS([]);
      renderColButtons();
    }});

    applyColVisCSS(getHiddenCols());
    renderColButtons();

    const MARK_LS_KEY = 'dlm_marked_rows_v2';

    function getMarked() {{
      try {{ return new Set(JSON.parse(localStorage.getItem(MARK_LS_KEY) || '[]')); }}
      catch {{ return new Set(); }}
    }}

    function saveMarked(set) {{
      localStorage.setItem(MARK_LS_KEY, JSON.stringify([...set]));
    }}

    function applyMarking() {{
      const marked = getMarked();
      for (const tr of document.querySelectorAll('tr.row-main[data-key]')) {{
        const key = tr.dataset.key;
        const id = tr.dataset.rowId;
        const isMarked = marked.has(key);
        tr.classList.toggle('row-marked', isMarked);
        const det = tr.nextElementSibling;
        if (det && det.classList.contains('row-detail')) {{
          det.classList.toggle('row-marked', isMarked);
        }}
        const cb = det?.querySelector?.('.mark-cb');
        if (cb) cb.checked = isMarked;
      }}
    }}

    document.querySelector('#tbl tbody').addEventListener('change', (e) => {{
      const cb = e.target.closest('.mark-cb');
      if (!cb) return;
      const key = cb.dataset.key;
      if (!key) return;
      const marked = getMarked();
      if (cb.checked) marked.add(key); else marked.delete(key);
      saveMarked(marked);
      const det = cb.closest('tr.row-detail');
      const id = det?.dataset?.rowId;
      const main = id ? document.querySelector('tr.row-main[data-row-id="' + id + '"]') : null;
      if (main) main.classList.toggle('row-marked', cb.checked);
      if (det) det.classList.toggle('row-marked', cb.checked);
    }});

    applyMarking();
    renumberVisible();
  </script>
</body>
</html>"""
    path.write_text(html, encoding="utf-8")


def write_extras_html(
    path: Path,
    rows: List[Dict[str, Any]],
    error_rows: Optional[List[Dict[str, Any]]] = None,
    *,
    dossier_chronological: bool = False,
) -> None:
    """Deprecated: writes the same unified master-detail HTML as write_filterable_html."""
    print(
        "report.py: write_extras_html / --extras-only is deprecated; "
        "writing the unified master-detail HTML (same as report_table.html).",
        file=sys.stderr,
    )
    write_filterable_html(
        path, rows, error_rows=error_rows, dossier_chronological=dossier_chronological
    )


def level_distribution(rows: List[Dict[str, Any]]) -> List[Tuple[str, int]]:
    counts: Dict[str, int] = {}
    for item in rows:
        analysis = _as_dict(item.get("analysis"))
        level = str(analysis.get("risk_level", "unknown")).lower()
        counts[level] = counts.get(level, 0) + 1
    return sorted(counts.items(), key=lambda x: x[0])


def read_errors_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except json.JSONDecodeError:
                continue
    return rows


def build_errors_summary(error_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return one aggregated dict per (model, run_id) run that had errors."""
    runs: Dict[str, Dict[str, Any]] = {}
    for item in error_rows:
        meta = item.get("run_meta") or {}
        model = str(meta.get("model", "") or "").strip() or "невідома модель"
        run_id = str(meta.get("run_id", "") or "").strip()
        started = str(meta.get("started_at_utc", "") or "").strip()
        key = run_id or started or model
        if key not in runs:
            runs[key] = {
                "model": model,
                "run_started_at": _fmt_date(started),
                "files": [],
                "errors": [],
            }
        runs[key]["files"].append(item.get("source_file", ""))
        runs[key]["errors"].append(str(item.get("error", ""))[:120])
    result = []
    for key, run in runs.items():
        unique_files = list(dict.fromkeys(run["files"]))
        unique_errors = list(dict.fromkeys(run["errors"]))
        result.append({
            "model": run["model"],
            "run_started_at": run["run_started_at"],
            "failed_files": len(unique_files),
            "sample_files": unique_files[:5],
            "sample_errors": unique_errors[:3],
        })
    result.sort(key=lambda x: x["run_started_at"] or "", reverse=True)
    return result


def _build_errors_html(error_rows: List[Dict[str, Any]]) -> str:
    if not error_rows:
        return ""
    runs = build_errors_summary(error_rows)
    if not runs:
        return ""

    blocks = []
    for run in runs:
        model = html_escape(run["model"])
        date = html_escape(run["run_started_at"] or "дата невідома")
        count = run["failed_files"]
        files_html = "".join(
            f'<li style="font-family:monospace;font-size:11px">{html_escape(f)}</li>'
            for f in run["sample_files"]
        )
        errors_html = "".join(
            f'<li style="color:#7f1d1d;font-size:11px">{html_escape(e)}</li>'
            for e in run["sample_errors"]
        )
        more = f" (та ін.)" if count > 5 else ""
        blocks.append(
            f'<div class="err-run">'
            f'<div class="err-run-header">'
            f'<span class="err-model">{model}</span>'
            f'<span class="err-date">{date}</span>'
            f'<span class="err-count">{count} файл(ів) з помилками{more}</span>'
            f'</div>'
            f'<ul class="err-list">{files_html}</ul>'
            f'<ul class="err-list">{errors_html}</ul>'
            f'</div>'
        )

    return (
        '<details class="errors-section">'
        '<summary>[!] Помилки запусків '
        f'<span class="err-badge">{sum(r["failed_files"] for r in runs)} файл(ів)</span>'
        '</summary>'
        + "".join(blocks)
        + "</details>"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert analysis_results.jsonl into readable CSV tables."
    )
    parser.add_argument(
        "--input",
        default="analysis_results.jsonl",
        help="Input JSONL from main.py.",
    )
    parser.add_argument(
        "--summary-csv",
        default="report_summary.csv",
        help="Output summary CSV (1 row per declaration).",
    )
    parser.add_argument(
        "--findings-csv",
        default="report_findings.csv",
        help="Output detailed findings CSV (1 row per finding).",
    )
    parser.add_argument(
        "--table-html",
        default="report_table.html",
        help="Output filterable HTML table.",
    )
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Disable deduplication by declaration_id.",
    )
    parser.add_argument(
        "--errors-input",
        default="analysis_errors.jsonl",
        help="Errors JSONL from main.py (shown in HTML report).",
    )
    parser.add_argument(
        "--extras-only",
        action="store_true",
        help="Deprecated: write unified master-detail HTML to --table-html-extras (same as main report).",
    )
    parser.add_argument(
        "--table-html-extras",
        default="report_table_extras.html",
        help="Output path when using --extras-only (same unified report as --table-html).",
    )
    parser.add_argument(
        "--dossier-chronological",
        action="store_true",
        help="Sort rows oldest→newest by declaration year/date (dossier mode; auto if input is under deep_research/).",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    raw_rows = read_jsonl(input_path)
    error_rows = read_errors_jsonl(Path(args.errors_input))
    dossier_chrono = bool(getattr(args, "dossier_chronological", False)) or is_dossier_report_input(
        input_path
    )

    if bool(getattr(args, "extras_only", False)):
        if not raw_rows:
            extras_path = Path(args.table_html_extras)
            write_extras_html(extras_path, [], error_rows=error_rows)
            print(
                f"Unified HTML written (empty): {extras_path} "
                f"(no valid rows in {input_path})"
            )
            return
        n_read = len(raw_rows)
        raw_rows = enrich_run_metadata(raw_rows)
        rows = raw_rows if args.no_dedupe else dedupe_by_latest(raw_rows)
        if dossier_chrono:
            rows = sort_rows_dossier_chronological(rows, input_path)
        extras_path = Path(args.table_html_extras)
        write_extras_html(
            extras_path, rows, error_rows=error_rows, dossier_chronological=dossier_chrono
        )
        print(
            f"Done (--extras-only, unified HTML). input_rows={n_read}, "
            f"final_rows={len(rows)}, output={extras_path}"
        )
        return

    if not raw_rows:
        raise SystemExit("No valid rows in input JSONL.")

    raw_rows = enrich_run_metadata(raw_rows)
    rows = raw_rows if args.no_dedupe else dedupe_by_latest(raw_rows)
    if dossier_chrono:
        rows = sort_rows_dossier_chronological(rows, input_path)
    summary = build_summary_rows(rows, dossier_chronological=dossier_chrono)
    findings = build_findings_rows(rows)

    summary_path = Path(args.summary_csv)
    findings_path = Path(args.findings_csv)
    table_path = Path(args.table_html)

    write_csv(
        summary_path,
        summary,
        [
            "run_seq",
            "model",
            "run_started_at",
            "source_file",
            "declaration_id",
            "user_declarant_id",
            "declarant_full_name",
            "position",
            "workplace",
            "declaration_year",
            "declaration_type_code",
            "declaration_type_label",
            "risk_score",
            "risk_level",
            "findings_count",
            "red_flags",
            "needs_verification",
            "final_assessment",
        ],
    )
    write_csv(
        findings_path,
        findings,
        [
            "run_seq",
            "model",
            "run_started_at",
            "source_file",
            "declaration_id",
            "user_declarant_id",
            "declarant_full_name",
            "position",
            "workplace",
            "risk_score",
            "risk_level",
            "finding_title",
            "finding_type",
            "severity",
            "confidence",
            "evidence",
            "rationale",
        ],
    )
    write_filterable_html(
        table_path, rows, error_rows=error_rows, dossier_chronological=dossier_chrono
    )

    print(
        f"Done. input_rows={len(raw_rows)}, final_rows={len(rows)}, "
        f"summary={summary_path}, findings={findings_path}, table={table_path}"
    )
    for level, count in level_distribution(rows):
        lv_uk = translate_risk_level(level)
        print(f"рівень_ризику[{lv_uk}] = {count}")


if __name__ == "__main__":
    main()
