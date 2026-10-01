"""Dossier summary after the combined HTML report (deep_research / dossier mode)."""

from __future__ import annotations

import html
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Tuple

# The project root must come first on sys.path. Otherwise `import main` may pick up
# nazk_parser/main.py (same module name) → ImportError for call_ollama_text.
_ROOT = Path(__file__).resolve().parent.parent
_rp = str(_ROOT)
try:
    sys.path.remove(_rp)
except ValueError:
    pass
sys.path.insert(0, _rp)

from main import call_ollama_text

SECTION_ID = "declarator-dossier-summary"
MAX_HTML_CHARS_DEFAULT = 250_000
# -1 = no artificial Ollama response-length limit (see main._ollama_num_predict_for_options).
DOSSIER_SUMMARY_NUM_PREDICT = -1

# Dossier summary prompt stays Ukrainian (report content and model reply language).
_SYSTEM = """Ти — аналітик е-декларацій і ризиків корупції.
Тобі передано HTML-звіт з попередніми знахідками по деклараціях однієї конкретної особи за різні роки (таблиця, статистика).

Правила:
- Спирайся лише на те, що є в HTML. Не вигадуй фактів і не припускай того, чого немає у звіті.
- Врахуй динаміку між роками: повторюваність підозрілих патернів, зміну ризику, різкі зміни в майні/доходах/боргах/сім'ї лише якщо це видно з таблиці.
- Якщо перед HTML є «Хронологія змін між сусідніми деклараціями» — це факти, пораховані програмою з самих декларацій; спирайся на неї, коли говориш про динаміку. Задекларована вартість майна за роки не змінюється — це не ознака ризику.
- Якщо даних недостатньо для висновку — прямо скажи про це одним-двома реченнями.

Формат відповіді:
- Лише звичайний текст українською, 5–10 речень (цілі речення).
- Без заголовків, без маркдауну, без JSON, без нумерованих списків, без HTML-тегів."""

DOSSIER_SYSTEM_PROMPT = _SYSTEM
DOSSIER_USER_PROMPT_TEMPLATE = (
    "Нижче — HTML зведеного звіту. Проаналізуй його як єдине досьє по цій особі.\n\n"
    "{changes_timeline}"
    "--- HTML ---\n{html_fragment}{truncation_note}"
)


def strip_scripts(html_text: str) -> str:
    return re.sub(
        r"<script\b[^>]*>.*?</script>",
        "",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )


def prepare_html_for_prompt(raw: str, max_chars: int) -> Tuple[str, str]:
    """Returns (prompt fragment, truncation note or empty string).

    Наявний розділ підсумку вирізається: при повторному підсумку готового звіту
    (debug, порівняння моделей) модель інакше бачила б власну стару відповідь і
    при temperature 0 переказувала її дослівно — виявлено 26.09.2026 на A/B.
    """
    cleaned = strip_scripts(remove_existing_summary_section(raw))
    if len(cleaned) <= max_chars:
        return cleaned, ""
    return cleaned[:max_chars], (
        f"\n\n[Увага: HTML обрізано до {max_chars} символів через обмеження розміру запиту.]"
    )


def build_prompts(
    html_fragment: str,
    truncation_note: str,
    *,
    system_override: str | None = None,
    user_template_override: str | None = None,
    changes_timeline: str = "",
) -> Tuple[str, str]:
    system = (system_override or "").strip() or DOSSIER_SYSTEM_PROMPT
    tmpl = (user_template_override or "").strip()
    # Порожня хронологія — рядок зникає цілком, промпт як до хронології змін (docs/JEV.md §3.6). Власний
    # шаблон без {changes_timeline} теж працює: format ігнорує зайві ключі.
    timeline_block = f"{changes_timeline.strip()}\n\n" if (changes_timeline or "").strip() else ""
    user = (tmpl or DOSSIER_USER_PROMPT_TEMPLATE).format(
        html_fragment=html_fragment,
        truncation_note=truncation_note,
        changes_timeline=timeline_block,
    )
    return system, user


def remove_existing_summary_section(html_text: str) -> str:
    pattern = re.compile(
        rf'<section\s+id="{re.escape(SECTION_ID)}"[^>]*>.*?</section>',
        re.DOTALL | re.IGNORECASE,
    )
    return pattern.sub("", html_text)


