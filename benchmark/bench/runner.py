"""Matrix runner: (model × prompt) cells via main.process_file."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Set
from uuid import uuid4

from .config import (
    BenchConfig,
    ModelSpec,
    PromptSpec,
    PROJECT_ROOT,
    cell_artifacts_dir,
    cell_report_dir,
)
from .state import BenchState, CellProgress, save_state

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ProgressCb = Callable[[str], None]


def _log(run_dir: Path, message: str, on_progress: Optional[ProgressCb] = None) -> None:
    line = message.rstrip() + "\n"
    try:
        with (run_dir / "bench.log").open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except OSError:
        pass
    if on_progress:
        on_progress(line.rstrip())


def _build_process_args(
    *,
    config: BenchConfig,
    model: ModelSpec,
    prompt: PromptSpec,
    run_id: str,
    started_at_utc: str,
    audit_dir: Path,
    pricing_per_token: Optional[dict] = None,
    context_length: Optional[dict] = None,
) -> Namespace:
    audit_on = bool(config.audit_enabled and config.audit_flags.any_enabled())
    kwargs = {
        "retries": int(config.retries),
        "retry_delay": float(config.retry_delay),
        "max_chars": int(config.max_chars),
        "save_compact_declarations": False,
        "compact_declarations_dir": "",
        "compact_legacy_payload": bool(config.compact_legacy_payload),
        "debug_payload_dir": "",
        "model": model.model_id,
        "host": model.host,
        "timeout": int(config.timeout),
        "num_predict": int(config.num_predict),
        "reasoning_debug": False,
        "api_key": model.api_key if model.provider == "ollama" else "",
        "cloud_mode": bool(model.cloud_mode),
        "provider": model.provider,
        "openrouter_model": model.model_id if model.provider == "openrouter" else "",
        "openrouter_host": model.host if model.provider == "openrouter" else "",
        "openrouter_api_key": model.api_key if model.provider == "openrouter" else "",
        "run_id": run_id,
        "started_at_utc": started_at_utc,
        "prompt_overrides": prompt.as_overrides(),
        "audit_mode": audit_on,
        "audit_mode_dir": str(audit_dir) if audit_on else "",
        **config.audit_flags.as_cli_kwargs(),
    }
    ns = Namespace(**kwargs)
    if pricing_per_token is not None:
        setattr(ns, "_openrouter_pricing_per_token", pricing_per_token)
    if context_length is not None:
        setattr(ns, "_openrouter_context_length", context_length)
    return ns


def _append_error(
    err_path: Path,
    *,
    file_name: str,
    exc: BaseException,
    model: ModelSpec,
    prompt_name: str,
    run_id: str,
) -> None:
    from main import append_jsonl, resolve_effective_model_and_mode

    ns = Namespace(
        provider=model.provider,
        model=model.model_id,
        openrouter_model=model.model_id,
        cloud_mode=model.cloud_mode,
        host=model.host,
    )
    mid, lm = resolve_effective_model_and_mode(ns)
    append_jsonl(
        err_path,
        {
            "file": file_name,
            "source_file": file_name,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "provider": model.provider,
            "cloud_mode": bool(model.cloud_mode),
            "model": f"{mid} ({lm})",
            "run_meta": {
                "run_id": run_id,
                "model": f"{mid} ({lm})",
                "model_id": mid,
                "launch_mode": lm,
                "prompt_name": prompt_name,
            },
        },
    )


def _already_done(out_jsonl: Path, model: ModelSpec) -> Set[str]:
    from main import load_processed_filenames

    return load_processed_filenames(out_jsonl, model.model_id, model.launch_mode())


def _process_one(
    path: Path,
    args: Namespace,
    *,
    out_jsonl: Path,
    err_jsonl: Path,
    model: ModelSpec,
    prompt_name: str,
    run_id: str,
) -> tuple[bool, str]:
    """Return (ok, detail). Never raises — all failures become err JSONL rows."""
    from main import (
        PayloadLimitExceededError,
        append_jsonl,
        process_file,
    )

    try:
        result = process_file(path, args)
        append_jsonl(out_jsonl, result)
        score = (result.get("analysis") or {}).get("risk_score")
        return True, f"ok risk_score={score}"
    except PayloadLimitExceededError as exc:
        _append_error(
            err_jsonl,
            file_name=path.name,
            exc=exc,
            model=model,
            prompt_name=prompt_name,
            run_id=run_id,
        )
        return False, f"payload_limit: {exc}"
    except Exception as exc:  # noqa: BLE001
        _append_error(
            err_jsonl,
            file_name=path.name,
            exc=exc,
            model=model,
            prompt_name=prompt_name,
            run_id=run_id,
        )
        return False, f"{type(exc).__name__}: {exc}"


def _dry_run_one(
    path: Path,
    args: Namespace,
    *,
    out_jsonl: Path,
    model: ModelSpec,
    prompt: PromptSpec,
    run_id: str,
) -> tuple[bool, str]:
    """Validate compact + prompt format without calling the LLM."""
    from main import (
        append_jsonl,
        compact_declaration,
        normalize_analysis_payload,
        pipeline_prompts_for_process,
        resolve_effective_model_and_mode,
    )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        compact = compact_declaration(
            raw, legacy_payload=bool(args.compact_legacy_payload)
        )
        compact_str = json.dumps(compact, ensure_ascii=False)
        if len(compact_str) > int(args.max_chars):
            raise RuntimeError(
                f"payload_limit: {len(compact_str)} > {args.max_chars}"
            )
        system, user_tmpl, prompt_name = pipeline_prompts_for_process(args)
        user_tmpl.format(declaration_payload=compact_str)
        mid, lm = resolve_effective_model_and_mode(args)
        meta = compact.get("meta") or {}
        declarant = meta.get("declarant") or {}
        full_name = " ".join(
            str(part).strip()
            for part in [
                declarant.get("lastname", ""),
                declarant.get("firstname", ""),
                declarant.get("middlename", ""),
            ]
            if str(part).strip()
        )
        fake_analysis = {
            "subject_profile": {
                "declaration_id": raw.get("id"),
                "user_declarant_id": raw.get("user_declarant_id"),
                "declarant_full_name": full_name,
                "position": declarant.get("work_post", ""),
                "workplace": declarant.get("work_place", ""),
                "declaration_year": meta.get("declaration_year"),
            },
            "risk_score": 0,
            "risk_level": "low",
            "findings": [],
            "family_assets_overview": [],
            "red_flags": [],
            "needs_verification": ["dry-run - без виклику LLM"],
            "clear_facts": ["dry-run: синтетичний рядок"],
            "final_assessment": "DRY-RUN: compact і формат промпту ОК, модель не викликалася.",
        }
        normalized = normalize_analysis_payload(
            fake_analysis,
            declaration_id=raw.get("id"),
            user_declarant_id=raw.get("user_declarant_id"),
            declarant_full_name=full_name,
            position=str(declarant.get("work_post", "")).strip(),
            workplace=str(declarant.get("work_place", "")).strip(),
            declaration_year=meta.get("declaration_year"),
            declaration_type_code="",
            declaration_type_label="",
        )
        row = {
            "run_meta": {
                "run_id": run_id,
                "model": f"{mid} ({lm})",
                "model_id": mid,
                "launch_mode": lm,
                "host": model.host,
                "started_at_utc": args.started_at_utc,
                "prompt_name": prompt_name,
                "dry_run": True,
            },
            "source_file": path.name,
            "declaration_id": raw.get("id"),
            "user_declarant_id": raw.get("user_declarant_id"),
            "context_snapshot": {
                "declarant_full_name": full_name,
                "payload_chars_sent": len(compact_str),
                "payload_was_truncated": False,
            },
            "analysis": normalized,
            "processing_duration_sec": 0.0,
        }
        append_jsonl(out_jsonl, row)
        # Silence unused warning for system
        _ = system
        return True, f"dry-run ok символів={len(compact_str)}"
    except Exception as exc:  # noqa: BLE001
        return False, f"dry-run помилка: {exc}"


def run_cell(
    *,
    config: BenchConfig,
    model: ModelSpec,
    prompt: PromptSpec,
    files: List[Path],
    run_dir: Path,
    state: BenchState,
    run_id: str,
    pricing_per_token: Optional[dict] = None,
    context_length: Optional[dict] = None,
    on_progress: Optional[ProgressCb] = None,
    abort_flag: Optional[Callable[[], bool]] = None,
) -> CellProgress:
    cell = state.ensure_cell(model.model_id, prompt.name)
    if cell.status == "done":
        _log(run_dir, f"[ПРОПУЩЕНО] клітинку вже завершено: {model.model_id} x {prompt.name}", on_progress)
        return cell

    report_dir = cell_report_dir(run_dir, model.model_id, prompt.name)
    audit_dir = cell_artifacts_dir(run_dir, model.model_id, prompt.name)
    out_jsonl = report_dir / "analysis_results.jsonl"
    err_jsonl = report_dir / "analysis_errors.jsonl"

    started = datetime.now(timezone.utc).isoformat()
    cell.status = "running"
    cell.started_at_utc = cell.started_at_utc or started
    cell.consecutive_failures = 0
    save_state(state, run_dir)

    args = _build_process_args(
        config=config,
        model=model,
        prompt=prompt,
        run_id=run_id,
        started_at_utc=started,
        audit_dir=audit_dir,
        pricing_per_token=pricing_per_token,
        context_length=context_length,
    )

    done_names = _already_done(out_jsonl, model)
    pending = [p for p in files if p.name not in done_names]
    _log(
        run_dir,
        f"[КЛІТИНКА] {model.model_id} x {prompt.name}: "
        f"залишилось {len(pending)} / всього {len(files)} "
        f"(вже готово {len(done_names)})",
        on_progress,
    )

    # Count already-done toward ok_count for resume display.
    cell.ok_count = max(cell.ok_count, len(done_names))

    def _should_abort() -> bool:
        return bool(abort_flag and abort_flag())

    breaker = int(config.circuit_breaker_failures)

    def handle_result(path: Path, ok: bool, detail: str) -> None:
        nonlocal cell
        if ok:
            cell.ok_count += 1
            cell.consecutive_failures = 0
            if path.name not in cell.processed_files:
                cell.processed_files.append(path.name)
        else:
            cell.err_count += 1
            cell.consecutive_failures += 1
            cell.last_error = detail
        _log(
            run_dir,
            f"  [{'OK' if ok else 'ERR'}] {path.name}: {detail}",
            on_progress,
        )
        save_state(state, run_dir)

    use_parallel = (
        model.provider == "openrouter"
        and int(config.max_concurrent) > 1
        and not config.dry_run
    )

    if use_parallel:
        workers = min(int(config.max_concurrent), 8, max(1, len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _process_one,
                    path,
                    args,
                    out_jsonl=out_jsonl,
                    err_jsonl=err_jsonl,
                    model=model,
                    prompt_name=prompt.name,
                    run_id=run_id,
                ): path
                for path in pending
            }
            for fut in as_completed(futures):
                if _should_abort():
                    cell.status = "aborted"
                    save_state(state, run_dir)
                    return cell
                path = futures[fut]
                try:
                    ok, detail = fut.result()
                except Exception as exc:  # noqa: BLE001
                    ok, detail = False, f"аварія воркера: {exc}"
                handle_result(path, ok, detail)
                if cell.consecutive_failures >= breaker:
                    cell.status = "circuit_open"
                    cell.last_error = (
                        f"запобіжник: {breaker} послідовних помилок поспіль"
                    )
                    _log(run_dir, f"[ЗАПОБІЖНИК] {cell.last_error}", on_progress)
                    save_state(state, run_dir)
                    return cell
    else:
        for path in pending:
            if _should_abort():
                cell.status = "aborted"
                save_state(state, run_dir)
                return cell
            if config.dry_run:
                ok, detail = _dry_run_one(
                    path,
                    args,
                    out_jsonl=out_jsonl,
                    model=model,
                    prompt=prompt,
                    run_id=run_id,
                )
            else:
                ok, detail = _process_one(
                    path,
                    args,
                    out_jsonl=out_jsonl,
                    err_jsonl=err_jsonl,
                    model=model,
                    prompt_name=prompt.name,
                    run_id=run_id,
                )
            handle_result(path, ok, detail)
            if cell.consecutive_failures >= breaker:
                cell.status = "circuit_open"
                cell.last_error = f"запобіжник: {breaker} послідовних помилок поспіль"
                _log(run_dir, f"[ЗАПОБІЖНИК] {cell.last_error}", on_progress)
                save_state(state, run_dir)
                return cell

    cell.status = "done"
    cell.finished_at_utc = datetime.now(timezone.utc).isoformat()
    save_state(state, run_dir)
    _log(
        run_dir,
        f"[КЛІТИНКУ ЗАВЕРШЕНО] {model.model_id} x {prompt.name}: "
        f"ok={cell.ok_count} err={cell.err_count}",
        on_progress,
    )
    return cell


def run_matrix(
    *,
    config: BenchConfig,
    files: List[Path],
    run_dir: Path,
    state: BenchState,
    on_progress: Optional[ProgressCb] = None,
    abort_flag: Optional[Callable[[], bool]] = None,
) -> BenchState:
    run_id = state.run_id or f"bench-{uuid4().hex[:12]}"
    state.run_id = run_id
    state.status = "running"
    save_state(state, run_dir)

    pricing_per_token: dict = {}
    context_length: dict = {}
    if any(m.provider == "openrouter" for m in config.models) and not config.dry_run:
        try:
            from openrouter_client import fetch_openrouter_models_enriched

            or_m = next(m for m in config.models if m.provider == "openrouter")
            enriched = fetch_openrouter_models_enriched(or_m.host, or_m.api_key)
            pricing_per_token = enriched.get("pricing_per_token") or {}
            context_length = enriched.get("context_length") or {}
        except Exception as exc:  # noqa: BLE001
            _log(run_dir, f"[ПОПЕРЕДЖЕННЯ] не вдалося завантажити ціни OpenRouter: {exc}", on_progress)

    try:
        for model, prompt in config.cells():
            if abort_flag and abort_flag():
                state.status = "aborted"
                save_state(state, run_dir)
                break
            run_cell(
                config=config,
                model=model,
                prompt=prompt,
                files=files,
                run_dir=run_dir,
                state=state,
                run_id=run_id,
                pricing_per_token=pricing_per_token or None,
                context_length=context_length or None,
                on_progress=on_progress,
                abort_flag=abort_flag,
            )
        else:
            # Completed all cells without break
            if state.status == "running":
                state.status = "done"
                save_state(state, run_dir)
    except KeyboardInterrupt:
        state.status = "aborted"
        save_state(state, run_dir)
        _log(run_dir, "[ПЕРЕРВАНО] KeyboardInterrupt - стан збережено для відновлення", on_progress)
        raise

    return state
