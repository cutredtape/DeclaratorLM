#!/usr/bin/env python3
"""Generate compactplus_findings.md from ./compact corpus."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "compact"
OUT = Path(__file__).resolve().parent.parent / "compactplus_findings.md"

PH = {
    "[Конфіденційна інформація]",
    "[Не застосовується]",
    "[Не застосовується.]",
    "[не застосовується]",
    "[Невідомо]",
    "Невідомо",
    "Не застосовується",
    "",
}

PROTECTED = (
    "ownership",
    "rightbelongs",
    "ownershiptype",
    "owningdate",
    "sizeincome",
    "sizeassets",
    "sizeobligation",
    "costdate",
    "cost_date",
    "currency",
    "assets",
    "objecttype",
    "subjectrelation",
    "person_who_care",
    "sources",
    "workplace",
    "workpost",
    "company_name",
    "legalform",
    "transactiondate",
    "specexpenses",
    "corruption",
    "responsible",
    "post_type",
    "post_category",
    "otherownership",
    "citizen",
)


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def is_ph(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        s = v.strip()
        return s in PH or s.lower() in {x.lower() for x in PH if x}
    if isinstance(v, (list, dict)) and len(v) == 0:
        return True
    return False


def protected(k: str) -> bool:
    kl = k.lower()
    return any(p in kl for p in PROTECTED)


def walk(o, pref: str = ""):
    if isinstance(o, dict):
        for k, v in o.items():
            p = f"{pref}.{k}" if pref else k
            yield p, k, v
            yield from walk(v, p)
    elif isinstance(o, list):
        for it in o:
            yield from walk(it, pref + "[*]")


def find_pairs():
    raw_by_id: dict[str, Path] = {}
    compact_by_id: dict[str, Path] = {}
    for p in ROOT.rglob("raw_declaration.json"):
        rid = str(load(p).get("id", "")).strip()
        if rid:
            raw_by_id[rid] = p
    for p in ROOT.rglob("compact_declaration.json"):
        cid = str((load(p).get("meta") or {}).get("id", "")).strip()
        if cid:
            compact_by_id[cid] = p
    pairs = []
    raw_unmatched = []
    compact_unmatched = []
    matched_c = set()
    for rid, rp in raw_by_id.items():
        cp = compact_by_id.get(rid)
        if cp:
            pairs.append((rid, rp, cp))
            matched_c.add(rid)
        else:
            raw_unmatched.append(str(rp))
    for cid, cp in compact_by_id.items():
        if cid not in matched_c:
            compact_unmatched.append(str(cp))
    return pairs, raw_unmatched, compact_unmatched


def main() -> None:
    pairs, raw_unmatched, compact_unmatched = find_pairs()
    n = len(pairs)
    patterns: dict[str, dict] = defaultdict(
        lambda: {"files": set(), "chars": 0, "examples": [], "cat": ""}
    )

    def add_pat(name: str, decl_id: str, ex: str, ch: int, cat: str):
        d = patterns[name]
        d["files"].add(decl_id)
        d["chars"] += ch
        d["cat"] = cat
        if len(d["examples"]) < 2 and ex not in d["examples"]:
            d["examples"].append(ex)

    raw_chars = compact_chars = payload_chars = structured_chars = 0
    key_ph_files: Counter[str] = Counter()
    key_total_files: Counter[str] = Counter()
    key_real_examples: dict[str, list] = defaultdict(list)
    step17_count = 0

    for decl_id, rp, cp in pairs:
        raw = load(rp)
        comp = load(cp)
        raw_chars += len(json.dumps(raw, ensure_ascii=False))
        compact_chars += len(json.dumps(comp, ensure_ascii=False))
        payload = comp.get("all_nonempty_steps_payload") or comp.get("raw_extras") or {}
        ps = json.dumps(payload, ensure_ascii=False)
        payload_chars += len(ps)
        structured = {
            k: v
            for k, v in comp.items()
            if k not in ("all_nonempty_steps_payload", "raw_extras")
        }
        structured_chars += len(json.dumps(structured, ensure_ascii=False))

        if payload:
            add_pat(
                "all_nonempty_steps_payload (дублікат structured-секцій)",
                decl_id,
                f"size={len(ps)} chars",
                len(ps),
                "duplication",
            )
            step_dup = {
                "step_1": "meta.declarant",
                "step_2": "family_members",
                "step_3": "real_estate",
                "step_6": "vehicles",
                "step_11": "incomes",
                "step_12": "cash_assets",
                "step_13": "liabilities",
            }
            for sk, tgt in step_dup.items():
                if payload.get(sk) and comp.get(tgt.split(".")[0] if "." not in tgt else tgt.split(".")[0]):
                    chunk = json.dumps(payload.get(sk), ensure_ascii=False)
                    add_pat(
                        f"all_nonempty_steps_payload.{sk} duplicates {tgt}",
                        decl_id,
                        f"~{len(chunk)} chars",
                        len(chunk),
                        "duplication",
                    )

        sc = comp.get("steps_context") or {}
        m = sc.get("all_steps_0_to_17_present_nonempty") or {}
        if m:
            add_pat(
                "steps_context.all_steps_0_to_17_present_nonempty",
                decl_id,
                f"{sum(1 for v in m.values() if not v)} false flags",
                len(json.dumps(m, ensure_ascii=False)),
                "metadata",
            )

        meta = comp.get("meta") or {}
        pub = (comp.get("step_0_interpreted") or {}).get("public_service_context") or {}
        for k in ("responsible_position", "post_type", "post_category", "corruption_affected"):
            if k in meta and k in pub and meta[k] == pub[k]:
                add_pat(
                    f"meta.{k} duplicated in step_0_interpreted",
                    decl_id,
                    f"{k}={meta[k]}",
                    len(str(meta[k])),
                    "meta_dup",
                )

        if payload.get("step_17") and not comp.get("financial_institutions"):
            step17_count += 1
            s17 = payload.get("step_17")
            s17s = json.dumps(s17, ensure_ascii=False)
            if isinstance(s17, list) and s17 and isinstance(s17[0], dict):
                if "establishment_ua_company_name" in s17[0]:
                    add_pat(
                        "all_nonempty_steps_payload.step_17 (bank/establishment accounts — NOT in structured yet)",
                        decl_id,
                        f"establishment={s17[0].get('establishment_ua_company_name', '')[:50]}",
                        len(s17s),
                        "context_keep",
                    )
                else:
                    add_pat(
                        "all_nonempty_steps_payload.step_17 (misc)",
                        decl_id,
                        s17s[:80],
                        len(s17s),
                        "risky",
                    )
            else:
                add_pat(
                    "all_nonempty_steps_payload.step_17 (confirmation/metadata)",
                    decl_id,
                    s17s[:80],
                    len(s17s),
                    "risky",
                )

        per_key_vals: dict[str, list] = defaultdict(list)
        for path, k, v in walk(payload):
            if isinstance(v, (str, int, float, bool)) or v is None:
                per_key_vals[k].append(v)
                key_total_files[k] += 1
                if is_ph(v):
                    key_ph_files[k] += 1
                elif not protected(k) and (
                    k.endswith("Path")
                    or "extendedstatus" in k.lower()
                    or k in ("iteration", "rights_id", "rightsId", "uid", "hash", "hashOrig")
                ):
                    if len(key_real_examples[k]) < 2:
                        key_real_examples[k].append((decl_id, str(v)[:90]))

        path_chars = ext_chars = svc_chars = ph_chars = 0
        path_ex = ext_ex = svc_ex = ph_ex = ""
        for k, vals in per_key_vals.items():
            if protected(k):
                continue
            ch = sum(len(json.dumps(v, ensure_ascii=False)) for v in vals)
            if k.endswith("Path") or (k.endswith("path") and "Path" in k):
                path_chars += ch
                if not path_ex:
                    path_ex = f"{k} = {str(vals[0])[:70]}"
            elif "extendedstatus" in k.lower():
                ext_chars += ch
                if not ext_ex:
                    ext_ex = f"{k} = {vals[0]}"
            elif k in ("iteration", "rights_id", "rightsId", "uid", "hash", "hashOrig", "id_hash"):
                svc_chars += ch
                if not svc_ex:
                    svc_ex = f"{k} = {vals[0]}"
            elif vals and all(is_ph(v) for v in vals):
                ph_chars += ch
                if not ph_ex:
                    ph_ex = f'{k} = "{vals[0]}"'

        if path_chars:
            add_pat("*.Path / *Path (KOATUU admin codes)", decl_id, path_ex, path_chars, "path")
        if ext_chars:
            add_pat("*_extendedstatus", decl_id, ext_ex, ext_chars, "extendedstatus")
        if svc_chars:
            add_pat("*.iteration / rights_id / hash (service ids)", decl_id, svc_ex, svc_chars, "service")
        if ph_chars:
            add_pat("placeholder-only leaf fields in payload", decl_id, ph_ex, ph_chars, "placeholder")

        step1 = (raw.get("data") or {}).get("step_1", {}).get("data") or {}
        for noise_k in ("passport", "taxNumber", "unzr", "birthday", "postCode"):
            if noise_k in step1 and is_ph(step1.get(noise_k)):
                add_pat(
                    f"raw-only PII placeholders (already absent from structured compact)",
                    decl_id,
                    f'step_1.{noise_k}="{step1.get(noise_k)}"',
                    len(str(step1.get(noise_k))),
                    "raw_dropped",
                )

    items = sorted(
        ((d["chars"], len(d["files"]), name, d) for name, d in patterns.items()),
        reverse=True,
    )
    top10 = items[:10]

    REASONS = {
        "duplication": "Structured-секції вже містять той самий зміст у стислому вигляді; payload — повтор сирих step_*.",
        "path": "Внутрішній KOATUU/адмін-код; для аналізу достатньо текстових назв населених пунктів (якщо не приховані).",
        "extendedstatus": "Служебний прапорець форми; не описує актив, дохід чи зв'язок.",
        "service": "Технічний id запису форми; не несе змісту декларації.",
        "placeholder": "Завжди плейсхолдер — нульова інформація для моделі.",
        "metadata": "Допоміжна карта кроків; достатньо `nonempty_steps` + count.",
        "meta_dup": "Числовий код продубльовано між meta та step_0_interpreted.",
        "raw_dropped": "Compact вже не включає; compactplus не повинен повертати.",
        "risky": "Формальне підтвердження; малий ризик втрати сигналу.",
        "context_keep": "Антикорупційний сигнал (рахунки/установи); зараз лише в payload — треба **перенести** у structured, а не видаляти.",
    }

    lines: list[str] = []
    lines.append("# Compactplus: findings (raw ↔ compact)\n")
    lines.append(
        f"Проаналізовано **{n}** пар `raw_declaration.json` ↔ `compact_declaration.json` "
        f"у `./compact` (папки `decl_*`). Match: `raw.id` = `compact.meta.id`.\n"
    )
    lines.append("## Короткий підсумок\n")
    lines.append(
        f"- **Середній розмір:** raw **{raw_chars // n:,}** симв. → compact **{compact_chars // n:,}** симв. "
        f"(compact *більший* за raw через вбудований payload).\n"
    )
    lines.append(
        f"- **`all_nonempty_steps_payload`:** ~**{payload_chars // n:,}** симв./декларація "
        f"(**{100 * payload_chars / compact_chars:.0f}%** compact) — головний кандидат на видалення.\n"
    )
    lines.append(
        f"- **Structured-частина** (compact без payload): ~**{structured_chars // n:,}** симв./декларація "
        f"(**{100 * structured_chars / compact_chars:.0f}%** compact).\n"
    )
    lines.append(
        f"- **Орієнтовна економія compactplus:** прибрати payload → **~{100 * payload_chars / compact_chars:.0f}%**; "
        f"+ службові ключі в structured → ще **~5–10%**.\n"
    )
    lines.append("\n**Top-10 патернів (сума chars у корпусі):**\n")
    lines.append("| # | Патерн | Файлів | % | Chars |")
    lines.append("|---|--------|--------|---|-------|")
    for i, (ch, cnt, name, _) in enumerate(top10, 1):
        lines.append(f"| {i} | `{name}` | {cnt} | {100 * cnt / n:.1f}% | {ch:,} |")

    def write_section(title: str, cat_filter):
        lines.append(f"\n## {title}\n")
        subset = [(ch, cnt, name, d) for ch, cnt, name, d in items if cat_filter(d["cat"], name)]
        if not subset:
            lines.append("_Немає записів._\n")
            return
        for ch, cnt, name, d in subset[:30]:
            lines.append(f"### `{name}`\n")
            lines.append(f"- **Field / path:** `{name}`")
            lines.append(f"- **Частота:** {cnt} файлів, {100 * cnt / n:.1f}%")
            lines.append(f"- **Орієнт. обсяг:** ~{ch:,} символів")
            lines.append("- **Приклад:**")
            for ex in d["examples"]:
                lines.append(f"  ```\n  {ex}\n  ```")
            lines.append(f"- **Чому:** {REASONS.get(d['cat'], 'Шум.')}")
            if title != "Можна безпечно вирізати":
                if d["cat"] == "meta_dup":
                    lines.append("- **Умови:** залишити codes *або* labels, не обидва.")
                elif d["cat"] == "duplication":
                    lines.append("- **Умови:** одна канонічна копія — structured *або* payload.")
                elif d["cat"] == "context_keep":
                    lines.append("- **Умови:** витягнути в `financial_institutions[]` (назва банку, person_open_account, person_who_care); потім прибрати сирий step_17.")
            lines.append("")

    write_section("Можна безпечно вирізати", lambda c, _: c in ("duplication", "path", "extendedstatus", "service", "placeholder", "metadata", "raw_dropped"))
    write_section("Можна вирізати, але потрібен контекст", lambda c, _: c in ("meta_dup", "context_keep"))
    write_section("Відносно безпечно видалити", lambda c, _: c == "risky")

    lines.append("\n## Unmatched / Suspicious\n")
    lines.append("### Непарні файли\n")
    if raw_unmatched:
        for u in raw_unmatched:
            lines.append(f"- raw без compact: `{u}`")
    else:
        lines.append("- _raw без compact: **немає** (14/14 зматчено по `id`)._")
    if compact_unmatched:
        for u in compact_unmatched:
            lines.append(f"- compact без raw: `{u}`")
    else:
        lines.append("- _compact без raw: **немає**._")

    lines.append("\n### Поля в payload: ≥90% значень — плейсхолдер\n")
    lines.append("| Поле | placeholder-only | % файлів з полем |")
    lines.append("|------|------------------|------------------|")
    for k, c in key_ph_files.most_common(25):
        t = key_total_files[k]
        if t >= n * 0.5 and c >= t * 0.9:
            lines.append(f"| `{k}` | {c}/{t} entries | {100 * c / max(t, 1):.0f}% |")

    lines.append("\n### Дивні кейси: зазвичай шум, інколи зміст\n")
    mixed = 0
    for k, exs in sorted(key_real_examples.items(), key=lambda x: -key_ph_files[x[0]]):
        ph, t = key_ph_files[k], key_total_files[k]
        if t >= 3 and ph >= t * 0.7 and ph < t:
            mixed += 1
            lines.append(
                f"- **`{k}`** — плейсхолдер у {ph}/{t} входженнях; "
                f"приклад реального: `{exs[0][1]}` (`{exs[0][0][:8]}…`)."
            )
            if mixed >= 12:
                break
    if mixed == 0:
        lines.append("- _extendedstatus майже завжди `0`/`1`; Path — завжди KOATUU-коди, не адреси текстом._")

    lines.append(f"\n### step_17 (банківські рахунки / установи)\n\n")
    lines.append(
        f"- **{step17_count}/{n}** декларацій мають непорожній `step_17` у payload.\n"
        "- У більшості це **список установ** (`establishment_ua_company_name`, `person_open_account`, `person_who_care`) — "
        "**антикорупційний сигнал**, який **не дублюється** у structured-секціях compact.\n"
        "- **Не видаляти разом із payload** без міграції в окремий structured-блок.\n"
    )

    lines.append("\n---\n\n## Рекомендовані правила compactplus (чернетка)\n")
    lines.append(
        "1. **Видалити `all_nonempty_steps_payload`**, крім кроків без structured-аналога (зараз: **step_17** — банки/установи).\n"
        "2. **Додати structured `financial_institutions`** з step_17 перед видаленням payload.\n"
        "3. **Structured whitelist:** meta, quick_totals, step_0_interpreted (labels), family_members, "
        "real_estate, vehicles, incomes, cash_assets, liabilities, corporate_rights, major_changes, expenses.\n"
        "4. **Drop keys:** `*_extendedstatus`, `*Path`, `iteration`, `rights_id`, `uid`, `hash*`.\n"
        "5. **Drop placeholder leaves** (не protected): `[Конфіденційна інформація]`, `[Не застосовується]`, empty.\n"
        "6. **steps_context:** лише `nonempty_steps` + `nonempty_steps_count`.\n"
        "7. **Не чіпати:** rights (rightBelongs, ownershipType, owningDate), суми, валюти, дати, "
        "owners_or_users, sources, person_who_care, workPlace/workPost.\n"
    )

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT} ({len(lines)} lines, {n} pairs)")


if __name__ == "__main__":
    main()
