"""Зшивання кількох аналізів однієї декларації в один через Jev (docs/JEV.md §3.4).

Споживач — `main.py --replicates N`: кожна декларація аналізується N разів
паралельно й одразу зшивається; далі пайплайн (resume, переміщення, звіт,
досьє) працює зі злитим записом як зі звичайним.

Порівнюються ВСІ пари знахідок з РІЗНИХ прогонів — не лише одного `type`:
різні прогони тегують той самий факт різними типами.
Три питання на пару (same / material_difference / conflict) + оцінка якості
кожної знахідки; кластеризація — повний зв'язок (кожна пара всередині
кластера проходить пороги), представник кластера — найякісніша знахідка.
Усі питання однієї декларації — в ОДНОМУ виклику Jev (~$0.0003).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import client as jev_client
from .client import _answer_block, _level_distribution, _noul_probability
from report_i18n import SEVERITY_SORT_RANK

MODEL = jev_client.DEFAULT_JEV_MODEL
URL = jev_client.DEFAULT_JEV_URL

SAME_INSTR = (
    "Знахідки {a} і {b} у полі `findings` стану описують ТОЙ САМИЙ базовий факт "
    "декларації (той самий актив/особа/операція як привід для ризику), навіть "
    "якщо сформульовані по-різному чи з різним рівнем деталізації."
)
MATERIAL_DIFF_INSTR = (
    "Якщо відкинути формулювання: чи відрізняються знахідки {a} і {b} конкретним "
    "фактом — іншою сумою, особою, датою чи активом, а не просто іншими словами "
    "про те саме?"
)
CONFLICT_INSTR = (
    "Чи суперечать знахідки {a} і {b} одна одній САМЕ в головному предметі "
    "знахідки — конкретній сумі, статусі особи (родич/не родич) чи даті, від "
    "якої залежить сама знахідка? "
    "Приклад КОНФЛІКТУ: одна каже «230 000 грн», інша — «330 000 грн» для "
    "того самого активу; одна каже «член сім'ї», інша — «не член сім'ї» для "
    "того самого співвласника. "
    "Приклад НЕ конфлікту: тексти згадують РІЗНІ додаткові деталі чи "
    "пояснення (наприклад, різні другорядні джерела доходу чи інший опис "
    "того самого висновку), але головна теза та сама. Різні деталі — це "
    "нормально, не конфлікт: став noul ближче до 0, якщо не зачеплено саме "
    "головний предмет знахідки."
)
QUALITY_INSTR = (
    "Оціни якість тексту знахідки {a} у полі `findings` стану: наскільки вона "
    "конкретна й підкріплена фактами (суми, дати, ПІБ), а не загальними фразами."
)
QUALITY_LEVELS = ["дуже слабка", "слабка", "середня", "добра", "відмінна"]
QUALITY_CRITERIA = [
    "Загальна фраза без жодного факту, суми чи імені.",
    "Є натяк на факт, але без конкретних чисел, дат чи імен.",
    "Є одна конкретна деталь (сума АБО дата АБО ім'я), решта — загальні слова.",
    "Кілька конкретних деталей (сума, дата, особа), логічно пов'язані.",
    "Вичерпно конкретна: суми, дати, особи й чіткий причинно-наслідковий зв'язок.",
]
QUALITY_MIDPOINTS = {lvl: i * 25 for i, lvl in enumerate(QUALITY_LEVELS)}  # 0,25,50,75,100

DEFAULT_SAME_THRESHOLD = 0.6
DEFAULT_CONFLICT_THRESHOLD = 0.4

# Кеш keyed за хешем ВМІСТУ знахідки. PROMPT_VERSION у ключі — щоб зміна
# формулювання питань (як-от 24.09.2026: загострення CONFLICT_INSTR
# прикладами) рахувала все заново, а не тихо повертала судження за старим текстом.
PROMPT_VERSION = "2"


def _finding_key_text(f: dict) -> str:
    """Стабільний ключ вмісту знахідки для кешу."""
    parts = [str(f.get("title", "")), str(f.get("rationale", "")), str(f.get("type", ""))]
    parts += [str(e) for e in (f.get("evidence") or [])]
    return "␟".join(parts)


def _hash(text: str) -> str:
    return hashlib.sha1(f"{PROMPT_VERSION}:{text}".encode("utf-8")).hexdigest()[:16]


class Cache:
    """Кеш за хешем ВМІСТУ (не позиції). `path=None` — лише в пам'яті: для
    пайплайну кеш на диску не потрібен (кожна декларація зшивається раз), а
    бенчмарк перезапускає ті самі прогони й економить на ньому."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path
        self.pairs: Dict[str, dict] = {}
        self.quality: Dict[str, dict] = {}
        if path is not None and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.pairs = data.get("pairs", {})
                self.quality = data.get("quality", {})
            except (OSError, json.JSONDecodeError):
                pass

    def pair_key(self, text_a: str, text_b: str) -> str:
        return "|".join(sorted((_hash(text_a), _hash(text_b))))

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"pairs": self.pairs, "quality": self.quality}, ensure_ascii=False),
            encoding="utf-8",
        )


