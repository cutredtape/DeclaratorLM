#!/usr/bin/env python3
"""DeclaratorLM benchmark TUI - точка входу.

Запуск із кореня проєкту або з цієї теки:

    venv\\Scripts\\python.exe benchmark\\run_benchmark.py
    venv\\Scripts\\python.exe benchmark\\run_benchmark.py --dry-run

Спершу встановіть залежності TUI:

    venv\\Scripts\\python.exe -m pip install -r benchmark\\requirements.txt
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

# Prefer UTF-8 on Windows consoles before Rich starts printing.
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

# Make `bench` and project root importable regardless of cwd.
BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parent
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.prompt import Confirm, IntPrompt, Prompt  # noqa: E402

from bench.config import (  # noqa: E402
    BenchConfig,
    ModelSpec,
    make_run_dir,
)
from bench.corpus import scan_corpus  # noqa: E402
from bench.cost import build_cost_estimate  # noqa: E402
from bench.preflight import run_preflight  # noqa: E402
from bench.prompts import builtin_core_as_prompt, discover_prompts  # noqa: E402
from bench.reporting import generate_all_cell_reports, write_matrix  # noqa: E402
from bench.runner import run_matrix  # noqa: E402
from bench.state import BenchState, save_state, write_manifest  # noqa: E402
from bench import ui  # noqa: E402


def _load_secrets_key() -> str:
    """Read openrouter key from project .declarator_secrets.json if present."""
    path = PROJECT_ROOT / ".declarator_secrets.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("openrouter_api_key") or "").strip()


def _resolve_api_keys(models: list[ModelSpec]) -> None:
    """Fill empty OpenRouter keys from env / secrets file (never log the value)."""
    from main import resolve_openrouter_api_key

    secrets = _load_secrets_key()
    for m in models:
        if m.provider != "openrouter":
            continue
        if str(m.api_key or "").strip():
            continue
        env_key = resolve_openrouter_api_key("")
        m.api_key = env_key or secrets


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="DeclaratorLM benchmark: матриця модель x промпт на benchmark/corpus"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Без викликів LLM: перевірити compact+промпти, записати синтетичний JSONL + матрицю",
    )
    p.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Пропустити smoke-виклик для кожної моделі (хост + каталог все одно перевіряються)",
    )
    p.add_argument(
        "--skip-confirm",
        action="store_true",
        help="Не питати підтвердження вартості (використовуйте обережно)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Псевдонім для --skip-confirm",
    )
    p.add_argument("--label", default="bench", help="Назва теки прогону")
    p.add_argument(
        "--model",
        action="append",
        default=[],
        help="Ідентифікатор моделі (можна повторювати). Префікс openrouter: для OpenRouter",
    )
    p.add_argument(
        "--provider",
        choices=["ollama", "openrouter"],
        default="ollama",
        help="Провайдер за замовчуванням для --model без префікса",
    )
    p.add_argument("--host", default="", help="Перевизначити хост провайдера")
    p.add_argument("--api-key", default="", help="Ключ API (краще через змінні середовища)")
    p.add_argument(
        "--prompt",
        action="append",
        default=[],
        help="Назва промпту для включення (можна повторювати). За замовчуванням: інтерактивно / усі",
    )
    p.add_argument("--max-files", type=int, default=0, help="Обмежити розмір корпусу (0=усі)")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--max-chars", type=int, default=64000)
    p.add_argument("--max-concurrent", type=int, default=1)
    p.add_argument(
        "--no-audit",
        action="store_true",
        help="Вимкнути збір артефактів аудиту",
    )
    p.add_argument(
        "--resume",
        default="",
        help="Відновити наявний прогін із benchmark/runs/",
    )
    p.add_argument(
        "--non-interactive",
        action="store_true",
        help="Вимагає --model; без запитань (для скриптів / CI dry-run)",
    )
    return p


def _parse_model_args(
    raw_models: list[str],
    *,
    default_provider: str,
    host: str,
    api_key: str,
) -> list[ModelSpec]:
    out: list[ModelSpec] = []
    for raw in raw_models:
        line = str(raw or "").strip()
        if not line:
            continue
        prov = default_provider
        mid = line
        if ":" in line and line.split(":", 1)[0].lower() in {"ollama", "openrouter"}:
            prov, mid = line.split(":", 1)
            prov = prov.lower().strip()
            mid = mid.strip()
        if not mid:
            continue
        if prov == "openrouter":
            m_host = host or "https://openrouter.ai/api/v1"
        else:
            m_host = host or "http://127.0.0.1:11434"
        out.append(
            ModelSpec(
                model_id=mid,
                provider=prov,
                host=m_host,
                api_key=api_key,
                cloud_mode=False,
            )
        )
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    ui.banner()

    # --- corpus ---
    scan = scan_corpus(BENCHMARK_DIR / "corpus")
    ui.show_corpus(scan)
    if scan.ok_count == 0:
        ui.console.print(
            "[red]Корпус порожній або не містить валідного JSON.[/]\n"
            f"Покладіть файли декларацій *.json у [cyan]{BENCHMARK_DIR / 'corpus'}[/] і запустіть знову."
        )
        return 2

    # --- prompts ---
    file_prompts, prompt_errors = discover_prompts(BENCHMARK_DIR / "prompts")
    try:
        core = builtin_core_as_prompt()
        all_prompts = [core] + file_prompts
    except Exception as exc:  # noqa: BLE001
        ui.console.print(f"[yellow]Не вдалося завантажити вбудований промпт core: {exc}[/]")
        all_prompts = list(file_prompts)
    # Deduplicate by name (file wins over builtin if same name)
    by_name = {}
    for p in all_prompts:
        by_name[p.name] = p
    all_prompts = list(by_name.values())
    ui.show_prompts(all_prompts, prompt_errors)
    if not all_prompts:
        ui.console.print("[red]Не знайдено жодного валідного промпту.[/]")
        return 2

    # --- model + prompt selection ---
    if args.model:
        models = _parse_model_args(
            args.model,
            default_provider=args.provider,
            host=args.host,
            api_key=args.api_key,
        )
    elif args.non_interactive:
        ui.console.print("[red]--non-interactive вимагає --model[/]")
        return 2
    else:
        models = ui.ask_models_interactive(
            default_provider=args.provider,
            default_host=args.host or "http://127.0.0.1:11434",
        )
        if args.api_key:
            for m in models:
                if not m.api_key:
                    m.api_key = args.api_key

    if not models:
        ui.console.print("[red]Жодної моделі не обрано.[/]")
        return 2

    _resolve_api_keys(models)

    if args.prompt:
        wanted = {str(x).strip() for x in args.prompt if str(x).strip()}
        prompts = [p for p in all_prompts if p.name in wanted]
        missing = wanted - {p.name for p in prompts}
        if missing:
            ui.console.print(f"[red]Невідомі назви промптів: {sorted(missing)}[/]")
            return 2
    elif args.non_interactive:
        prompts = list(all_prompts)
    else:
        idxs = ui.pick_indices(
            "Оберіть промпти (номери або 'all')",
            len(all_prompts),
        )
        prompts = [all_prompts[i] for i in idxs]

    if not prompts:
        ui.console.print("[red]Жодного промпту не обрано.[/]")
        return 2

    if args.non_interactive or args.no_audit:
        audit_enabled = not args.no_audit
        from bench.config import AuditCaptureFlags

        audit_flags = AuditCaptureFlags()
    else:
        audit_enabled, audit_flags = ui.ask_audit_flags(default_enabled=True)

    label = args.label
    if not args.non_interactive and not args.resume:
        label = Prompt.ask("Назва прогону", default=label)

    max_files = int(args.max_files or 0)
    if not args.non_interactive and max_files == 0:
        if Confirm.ask("Обмежити кількість декларацій?", default=False):
            max_files = IntPrompt.ask("Макс. файлів", default=min(3, scan.ok_count))

    config = BenchConfig(
        label=label,
        models=models,
        prompts=prompts,
        corpus_dir=BENCHMARK_DIR / "corpus",
        max_chars=int(args.max_chars),
        timeout=int(args.timeout),
        retries=int(args.retries),
        max_concurrent=max(1, min(8, int(args.max_concurrent))),
        audit_enabled=audit_enabled,
        audit_flags=audit_flags,
        dry_run=bool(args.dry_run),
        max_files=max_files,
        skip_smoke=bool(args.skip_smoke),
        skip_confirm=bool(args.skip_confirm or args.yes),
    )

    files = scan.paths(max_files=config.max_files)
    ui.console.print(
        f"[bold]Матриця:[/] моделей {len(config.models)} x промптів {len(config.prompts)} "
        f"x декларацій {len(files)} "
        f"= [cyan]{len(config.models) * len(config.prompts) * len(files)}[/] викликів LLM"
        + (" [yellow](dry-run)[/]" if config.dry_run else "")
    )

    # --- preflight (skip smoke entirely in dry-run) ---
    if config.dry_run:
        ui.console.print("[dim]Dry-run: перевірку хоста/smoke пропущено[/]")
    else:
        ui.console.print("[bold]Виконується перевірка перед запуском…[/]")
        report = run_preflight(config.models, skip_smoke=config.skip_smoke)
        ui.show_preflight(report)
        if not report.all_ok:
            failed = ", ".join(r.model_id for r in report.failed_models)
            ui.console.print(f"[red]Перевірку не пройшли: {failed}[/]")
            if args.non_interactive:
                return 3
            if not Confirm.ask("Продовжити лише з доступними моделями?", default=False):
                return 3
            ok_ids = {r.model_id for r in report.ok_models}
            config.models = [m for m in config.models if m.model_id in ok_ids]
            if not config.models:
                ui.console.print("[red]Після перевірки не залишилось жодної моделі.[/]")
                return 3

    # --- cost gate ---
    est = build_cost_estimate(config, files)
    ui.show_cost(est)
    if est.over_limit_count:
        ui.console.print(
            f"[yellow]{est.over_limit_count} декларація(й) перевищують max_chars="
            f"{config.max_chars} - вони будуть зафіксовані як помилки.[/]"
        )
    if not config.dry_run and not config.skip_confirm:
        if not Confirm.ask("Почати прогін? Це може витратити кредити API.", default=False):
            ui.console.print("[dim]Скасовано.[/]")
            return 0

    # --- run dir ---
    if args.resume:
        run_dir = Path(args.resume)
        if not run_dir.is_absolute():
            run_dir = (BENCHMARK_DIR / "runs" / args.resume).resolve()
        if not run_dir.is_dir():
            ui.console.print(f"[red]Теку для відновлення не знайдено: {run_dir}[/]")
            return 2
        from bench.state import load_state

        state = load_state(run_dir) or BenchState(
            run_dir=str(run_dir),
            run_id=f"bench-{uuid4().hex[:12]}",
        )
    else:
        run_dir = make_run_dir(config.label)
        state = BenchState(run_dir=str(run_dir), run_id=f"bench-{uuid4().hex[:12]}")

    manifest = config.to_manifest_dict()
    manifest["corpus"] = scan.to_manifest()
    manifest["selected_files"] = [p.name for p in files]
    manifest["cost_estimate"] = {
        "mean_compact_chars": est.mean_compact_chars,
        "max_compact_chars": est.max_compact_chars,
        "over_limit_count": est.over_limit_count,
        "total_cost_usd": est.total_cost_usd,
        "per_model": [
            {
                "model_id": m.model_id,
                "provider": m.provider,
                "cost_usd": m.cost_usd,
                "prompt_tokens_est": m.prompt_tokens_est,
                "completion_tokens_est": m.completion_tokens_est,
                "note": m.note,
            }
            for m in est.per_model
        ],
    }
    write_manifest(run_dir, manifest)
    save_state(state, run_dir)
    ui.console.print(f"[green]Тека прогону:[/] {run_dir}")

    abort = {"flag": False}

    def on_progress(msg: str) -> None:
        ui.show_progress_line(msg)

    try:
        run_matrix(
            config=config,
            files=files,
            run_dir=run_dir,
            state=state,
            on_progress=on_progress,
            abort_flag=lambda: abort["flag"],
        )
    except KeyboardInterrupt:
        abort["flag"] = True
        ui.console.print("\n[yellow]Перервано - зберігаю стан...[/]")
        state.status = "aborted"
        save_state(state, run_dir)

    # --- reports + matrix ---
    ui.console.print("[bold]Генерація звітів по клітинках…[/]")
    for msg in generate_all_cell_reports(run_dir, state):
        ui.console.print(f"  {msg}")

    ui.console.print("[bold]Побудова матриці…[/]")
    matrix_paths = write_matrix(run_dir, state)
    ui.show_final(state, matrix_paths)

    return 0 if state.status in {"done", "aborted"} else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nПерервано.", file=sys.stderr)
        raise SystemExit(130)