def append_summary_to_html(path: Path, summary: str) -> None:
    """Insert or replace the summary section before </body>."""
    raw = path.read_text(encoding="utf-8")
    body = remove_existing_summary_section(raw)
    safe = html.escape(summary.strip())
    block = f"""  <section id="{SECTION_ID}" style="margin-top:28px;padding:14px 16px;border:1px solid #cbd5e1;border-radius:8px;background:#f8fafc;max-width:100%;">
    <h2 style="margin:0 0 10px 0;font-size:17px;color:#0f172a;">Підсумок досьє (динаміка по роках)</h2>
    <div style="font-size:14px;line-height:1.55;color:#1e293b;white-space:pre-wrap;">{safe}</div>
  </section>
"""
    lower = body.lower()
    idx = lower.rfind("</body>")
    if idx != -1:
        out = body[:idx] + block + body[idx:]
    else:
        out = body + "\n" + block
    # Atomic rewrite: write to a sibling temp file and rename. Without this,
    # a crash mid-write would leave the existing report HTML truncated/empty.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(out, encoding="utf-8")
    os.replace(tmp, path)


def run_dossier_table_summary_append(
    *,
    table_html_path: Path,
    model: str,
    host: str,
    timeout_sec: int,
    num_predict: int = DOSSIER_SUMMARY_NUM_PREDICT,
    api_key: str = "",
    cloud_mode: bool = False,
    max_html_chars: int = MAX_HTML_CHARS_DEFAULT,
    prompt_overrides: Mapping[str, Any] | None = None,
    html_source_override: str | None = None,
    provider: str = "ollama",
    changes_timeline: str = "",
) -> Tuple[bool, str]:
    """
    Read the HTML report, call the LLM, append the summary section.
    Returns (success, log line).

    changes_timeline — хронологія змін між роками (dossier_changes.timeline_text),
    іде в промпт перед HTML; порожня — промпт як раніше.

    If html_source_override is set, that string goes into the prompt (after strip_scripts),
    while the summary is still written to table_html_path (file must exist).
    """
    if not table_html_path.exists():
        return False, f"[Досьє] Пропуск підсумку: файл не знайдено: {table_html_path}"

    if html_source_override is not None:
        raw = html_source_override
    else:
        raw = table_html_path.read_text(encoding="utf-8")
    fragment, trunc_note = prepare_html_for_prompt(raw, max_html_chars)
    warn = ""
    if trunc_note:
        warn = f"[Досьє] HTML обрізано до {max_html_chars} символів перед відправкою в модель.\n"

    po = dict(prompt_overrides) if prompt_overrides else {}
    d_sys = po.get("dossier_system_prompt")
    d_user_tmpl = po.get("dossier_user_prompt_template")
    try:
        system_p, user_p = build_prompts(
            fragment,
            trunc_note,
            system_override=d_sys if isinstance(d_sys, str) else None,
            user_template_override=d_user_tmpl if isinstance(d_user_tmpl, str) else None,
            changes_timeline=changes_timeline,
        )
    except KeyError as exc:
        return (
            False,
            warn
            + "[Досьє] Некоректний шаблон user-промпта: потрібні плейсхолдери "
            + "{html_fragment} та {truncation_note}. "
            + str(exc),
        )
    try:
        if str(provider or "ollama").lower() == "openrouter":
            # Alternate path: neither call_ollama_text nor /api/chat is used here.
            from openrouter_client import call_openrouter_text

            summary = call_openrouter_text(
                model,
                system_p,
                user_p,
                host=host,
                timeout_sec=timeout_sec,
                num_predict=num_predict,
                api_key=api_key,
            )
        else:
            summary = call_ollama_text(
                model,
                system_p,
                user_p,
                host=host,
                timeout_sec=timeout_sec,
                num_predict=num_predict,
                api_key=api_key,
                cloud_mode=cloud_mode,
            )
    except Exception as exc:  # noqa: BLE001
        return False, warn + f"[Досьє] Підсумок досьє не згенеровано: {exc}"

    if not summary.strip():
        return False, warn + "[Досьє] Модель повернула порожню відповідь; HTML не змінено."

    try:
        append_summary_to_html(table_html_path, summary)
    except OSError as exc:
        return False, warn + f"[Досьє] Не вдалося записати підсумок у HTML: {exc}"

    return True, warn + f"[Досьє] Підсумок досьє додано до: {table_html_path}"