def build_merge_call(findings_by_label: Dict[str, List[dict]], cache: Cache):
    """(state, questions) для ОДНОГО виклику Jev на всі пари+якості декларації,
    що ще не в кеші, плюс те, що вже в кеші."""
    labeled: Dict[str, dict] = {}
    for run_label, findings in findings_by_label.items():
        for i, f in enumerate(findings):
            labeled[f"{run_label}_{i}"] = f

    state_findings = {
        key: {
            "title": f.get("title", ""),
            "type": f.get("type", ""),
            "rationale": f.get("rationale", ""),
            "evidence": f.get("evidence") or [],
        }
        for key, f in labeled.items()
    }

    same_cached: Dict[tuple, float] = {}
    material_cached: Dict[tuple, float] = {}
    conflict_cached: Dict[tuple, float] = {}
    quality_cached: Dict[str, float] = {}
    questions: Dict[str, dict] = {}
    pair_keys: List[tuple] = []
    quality_keys: List[str] = []

    keys = list(labeled.keys())
    for i, ka in enumerate(keys):
        for kb in keys[i + 1:]:
            if ka.rsplit("_", 1)[0] == kb.rsplit("_", 1)[0]:
                continue  # той самий прогін сам із собою не порівнюється
            ck = cache.pair_key(_finding_key_text(labeled[ka]), _finding_key_text(labeled[kb]))
            if ck in cache.pairs:
                c = cache.pairs[ck]
                same_cached[(ka, kb)] = c["same"]
                material_cached[(ka, kb)] = c["material_difference"]
                conflict_cached[(ka, kb)] = c["conflict"]
                continue
            pair_keys.append((ka, kb, ck))
            qk = f"pair_{len(pair_keys)}"
            questions[f"{qk}_same"] = {"type": "noul", "instructions": SAME_INSTR.format(a=ka, b=kb)}
            questions[f"{qk}_material"] = {"type": "noul", "instructions": MATERIAL_DIFF_INSTR.format(a=ka, b=kb)}
            questions[f"{qk}_conflict"] = {"type": "noul", "instructions": CONFLICT_INSTR.format(a=ka, b=kb)}

    for key in keys:
        ck = _hash(_finding_key_text(labeled[key]))
        if ck in cache.quality:
            quality_cached[key] = cache.quality[ck]["score"]
            continue
        quality_keys.append(key)
        questions[f"quality_{key}"] = {
            "type": "score",
            "instructions": QUALITY_INSTR.format(a=key),
            "criteria": QUALITY_CRITERIA,
        }

    cached_results = {
        "same": same_cached, "material": material_cached, "conflict": conflict_cached,
        "quality": quality_cached,
    }
    return {"findings": state_findings}, questions, pair_keys, quality_keys, cached_results, labeled


