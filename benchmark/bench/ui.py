"""Rich TUI screens for the benchmark runner."""
from __future__ import annotations

from typing import List, Optional, Sequence

import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from .config import AuditCaptureFlags, ModelSpec
from .corpus import CorpusScan, format_bytes
from .cost import CostEstimate
from .preflight import PreflightReport
from .prompts import PromptSpec
from .state import BenchState

# Windows cp1251 consoles choke on some Unicode (e.g. multiplication sign).
console = Console(force_terminal=True, soft_wrap=True)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    console = Console(
        force_terminal=True,
        soft_wrap=True,
        legacy_windows=False,
    )


def banner() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]DeclaratorLM[/] [bold]Бенчмарк[/]\n"
            "[dim]матриця модель x промпт на спільному корпусі[/]",
            border_style="cyan",
        )
    )


def show_corpus(scan: CorpusScan) -> None:
    table = Table(title="Корпус", show_header=True, header_style="bold")
    table.add_column("Показник")
    table.add_column("Значення", justify="right")
    table.add_row("Тека", str(scan.corpus_dir))
    table.add_row("JSON-файлів", str(len(scan.files)))
    table.add_row("Валідних", f"[green]{scan.ok_count}[/]")
    table.add_row("Биті", f"[red]{scan.bad_count}[/]" if scan.bad_count else "0")
    table.add_row("Сумарний розмір", format_bytes(scan.total_bytes))
    table.add_row("Порожньо?", "так - покладіть сюди *.json" if scan.empty else "ні")
    console.print(table)
    if scan.bad_files:
        console.print("[yellow]Биті файли:[/]")
        for f in scan.bad_files[:10]:
            console.print(f"  • {f.name}: {f.error}")


