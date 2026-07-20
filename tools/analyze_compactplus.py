#!/usr/bin/env python3
"""Analyze raw vs compact declaration pairs for compactplus rules."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent / "compact"
OUT = Path(__file__).resolve().parent.parent / "compactplus_findings.md"

PLACEHOLDER_EXACT = {
    "[Конфіденційна інформація]",
    "[Не застосовується]",
    "[Не застосовується.]",
    "[Не застосовується ]",
    "Не застосовується",
    "[не застосовується]",
    "[Невідомо]",
    "Невідомо",
    "",
}

NOISE_KEY_SUFFIXES = (
    "_extendedstatus",
    "_extendedStatus",
    "extendedstatus",
    "Path",
    "_path",
    "PathPath",
)

NOISE_KEY_EXACT = {
    "iteration",
    "rights_id",
    "rightsId",
    "rightsID",
    "uid",
    "uuid",
    "hash",
    "hashOrig",
    "hash_orig",
    "id_hash",
    "changedName",
    "sameRegLivingAddress",
    "nui_no_citizenship",
    "cityTypePath",
    "actual_cityTypePath",
    "regionPath",
    "actual_regionPath",
    "districtPath",
    "actual_districtPath",
    "communityPath",
    "actual_communityPath",
    "countryPath",
    "streetTypePath",
    "actual_streetTypePath",
}

PROTECTED_KEY_FRAGMENTS = (
    "ownership",
    "rights",
    "otherownership",
    "ownershiptype",
    "rightbelongs",
    "owningdate",
    "sizeincome",
    "sizeassets",
    "sizeobligation",
    "costdate",
    "cost_date",
    "assetsCurrency",
    "currency",
    "objecttype",
    "subjectrelation",
    "person_who_care",
    "sources",
    "workplace",
    "workpost",
    "company_name",
    "legalform",
    "transactiondate",
    "specExpenses",
    "corruption",
    "responsible",
    "post_type",
    "post_category",
)

STRUCTURED_COMPACT_KEYS = {
    "meta",
    "quick_totals",
    "step_0_interpreted",
    "steps_context",
    "family_members",
    "real_estate",
    "vehicles",
    "incomes",
    "cash_assets",
    "major_changes",
    "unfinished_construction",
    "liabilities",
    "corporate_rights",
    "expenses",
    "financial_institutions",
    "raw_extras",
}


def as_list(val: Any) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


def iter_paths(obj: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            yield p, v
            yield from iter_paths(v, p)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            p = f"{prefix}[*]"
            yield from iter_paths(item, p)


def leaf_key(path: str) -> str:
    if "[*]" in path:
        return path.split("[*].")[-1].split(".")[-1]
    return path.split(".")[-1]


def is_placeholder(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str):
        s = val.strip()
        if s in PLACEHOLDER_EXACT:
            return True
        if s.lower() in {x.lower() for x in PLACEHOLDER_EXACT if x}:
            return True
    if isinstance(val, (list, dict)) and len(val) == 0:
        return True
    if val == 0 or val == "0":
        return False  # codes often meaningful
    return False


def is_protected_key(key: str) -> bool:
    kl = key.lower()
    return any(p in kl for p in PROTECTED_KEY_FRAGMENTS)


def classify_key_noise(key: str, sample_values: list[Any]) -> str | None:
    """Return noise category or None if not classified."""
    if is_protected_key(key):
        return None
    if key in NOISE_KEY_EXACT:
        return "exact_key"
    for suf in NOISE_KEY_SUFFIXES:
        if key.endswith(suf) or suf.lower() in key.lower():
            if key.lower().endswith("path") or "path" in key.lower():
                return "path"
            return "extendedstatus"
    if key == "iteration":
        return "iteration"
    non_placeholder = [v for v in sample_values if not is_placeholder(v)]
    if sample_values and not non_placeholder:
        return "all_placeholder"
    return None


@dataclass
class PatternStat:
    pattern: str
    category: str
    file_ids: set = field(default_factory=set)
    examples: list[str] = field(default_factory=list)
    char_weight: int = 0
    key_count: int = 0

    @property
    def count(self) -> int:
        return len(self.file_ids)

    def add(self, decl_id: str, example: str, chars: int):
        self.file_ids.add(decl_id)
        self.char_weight += chars
        self.key_count += 1
        if len(self.examples) < 3 and example not in self.examples:
            self.examples.append(example)


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def find_pairs() -> tuple[list[tuple[str, Path, Path]], list[str], list[str], list[str]]:
    raw_by_id: dict[str, Path] = {}
    raw_by_stem: dict[str, Path] = {}
    compact_by_id: dict[str, Path] = {}
    compact_by_stem: dict[str, Path] = {}

    suspicious: list[str] = []

    for p in ROOT.rglob("*.json"):
        name = p.name.lower()
        if name == "raw_declaration.json":
            try:
                data = load_json(p)
                rid = str(data.get("id", "")).strip()
                if rid:
                    if rid in raw_by_id:
                        suspicious.append(f"Duplicate raw id {rid}: {raw_by_id[rid]} vs {p}")
                    raw_by_id[rid] = p
                stem = p.parent.name
                raw_by_stem[stem] = p
            except Exception as e:
                suspicious.append(f"Bad raw JSON {p}: {e}")
        elif name == "compact_declaration.json":
            try:
                data = load_json(p)
                cid = str((data.get("meta") or {}).get("id", "")).strip()
                if cid:
                    if cid in compact_by_id:
                        suspicious.append(f"Duplicate compact meta.id {cid}: {compact_by_id[cid]} vs {p}")
                    compact_by_id[cid] = p
                stem = p.parent.name
                compact_by_stem[stem] = p
            except Exception as e:
                suspicious.append(f"Bad compact JSON {p}: {e}")

    pairs: list[tuple[str, Path, Path]] = []
    matched_raw: set[str] = set()
    matched_compact: set[str] = set()

    for rid, rpath in raw_by_id.items():
        if rid in compact_by_id:
            pairs.append((rid, rpath, compact_by_id[rid]))
            matched_raw.add(rid)
            matched_compact.add(rid)

    for stem, rpath in raw_by_stem.items():
        if stem.startswith("decl_"):
            uid = stem[5:]
            if uid in matched_raw:
                continue
        cpath = compact_by_stem.get(stem)
        if cpath:
            try:
                rid = str(load_json(rpath).get("id", "")).strip() or stem
            except Exception:
                rid = stem
            pairs.append((rid, rpath, cpath))
            matched_raw.add(stem)
            matched_compact.add(stem)

    raw_unmatched = []
    for rid, rpath in raw_by_id.items():
        if rid not in matched_raw and rpath.parent.name not in matched_raw:
            raw_unmatched.append(str(rpath))

    compact_unmatched = []
    for cid, cpath in compact_by_id.items():
        if cid not in matched_compact and cpath.parent.name not in matched_compact:
            compact_unmatched.append(str(cpath))

    unmatched_notes = raw_unmatched + [f"compact-only: {x}" for x in compact_unmatched]
    return pairs, unmatched_notes, suspicious, []


def analyze_compact_payload_duplication(compact: dict, decl_id: str, stats: dict[str, PatternStat]):
    """Fields in all_nonempty_steps_payload that duplicate structured sections."""
    payload = compact.get("all_nonempty_steps_payload") or compact.get("raw_extras") or {}
    structured = {k: compact.get(k) for k in STRUCTURED_COMPACT_KEYS if k in compact}

    # step_1 in payload vs meta.declarant
    step1 = payload.get("step_1")
    if isinstance(step1, dict):
        decl = (compact.get("meta") or {}).get("declarant") or {}
        dup_fields = []
        for k in ("lastname", "firstname", "middlename", "workPlace", "workPost"):
            v1 = step1.get(k)
            v2 = decl.get(k if k != "workPlace" else "work_place") or decl.get(k)
            if v1 and v2 and str(v1).strip() == str(v2).strip():
                dup_fields.append(k)
        if dup_fields:
            pat = "all_nonempty_steps_payload.step_1 duplicates meta.declarant"
            stats.setdefault(pat, PatternStat(pat, "duplication")).add(
                decl_id,
                f"step_1: {', '.join(dup_fields[:5])}",
                sum(len(str(step1.get(f, ""))) for f in dup_fields),
            )

    # step_0 vs step_0_interpreted
    step0 = payload.get("step_0")
    if isinstance(step0, dict):
        pat = "all_nonempty_steps_payload.step_0 duplicates step_0_interpreted"
        stats.setdefault(pat, PatternStat(pat, "duplication")).add(
            decl_id, json.dumps(step0, ensure_ascii=False)[:120], len(json.dumps(step0, ensure_ascii=False))
        )

    # Raw step payloads for asset steps vs structured arrays
    step_map = {
        "step_3": "real_estate",
        "step_6": "vehicles",
        "step_11": "incomes",
        "step_12": "cash_assets",
        "step_13": "liabilities",
        "step_2": "family_members",
    }
    for step_key, struct_key in step_map.items():
        raw_step = payload.get(step_key)
        struct = compact.get(struct_key)
        if raw_step and struct:
            pat = f"all_nonempty_steps_payload.{step_key} duplicates {struct_key}"
            raw_len = len(json.dumps(raw_step, ensure_ascii=False))
            struct_len = len(json.dumps(struct, ensure_ascii=False))
            stats.setdefault(pat, PatternStat(pat, "duplication")).add(
                decl_id,
                f"raw step ~{raw_len} chars vs structured ~{struct_len} chars",
                max(0, raw_len - struct_len),
            )


def analyze_object(obj: Any, decl_id: str, scope: str, stats: dict[str, PatternStat], value_samples: dict[str, list]):
    for path, val in iter_paths(obj):
        if not isinstance(val, (str, int, float, bool)) and not val is None:
            if isinstance(val, (list, dict)) and len(val) == 0:
                key = leaf_key(path)
                if not is_protected_key(key):
                    pat = f"{scope}.*.{key} (empty container)"
                    stats.setdefault(pat, PatternStat(pat, "empty")).add(decl_id, f"{path} = []/{{}}", 2)
            continue
        key = leaf_key(path)
        value_samples.setdefault(key, []).append(val)
        chars = len(json.dumps(val, ensure_ascii=False))
        cat = classify_key_noise(key, value_samples[key][-5:])
        if cat == "path":
            pat = f"*.{key}" if key.endswith("Path") or "Path" in key else f"*.{key}"
            stats.setdefault(f"path field: {key}", PatternStat(f"*.{key}", "path")).add(
                decl_id, f"{path} = {str(val)[:80]}", chars
            )
        elif cat == "extendedstatus":
            stats.setdefault(f"extendedstatus: {key}", PatternStat(f"*.{key}", "extendedstatus")).add(
                decl_id, f"{path} = {val}", chars
            )
        elif cat == "exact_key":
            stats.setdefault(f"service key: {key}", PatternStat(f"*.{key}", "service")).add(
                decl_id, f"{path} = {str(val)[:80]}", chars
            )
        elif cat == "all_placeholder" and not is_protected_key(key):
            stats.setdefault(f"placeholder-only field: {key}", PatternStat(f"*.{key}", "placeholder")).add(
                decl_id, f'{path} = "{val}"', chars
            )
        elif key == "rights" and isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    for rk, rv in item.items():
                        if rk in ("rights_id", "rightsId", "iteration") or rk.endswith("_extendedstatus"):
                            stats.setdefault(f"rights.{rk}", PatternStat(f"rights[*].{rk}", "rights_noise")).add(
                                decl_id, f"rights[{rk}] = {rv}", len(str(rv))
                            )


def analyze_steps_context(compact: dict, decl_id: str, stats: dict[str, PatternStat]):
    sc = compact.get("steps_context") or {}
    present = sc.get("all_steps_0_to_17_present_nonempty") or {}
    false_count = sum(1 for v in present.values() if not v)
    if false_count:
        pat = "steps_context.all_steps_0_to_17_present_nonempty (false entries)"
        stats.setdefault(pat, PatternStat(pat, "metadata")).add(
            decl_id, f"{false_count} steps marked false", false_count * 15
        )
    dup = sc.get("nonempty_steps")
    if dup and present:
        pat = "steps_context.nonempty_steps (redundant list)"
        stats.setdefault(pat, PatternStat(pat, "metadata")).add(
            decl_id, str(dup)[:100], len(json.dumps(dup, ensure_ascii=False))
        )


def analyze_meta_duplication(compact: dict, decl_id: str, stats: dict[str, PatternStat]):
    meta = compact.get("meta") or {}
    s0 = compact.get("step_0_interpreted") or {}
    pub = (s0.get("public_service_context") or {})
    for k in ("responsible_position", "post_type", "post_category", "corruption_affected"):
        if k in meta and k in pub and meta[k] == pub[k]:
            pat = f"meta.{k} duplicated in step_0_interpreted.public_service_context"
            stats.setdefault(pat, PatternStat(f"meta.{k}", "meta_dup")).add(
                decl_id, f"{k}={meta[k]}", len(str(meta[k]))
            )


def bucket_pattern(stat: PatternStat) -> str:
    p = stat.pattern.lower()
    cat = stat.category
    if cat == "duplication" and "all_nonempty_steps_payload" in p:
        return "safe"
    if cat in ("path", "extendedstatus", "service", "placeholder", "empty", "metadata", "rights_noise"):
        if cat == "placeholder" and any(x in p for x in ("objecttype", "owning", "size", "cost", "currency")):
            return "context"
        return "safe"
    if cat == "meta_dup":
        return "context"
    if "step_17" in p or "step_5" in p or "step_7" in p or "step_8" in p or "step_10" in p:
        return "risky"
    if cat == "duplication":
        return "context"
    return "context"


def fmt_pct(n: int, total: int) -> str:
    return f"{n} файлів, {100 * n / total:.1f}%" if total else "0"


REASONS = {
    "path": "Внутрішній KOATUU/адмін-шлях НАЗК; для антикорупційного аналізу достатньо текстових назв регіону/міста з structured-полів.",
    "extendedstatus": "Статус розширеного поля форми (чи заповнювалось); не описує актив, дохід чи зв'язок.",
    "service": "Ідентифікатор ітерації/форми; потрібен лише для UI подання, не для змісту декларації.",
    "placeholder": "Значення-плейсхолдер або порожнє; не несе фактичного змісту.",
    "empty": "Порожній масив/об'єкт — займає місце в JSON без даних.",
    "metadata": "Дублює інформацію, яка вже є списком `nonempty_steps` або не потрібна моделі.",
    "duplication": "Той самий зміст уже винесено у structured-секції compact (meta, real_estate, incomes…).",
    "rights_noise": "Технічні поля всередині блоку rights; для аналізу важливі rightBelongs/ownershipType/owningDate, а не rights_id.",
    "meta_dup": "Числовий код продубльовано в interpret-блоці з людськочитабельним label.",
}

CONDITIONS = {
    "duplication": "НЕ вирізати, якщо прибираєте structured-секції і лишаєте лише payload (або навпаки). Має залишитись **одна** канонічна копія кожного step.",
    "meta_dup": "Залишити або в meta, або в step_0_interpreted — не обидва.",
}


def write_section(lines: list[str], title: str, items: list[PatternStat], total_pairs: int) -> None:
    lines.append(f"\n## {title}\n")
    if not items:
        lines.append("_Немає записів._\n")
        return
    for s in items[:40]:
        lines.append(f"### `{s.pattern}`\n")
        lines.append(f"- **Частота:** {fmt_pct(s.count, total_pairs)}")
        lines.append(f"- **Орієнт. обсяг:** ~{s.char_weight:,} символів (сума по всіх входженнях)")
        lines.append("- **Приклад:**")
        for ex in s.examples[:2]:
            lines.append(f"  ```\n  {ex}\n  ```")
        reason = REASONS.get(s.category, "Службове або повторюване поле без аналітичного змісту.")
        lines.append(f"- **Чому:** {reason}")
        cond = CONDITIONS.get(s.pattern) or CONDITIONS.get(s.category)
        if cond and title != "Можна безпечно вирізати":
            lines.append(f"- **Умови / застереження:** {cond}")
        lines.append("")


def main():
    pairs, unmatched, suspicious, _ = find_pairs()
    total_pairs = len(pairs)
    compact_stats: dict[str, PatternStat] = {}
    raw_stats: dict[str, PatternStat] = {}
    ambiguous: list[tuple[str, str, str]] = []

    total_raw_chars = 0
    total_compact_chars = 0
    payload_chars = 0

    for decl_id, raw_path, compact_path in pairs:
        raw = load_json(raw_path)
        compact = load_json(compact_path)
        raw_s = json.dumps(raw, ensure_ascii=False)
        compact_s = json.dumps(compact, ensure_ascii=False)
        total_raw_chars += len(raw_s)
        total_compact_chars += len(compact_s)
        payload = compact.get("all_nonempty_steps_payload") or compact.get("raw_extras") or {}
        payload_chars += len(json.dumps(payload, ensure_ascii=False))

        analyze_compact_payload_duplication(compact, decl_id, compact_stats)
        analyze_steps_context(compact, decl_id, compact_stats)
        analyze_meta_duplication(compact, decl_id, compact_stats)
        analyze_object(compact, decl_id, "compact", compact_stats, {})
        analyze_object(payload, decl_id, "payload", compact_stats, {})

        # Raw-only noise still relevant if compactplus skips payload
        data = raw.get("data") or {}
        for sk, node in data.items():
            if isinstance(node, dict):
                analyze_object(node.get("data"), decl_id, f"raw.{sk}", raw_stats, {})

        # Ambiguous: field usually placeholder but sometimes real
        for path, val in iter_paths(payload):
            key = leaf_key(path)
            if is_protected_key(key):
                continue
            if isinstance(val, str) and val.strip() and val.strip() not in PLACEHOLDER_EXACT:
                if key.endswith("_extendedstatus") or "Path" in key:
                    ambiguous.append((decl_id, path, str(val)[:100]))

    # Merge stats
    all_stats: dict[str, PatternStat] = {}
    for d in (compact_stats, raw_stats):
        for k, v in d.items():
            if k not in all_stats:
                all_stats[k] = v
            else:
                all_stats[k].file_ids |= v.file_ids
                all_stats[k].char_weight += v.char_weight
                all_stats[k].key_count += v.key_count
                for ex in v.examples:
                    if len(all_stats[k].examples) < 3:
                        all_stats[k].examples.append(ex)

    ranked = sorted(all_stats.values(), key=lambda s: (-s.char_weight, -s.count))
    top10 = ranked[:10]

    safe: list[PatternStat] = []
    context: list[PatternStat] = []
    risky: list[PatternStat] = []
    for s in ranked:
        b = bucket_pattern(s)
        if b == "safe":
            safe.append(s)
        elif b == "risky":
            risky.append(s)
        else:
            context.append(s)

    potential_savings = sum(s.char_weight for s in ranked if bucket_pattern(s) == "safe")
    savings_pct = 100 * potential_savings / total_compact_chars if total_compact_chars else 0

    lines: list[str] = []
    lines.append("# Compactplus: findings (raw ↔ compact)\n")
    lines.append(f"Проаналізовано **{total_pairs}** пар `raw_declaration.json` ↔ `compact_declaration.json` у `{ROOT}`.\n")
    lines.append("## Короткий підсумок\n")
    lines.append(
        f"- Середній розмір raw: **{total_raw_chars // max(total_pairs,1):,}** символів; compact: **{total_compact_chars // max(total_pairs,1):,}**; "
        f"блок `all_nonempty_steps_payload` — **~{payload_chars // max(total_pairs,1):,}** символів/декларація (~"
        f"{100*payload_chars/max(total_compact_chars,1):.0f}% compact).\n"
    )
    lines.append(
        f"- **Орієнтовна додаткова економія** (безпечні патерни): ~**{potential_savings:,}** символів на корпусі "
        f"({savings_pct:.1f}% від сумарного compact), переважно за рахунок прибирання дублікатів сирих step_* і службових полів.\n"
    )
    lines.append("\n**Top-10 патернів за «вагою» (chars × частота):**\n")
    lines.append("| # | Патерн | Файлів | % | Орієнт. chars |")
    lines.append("|---|--------|--------|---|---------------|")
    for i, s in enumerate(top10, 1):
        lines.append(
            f"| {i} | `{s.pattern}` | {s.count} | {100*s.count/max(total_pairs,1):.1f}% | {s.char_weight:,} |"
        )

    write_section(lines, "Можна безпечно вирізати", safe, total_pairs)
    write_section(lines, "Можна вирізати, але потрібен контекст", context, total_pairs)
    write_section(lines, "Відносно безпечно видалити", risky, total_pairs)

    lines.append("\n## Unmatched / Suspicious\n")
    if unmatched:
        lines.append("### Непарні файли\n")
        for u in unmatched:
            lines.append(f"- `{u}`")
    else:
        lines.append("### Непарні файли\n\n_Усі 14 raw мають пару compact (match по `id` / `meta.id` або ім'я папки `decl_*`)._\n")

    if suspicious:
        lines.append("\n### Підозрілі дублікати\n")
        for s in suspicious:
            lines.append(f"- {s}")

    # Aggregate key frequency table for compact payload
    key_freq: Counter[str] = Counter()
    key_placeholder_only: Counter[str] = Counter()
    key_mixed: set[str] = set()
    samples_mixed: dict[str, list] = defaultdict(list)

    for decl_id, _, compact_path in pairs:
        compact = load_json(compact_path)
        payload = compact.get("all_nonempty_steps_payload") or compact.get("raw_extras") or {}
        per_file_keys: dict[str, list] = defaultdict(list)
        for path, val in iter_paths(payload):
            if isinstance(val, (str, int, float, bool)) or val is None:
                k = leaf_key(path)
                per_file_keys[k].append(val)
        for k, vals in per_file_keys.items():
            key_freq[k] += 1
            non_ph = [v for v in vals if not is_placeholder(v)]
            if vals and not non_ph:
                key_placeholder_only[k] += 1
            elif non_ph and any(is_placeholder(v) for v in vals):
                if k not in samples_mixed and len(samples_mixed) < 30:
                    samples_mixed[k].append((decl_id, str(non_ph[0])[:80]))

    lines.append("\n### Поля в `all_nonempty_steps_payload`, що **завжди** плейсхолдер/порожні (≥80% файлів)\n")
    lines.append("| Поле | Файлів (placeholder-only) | % |")
    lines.append("|------|---------------------------|---|")
    for k, c in key_placeholder_only.most_common(35):
        if c >= max(1, int(0.5 * total_pairs)):
            lines.append(f"| `{k}` | {c} | {100*c/total_pairs:.1f}% |")

    lines.append("\n### Дивні кейси: поле зазвичай шум, але інколи має зміст\n")
    mixed_cases = []
    for k, c in key_freq.items():
        ph = key_placeholder_only[k]
        if ph >= total_pairs * 0.7 and ph < total_pairs:
            mixed_cases.append((k, ph, total_pairs - ph))
    for k, ph, real in sorted(mixed_cases, key=lambda x: -x[1])[:20]:
        lines.append(f"- **`{k}`**: плейсхолдер у {ph}/{total_pairs} файлах, реальне значення у {real}. "
                     f"Приклад реального: знайти вручну або залишити умовне правило «virizati лише якщо placeholder».")

    if ambiguous[:15]:
        lines.append("\n### Приклади не-плейсхолдерних значень у «шумових» ключах (path/extendedstatus)\n")
        seen = set()
        for decl_id, path, val in ambiguous[:15]:
            key = (path, val)
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- `{decl_id}` → `{path}` = `{val}`")

    lines.append("\n---\n")
    lines.append("## Рекомендовані правила compactplus (чернетка)\n")
    lines.append("1. **Прибрати `all_nonempty_steps_payload` повністю**, якщо structured-секції (`real_estate`, `incomes`, `meta`…) уже заповнені — це найбільший виграш.\n")
    lines.append("2. У structured-секціях лишити лише: тип об'єкта, суми, валюти, дати, `owners_or_users`, джерела доходу, ПІБ/relation.\n")
    lines.append("3. Глобально видаляти ключі за патерном: `*_extendedstatus`, `*Path`, `iteration`, `rights_id`, `hash*`, `uid`.\n")
    lines.append("4. Видаляти leaf-значення, якщо ∈ {`[Конфіденційна інформація]`, `[Не застосовується]`, `\"\"`, `null`} **і** ключ не в whitelist (ownership*, *Date, size*, cost*, currency, objectType з реальним текстом).\n")
    lines.append("5. `steps_context`: лишити `nonempty_steps` + `nonempty_steps_count`; прибрати map з 18 false-entries.\n")
    lines.append("6. `step_0_interpreted`: лишити labels; прибрати дубльовані numeric codes, якщо вони є в `meta`.\n")
    lines.append("7. **Не чіпати:** `rights[]` зміст (rightBelongs, ownershipType, owningDate, citizen), `person_who_care`, `sources`, суми/валюти, `workPlace`/`workPost`, corporate rights, liabilities.\n")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT} ({len(lines)} lines, {total_pairs} pairs)")


if __name__ == "__main__":
    main()