def call_and_parse(state, questions, pair_keys, quality_keys, api_key, timeout_sec, retries, retry_delay):
    """Виклик (якщо є що питати) і розбір. `quality` — за позиційним ключем
    ("r1_0"); контент-хеш для кешу рахує merge_declaration."""
    same: Dict[tuple, float] = {}
    material: Dict[tuple, float] = {}
    conflict: Dict[tuple, float] = {}
    quality: Dict[str, float] = {}
    cache_updates_pairs: Dict[str, dict] = {}
    if not questions:
        return same, material, conflict, quality, cache_updates_pairs

    raw = jev_client.call_jev(
        state, questions, model=MODEL, url=URL, api_key=api_key,
        timeout_sec=timeout_sec, retries=retries, retry_delay=retry_delay,
    )
    for idx, (ka, kb, ck) in enumerate(pair_keys, start=1):
        qk = f"pair_{idx}"
        s = _noul_probability(_answer_block(raw, f"{qk}_same"))
        m = _noul_probability(_answer_block(raw, f"{qk}_material"))
        c = _noul_probability(_answer_block(raw, f"{qk}_conflict"))
        same[(ka, kb)] = s
        material[(ka, kb)] = m
        conflict[(ka, kb)] = c
        cache_updates_pairs[ck] = {"same": s, "material_difference": m, "conflict": c}
    for key in quality_keys:
        dist = _level_distribution(_answer_block(raw, f"quality_{key}"), QUALITY_LEVELS)
        quality[key] = sum(p * QUALITY_MIDPOINTS[lvl] for lvl, p in dist.items())
    return same, material, conflict, quality, cache_updates_pairs


def complete_linkage_clusters(keys, same, conflict, same_thr, conflict_thr) -> List[List[str]]:
    """Жадібне повне зчеплення: новий елемент мусить пройти пороги з УСІМА вже
    включеними. Може розбити на два те, що могло бути одним, — не може злити
    те, що не мало б. Коректність важливіша за оптимальність."""

    def connected(a: str, b: str) -> bool:
        pair = (a, b) if (a, b) in same else (b, a)
        s = same.get(pair)
        if s is None:
            return False
        return s >= same_thr and conflict.get(pair, 0.0) < conflict_thr

    remaining = set(keys)
    clusters: List[List[str]] = []
    for seed in sorted(keys):
        if seed not in remaining:
            continue
        cluster = [seed]
        remaining.discard(seed)
        for cand in sorted(remaining):
            if all(connected(cand, m) for m in cluster):
                cluster.append(cand)
        for m in cluster[1:]:
            remaining.discard(m)
        clusters.append(cluster)
    return clusters


def pick_representative(cluster: List[str], labeled: Dict[str, dict], quality: Dict[str, float]) -> str:
    def sort_key(key: str):
        return (-quality.get(key, 0.0), -len(labeled[key].get("evidence") or []), key)
    return sorted(cluster, key=sort_key)[0]


