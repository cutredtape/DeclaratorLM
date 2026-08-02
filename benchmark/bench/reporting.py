"""Per-cell report.py invocation and cross-cell metrics matrix."""
from __future__ import annotations

import csv
import json
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .config import PROJECT_ROOT, cell_key
from .state import BenchState


def generate_cell_report(report_dir: Path) -> tuple[bool, str]:
    """Call report.py CLI for one cell. Returns (ok, message)."""
    out_jsonl = report_dir / "analysis_results.jsonl"
    err_jsonl = report_dir / "analysis_errors.jsonl"
    if not out_jsonl.exists():
        out_jsonl.write_text("", encoding="utf-8")

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "report.py"),
        "--input",
        str(out_jsonl),
        "--errors-input",
        str(err_jsonl),
        "--summary-csv",
        str(report_dir / "report_summary.csv"),
        "--findings-csv",
        str(report_dir / "report_findings.csv"),
        "--table-html",
        str(report_dir / "report_table.html"),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    msg = (proc.stdout or "").strip()
    if proc.stderr:
        msg = (msg + "\n" + proc.stderr.strip()).strip()
    if proc.returncode != 0:
        return False, f"report.py завершився з кодом {proc.returncode}: {msg or '(немає виводу)'}"
    return True, msg or f"звіт записано в {report_dir}"


def generate_all_cell_reports(run_dir: Path, state: BenchState) -> List[str]:
    messages: List[str] = []
    reports_root = Path(run_dir) / "reports"
    if not reports_root.is_dir():
        return ["немає теки reports/"]
    for cell in state.cells.values():
        d = reports_root / cell_key(cell.model_id, cell.prompt_name)
        if not d.is_dir():
            messages.append(f"відсутня тека клітинки: {d.name}")
            continue
        ok, msg = generate_cell_report(d)
        messages.append(f"{'OK' if ok else 'ERR'} {d.name}: {msg}")
    return messages


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
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
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


@dataclass
class CellMetrics:
    model_id: str
    prompt_name: str
    status: str
    declarations: int = 0
    errors: int = 0
    risk_score_mean: float = 0.0
    risk_score_median: float = 0.0
    risk_score_min: float = 0.0
    risk_score_max: float = 0.0
    low_count: int = 0
    medium_count: int = 0
    high_count: int = 0
    critical_count: int = 0
    findings_count_mean: float = 0.0
    findings_count_total: int = 0
    empty_final_assessment: int = 0
    final_assessment_len_mean: float = 0.0
    evidence_len_mean: float = 0.0
    rationale_len_mean: float = 0.0
    payload_chars_mean: float = 0.0
    duration_sec_mean: float = 0.0
    cost_usd_sum: Optional[float] = None
    prompt_tokens_sum: int = 0
    completion_tokens_sum: int = 0
    finding_types: Dict[str, int] = field(default_factory=dict)
    source_files: Set[str] = field(default_factory=set)

    def to_row(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "prompt_name": self.prompt_name,
            "status": self.status,
            "declarations": self.declarations,
            "errors": self.errors,
            "risk_score_mean": self.risk_score_mean,
            "risk_score_median": self.risk_score_median,
            "risk_score_min": self.risk_score_min,
            "risk_score_max": self.risk_score_max,
            "low": self.low_count,
            "medium": self.medium_count,
            "high": self.high_count,
            "critical": self.critical_count,
            "findings_count_mean": self.findings_count_mean,
            "findings_count_total": self.findings_count_total,
            "empty_final_assessment": self.empty_final_assessment,
            "final_assessment_len_mean": self.final_assessment_len_mean,
            "evidence_len_mean": self.evidence_len_mean,
            "rationale_len_mean": self.rationale_len_mean,
            "payload_chars_mean": self.payload_chars_mean,
            "duration_sec_mean": self.duration_sec_mean,
            "cost_usd_sum": self.cost_usd_sum if self.cost_usd_sum is not None else "",
            "prompt_tokens_sum": self.prompt_tokens_sum,
            "completion_tokens_sum": self.completion_tokens_sum,
            "finding_types": json.dumps(self.finding_types, ensure_ascii=False),
        }