def show_prompts(prompts: Sequence[PromptSpec], errors: Sequence[str]) -> None:
    table = Table(title="Версії промптів", show_header=True, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("Назва")
    table.add_column("Джерело")
    table.add_column("Системний", justify="right")
    table.add_column("Користувацький", justify="right")
    for i, p in enumerate(prompts, 1):
        table.add_row(
            str(i),
            p.name,
            p.path.name,
            str(len(p.system_prompt)),
            str(len(p.user_prompt_template)),
        )
    console.print(table)
    for err in errors:
        console.print(f"[red]помилка промпту:[/] {err}")


def pick_indices(prompt: str, n: int, *, allow_empty: bool = False) -> List[int]:
    """Parse '1,3' or 'all' into 0-based indices."""
    while True:
        raw = Prompt.ask(prompt, default="all" if n else "")
        raw = raw.strip().lower()
        if not raw and allow_empty:
            return []
        if raw in {"all", "*"}:
            return list(range(n))
        try:
            parts = [p.strip() for p in raw.replace(" ", ",").split(",") if p.strip()]
            idxs = []
            for p in parts:
                i = int(p)
                if i < 1 or i > n:
                    raise ValueError(f"поза межами: {i}")
                idxs.append(i - 1)
            if not idxs and not allow_empty:
                raise ValueError("порожній вибір")
            # unique, preserve order
            seen = set()
            out = []
            for i in idxs:
                if i not in seen:
                    seen.add(i)
                    out.append(i)
            return out
        except ValueError as exc:
            console.print(f"[red]Некоректний вибір:[/] {exc}")


def ask_models_interactive(
    *,
    default_provider: str = "ollama",
    default_host: str = "http://127.0.0.1:11434",
) -> List[ModelSpec]:
    console.print(
        Panel(
            "Введіть моделі по одній на рядок.\n"
            "Формат: [cyan]model_id[/]   або   [cyan]provider:model_id[/]\n"
            "Приклади:\n"
            "  llama3.1\n"
            "  openrouter:meta-llama/llama-3.3-70b-instruct\n"
            "Порожній рядок завершує список.",
            title="Моделі",
            border_style="blue",
        )
    )
    provider = Prompt.ask(
        "Провайдер за замовчуванням",
        choices=["ollama", "openrouter"],
        default=default_provider,
    )
    if provider == "openrouter":
        host = Prompt.ask("Хост OpenRouter", default="https://openrouter.ai/api/v1")
        api_key = Prompt.ask("Ключ API OpenRouter (залиште порожнім, щоб узяти з env)", password=True, default="")
        cloud_mode = False
    else:
        host = Prompt.ask("Хост Ollama", default=default_host)
        cloud = Confirm.ask("Хмарна Ollama (потрібен ключ API)?", default=False)
        cloud_mode = cloud
        api_key = ""
        if cloud:
            api_key = Prompt.ask("Ключ API хмарної Ollama", password=True, default="")

    models: List[ModelSpec] = []
    console.print("[dim]Ідентифікатори моделей (порожній рядок - завершити):[/]")
    while True:
        line = Prompt.ask("модель", default="")
        line = line.strip()
        if not line:
            break
        prov = provider
        mid = line
        if ":" in line and line.split(":", 1)[0].lower() in {"ollama", "openrouter"}:
            prov, mid = line.split(":", 1)
            prov = prov.lower().strip()
            mid = mid.strip()
        if not mid:
            continue
        m_host = host
        m_key = api_key
        m_cloud = cloud_mode
        if prov == "openrouter" and provider != "openrouter":
            m_host = "https://openrouter.ai/api/v1"
            m_key = Prompt.ask(f"Ключ API для {mid}", password=True, default="")
            m_cloud = False
        models.append(
            ModelSpec(
                model_id=mid,
                provider=prov,
                host=m_host,
                api_key=m_key,
                cloud_mode=m_cloud if prov == "ollama" else False,
            )
        )
    return models


def ask_audit_flags(default_enabled: bool = True) -> tuple[bool, AuditCaptureFlags]:
    enabled = Confirm.ask("Зберігати артефакти аудиту?", default=default_enabled)
    flags = AuditCaptureFlags()
    if not enabled:
        return False, flags
    if Confirm.ask("Налаштувати, які саме артефакти зберігати?", default=False):
        flags.raw_declaration = Confirm.ask("  сира декларація", default=True)
        flags.compact_declaration = Confirm.ask("  compact-декларація", default=True)
        flags.request_payload = Confirm.ask("  payload запиту", default=True)
        flags.response_raw = Confirm.ask("  сира відповідь", default=True)
        flags.response_parsed = Confirm.ask("  розпарсена відповідь", default=True)
        flags.normalized_analysis = Confirm.ask("  нормалізований аналіз", default=True)
        flags.attempt_meta = Confirm.ask("  метадані спроби", default=True)
    return True, flags


def show_preflight(report: PreflightReport) -> None:
    table = Table(title="Перевірка перед запуском", show_header=True, header_style="bold")
    table.add_column("Модель")
    table.add_column("Провайдер")
    table.add_column("Статус")
    table.add_column("Хост")
    table.add_column("У списку")
    table.add_column("Smoke-тест")
    table.add_column("Додатково")
    for r in report.results:
        style = "green" if r.ok else ("dim" if r.skipped else "red")
        extra = r.pricing_hint or r.credits_label or ""
        table.add_row(
            r.model_id,
            r.provider,
            Text(r.status_label(), style=style),
            r.host_message[:48],
            r.listed_message[:40],
            r.smoke_message[:40],
            extra[:30],
        )
    console.print(table)


def show_cost(est: CostEstimate) -> None:
    console.print(Panel("\n".join(est.summary_lines()), title="Оцінка вартості", border_style="yellow"))
    if est.per_model:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Модель")
        table.add_column("Провайдер")
        table.add_column("Вх. токени", justify="right")
        table.add_column("Вих. токени", justify="right")
        table.add_column("USD", justify="right")
        table.add_column("Примітка")
        for m in est.per_model:
            usd = f"${m.cost_usd:.4f}" if m.cost_usd is not None else "-"
            table.add_row(
                m.model_id,
                m.provider,
                f"{m.prompt_tokens_est:,}",
                f"{m.completion_tokens_est:,}",
                usd,
                m.note,
            )
        console.print(table)


def show_progress_line(message: str) -> None:
    console.print(message)


def show_final(state: BenchState, matrix_paths: Optional[dict] = None) -> None:
    table = Table(title="Підсумок прогону", show_header=True, header_style="bold")
    table.add_column("Модель")
    table.add_column("Промпт")
    table.add_column("Статус")
    table.add_column("OK", justify="right")
    table.add_column("ERR", justify="right")
    for cell in state.cells.values():
        style = {
            "done": "green",
            "circuit_open": "red",
            "failed": "red",
            "aborted": "yellow",
        }.get(cell.status, "white")
        table.add_row(
            cell.model_id,
            cell.prompt_name,
            Text(cell.status, style=style),
            str(cell.ok_count),
            str(cell.err_count),
        )
    console.print(table)
    console.print(f"Статус прогону: [bold]{state.status}[/]  тека: [cyan]{state.run_dir}[/]")
    if matrix_paths:
        console.print("[bold]Матриця:[/]")
        for kind, path in matrix_paths.items():
            console.print(f"  {kind}: {path}")