def merge_declaration(
    source_file: str,
    runs: Dict[str, Dict[str, dict]],
    cache: Cache,
    api_key: str,
    *,
    risk_level_fn: Callable[[float], str],
    same_thr: float = DEFAULT_SAME_THRESHOLD,
    conflict_thr: float = DEFAULT_CONFLICT_THRESHOLD,
    timeout_sec: int = 60,
    retries: int = 2,
    retry_delay: float = 3.0,
):
    """runs: мітка прогону → {source_file: рядок}. Повертає (злитий рядок, audit).

    `risk_level_fn` (бал → рівень) передає викликач: межі рівнів живуть у
    main.normalize_risk_level, а пакет jev від main не залежить."""
    findings_by_label: Dict[str, List[dict]] = {}
    present_labels: List[str] = []
    risk_scores: List[float] = []
    rows_present: List[dict] = []
    for label, rows in runs.items():
        row = rows.get(source_file)
        if row is None:
            continue
        present_labels.append(label)
        rows_present.append(row)
        findings_by_label[label] = [
            f for f in ((row.get("analysis") or {}).get("findings") or []) if isinstance(f, dict)
        ]
        rs = (row.get("analysis") or {}).get("risk_score")
        if isinstance(rs, (int, float)):
            risk_scores.append(float(rs))

    state, questions, pair_keys, quality_keys, cached, labeled = build_merge_call(findings_by_label, cache)
    same, material, conflict, quality, cache_updates_pairs = call_and_parse(
        state, questions, pair_keys, quality_keys, api_key, timeout_sec, retries, retry_delay,
    )
    same.update(cached["same"])
    material.update(cached["material"])
    conflict.update(cached["conflict"])
    quality.update(cached["quality"])
    for key in quality_keys:
        if key in quality:
            cache.quality[_hash(_finding_key_text(labeled[key]))] = {"score": quality[key]}
    for ck, val in cache_updates_pairs.items():
        cache.pairs[ck] = val

    audit_entries = [
        {
            "source_file": source_file, "a": ka, "b": kb,
            "same": round(s, 4), "material_difference": round(material.get((ka, kb), 0.0), 4),
            "conflict": round(conflict.get((ka, kb), 0.0), 4),
        }
        for (ka, kb), s in same.items()
    ]

    clusters = complete_linkage_clusters(list(labeled.keys()), same, conflict, same_thr, conflict_thr)
    total_runs = len(present_labels)
    merged_findings = []
    for cluster in clusters:
        f = dict(labeled[pick_representative(cluster, labeled, quality)])
        # Впевненість — середня по кластеру, а не представника: середня краще
        # відділяє влучні знахідки від хибних. Підтримку k/N сюди НЕ домішуємо:
        # вона влучність не передбачає — репліки однієї моделі відтворюють і ті
        # самі хибні знахідки.
        confs = []
        for k in cluster:
            try:
                confs.append(float(labeled[k].get("confidence")))
            except (TypeError, ValueError):
                continue
        if confs:
            f["confidence"] = round(sum(confs) / len(confs), 2)
        support_runs = sorted({k.rsplit("_", 1)[0] for k in cluster})
        f["_merge_support"] = f"{len(support_runs)}/{total_runs}"
        f["_merge_support_runs"] = support_runs
        f["_merge_cluster"] = cluster
        merged_findings.append(f)
    merged_findings.sort(
        key=lambda f: (SEVERITY_SORT_RANK.get(str(f.get("severity", "")).lower(), 0),
                       len(f.get("_merge_support_runs") or [])),
        reverse=True,
    )

    merged_risk_score = round(sum(risk_scores) / len(risk_scores)) if risk_scores else 0
    # Основа — повний рядок репліки з балом, найближчим до середнього, а не
    # лише бал і знахідки: інакше зникали б red_flags, needs_verification,
    # final_assessment, профіль — у звіті ці блоки злитих записів були порожні.
    # Їхній текст належить одній репліці й може згадувати знахідку, якої в
    # злитому списку немає; знахідки ж — консенсус усіх.
    base = min(
        rows_present,
        key=lambda r: abs(float((r.get("analysis") or {}).get("risk_score") or 0) - merged_risk_score),
    ) if rows_present else {}
    base_label = present_labels[rows_present.index(base)] if rows_present else ""
    analysis = dict(base.get("analysis") or {})
    analysis.update({
        "risk_score": merged_risk_score,
        "risk_level": risk_level_fn(merged_risk_score),
        "findings": merged_findings,
    })
    row = dict(base)
    row["run_meta"] = {
        **(base.get("run_meta") or {}),
        "merge": {
            "source_runs": present_labels,
            "base_run": base_label,
            "same_threshold": same_thr,
            "conflict_threshold": conflict_thr,
            "n_findings_raw": sum(len(v) for v in findings_by_label.values()),
            "n_findings_merged": len(merged_findings),
            # Бали й кількості знахідок кожної репліки: розкид видно у звіті, а
            # графік бере середню кількість на прогін, а не кількість кластерів
            # (кластери — усе, що сказала хоч одна репліка; вони скачуть сильніше
            # за одиночний прогін).
            "replica_risk_scores": [
                (r.get("analysis") or {}).get("risk_score") for r in rows_present
            ],
            "replica_finding_counts": [len(findings_by_label[lbl]) for lbl in present_labels],
        },
    }
    row["source_file"] = source_file
    row["analysis"] = analysis
    return row, audit_entries


def sum_openrouter_usage(rows: List[dict]) -> Optional[Dict[str, Any]]:
    """Облік вартості зшитого запису — сума по всіх репліках, а не одна з них:
    інакше лічильник витрат у застосунку показував би N-ту частину реальних."""
    usages = [r.get("openrouter_usage") for r in rows if isinstance(r.get("openrouter_usage"), dict)]
    if not usages:
        return None
    total: Dict[str, Any] = {
        k: sum(int(u.get(k) or 0) for u in usages)
        for k in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    costs = [u.get("cost_usd") for u in usages]
    # Невідома вартість хоча б однієї репліки — сума теж невідома (не занижуємо).
    total["cost_usd"] = None if any(c is None for c in costs) else round(sum(float(c) for c in costs), 6)
    total["cost_estimated"] = any(bool(u.get("cost_estimated")) for u in usages)
    total["replicas"] = len(usages)
    return total
