"""Dossier summary after the combined HTML report (deep_research / dossier mode)."""

from __future__ import annotations

import html
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence, Tuple

# This file's directory is the project root. Otherwise `import main` may pick up
# nazk_parser/main.py (same module name) → ImportError for call_ollama_text.
_ROOT = Path(__file__).resolve().parent
_rp = str(_ROOT)
try:
    sys.path.remove(_rp)
except ValueError:
    pass
sys.path.insert(0, _rp)

from main import call_ollama_text

SECTION_ID = "declarator-dossier-summary"
COMPARE_SECTION_ID = "declarator-dossier-model-compare"
MAX_HTML_CHARS_DEFAULT = 250_000
# -1 = no artificial Ollama response-length limit (see main._ollama_num_predict_for_options).
DOSSIER_SUMMARY_NUM_PREDICT = -1

# Dossier summary prompt stays Ukrainian (report content and model reply language).
_SYSTEM = """Ти — аналітик е-декларацій і ризиків корупції.
Тобі передано HTML-звіт з попередніми знахідками по деклараціях однієї конкретної особи за різні роки (таблиця, статистика).

Правила:
- Спирайся лише на те, що є в HTML. Не вигадуй фактів і не припускай того, чого немає у звіті.
- Врахуй динаміку між роками: повторюваність підозрілих патернів, зміну ризику, різкі зміни в майні/доходах/боргах/сім'ї лише якщо це видно з таблиці.
- Якщо даних недостатньо для висновку — прямо скажи про це одним-двома реченнями.

Формат відповіді:
- Лише звичайний текст українською, 5–10 речень (цілі речення).
- Без заголовків, без маркдауну, без JSON, без нумерованих списків, без HTML-тегів."""

DOSSIER_SYSTEM_PROMPT = _SYSTEM
DOSSIER_USER_PROMPT_TEMPLATE = (
    "Нижче — HTML зведеного звіту. Проаналізуй його як єдине досьє по цій особі.\n\n"
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
    """Returns (prompt fragment, truncation note or empty string)."""
    cleaned = strip_scripts(raw)
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
) -> Tuple[str, str]:
    system = (system_override or "").strip() or DOSSIER_SYSTEM_PROMPT
    tmpl = (user_template_override or "").strip()
    if tmpl:
        user = tmpl.format(html_fragment=html_fragment, truncation_note=truncation_note)
    else:
        user = DOSSIER_USER_PROMPT_TEMPLATE.format(
            html_fragment=html_fragment,
            truncation_note=truncation_note,
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
) -> Tuple[bool, str]:
    """
    Read the HTML report, call the LLM, append the summary section.
    Returns (success, log line).

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


def _render_compare_section(rows: Sequence[dict[str, str]]) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards: list[str] = []
    for row in rows:
        model = html.escape(str(row.get("model", "") or ""))
        status = str(row.get("status", "ok") or "ok")
        body = html.escape(str(row.get("text", "") or "").strip())
        color = "#334155" if status == "ok" else "#b45309"
        label = "OK" if status == "ok" else "ERROR"
        cards.append(
            f"""    <article style="border:1px solid #cbd5e1;border-radius:8px;padding:12px;background:#ffffff;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;">
        <strong style="font-size:14px;color:#0f172a;">{model}</strong>
        <span style="font-size:11px;letter-spacing:.03em;color:{color};">{label}</span>
      </div>
      <div style="font-size:13px;line-height:1.55;color:#1e293b;white-space:pre-wrap;">{body}</div>
    </article>"""
        )
    cards_html = "\n".join(cards)
    return f"""  <section id="{COMPARE_SECTION_ID}" style="margin-top:28px;padding:14px 16px;border:1px solid #cbd5e1;border-radius:8px;background:#f8fafc;max-width:100%;">
    <h2 style="margin:0 0 8px 0;font-size:17px;color:#0f172a;">Порівняння моделей (debug)</h2>
    <div style="font-size:12px;color:#475569;margin-bottom:10px;">Згенеровано: {ts}</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;">
{cards_html}
    </div>
  </section>
"""


def build_dossier_models_comparison_report(
    *,
    source_table_html_path: Path,
    output_html_path: Path,
    models: Sequence[str],
    host: str,
    timeout_sec: int,
    num_predict: int = DOSSIER_SUMMARY_NUM_PREDICT,
    api_key: str = "",
    cloud_mode: bool = False,
    max_html_chars: int = MAX_HTML_CHARS_DEFAULT,
    prompt_overrides: Mapping[str, Any] | None = None,
    provider: str = "ollama",
) -> Tuple[bool, str]:
    """
    Build a standalone HTML report comparing models.
    The main report_table.html is left unchanged.
    """
    if not source_table_html_path.exists():
        return False, f"[Досьє/Compare] Джерело не знайдено: {source_table_html_path}"
    uniq_models = [m.strip() for m in models if str(m or "").strip()]
    uniq_models = list(dict.fromkeys(uniq_models))
    if len(uniq_models) < 2:
        return False, "[Досьє/Compare] Потрібно щонайменше 2 унікальні моделі."
    if len(uniq_models) > 4:
        return False, "[Досьє/Compare] Максимум 4 моделі для порівняння."

    raw = source_table_html_path.read_text(encoding="utf-8")
    fragment, trunc_note = prepare_html_for_prompt(raw, max_html_chars)
    po = dict(prompt_overrides) if prompt_overrides else {}
    d_sys = po.get("dossier_system_prompt")
    d_user_tmpl = po.get("dossier_user_prompt_template")
    try:
        system_p, user_p = build_prompts(
            fragment,
            trunc_note,
            system_override=d_sys if isinstance(d_sys, str) else None,
            user_template_override=d_user_tmpl if isinstance(d_user_tmpl, str) else None,
        )
    except KeyError as exc:
        return False, "[Досьє/Compare] Некоректний шаблон user-промпта: " + str(exc)

    rows: list[dict[str, str]] = []
    for model in uniq_models:
        try:
            if str(provider or "ollama").lower() == "openrouter":
                from openrouter_client import call_openrouter_text

                txt = call_openrouter_text(
                    model,
                    system_p,
                    user_p,
                    host=host,
                    timeout_sec=timeout_sec,
                    num_predict=num_predict,
                    api_key=api_key,
                )
            else:
                txt = call_ollama_text(
                    model,
                    system_p,
                    user_p,
                    host=host,
                    timeout_sec=timeout_sec,
                    num_predict=num_predict,
                    api_key=api_key,
                    cloud_mode=cloud_mode,
                )
            rows.append({"model": model, "status": "ok", "text": str(txt or "").strip()})
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "model": model,
                    "status": "error",
                    "text": f"Не вдалося отримати відповідь: {exc}",
                }
            )

    clean = remove_existing_summary_section(raw)
    clean = re.sub(
        rf'<section\s+id="{re.escape(COMPARE_SECTION_ID)}"[^>]*>.*?</section>',
        "",
        clean,
        flags=re.DOTALL | re.IGNORECASE,
    )
    compare_block = _render_compare_section(rows)
    lower = clean.lower()
    idx = lower.rfind("</body>")
    if idx != -1:
        out = clean[:idx] + compare_block + clean[idx:]
    else:
        out = clean + "\n" + compare_block

    output_html_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_html_path.with_name(output_html_path.name + ".tmp")
    tmp.write_text(out, encoding="utf-8")
    os.replace(tmp, output_html_path)
    return True, f"[Досьє/Compare] Звіт порівняння збережено: {output_html_path}"