def analyze_cell(report_dir: Path, *, model_id: str, prompt_name: str, status: str) -> CellMetrics:
    m = CellMetrics(model_id=model_id, prompt_name=prompt_name, status=status)
    rows = _read_jsonl(report_dir / "analysis_results.jsonl")
    err_rows = _read_jsonl(report_dir / "analysis_errors.jsonl")
    m.errors = len(err_rows)
    m.declarations = len(rows)

    scores: List[float] = []
    fc: List[int] = []
    fa_lens: List[int] = []
    ev_lens: List[int] = []
    rat_lens: List[int] = []
    payload_chars: List[float] = []
    durations: List[float] = []
    cost_sum = 0.0
    cost_n = 0
    levels = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    types: Dict[str, int] = {}

    for item in rows:
        src = str(item.get("source_file") or "").strip()
        if src:
            m.source_files.add(src)
        a = item.get("analysis") or {}
        try:
            score = float(a.get("risk_score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        scores.append(score)
        lvl = str(a.get("risk_level") or "").strip().lower()
        if lvl in levels:
            levels[lvl] += 1
        findings = a.get("findings") or []
        if not isinstance(findings, list):
            findings = []
        fc.append(len(findings))
        for fnd in findings:
            if not isinstance(fnd, dict):
                continue
            t = str(fnd.get("type") or "other").strip() or "other"
            types[t] = types.get(t, 0) + 1
            ev = fnd.get("evidence") or []
            if isinstance(ev, list):
                ev_lens.append(sum(len(str(x)) for x in ev))
            else:
                ev_lens.append(len(str(ev)))
            rat_lens.append(len(str(fnd.get("rationale") or "")))
        fa = str(a.get("final_assessment") or "").strip()
        fa_lens.append(len(fa))
        if not fa:
            m.empty_final_assessment += 1
        snap = item.get("context_snapshot") or {}
        try:
            payload_chars.append(float(snap.get("payload_chars_sent") or 0))
        except (TypeError, ValueError):
            pass
        try:
            durations.append(float(item.get("processing_duration_sec") or 0))
        except (TypeError, ValueError):
            pass
        usage = item.get("openrouter_usage")
        if isinstance(usage, dict):
            m.prompt_tokens_sum += int(usage.get("prompt_tokens") or 0)
            m.completion_tokens_sum += int(usage.get("completion_tokens") or 0)
            c = usage.get("cost_usd")
            if c is not None:
                try:
                    cost_sum += float(c)
                    cost_n += 1
                except (TypeError, ValueError):
                    pass

    if scores:
        m.risk_score_mean = round(statistics.mean(scores), 2)
        m.risk_score_median = round(statistics.median(scores), 2)
        m.risk_score_min = round(min(scores), 2)
        m.risk_score_max = round(max(scores), 2)
    m.low_count = levels["low"]
    m.medium_count = levels["medium"]
    m.high_count = levels["high"]
    m.critical_count = levels["critical"]
    if fc:
        m.findings_count_mean = round(statistics.mean(fc), 2)
        m.findings_count_total = sum(fc)
    if fa_lens:
        m.final_assessment_len_mean = round(statistics.mean(fa_lens), 1)
    if ev_lens:
        m.evidence_len_mean = round(statistics.mean(ev_lens), 1)
    if rat_lens:
        m.rationale_len_mean = round(statistics.mean(rat_lens), 1)
    if payload_chars:
        m.payload_chars_mean = round(statistics.mean(payload_chars), 0)
    if durations:
        m.duration_sec_mean = round(statistics.mean(durations), 2)
    if cost_n:
        m.cost_usd_sum = round(cost_sum, 6)
    m.finding_types = types
    return m


def build_matrix(run_dir: Path, state: BenchState) -> Dict[str, Any]:
    metrics: List[CellMetrics] = []
    reports_root = Path(run_dir) / "reports"
    for cell in state.cells.values():
        d = reports_root / cell_key(cell.model_id, cell.prompt_name)
        metrics.append(
            analyze_cell(
                d,
                model_id=cell.model_id,
                prompt_name=cell.prompt_name,
                status=cell.status,
            )
        )

    # Declarations present in every successful cell?
    complete_sets = [m.source_files for m in metrics if m.declarations > 0]
    if complete_sets:
        intersection = set.intersection(*complete_sets) if complete_sets else set()
        union = set.union(*complete_sets) if complete_sets else set()
        incomplete = sorted(union - intersection)
    else:
        intersection = set()
        union = set()
        incomplete = []

    payload = {
        "run_dir": str(run_dir),
        "run_id": state.run_id,
        "run_status": state.status,
        "cells": [m.to_row() for m in metrics],
        "coverage": {
            "union_declarations": len(union),
            "intersection_declarations": len(intersection),
            "incomplete_across_cells": incomplete,
            "incomplete_count": len(incomplete),
        },
    }
    return payload


def write_matrix(run_dir: Path, state: BenchState) -> Dict[str, Path]:
    matrix_dir = Path(run_dir) / "matrix"
    matrix_dir.mkdir(parents=True, exist_ok=True)
    payload = build_matrix(run_dir, state)

    json_path = matrix_dir / "matrix.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    rows = payload.get("cells") or []
    csv_path = matrix_dir / "matrix.csv"
    columns = [
        "model_id",
        "prompt_name",
        "status",
        "declarations",
        "errors",
        "risk_score_mean",
        "risk_score_median",
        "risk_score_min",
        "risk_score_max",
        "low",
        "medium",
        "high",
        "critical",
        "findings_count_mean",
        "findings_count_total",
        "empty_final_assessment",
        "final_assessment_len_mean",
        "evidence_len_mean",
        "rationale_len_mean",
        "payload_chars_mean",
        "duration_sec_mean",
        "cost_usd_sum",
        "prompt_tokens_sum",
        "completion_tokens_sum",
        "finding_types",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    cov = payload.get("coverage") or {}
    html_path = matrix_dir / "matrix.html"
    html_rows = []
    for row in rows:
        html_rows.append(
            "<tr>"
            + "".join(
                f"<td>{_esc(row.get(c, ''))}</td>" for c in columns if c != "finding_types"
            )
            + f"<td><code>{_esc(row.get('finding_types', ''))}</code></td>"
            + "</tr>"
        )
    header = "".join(
        f"<th>{_esc(c)}</th>" for c in columns
    )
    incomplete = cov.get("incomplete_across_cells") or []
    incomplete_html = (
        "<ul>" + "".join(f"<li><code>{_esc(x)}</code></li>" for x in incomplete[:50]) + "</ul>"
        if incomplete
        else "<p>Усі декларації присутні в кожній клітинці з результатами.</p>"
    )
    html = f"""<!DOCTYPE html>
<html lang="uk"><head><meta charset="utf-8"/>
<title>Матриця бенчмарку - {_esc(payload.get('run_id', ''))}</title>
<style>
body{{font-family:system-ui,Segoe UI,sans-serif;margin:24px;background:#0f172a;color:#e2e8f0}}
h1,h2{{color:#f8fafc}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #334155;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#1e293b;position:sticky;top:0}}
tr:nth-child(even){{background:#1e293b88}}
code{{font-size:11px;word-break:break-all}}
.meta{{color:#94a3b8;margin-bottom:16px}}
</style></head><body>
<h1>Матриця бенчмарку</h1>
<div class="meta">run_id={_esc(payload.get('run_id'))} · статус={_esc(payload.get('run_status'))}<br/>
покриття: об'єднання={cov.get('union_declarations')} · перетин={cov.get('intersection_declarations')} ·
неповних={cov.get('incomplete_count')}</div>
<table><thead><tr>{header}</tr></thead>
<tbody>{''.join(html_rows) or '<tr><td colspan="25">немає клітинок</td></tr>'}</tbody></table>
<h2>Неповні в різних клітинках</h2>
{incomplete_html}
</body></html>
"""
    html_path.write_text(html, encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "html": html_path}


def _esc(value: Any) -> str:
    s = str(value if value is not None else "")
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
