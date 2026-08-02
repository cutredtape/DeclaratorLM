"""PyWebView desktop app (Ukrainian UI): hosts the React frontend and runs main.py as a subprocess."""
import runpy
import sys
from pathlib import Path

# --- PyInstaller onefile: cannot invoke `[DeclaratorLM.exe, main.py, ...]` —
# the exe always starts the GUI (webview). Child main/report processes are launched via a marker + runpy.
_RUNPY_MARKER = "__DECLARATOR_RUNPY__"


def _early_frozen_meipass() -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return None


def _dispatch_frozen_subprocess_cli() -> None:
    if not getattr(sys, "frozen", False):
        return
    if len(sys.argv) < 3 or sys.argv[1] != _RUNPY_MARKER:
        return
    job = sys.argv[2]
    root = _early_frozen_meipass()
    if root is None:
        print("INTERNAL: frozen build missing sys._MEIPASS", file=sys.stderr)
        raise SystemExit(2)
    rest = sys.argv[3:]
    if job == "main":
        script = root / "main.py"
    elif job == "report":
        script = root / "report.py"
    else:
        print(f"INTERNAL: unknown subprocess job {job!r}", file=sys.stderr)
        raise SystemExit(2)
    if not script.is_file():
        print(f"INTERNAL: bundled script missing: {script}", file=sys.stderr)
        raise SystemExit(2)
    sys.argv = [str(script)] + rest
    runpy.run_path(str(script), run_name="__main__")
    raise SystemExit(0)


_dispatch_frozen_subprocess_cli()

import base64
import ctypes
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib import request
from urllib import error as urlerror

import webview
try:
    import psutil  # type: ignore
except Exception:  # noqa: BLE001
    psutil = None


def _app_bundle_dir() -> Path:
    """Files inside the PyInstaller build (onefile → sys._MEIPASS); in dev — the webview_app.py directory."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _app_root_dir() -> Path:
    """Persistent "project root": next to the .exe when frozen; in dev — the webview_app.py directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BUNDLE_DIR = _app_bundle_dir()
BASE_DIR = _app_root_dir()
MAIN_SCRIPT = BUNDLE_DIR / "main.py"
REPORT_SCRIPT = BUNDLE_DIR / "report.py"
SETTINGS_FILE = BASE_DIR / "settings.json"
SECRETS_FILE = BASE_DIR / ".declarator_secrets.json"
_SECRET_SETTINGS_KEYS = frozenset({"openrouter_api_key", "cloud_api_key"})
CONTROL_FILE = BASE_DIR / ".run_control.json"
SESSION_PROMPT_OVERRIDES_FILE = BASE_DIR / ".debug_session_prompt_overrides.json"
DIST_DIR = BUNDLE_DIR / "declarator-lm" / "dist"
APP_HTTP_USER_AGENT = "DeclaratorLM/0.70 (+https://console.groq.com)"


def _subprocess_script_argv(job: str, tail: list[str]) -> list[str]:
    """Arguments to launch main.py / report.py (frozen → no .py path after the exe)."""
    if job not in ("main", "report"):
        raise ValueError(job)
    if getattr(sys, "frozen", False):
        return [sys.executable, _RUNPY_MARKER, job] + tail
    exe = sys.executable
    script = MAIN_SCRIPT if job == "main" else REPORT_SCRIPT
    return [exe, str(script)] + tail

# Not persisted to settings.json (only for a single run from the frontend).
_EPHEMERAL_SETTINGS_KEYS = frozenset({
    "debug_mode_ui",
    "prompt_session_pipeline_system",
    "prompt_session_pipeline_user_template",
    "prompt_session_dossier_system",
    "prompt_session_dossier_user_template",
    "prompt_session_pipeline_name",
})
REASONING_DEBUG = os.environ.get("DECLARATOR_REASONING_DEBUG", "").strip() in {
    "1",
    "true",
    "True",
    "yes",
    "on",
}
_DEBUG_UI_MODE_FROM_ENV = os.environ.get("DECLARATOR_DEBUG_UI", "").strip() in {
    "1",
    "true",
    "True",
    "yes",
    "on",
}

PATH_KEYS = frozenset({
    "input_dir", "processed_dir", "output_jsonl", "errors_jsonl",
    "summary_csv", "findings_csv", "table_html",
})

DEFAULTS = {
    "input_dir": "dataset_declarations",
    "processed_dir": "dataset_declarations_done",
    "move_processed": True,
    "save_compact_declarations": False,
    "audit_mode_enabled": False,
    "audit_mode_dir": "audit",
    "audit_capture_raw_declaration": True,
    "audit_capture_compact_declaration": True,
    "audit_capture_request_payload": True,
    "audit_capture_response_raw": True,
    "audit_capture_response_parsed": True,
    "audit_capture_normalized_analysis": True,
    "audit_capture_attempt_meta": True,
    "compact_legacy_payload": False,
    "max_files": 1,
    "model": "llama3.1",
    "host": "http://127.0.0.1:11434",
    "timeout": 600,
    "retries": 2,
    "retry_delay": 5,
    "max_chars": 64000,
    "num_predict": 16000,
    "make_report": True,
    "no_dedupe": False,
    "output_jsonl": "analysis_results.jsonl",
    "errors_jsonl": "analysis_errors.jsonl",
    "summary_csv": "report_summary.csv",
    "findings_csv": "report_findings.csv",
    "table_html": "report_table.html",
    "show_system_metrics": False,
    "play_completion_sound": True,
    "think_event_debug": False,
    "sort_order": "alpha",
    "selected_files": [],
    "file_queue_mode": "sort",
    "cloud_mode": False,
    "cloud_provider": "ollama",
    "cloud_host": "https://ollama.com",
    "cloud_model": "",
    "cloud_api_key": "",
    # Alternative (isolated) OpenRouter path. Does not affect Ollama fields in any way.
    "openrouter_host": "https://openrouter.ai/api/v1",
    "openrouter_model": "meta-llama/llama-3.3-70b-instruct",
    "openrouter_api_key": "",
    "compare_enabled": False,
    "compare_count": 2,
    "compare_models": [],
    "welcome_modal_seen": False,
    "show_header_taglines": True,
    "pipeline_max_concurrent": 1,
}

DEEP_PATH_KEYS = {
    "deep_input_dir",
    "deep_output_jsonl",
    "deep_errors_jsonl",
    "deep_summary_csv",
    "deep_findings_csv",
    "deep_table_html",
}


def _resolve_path(raw: str) -> str:
    p = Path(raw)
    if not p.is_absolute():
        p = BASE_DIR / p
    return str(p)


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text via a temp file in the same directory + os.replace.

    Prevents truncated/corrupt JSON if the process is killed mid-write.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def _safe_user_path(raw: str) -> Path | None:
    """Resolve a user-supplied path, blocking relative traversal escape from project root.

    Policy:
    - Empty/blank input → None.
    - Relative path: joined with BASE_DIR (next to the exe when frozen); rejected if `..` escapes.
    - Absolute path: accepted as-is (the user explicitly opted in via picker).

    Returns None if the path cannot be resolved or escapes the project root.
    """
    raw_str = (raw or "").strip()
    if not raw_str:
        return None
    try:
        p = Path(raw_str)
    except (OSError, ValueError):
        return None
    if p.is_absolute():
        try:
            return p.resolve()
        except (OSError, ValueError):
            return None
    base = BASE_DIR.resolve()
    try:
        resolved = (base / p).resolve()
    except (OSError, ValueError):
        return None
    try:
        resolved.relative_to(base)
    except ValueError:
        return None
    return resolved


def _make_relative(raw: str) -> str:
    try:
        return str(Path(raw).resolve().relative_to(BASE_DIR.resolve()))
    except ValueError:
        return raw


def _is_under_deep_research(input_dir_raw: str) -> bool:
    """Whether input_dir is inside BASE_DIR/deep_research (for the HTML report next to the declarations)."""
    raw = (input_dir_raw or "").strip()
    if not raw:
        return False
    try:
        p = Path(raw)
        if not p.is_absolute():
            p = BASE_DIR / p
        return p.resolve().is_relative_to((BASE_DIR / "deep_research").resolve())
    except (OSError, ValueError):
        return False


def _resolve_input_dir_path(input_dir_arg: str) -> Path | None:
    raw = (input_dir_arg or "").strip()
    if not raw:
        return None
    try:
        p = Path(raw)
        if not p.is_absolute():
            p = BASE_DIR / p
        return p.resolve()
    except (OSError, ValueError):
        return None


def _deep_research_session_paths(in_dir: Path) -> dict[str, str]:
    """Local analysis/report paths within the research directory (without mixing with the global JSONL)."""
    return {
        "output_jsonl": str(in_dir / "analysis_results.jsonl"),
        "errors_jsonl": str(in_dir / "analysis_errors.jsonl"),
        "summary_csv": str(in_dir / "report_summary.csv"),
        "findings_csv": str(in_dir / "report_findings.csv"),
        "table_html": str(in_dir / "report_table.html"),
    }


_PIPELINE_PATH_KEYS = (
    "output_jsonl",
    "errors_jsonl",
    "summary_csv",
    "findings_csv",
    "table_html",
)


def _path_is_under_deep_research(path_str: str) -> bool:
    """Whether the file/directory is inside BASE_DIR/deep_research."""
    raw = (path_str or "").strip()
    if not raw:
        return False
    try:
        p = Path(raw)
        if not p.is_absolute():
            p = BASE_DIR / p
        return p.resolve().is_relative_to((BASE_DIR / "deep_research").resolve())
    except (OSError, ValueError):
        return False


def _resolve_pipeline_path(path_str: str) -> str:
    p = Path((path_str or "").strip())
    if not p.is_absolute():
        p = BASE_DIR / p
    return str(p.resolve())


def _normal_scope_paths() -> dict[str, str]:
    """Global paths for normal processing (project root)."""
    return {k: str((BASE_DIR / DEFAULTS[k]).resolve()) for k in _PIPELINE_PATH_KEYS}


def _coerce_pipeline_paths_from_args(args: dict) -> tuple[dict[str, str], list[str]]:
    """Reconcile JSONL/CSV/HTML with the input_dir mode; strip leftover deep_research paths in normal mode."""
    warnings: list[str] = []
    input_dir_arg = str(args.get("input_dir", "") or "").strip()
    under_deep = _is_under_deep_research(input_dir_arg)
    in_path = _resolve_input_dir_path(input_dir_arg)
    incoming = {k: str(args.get(k, "") or "").strip() for k in _PIPELINE_PATH_KEYS}

    if under_deep and in_path is not None:
        target = _deep_research_session_paths(in_path)
        for k in _PIPELINE_PATH_KEYS:
            old = incoming.get(k, "")
            if old:
                try:
                    old_res = _resolve_pipeline_path(old)
                except OSError:
                    old_res = old
                if old_res != target[k] and not _path_is_under_deep_research(old):
                    warnings.append(
                        f"Режим досьє: «{k}» вказував на звичайний каталог ({old}); "
                        f"використано {target[k]}"
                    )
        return dict(target), warnings

    normal = _normal_scope_paths()
    coerced: dict[str, str] = {}
    for k in _PIPELINE_PATH_KEYS:
        val = incoming.get(k, "")
        if not val or _path_is_under_deep_research(val):
            if val and _path_is_under_deep_research(val):
                warnings.append(
                    f"Звичайна обробка: «{k}» вказував на deep_research ({val}); "
                    f"скинуто на {normal[k]}"
                )
            coerced[k] = normal[k]
            continue
        try:
            resolved = _resolve_pipeline_path(val)
        except OSError:
            resolved = normal[k]
            warnings.append(f"Звичайна обробка: не вдалося прочитати «{k}» ({val}); скинуто на {resolved}")
        if _path_is_under_deep_research(resolved):
            warnings.append(
                f"Звичайна обробка: «{k}» ({val}) усередині deep_research; скинуто на {normal[k]}"
            )
            coerced[k] = normal[k]
        else:
            coerced[k] = resolved
    return coerced, warnings


def _resolve_report_csv_paths(args: dict, table_p: Path) -> tuple[Path, Path]:
    """Summary/findings CSV paths from args, accounting for deep research."""
    coerced, _ = _coerce_pipeline_paths_from_args(args)
    s = Path(coerced["summary_csv"])
    f = Path(coerced["findings_csv"])
    return s, f


def _resolve_report_paths_for_extra(args: dict) -> tuple[Path, Path, Path]:
    """Absolute paths for the errors/results JSONL and the main HTML, accounting for deep research."""
    coerced, _ = _coerce_pipeline_paths_from_args(args)
    return (
        Path(coerced["output_jsonl"]),
        Path(coerced["errors_jsonl"]),
        Path(coerced["table_html"]),
    )


def _load_secrets_file() -> dict:
    if not SECRETS_FILE.is_file():
        return {}
    try:
        raw = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_secrets_file(secrets: dict) -> None:
    try:
        _atomic_write_text(
            SECRETS_FILE,
            json.dumps(secrets, ensure_ascii=False, indent=2),
        )
    except OSError:
        pass


def _migrate_api_secrets_off_settings_file() -> None:
    """One-time migration of keys from settings.json to .declarator_secrets.json."""
    if not SETTINGS_FILE.is_file():
        return
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(raw, dict):
        return
    secrets = _load_secrets_file()
    changed = False
    for key in _SECRET_SETTINGS_KEYS:
        legacy = str(raw.get(key, "") or "").strip()
        if legacy and not str(secrets.get(key, "") or "").strip():
            secrets[key] = legacy
            changed = True
        if legacy and key in raw:
            raw.pop(key, None)
            changed = True
    if not changed:
        return
    _save_secrets_file(secrets)
    try:
        _atomic_write_text(
            SETTINGS_FILE,
            json.dumps(raw, ensure_ascii=False, indent=2),
        )
    except OSError:
        pass


def _merge_api_secrets_into_settings(data: dict) -> None:
    """Fill in keys from .declarator_secrets.json or the legacy settings.json."""
    _migrate_api_secrets_off_settings_file()
    secrets = _load_secrets_file()
    for key in _SECRET_SETTINGS_KEYS:
        val = str(secrets.get(key, "") or data.get(key, "") or "").strip()
        if val:
            data[key] = val


def _load_usage_aggregate_from_settings() -> dict:
    from usage_dashboard import default_usage_aggregate, normalize_usage_aggregate

    if not SETTINGS_FILE.is_file():
        return default_usage_aggregate()
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return normalize_usage_aggregate(raw.get("usage_aggregate"))
    except Exception:
        pass
    return default_usage_aggregate()


def _save_usage_aggregate_to_settings(agg: dict) -> None:
    existing: dict = {}
    if SETTINGS_FILE.is_file():
        try:
            loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {}
    existing["usage_aggregate"] = agg
    _atomic_write_text(
        SETTINGS_FILE,
        json.dumps(existing, ensure_ascii=False, indent=2),
    )


def _read_jsonl_lines_after(path: Path, skip_lines: int) -> list[dict]:
    rows: list[dict] = []
    if not path.is_file() or skip_lines < 0:
        return rows
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line_no, raw in enumerate(fh):
                if line_no < skip_lines:
                    continue
                line = raw.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except OSError:
        pass
    return rows


def _distinct_declarants_in_jsonl(path: Path) -> list[str]:
    """Unique declarants in the JSONL (by user_declarant_id, otherwise by full name)."""
    found: dict[str, str] = {}
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                ctx = obj.get("context_snapshot")
                ctx = ctx if isinstance(ctx, dict) else {}
                analysis = obj.get("analysis")
                analysis = analysis if isinstance(analysis, dict) else {}
                prof = analysis.get("subject_profile")
                prof = prof if isinstance(prof, dict) else {}
                uid = obj.get("user_declarant_id")
                if uid in (None, ""):
                    uid = prof.get("user_declarant_id")
                name = str(
                    ctx.get("declarant_full_name")
                    or prof.get("declarant_full_name")
                    or ""
                ).strip()
                if uid not in (None, ""):
                    key = f"id:{uid}"
                elif name:
                    key = f"name:{name.lower()}"
                else:
                    continue
                if key not in found:
                    found[key] = name or str(uid)
    except OSError:
        return []
    return list(found.values())


def _effective_model_short_from_args(args: dict) -> str:
    from argparse import Namespace

    from main import resolve_effective_model_and_mode

    cloud = bool(args.get("cloud_mode"))
    cp = str(args.get("cloud_provider", "ollama") or "ollama").lower()
    if cloud and cp == "openrouter":
        provider = "openrouter"
        model = str(args.get("openrouter_model", "") or args.get("model", "")).strip()
        ns = Namespace(
            provider=provider,
            cloud_mode=False,
            model=model,
            openrouter_model=model,
        )
    elif cloud:
        provider = "ollama"
        model = str(args.get("cloud_model", "") or args.get("model", "llama3.1")).strip()
        ns = Namespace(provider=provider, cloud_mode=True, model=model)
    else:
        model = str(args.get("model", "llama3.1")).strip()
        ns = Namespace(provider="ollama", cloud_mode=False, model=model)
    mid, _mode = resolve_effective_model_and_mode(ns)
    slash = mid.rfind("/")
    if slash >= 0 and slash < len(mid) - 1:
        return mid[slash + 1 :]
    return mid or "unknown"


def _count_critical_in_jsonl_rows(rows: list[dict]) -> int:
    from report import _as_dict

    n = 0
    for item in rows:
        analysis = _as_dict(item.get("analysis"))
        if str(analysis.get("risk_level", "")).strip().lower() == "critical":
            n += 1
    return n


WIPE_PROTECTED_SUBDIRS = frozenset({
    "venv",
    "build",
    "declarator-lm",
    "assets",
    "nazk_parser",
    "dist",
    ".git",
})
WIPE_BLOCKED_SUFFIXES = frozenset({".py", ".spec", ".exe"})
WIPE_RUNTIME_ROOT_FILES = (
    SETTINGS_FILE.name,
    f"{SETTINGS_FILE.name}.tmp",
    CONTROL_FILE.name,
    SESSION_PROMPT_OVERRIDES_FILE.name,
    DEFAULTS["output_jsonl"],
    DEFAULTS["errors_jsonl"],
    DEFAULTS["summary_csv"],
    DEFAULTS["findings_csv"],
    DEFAULTS["table_html"],
)
WIPE_SETTINGS_PATH_KEYS = frozenset(
    PATH_KEYS
    | DEEP_PATH_KEYS
    | frozenset({"audit_mode_dir", "normal_input_dir"})
)
WIPE_FIXED_TREE_DIRS = (
    Path("compare"),
    Path("deep_research"),
    Path("оброблені декларації") / "compact",
)


def _resolve_wipe_path(raw: str) -> Path | None:
    raw_str = (raw or "").strip()
    if not raw_str:
        return None
    try:
        p = Path(raw_str)
    except (OSError, ValueError):
        return None
    if not p.is_absolute():
        p = BASE_DIR / p
    try:
        return p.resolve()
    except (OSError, ValueError):
        return None


def _is_wipe_protected_file(path: Path) -> bool:
    if path.suffix.lower() in WIPE_BLOCKED_SUFFIXES:
        return True
    try:
        resolved = path.resolve()
    except OSError:
        return True
    if not resolved.is_file():
        return True
    base = BASE_DIR.resolve()
    try:
        rel = resolved.relative_to(base)
    except ValueError:
        return False
    if rel.parts and rel.parts[0] in WIPE_PROTECTED_SUBDIRS:
        return True
    return False


def _add_wipe_file(targets: set[Path], path: Path) -> None:
    try:
        resolved = path.resolve()
    except OSError:
        return
    if not resolved.is_file() or _is_wipe_protected_file(resolved):
        return
    targets.add(resolved)


def _collect_files_under_dir(targets: set[Path], directory: Path) -> None:
    if not directory.is_dir():
        return
    try:
        for item in directory.rglob("*"):
            if item.is_file():
                _add_wipe_file(targets, item)
    except OSError:
        pass


def _merge_wipe_path_settings(args: dict) -> dict:
    merged = dict(args or {})
    if SETTINGS_FILE.is_file():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            saved = None
        if isinstance(saved, dict):
            for key in WIPE_SETTINGS_PATH_KEYS:
                if key not in saved:
                    continue
                cur = str(merged.get(key, "") or "").strip()
                if cur:
                    continue
                val = saved.get(key)
                if isinstance(val, str) and val.strip():
                    merged[key] = _resolve_path(val)
    return merged


def _collect_wipe_targets(args: dict) -> set[Path]:
    targets: set[Path] = set()
    for name in WIPE_RUNTIME_ROOT_FILES:
        _add_wipe_file(targets, BASE_DIR / name)

    merged = _merge_wipe_path_settings(args)
    for key in WIPE_SETTINGS_PATH_KEYS:
        raw = str(merged.get(key, "") or "").strip()
        if not raw:
            continue
        resolved = _resolve_wipe_path(raw)
        if resolved is None:
            continue
        if resolved.is_file():
            _add_wipe_file(targets, resolved)
        elif resolved.is_dir():
            _collect_files_under_dir(targets, resolved)

    for rel_dir in WIPE_FIXED_TREE_DIRS:
        try:
            root = (BASE_DIR / rel_dir).resolve()
        except OSError:
            continue
        if root.is_dir():
            _collect_files_under_dir(targets, root)

    return targets


class Api:
    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._proc: subprocess.Popen | None = None
        self._metrics_cache: dict = {}
        self._metrics_cache_ts: float = 0.0
        # Guards mutation of `_proc` and writes to CONTROL_FILE / SETTINGS_FILE
        # so concurrent js_api calls (run_pipeline, control_pipeline,
        # save_settings, dismiss_welcome_modal) don't corrupt state.
        self._lock = threading.Lock()
        self._is_running = False
        self._debug_ui_mode: bool = _DEBUG_UI_MODE_FROM_ENV

    def set_window(self, window: webview.Window) -> None:
        self._window = window

    def _emit_log(self, line: str) -> None:
        if self._window is None:
            return
        escaped = json.dumps(line)
        self._window.evaluate_js(f"window._onLogLine({escaped})")

    # ── Settings ──────────────────────────────────────────────

    def load_settings(self) -> dict:
        data = dict(DEFAULTS)
        had_settings_file = False
        saved_raw: dict = {}
        if SETTINGS_FILE.exists():
            try:
                saved_raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                if isinstance(saved_raw, dict):
                    had_settings_file = True
                    data.update(saved_raw)
            except Exception:
                pass
        _merge_api_secrets_into_settings(data)
        # "First run" modal: new profile (no settings.json) — show it;
        # existing file without the key — treat as an old install, don't show it.
        if had_settings_file:
            if "welcome_modal_seen" not in saved_raw:
                data["welcome_modal_seen"] = True
        else:
            data["welcome_modal_seen"] = False
        # Old sessions may have saved a deep_research path into the normal input_dir.
        # In normal mode, fall back to a safe default / the last normal path.
        raw_input = str(data.get("input_dir", "") or "")
        if _is_under_deep_research(raw_input):
            fallback = str(data.get("normal_input_dir", "") or DEFAULTS["input_dir"])
            data["input_dir"] = fallback
        if not _is_under_deep_research(str(data.get("input_dir", "") or "")):
            normal_paths = _normal_scope_paths()
            for key in _PIPELINE_PATH_KEYS:
                val = str(data.get(key, "") or "")
                if _path_is_under_deep_research(val):
                    data[key] = normal_paths[key]
        for key in PATH_KEYS:
            if key in data and isinstance(data[key], str):
                data[key] = _resolve_path(data[key])
        for key in DEEP_PATH_KEYS:
            if key in data and isinstance(data[key], str):
                data[key] = _resolve_path(data[key])
        with self._lock:
            dbg_ui = self._debug_ui_mode
        data["debug_mode_ui"] = dbg_ui
        return data

    def unlock_debug_ui_mode(self) -> dict:
        """Enable debug UI for the current session without a restart (frontend gesture)."""
        with self._lock:
            self._debug_ui_mode = True
        self._emit_log("[INFO] Debug UI mode увімкнено під час роботи сесії.\n")
        return {"ok": True, "debug_mode_ui": True}

    def debug_wipe_usage_traces(self, args: dict) -> dict:
        """Debug-only: delete usage-trace files (leave directories untouched)."""
        with self._lock:
            if not self._debug_ui_mode:
                return {"ok": False, "errors": ["Доступно лише в режимі Debug UI."]}
            if self._proc is not None and self._proc.poll() is None:
                return {
                    "ok": False,
                    "errors": ["Зупиніть пайплайн перед видаленням слідів використання."],
                }

        targets = _collect_wipe_targets(args or {})
        deleted: list[str] = []
        errors: list[str] = []

        self._emit_log("\n=== [WIPE] Видалення слідів використання ===\n")
        self._emit_log(f"[WIPE] Знайдено файлів для видалення: {len(targets)}\n")

        for path in sorted(targets, key=lambda p: str(p).lower()):
            try:
                path.unlink()
                deleted.append(str(path))
            except OSError as exc:
                errors.append(f"{path}: {exc}")

        for line in deleted[:20]:
            self._emit_log(f"[WIPE] видалено: {line}\n")
        if len(deleted) > 20:
            self._emit_log(f"[WIPE] ... ще {len(deleted) - 20} файл(ів)\n")
        for err in errors[:10]:
            self._emit_log(f"[WIPE][ERR] {err}\n")

        self._emit_log(
            f"[WIPE] Готово: видалено {len(deleted)} файл(ів)"
            f"{f', помилок: {len(errors)}' if errors else ''}.\n"
        )

        return {
            "ok": len(errors) == 0,
            "deleted_count": len(deleted),
            "deleted_sample": deleted[:20],
            "errors": errors,
        }

    def save_settings(self, settings: dict) -> None:
        with self._lock:
            existing: dict = {}
            if SETTINGS_FILE.exists():
                try:
                    existing = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                except Exception:
                    existing = {}

            out = dict(existing)
            secrets_out = _load_secrets_file()
            input_dir_raw = str(settings.get("input_dir", "") or "")
            deep_mode_now = _is_under_deep_research(input_dir_raw)

            for key, value in settings.items():
                if key in _EPHEMERAL_SETTINGS_KEYS:
                    continue
                if key in _SECRET_SETTINGS_KEYS:
                    if isinstance(value, str) and value.strip():
                        secrets_out[key] = value.strip()
                    continue
                if key in PATH_KEYS and isinstance(value, str):
                    rel_val = _make_relative(value)
                    if deep_mode_now:
                        # Deep mode must not overwrite normal-mode paths.
                        deep_map = {
                            "input_dir": "deep_input_dir",
                            "output_jsonl": "deep_output_jsonl",
                            "errors_jsonl": "deep_errors_jsonl",
                            "summary_csv": "deep_summary_csv",
                            "findings_csv": "deep_findings_csv",
                            "table_html": "deep_table_html",
                        }
                        # processed_dir is not duplicated into deep_* in deep mode — keep the normal key
                        # (moving JSON in dossier mode is disabled at the pipeline level anyway).
                        deep_key = deep_map.get(key)
                        if deep_key is not None:
                            out[deep_key] = rel_val
                            continue
                        out[key] = rel_val
                        continue
                    out[key] = rel_val
                    if key == "input_dir":
                        out["normal_input_dir"] = rel_val
                    continue
                out[key] = value
            for secret_key in _SECRET_SETTINGS_KEYS:
                legacy = str(existing.get(secret_key, "") or "").strip()
                if legacy and not str(secrets_out.get(secret_key, "") or "").strip():
                    secrets_out[secret_key] = legacy
                out.pop(secret_key, None)
            try:
                _save_secrets_file(secrets_out)
                _atomic_write_text(
                    SETTINGS_FILE,
                    json.dumps(out, ensure_ascii=False, indent=2),
                )
            except Exception:
                pass

    def dismiss_welcome_modal(self) -> dict:
        """Mark the welcome modal as seen (without a full save_settings from the form)."""
        with self._lock:
            existing: dict = {}
            if SETTINGS_FILE.exists():
                try:
                    raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        existing = raw
                except Exception:
                    existing = {}
            existing["welcome_modal_seen"] = True
            try:
                _atomic_write_text(
                    SETTINGS_FILE,
                    json.dumps(existing, ensure_ascii=False, indent=2),
                )
                return {"ok": True}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "errors": [str(exc)]}

    def copy_to_clipboard(self, text: str) -> dict:
        """Copy via the backend (workaround for the unreliable webview clipboard)."""
        payload = str(text or "")
        if not payload:
            return {"ok": False, "message": "Нічого копіювати."}
        try:
            if os.name == "nt":
                # Use native WinAPI Unicode clipboard to avoid codepage mojibake.
                user32 = ctypes.windll.user32  # type: ignore[attr-defined]
                kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                GMEM_MOVEABLE = 0x0002
                CF_UNICODETEXT = 13
                c_void_p = ctypes.c_void_p
                c_size_t = ctypes.c_size_t

                # Explicit signatures are critical on x64; otherwise pointers can be truncated.
                user32.OpenClipboard.argtypes = [c_void_p]
                user32.OpenClipboard.restype = ctypes.c_int
                user32.CloseClipboard.argtypes = []
                user32.CloseClipboard.restype = ctypes.c_int
                user32.EmptyClipboard.argtypes = []
                user32.EmptyClipboard.restype = ctypes.c_int
                user32.SetClipboardData.argtypes = [ctypes.c_uint, c_void_p]
                user32.SetClipboardData.restype = c_void_p
                kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, c_size_t]
                kernel32.GlobalAlloc.restype = c_void_p
                kernel32.GlobalLock.argtypes = [c_void_p]
                kernel32.GlobalLock.restype = c_void_p
                kernel32.GlobalUnlock.argtypes = [c_void_p]
                kernel32.GlobalUnlock.restype = ctypes.c_int
                kernel32.GlobalFree.argtypes = [c_void_p]
                kernel32.GlobalFree.restype = c_void_p

                # Clipboard can be temporarily locked by another process.
                opened = False
                for _ in range(20):
                    if user32.OpenClipboard(None):
                        opened = True
                        break
                    time.sleep(0.01)
                if not opened:
                    return {"ok": False, "message": "Не вдалося відкрити буфер обміну (clipboard зайнятий)."}
                h_mem = None
                try:
                    if not user32.EmptyClipboard():
                        return {"ok": False, "message": "EmptyClipboard не вдалося."}
                    data = payload + "\x00"
                    size = len(data.encode("utf-16-le"))
                    h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
                    if not h_mem:
                        return {"ok": False, "message": "GlobalAlloc не зміг виділити пам'ять."}
                    ptr = kernel32.GlobalLock(h_mem)
                    if not ptr:
                        return {"ok": False, "message": "GlobalLock повернув NULL."}
                    try:
                        ctypes.memmove(ptr, data.encode("utf-16-le"), size)
                    finally:
                        kernel32.GlobalUnlock(h_mem)
                    if not user32.SetClipboardData(CF_UNICODETEXT, h_mem):
                        return {"ok": False, "message": "SetClipboardData не вдалося."}
                    # After successful SetClipboardData ownership passes to system.
                    h_mem = None
                    return {"ok": True, "message": "Лог скопійовано в буфер обміну"}
                finally:
                    if h_mem:
                        kernel32.GlobalFree(h_mem)
                    user32.CloseClipboard()
            return {"ok": False, "message": "Clipboard backend не підтримується на цій ОС."}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"Clipboard error: {exc}"}

    # ── Validation ─────────────────────────────────────────────

    def validate(self, args: dict) -> dict:
        errors = []

        try:
            conc = int(args.get("pipeline_max_concurrent", 1) or 1)
        except (TypeError, ValueError):
            errors.append("Некоректне значення поля «Паралельні декларації» (ціле число).")
            conc = 1
        if conc < 1 or conc > 8:
            errors.append("Паралельна обробка: допустимо від 1 до 8 одночасних декларацій.")

        input_dir = args.get("input_dir", "").strip()
        if not input_dir:
            errors.append("Не вказана папка декларацій.")
        elif not Path(input_dir).exists():
            errors.append(f"Папка декларацій не існує: {input_dir}")

        cloud_mode = bool(args.get("cloud_mode", False))
        cloud_provider = str(args.get("cloud_provider", "ollama") or "ollama").lower()

        if conc > 1 and not (cloud_mode and cloud_provider == "openrouter"):
            errors.append(
                "Паралельна обробка (2–8) доступна лише в режимі Cloud з провайдером OpenRouter."
            )

        if cloud_mode and cloud_provider == "openrouter":
            # Alternative path: no call to Ollama's /api/tags happens here.
            host = str(args.get("openrouter_host", "") or "https://openrouter.ai/api/v1").rstrip("/")
            api_key = str(args.get("openrouter_api_key", "") or "").strip()
            model = str(args.get("openrouter_model", "") or "").strip()
            if not api_key:
                errors.append("Для OpenRouter вкажіть API key (sk-or-v1-...).")
            if not model:
                errors.append("Для OpenRouter вкажіть модель.")
            if not host.startswith("http://") and not host.startswith("https://"):
                errors.append("OpenRouter host має починатися з http:// або https://")
            return {"ok": len(errors) == 0, "errors": errors}

        host_key = "cloud_host" if cloud_mode else "host"
        model_key = "cloud_model" if cloud_mode else "model"
        host_default = "https://ollama.com" if cloud_mode else "http://127.0.0.1:11434"
        host = (args.get(host_key, "") or host_default).rstrip("/")

        if cloud_mode:
            api_key = str(args.get("cloud_api_key", "") or "").strip()
            model = str(args.get("cloud_model", "") or "").strip()
            if not api_key:
                errors.append("Для Cloud режиму вкажіть API key.")
            if not model:
                errors.append("Для Cloud режиму вкажіть cloud model.")
            if not host.startswith("http://") and not host.startswith("https://"):
                errors.append("Cloud host має починатися з http:// або https://")
            return {"ok": len(errors) == 0, "errors": errors}

        available = []
        try:
            req = request.Request(f"{host}/api/tags", method="GET")
            with request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                available = [m["name"] for m in data.get("models", [])]
        except Exception:
            errors.append(f"Ollama недоступна за адресою: {host}")
            return {"ok": False, "errors": errors}

        model = args.get(model_key, "").strip()
        if model and available and model not in available:
            short = ", ".join(available[:5])
            errors.append(f"Модель \"{model}\" не знайдена в Ollama. Доступні: {short}")

        return {"ok": len(errors) == 0, "errors": errors}

    def get_builtin_prompts(self) -> dict:
        """Built-in prompt texts (for the debug UI editor; does not modify project files)."""
        from dossier_html_summary import (
            DOSSIER_SYSTEM_PROMPT,
            DOSSIER_USER_PROMPT_TEMPLATE,
        )
        from main import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

        return {
            "pipeline_system_prompt": SYSTEM_PROMPT,
            "pipeline_user_prompt_template": USER_PROMPT_TEMPLATE,
            "dossier_system_prompt": DOSSIER_SYSTEM_PROMPT,
            "dossier_user_prompt_template": DOSSIER_USER_PROMPT_TEMPLATE,
        }

    def _write_session_prompt_overrides(self, args: dict) -> str | None:
        """Returns the path to the JSON, or None if there are no overrides."""
        if not bool(args.get("debug_mode_ui")):
            self._remove_session_prompt_overrides()
            return None
        mapping = (
            ("prompt_session_pipeline_system", "pipeline_system_prompt"),
            ("prompt_session_pipeline_user_template", "pipeline_user_prompt_template"),
            ("prompt_session_dossier_system", "dossier_system_prompt"),
            ("prompt_session_dossier_user_template", "dossier_user_prompt_template"),
        )
        data: dict[str, str] = {}
        for arg_key, json_key in mapping:
            val = str(args.get(arg_key, "") or "").strip()
            if val:
                data[json_key] = val
        name_val = str(args.get("prompt_session_pipeline_name", "") or "").strip()
        if name_val and (
            "pipeline_system_prompt" in data or "pipeline_user_prompt_template" in data
        ):
            data["pipeline_prompt_name"] = name_val
        if not data:
            self._remove_session_prompt_overrides()
            return None
        try:
            SESSION_PROMPT_OVERRIDES_FILE.write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            return None
        return str(SESSION_PROMPT_OVERRIDES_FILE.resolve())

    @staticmethod
    def _remove_session_prompt_overrides() -> None:
        try:
            if SESSION_PROMPT_OVERRIDES_FILE.is_file():
                SESSION_PROMPT_OVERRIDES_FILE.unlink()
        except OSError:
            pass

    def _load_session_prompt_overrides_dict(self) -> dict:
        if not SESSION_PROMPT_OVERRIDES_FILE.is_file():
            return {}
        try:
            raw = json.loads(
                SESSION_PROMPT_OVERRIDES_FILE.read_text(encoding="utf-8")
            )
            return raw if isinstance(raw, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    # ── Ollama models ─────────────────────────────────────────

    def fetch_models(self, host: str, api_key: str = "") -> list[str]:
        host = (host or "http://127.0.0.1:11434").rstrip("/")
        try:
            headers = {}
            if api_key and str(api_key).strip():
                headers["Authorization"] = f"Bearer {str(api_key).strip()}"
            req = request.Request(f"{host}/api/tags", headers=headers, method="GET")
            with request.urlopen(req, timeout=4) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in raw.get("models", [])]
        except Exception:
            return []

    # ── OpenRouter models (alternative path, unrelated to Ollama) ────────

    def fetch_openrouter_models(self, host: str = "", api_key: str = "") -> list[str]:
        try:
            from openrouter_client import fetch_openrouter_models as _fetch, DEFAULT_OPENROUTER_HOST

            return _fetch(host or DEFAULT_OPENROUTER_HOST, api_key or "")
        except Exception:  # noqa: BLE001
            return []

    def fetch_openrouter_models_enriched(self, host: str = "", api_key: str = "") -> dict:
        """List of models + short pricing ($/1M in/out) for each id."""
        try:
            from openrouter_client import (
                fetch_openrouter_models_enriched as _fetch_e,
                DEFAULT_OPENROUTER_HOST,
            )

            out = _fetch_e(host or DEFAULT_OPENROUTER_HOST, api_key or "")
            return (
                out
                if isinstance(out, dict)
                else {
                    "models": [],
                    "pricing": {},
                    "pricing_per_token": {},
                    "context_length": {},
                }
            )
        except Exception:  # noqa: BLE001
            return {
                "models": [],
                "pricing": {},
                "pricing_per_token": {},
                "context_length": {},
            }

    def fetch_openrouter_credits(self, host: str = "", api_key: str = "") -> dict:
        """GET /credits — remaining balance (USD) for the Bearer key."""
        try:
            from openrouter_client import fetch_openrouter_credits as _credits, DEFAULT_OPENROUTER_HOST

            res = _credits(host or DEFAULT_OPENROUTER_HOST, api_key or "")
            return res if isinstance(res, dict) else {"ok": False, "message": "bad response", "balance_label": ""}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc), "balance_label": ""}

    def test_openrouter_connection(self, host: str = "", api_key: str = "", model: str = "") -> dict:
        """DEBUG-only quick check for OpenRouter auth/connectivity via GET /models."""
        host_norm = str(host or "https://openrouter.ai/api/v1").rstrip("/")
        key = str(api_key or "").strip()
        model_hint = str(model or "").strip()
        if not key:
            return {"ok": False, "message": "Порожній OpenRouter API key."}
        if not host_norm.startswith("http://") and not host_norm.startswith("https://"):
            return {"ok": False, "message": "OpenRouter host має починатися з http:// або https://"}
        try:
            req = request.Request(
                f"{host_norm}/models",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {key}",
                    "User-Agent": APP_HTTP_USER_AGENT,
                },
                method="GET",
            )
            with request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            items = raw.get("data", []) if isinstance(raw, dict) else []
            ids = []
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        mid = item.get("id")
                        if isinstance(mid, str) and mid.strip():
                            ids.append(mid.strip())
            if model_hint and ids and model_hint not in ids:
                short = ", ".join(ids[:6])
                return {
                    "ok": True,
                    "message": f"Підключення OK, але модель \"{model_hint}\" не знайдена. Наприклад: {short}",
                    "models": ids,
                }
            return {
                "ok": True,
                "message": f"Підключення до OpenRouter успішне. Доступно моделей: {len(ids)}",
                "models": ids,
            }
        except urlerror.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return {
                "ok": False,
                "message": f"OpenRouter HTTP {exc.code}: {exc.reason}. Body: {body}",
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"OpenRouter connection error: {exc}"}

    def test_ollama_connection(self, host: str = "", model: str = "") -> dict:
        """DEBUG-only quick check for Ollama via GET /api/tags."""
        host_norm = str(host or "http://127.0.0.1:11434").rstrip("/")
        model_hint = str(model or "").strip()
        if not host_norm.startswith("http://") and not host_norm.startswith("https://"):
            return {"ok": False, "message": "Ollama host має починатися з http:// або https://"}
        try:
            req = request.Request(f"{host_norm}/api/tags", method="GET")
            with request.urlopen(req, timeout=8) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name") for m in raw.get("models", []) if isinstance(m, dict)]
            models = [m for m in models if isinstance(m, str) and m.strip()]
            if model_hint and models and model_hint not in models:
                short = ", ".join(models[:6])
                return {
                    "ok": True,
                    "message": f"Підключення OK, але модель \"{model_hint}\" не знайдена. Доступні: {short}",
                    "models": models,
                }
            return {
                "ok": True,
                "message": f"Підключення до Ollama успішне. Доступно моделей: {len(models)}",
                "models": models,
            }
        except urlerror.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return {
                "ok": False,
                "message": f"Ollama HTTP {exc.code}: {exc.reason}. Body: {body}",
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"Ollama connection error: {exc}"}

    # ── File dialogs ──────────────────────────────────────────

    def pick_folder(self) -> str | None:
        if self._window is None:
            return None
        result = self._window.create_file_dialog(
            webview.FOLDER_DIALOG, directory=str(BASE_DIR)
        )
        if result and len(result) > 0:
            return result[0]
        return None

    def pick_file(self) -> str | None:
        if self._window is None:
            return None
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=str(BASE_DIR),
            file_types=("All files (*.*)",),
        )
        if result:
            return result if isinstance(result, str) else result[0]
        return None

    def pick_html_file_open(self) -> str | None:
        """Open an existing HTML file (for the debug dossier summary, etc.)."""
        if self._window is None:
            return None
        fd_open = getattr(webview, "FileDialog", None)
        dialog_type = fd_open.OPEN if fd_open is not None else getattr(
            webview, "OPEN_DIALOG", 10
        )
        result = self._window.create_file_dialog(
            dialog_type,
            directory=str(BASE_DIR),
            file_types=("HTML (*.html;*.htm)", "All files (*.*)"),
        )
        if not result:
            return None
        return result if isinstance(result, str) else result[0]

    @staticmethod
    def _json_dir_fingerprint(dir_path: Path) -> tuple[int, str]:
        """Count of *.json files and a fingerprint (name+mtime+size) without reading file contents."""
        rows: list[tuple[str, int, int]] = []
        try:
            if not dir_path.is_dir():
                return 0, ""
        except OSError:
            return 0, ""
        for fp in sorted(dir_path.glob("*.json")):
            try:
                st = fp.stat()
            except OSError:
                continue
            mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
            rows.append((fp.name, mtime_ns, int(st.st_size)))
        if not rows:
            return 0, ""
        payload = "\n".join(f"{n}\t{t}\t{s}" for n, t, s in rows).encode("utf-8")
        return len(rows), hashlib.sha256(payload).hexdigest()

    def declaration_folders_snapshot(
        self, input_dir_arg: str, processed_dir_arg: str
    ) -> dict:
        """
        Lightweight snapshot of the declaration and processed directories: only stat on *.json.
        Needed by the UI to cache the file list without re-parsing JSON.
        """
        raw_in = str(input_dir_arg or "").strip()
        raw_proc = str(processed_dir_arg or "").strip()
        if not raw_in:
            return {
                "ok": False,
                "errors": ["Не вказано папку декларацій."],
                "input": {"count": 0, "fingerprint": ""},
                "processed": {"count": 0, "fingerprint": ""},
            }
        p_in = _safe_user_path(raw_in)
        if p_in is None:
            return {
                "ok": False,
                "errors": ["Некоректний шлях до папки декларацій."],
                "input": {"count": 0, "fingerprint": ""},
                "processed": {"count": 0, "fingerprint": ""},
            }
        if not p_in.is_dir():
            return {
                "ok": False,
                "errors": [f"Каталог не існує: {p_in}"],
                "input": {"count": 0, "fingerprint": ""},
                "processed": {"count": 0, "fingerprint": ""},
            }

        ci, fi = self._json_dir_fingerprint(p_in)
        cp, fp_f = (0, "")
        if raw_proc:
            p_proc = _safe_user_path(raw_proc)
            if p_proc is not None and p_proc.is_dir():
                cp, fp_f = self._json_dir_fingerprint(p_proc)

        return {
            "ok": True,
            "errors": [],
            "input": {"count": ci, "fingerprint": fi},
            "processed": {"count": cp, "fingerprint": fp_f},
        }

    def list_declaration_files(self, input_dir_arg: str) -> dict:
        """List of *.json files in the directory with short metadata for the UI (no full analysis)."""
        raw = str(input_dir_arg or "").strip()
        if not raw:
            return {"ok": False, "errors": ["Не вказано папку декларацій."], "files": []}
        p = _safe_user_path(raw)
        if p is None:
            return {
                "ok": False,
                "errors": ["Некоректний шлях до папки декларацій."],
                "files": [],
            }
        if not p.is_dir():
            return {"ok": False, "errors": [f"Каталог не існує: {p}"], "files": []}

        files_out: list[dict] = []
        for fp in sorted(p.glob("*.json")):
            try:
                st = fp.stat()
            except OSError:
                continue
            mtime_iso = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
            size_bytes = int(st.st_size)
            full_name = ""
            declaration_year: str | int = ""
            position = ""
            workplace = ""
            try:
                raw_json = json.loads(fp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw_json = {}
            data = raw_json.get("data", {}) if isinstance(raw_json, dict) else {}
            step1_node = data.get("step_1", {}) if isinstance(data, dict) else {}
            step1 = step1_node.get("data", {}) if isinstance(step1_node, dict) else {}
            if isinstance(step1, dict):
                ln = str(step1.get("lastname", "") or "").strip()
                fn = str(step1.get("firstname", "") or "").strip()
                mn = str(step1.get("middlename", "") or "").strip()
                full_name = " ".join(x for x in (ln, fn, mn) if x).strip()
                position = str(step1.get("workPost", "") or "").strip()
                workplace = str(step1.get("workPlace", "") or "").strip()
            if isinstance(raw_json, dict):
                declaration_year = raw_json.get("declaration_year", "")
                if declaration_year in (None, ""):
                    step0 = (data.get("step_0", {}) or {}).get("data", {})
                    if isinstance(step0, dict):
                        declaration_year = step0.get("declarationYear1", "")
            files_out.append(
                {
                    "name": fp.name,
                    "full_name": full_name,
                    "declaration_year": declaration_year,
                    "position": position,
                    "workplace": workplace,
                    "mtime_iso": mtime_iso,
                    "size_bytes": size_bytes,
                }
            )
        return {"ok": True, "errors": [], "files": files_out}

    def debug_run_dossier_html_summary(self, args: dict) -> dict:
        """
        DEBUG UI only: dossier HTML summary without running the full pipeline.
        Report path: same as in the pipeline — if input_dir is under deep_research, always use
        the session's report_table.html (ignores the stale table_html field from the project root).
        Optionally html_debug_override — raw HTML for the prompt.
        """
        if not bool(args.get("debug_mode_ui")):
            return {
                "ok": False,
                "message": "Доступно лише в режимі DEBUG (debug_mode.bat).",
            }
        input_dir_arg = str(args.get("input_dir", "") or "").strip()
        if not _is_under_deep_research(input_dir_arg) and not str(
            args.get("table_html", "") or ""
        ).strip():
            return {
                "ok": False,
                "message": "Вкажіть шлях до HTML у полі «Таблиця (HTML)» або оберіть файл.",
            }

        jsonl_p, _, th = _resolve_report_paths_for_extra(args)
        if not th.exists():
            hint = ""
            if _is_under_deep_research(input_dir_arg):
                hint = " Спочатку згенеруйте звіт (пайплайн або «Перегенерувати HTML + CSV»)."
            return {
                "ok": False,
                "message": f"HTML-звіт не знайдено: {th}.{hint}",
            }

        override_raw = args.get("html_debug_override")
        html_override: str | None
        if isinstance(override_raw, str) and override_raw.strip():
            html_override = override_raw
        else:
            html_override = None

        # A "dossier" is one person across different years. If the report contains many
        # different declarants (e.g. the root report_table.html from a combined JSONL),
        # the summary becomes meaningless — block it and explain why.
        if html_override is None:
            declarants = _distinct_declarants_in_jsonl(jsonl_p)
            if len(declarants) > 1:
                preview = ", ".join(d for d in declarants[:5] if d)
                more = "…" if len(declarants) > 5 else ""
                return {
                    "ok": False,
                    "message": (
                        f"Підсумок досьє розрахований на ОДНУ особу, а у звіті виявлено "
                        f"{len(declarants)} різних декларантів ({preview}{more}). "
                        "Скористайтеся режимом глибокого дослідження (deep research) для "
                        "конкретної особи або вкажіть HTML-звіт однієї особи."
                    ),
                }

        self._write_session_prompt_overrides(args)
        dossier_po = self._load_session_prompt_overrides_dict()

        cloud = bool(args.get("cloud_mode"))
        cloud_provider = str(args.get("cloud_provider", "ollama") or "ollama").lower()
        if cloud and cloud_provider == "openrouter":
            provider = "openrouter"
            model = (str(args.get("openrouter_model") or "").strip() or "meta-llama/llama-3.3-70b-instruct")
            host = str(args.get("openrouter_host", "https://openrouter.ai/api/v1"))
            key = str(args.get("openrouter_api_key", "") or "")
        elif cloud:
            provider = "ollama"
            model = (str(args.get("cloud_model") or "").strip() or args.get(
                "model", "llama3.1"
            ))
            host = str(args.get("cloud_host", "https://ollama.com"))
            key = str(args.get("cloud_api_key", "") or "")
        else:
            provider = "ollama"
            model = str(args.get("model", "llama3.1"))
            host = str(args.get("host", "http://127.0.0.1:11434"))
            key = ""

        try:
            timeout_sec = int(args.get("timeout", 600))
        except (TypeError, ValueError):
            timeout_sec = 600
        try:
            num_predict = int(args.get("num_predict", -1))
        except (TypeError, ValueError):
            num_predict = -1

        from dossier_html_summary import run_dossier_table_summary_append

        self._emit_log("\n=== [DEBUG] Підсумок досьє по HTML (без пайплайну) ===\n")
        if _is_under_deep_research(input_dir_arg):
            self._emit_log(
                f"[DEBUG] Підсумок досьє: HTML → {th} (режим deep_research, узгоджено з пайплайном).\n"
            )

        ok, msg = run_dossier_table_summary_append(
            table_html_path=th,
            model=str(model),
            host=str(host),
            timeout_sec=timeout_sec,
            num_predict=num_predict,
            api_key=key,
            cloud_mode=cloud,
            prompt_overrides=dossier_po or None,
            html_source_override=html_override,
            provider=provider,
        )
        return {"ok": ok, "message": msg}

    def debug_compare_models_html(self, args: dict) -> dict:
        """DEBUG UI only: run ONE declaration through 2-4 models and gather comparison reports."""
        if not bool(args.get("debug_mode_ui")):
            return {"ok": False, "message": "Доступно лише в режимі DEBUG (debug_mode.bat)."}
        models_raw = args.get("compare_models")
        models: list[str]
        if isinstance(models_raw, list):
            models = [str(m or "").strip() for m in models_raw if str(m or "").strip()]
        else:
            models = []
        models = list(dict.fromkeys(models))
        if len(models) < 2 or len(models) > 4:
            return {"ok": False, "message": "Оберіть від 2 до 4 унікальних моделей."}

        input_dir_arg = str(args.get("input_dir", "") or "").strip()
        input_dir_path = _resolve_input_dir_path(input_dir_arg)
        if input_dir_path is None or not input_dir_path.exists() or not input_dir_path.is_dir():
            return {"ok": False, "message": "Вкажіть коректну папку з деклараціями (input_dir)."}

        cloud = bool(args.get("cloud_mode"))
        cloud_provider = str(args.get("cloud_provider", "ollama") or "ollama").lower()
        if cloud and cloud_provider == "openrouter":
            provider = "openrouter"
            host = str(args.get("openrouter_host", "https://openrouter.ai/api/v1") or "").strip()
            api_key = str(args.get("openrouter_api_key", "") or "").strip()
        elif cloud:
            provider = "ollama"
            host = str(args.get("cloud_host", "https://ollama.com") or "").strip()
            api_key = str(args.get("cloud_api_key", "") or "").strip()
        else:
            provider = "ollama"
            host = str(args.get("host", "http://127.0.0.1:11434") or "").strip()
            api_key = ""
        if not host:
            return {"ok": False, "message": "Вкажіть host для порівняння моделей."}

        try:
            timeout_sec = int(args.get("timeout", 600))
        except (TypeError, ValueError):
            timeout_sec = 600
        try:
            num_predict = int(args.get("num_predict", -1))
        except (TypeError, ValueError):
            num_predict = -1

        self._write_session_prompt_overrides(args)
        prompt_overrides = self._load_session_prompt_overrides_dict()

        selected_raw = args.get("selected_files")
        selected_list = (
            [str(x or "").strip() for x in selected_raw if str(x or "").strip()]
            if isinstance(selected_raw, list)
            else []
        )
        target_file: Path | None = None
        if selected_list:
            first_selected = selected_list[0]
            cand = _safe_user_path(first_selected) or (input_dir_path / first_selected).resolve()
            if cand.exists() and cand.is_file():
                target_file = cand
        if target_file is None:
            candidates = sorted(input_dir_path.glob("*.json"), key=lambda p: p.name.lower())
            if not candidates:
                return {"ok": False, "message": f"У папці немає JSON-декларацій: {input_dir_path}"}
            target_file = candidates[0]

        from main import append_jsonl, process_file, resolve_effective_model_and_mode

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        compare_dir = (BASE_DIR / "compare" / f"{ts}_{target_file.stem[:32]}").resolve()
        compare_dir.mkdir(parents=True, exist_ok=True)
        out_jsonl = compare_dir / "analysis_results.compare.jsonl"
        err_jsonl = compare_dir / "analysis_errors.compare.jsonl"
        summary_csv = compare_dir / "report_summary.compare.csv"
        findings_csv = compare_dir / "report_findings.compare.csv"
        table_html = compare_dir / "report_table.compare.html"

        self._emit_log("\n=== [COMPARE] Порівняння моделей на одній декларації ===\n")
        self._emit_log(f"[COMPARE] Папка: {compare_dir}\n")
        self._emit_log(f"[COMPARE] Декларація: {target_file}\n")
        self._emit_log(f"[COMPARE] Provider: {provider}; моделей: {len(models)}\n")

        pricing_per_token: dict[str, dict[str, float]] = {}
        context_length_map: dict[str, int] = {}
        compare_or_totals: dict[str, int | float] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "cost_known_n": 0,
            "n": 0,
        }
        if provider == "openrouter":
            try:
                from openrouter_client import fetch_openrouter_models_enriched

                or_host = str(args.get("openrouter_host", host) or host).strip()
                or_key = str(args.get("openrouter_api_key", api_key) or api_key).strip()
                enriched = fetch_openrouter_models_enriched(or_host, or_key)
                pricing_per_token = enriched.get("pricing_per_token") or {}
                context_length_map = enriched.get("context_length") or {}
            except Exception as exc:  # noqa: BLE001
                self._emit_log(f"[COMPARE][WARN] Не вдалося завантажити прайс /models: {exc}\n")

        from openrouter_client import (
            format_openrouter_run_totals_footer,
            format_openrouter_usage_log_suffix,
        )

        ok_count = 0
        err_count = 0
        for idx, model_name in enumerate(models, start=1):
            self._emit_log(f"[{idx}/{len(models)}] RUN model={model_name}\n")
            run_args = {
                "retries": args.get("retries", 1),
                "retry_delay": args.get("retry_delay", 1.5),
                "max_chars": args.get("max_chars", 120000),
                "save_compact_declarations": False,
                "compact_declarations_dir": str(compare_dir / "compact"),
                "debug_payload_dir": str(compare_dir / "payload"),
                "model": str(model_name),
                "host": host,
                "timeout": timeout_sec,
                "num_predict": num_predict,
                "reasoning_debug": bool(args.get("reasoning_debug", REASONING_DEBUG)),
                "api_key": api_key,
                "cloud_mode": cloud,
                "provider": provider,
                "openrouter_model": str(model_name),
                "openrouter_host": str(args.get("openrouter_host", host) or host),
                "openrouter_api_key": str(args.get("openrouter_api_key", api_key) or api_key),
                "run_id": f"compare-{ts}",
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "prompt_overrides": prompt_overrides if prompt_overrides else None,
                "audit_mode": False,
                "audit_mode_dir": "",
                "audit_capture_raw_declaration": False,
                "audit_capture_compact_declaration": False,
                "audit_capture_request_payload": False,
                "audit_capture_response_raw": False,
                "audit_capture_response_parsed": False,
                "audit_capture_normalized_analysis": False,
                "audit_capture_attempt_meta": False,
            }
            ns = SimpleNamespace(**run_args)
            if provider == "openrouter":
                setattr(ns, "_openrouter_pricing_per_token", pricing_per_token)
                setattr(ns, "_openrouter_context_length", context_length_map)
            try:
                result = process_file(target_file, ns)
                append_jsonl(out_jsonl, result)
                ok_count += 1
                log_ok = f"[{idx}/{len(models)}] OK model={model_name}"
                if provider == "openrouter":
                    u = result.get("openrouter_usage")
                    if isinstance(u, dict):
                        suf = format_openrouter_usage_log_suffix(u)
                        if suf:
                            log_ok += f" | OpenRouter: {suf}"
                        compare_or_totals["prompt_tokens"] = int(
                            compare_or_totals["prompt_tokens"]
                        ) + int(u.get("prompt_tokens") or 0)
                        compare_or_totals["completion_tokens"] = int(
                            compare_or_totals["completion_tokens"]
                        ) + int(u.get("completion_tokens") or 0)
                        compare_or_totals["total_tokens"] = int(
                            compare_or_totals["total_tokens"]
                        ) + int(u.get("total_tokens") or 0)
                        c2 = u.get("cost_usd")
                        if c2 is not None:
                            compare_or_totals["cost_usd"] = float(compare_or_totals["cost_usd"]) + float(
                                c2
                            )
                            compare_or_totals["cost_known_n"] = int(
                                compare_or_totals["cost_known_n"]
                            ) + 1
                        compare_or_totals["n"] = int(compare_or_totals["n"]) + 1
                self._emit_log(log_ok + "\n")
            except Exception as exc:  # noqa: BLE001
                effective_model, launch_mode = resolve_effective_model_and_mode(ns)
                mode_norm = str(launch_mode or "").strip().lower()
                effective_provider = "openrouter" if mode_norm == "openrouter" else "ollama"
                effective_cloud = mode_norm in {"openrouter", "ollama cloud"}
                append_jsonl(
                    err_jsonl,
                    {
                        "file": str(target_file.name),
                        "error": str(exc),
                        "provider": effective_provider,
                        "cloud_mode": bool(effective_cloud),
                        "model": effective_model,
                    },
                )
                err_count += 1
                self._emit_log(f"[{idx}/{len(models)}] ERR model={model_name}: {exc}\n")

        if provider == "openrouter" and int(compare_or_totals.get("n") or 0) > 0:
            self._emit_log(
                format_openrouter_run_totals_footer(
                    compare_or_totals,
                    unit_label="успішних моделей",
                    scope_title="це порівняння",
                )
                + "\n"
            )

        cmd = _subprocess_script_argv(
            "report",
            [
                "--input",
                str(out_jsonl),
                "--errors-input",
                str(err_jsonl),
                "--summary-csv",
                str(summary_csv),
                "--findings-csv",
                str(findings_csv),
                "--table-html",
                str(table_html),
            ],
        )
        proc = subprocess.run(
            cmd,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.stdout:
            self._emit_log(proc.stdout.rstrip() + "\n")
        if proc.stderr:
            self._emit_log(proc.stderr.rstrip() + "\n")
        if proc.returncode != 0:
            return {
                "ok": False,
                "message": f"[COMPARE] Помилка генерації таблиць/HTML (code={proc.returncode}).",
                "path": str(table_html),
                "compare_dir": str(compare_dir),
            }

        msg = (
            f"[COMPARE] Готово. Успішно: {ok_count}, з помилками: {err_count}. "
            f"Таблиця: {table_html}"
        )
        self._emit_log(msg + "\n")
        return {"ok": True, "message": msg, "path": str(table_html), "compare_dir": str(compare_dir)}

    def open_file_path(self, path_str: str) -> dict:
        """Open a file by absolute/relative path."""
        p = _safe_user_path(str(path_str or "").strip())
        if p is None:
            return {"ok": False, "errors": ["Некоректний шлях."]}
        target = p.resolve()
        if not target.exists():
            return {"ok": False, "errors": [f"Файл не знайдено: {target}"], "path": str(target)}
        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
            return {"ok": True, "path": str(target)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "errors": [str(exc)], "path": str(target)}

    def open_report_table(self, input_dir: str, table_html: str, deep_mode: bool = False) -> dict:
        """Open report_table.html: the root one in normal mode, the session one in deep mode."""
        target: Path
        if bool(deep_mode):
            in_path = _resolve_input_dir_path(str(input_dir or ""))
            if in_path is not None and _is_under_deep_research(str(in_path)):
                target = Path(_deep_research_session_paths(in_path)["table_html"]).resolve()
            else:
                # input_dir may have diverged from the UI; try the path from the "Table (HTML)" field
                th_raw = str(table_html or "").strip()
                th_candidate = _safe_user_path(th_raw) if th_raw else None
                if th_candidate is not None:
                    try:
                        th_res = th_candidate.resolve()
                    except OSError:
                        th_res = th_candidate
                    if th_res.is_file() and _is_under_deep_research(str(th_res.parent)):
                        target = th_res
                        self._emit_log(
                            "[INFO] Відкриття звіту досьє: використано шлях з поля HTML "
                            "(input_dir не всередині deep_research).\n"
                        )
                    else:
                        return {
                            "ok": False,
                            "errors": [
                                "Режим досьє неактивний або каталог deep_research не визначено."
                            ],
                        }
                else:
                    return {
                        "ok": False,
                        "errors": [
                            "Режим досьє неактивний або каталог deep_research не визначено."
                        ],
                    }
        else:
            # In normal mode always open the root report_table.html.
            target = (BASE_DIR / DEFAULTS["table_html"]).resolve()

        if not target.exists():
            return {"ok": False, "errors": [f"Файл звіту не знайдено: {target}"], "path": str(target)}

        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
            return {"ok": True, "path": str(target)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "errors": [str(exc)], "path": str(target)}

    def get_usage_dashboard_stats(self, args: dict) -> str:
        """Aggregated stats for the info dashboard (JSON for React)."""
        from usage_dashboard import aggregate_dashboard

        try:
            jsonl_p, _, _ = _resolve_report_paths_for_extra(args or {})
            no_dedupe = bool((args or {}).get("no_dedupe"))
            usage_agg = _load_usage_aggregate_from_settings()
            payload = aggregate_dashboard(
                jsonl_p,
                no_dedupe=no_dedupe,
                usage_aggregate=usage_agg,
            )
            return json.dumps(payload, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
            )

    def get_dossier_chart_data(self, args: dict) -> str:
        """Time series for the dossier charts (deep research)."""
        from dossier_charts import build_dossier_chart_series

        try:
            a = args or {}
            input_dir_arg = str(a.get("input_dir", "") or "").strip()
            if not _is_under_deep_research(input_dir_arg):
                return json.dumps(
                    {"ok": False, "error": "Режим досьє: input_dir не в deep_research"},
                    ensure_ascii=False,
                )
            in_path = _resolve_input_dir_path(input_dir_arg)
            if in_path is None:
                return json.dumps(
                    {"ok": False, "error": "Невірний input_dir"},
                    ensure_ascii=False,
                )
            jsonl_p, err_jsonl_p, _ = _resolve_report_paths_for_extra(a)
            no_dedupe = bool(a.get("no_dedupe"))
            payload = build_dossier_chart_series(
                in_path,
                jsonl_p,
                base_dir=BASE_DIR,
                errors_jsonl=err_jsonl_p,
                no_dedupe=no_dedupe,
            )
            return json.dumps(payload, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
            )

    def _record_usage_session_after_pipeline(
        self,
        out_jsonl: str,
        jsonl_lines_before: int,
        pipeline_t0: float,
        args: dict,
    ) -> None:
        from usage_dashboard import append_usage_session

        j = Path(out_jsonl)
        if not j.is_absolute():
            j = BASE_DIR / j
        new_rows = _read_jsonl_lines_after(j.resolve(), jsonl_lines_before)
        wall_sec = max(0.0, time.monotonic() - pipeline_t0)
        critical_count = _count_critical_in_jsonl_rows(new_rows)
        model_label = _effective_model_short_from_args(args)
        finished_at = datetime.now(timezone.utc).isoformat()
        agg = _load_usage_aggregate_from_settings()
        updated = append_usage_session(
            agg,
            finished_at_utc=finished_at,
            wall_sec=wall_sec,
            declarations_ok=len(new_rows),
            critical_count=critical_count,
            model_label=model_label,
        )
        try:
            _save_usage_aggregate_to_settings(updated)
        except OSError as exc:
            self._emit_log(f"[WARN] Не вдалось зберегти usage_aggregate: {exc}\n")

    def _append_dossier_charts_after_report(self, args: dict, table_html_path: Path) -> None:
        """Add interactive charts to report_table.html for deep research."""
        input_dir_arg = str(args.get("input_dir", "") or "").strip()
        if not _is_under_deep_research(input_dir_arg):
            return
        in_path = _resolve_input_dir_path(input_dir_arg)
        if in_path is None:
            return
        th = table_html_path
        if not th.is_absolute():
            th = (BASE_DIR / th).resolve()
        else:
            th = th.resolve()
        jsonl_p, err_p, _ = _resolve_report_paths_for_extra(args)
        from dossier_charts_html import append_dossier_charts_to_html

        self._emit_log("\n=== Графіки досьє (HTML) ===\n")
        ok, msg = append_dossier_charts_to_html(
            th,
            input_dir=in_path,
            output_jsonl=jsonl_p,
            errors_jsonl=err_p,
            base_dir=BASE_DIR,
            no_dedupe=bool(args.get("no_dedupe")),
        )
        self._emit_log(msg + "\n")
        if not ok:
            self._emit_log("[INFO] HTML-звіт без блоку графіків.\n")

    def run_extra_report(self, args: dict) -> str:
        """Regenerate the CSV and the single HTML report (report_table.html) from the current JSONL."""
        coerced, path_warnings = _coerce_pipeline_paths_from_args(args)
        args.update(coerced)
        for msg in path_warnings:
            self._emit_log(f"[WARN] {msg}\n")
        jsonl_p, err_p, table_p = _resolve_report_paths_for_extra(args)
        if not jsonl_p.exists():
            self._emit_log(f"[REPORT] Файл результатів не знайдено: {jsonl_p}\n")
            return json.dumps(
                {"ok": False, "path": "", "errors": [f"Не знайдено: {jsonl_p}"]},
                ensure_ascii=False,
            )
        summary_p, findings_p = _resolve_report_csv_paths(args, table_p)
        table_p.parent.mkdir(parents=True, exist_ok=True)
        cmd = _subprocess_script_argv(
            "report",
            [
                "--input",
                str(jsonl_p),
                "--errors-input",
                str(err_p),
                "--summary-csv",
                str(summary_p),
                "--findings-csv",
                str(findings_p),
                "--table-html",
                str(table_p),
            ],
        )
        if bool(args.get("no_dedupe")):
            cmd.append("--no-dedupe")
        if _is_under_deep_research(str(args.get("input_dir", "") or "")):
            cmd.append("--dossier-chronological")
        self._emit_log("\n=== [REPORT] Перегенерація звітів (HTML + CSV) ===\n")
        code = self._run_subprocess(cmd)
        if code != 0:
            self._emit_log(f"[REPORT] report.py завершився з кодом {code}\n")
            return json.dumps(
                {
                    "ok": False,
                    "path": str(table_p),
                    "errors": [f"report.py exit code {code}"],
                },
                ensure_ascii=False,
            )
        self._emit_log(f"[REPORT] Готово: {table_p}\n")
        self._append_dossier_charts_after_report(args, table_p)
        return json.dumps(
            {"ok": True, "path": str(table_p), "message": str(table_p)},
            ensure_ascii=False,
        )

    def open_extra_report(self, args: dict) -> dict:
        """Open the main HTML report (the same as report_table.html)."""
        _jsonl_p, _err_p, table_p = _resolve_report_paths_for_extra(args)
        target = table_p
        if not target.exists():
            return {
                "ok": False,
                "errors": [f"Файл не знайдено: {target}"],
                "path": str(target),
            }
        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
            return {"ok": True, "path": str(target)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "errors": [str(exc)], "path": str(target)}

    def open_declarations_folder(self, input_dir_arg: str) -> dict:
        """Open the declarations directory in the system file manager."""
        target = _resolve_input_dir_path(str(input_dir_arg or ""))
        if target is None:
            target = (BASE_DIR / DEFAULTS["input_dir"]).resolve()

        if not target.exists() or not target.is_dir():
            return {"ok": False, "errors": [f"Папку декларацій не знайдено: {target}"], "path": str(target)}

        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
            return {"ok": True, "path": str(target)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "errors": [str(exc)], "path": str(target)}

    # ── Notification ──────────────────────────────────────────

    @staticmethod
    def _ps_single_quoted_literal(s: str) -> str:
        """String for PowerShell in single quotes: ' → ''."""
        return str(s or "").replace("'", "''")

    def _notify(self, title: str, body: str) -> None:
        """
        Windows tray notification (WinForms NotifyIcon balloon / Action Center toast).

        Often "doesn't arrive" if:
        - not Windows;
        - WinForms without STA (fixed: -STA for powershell.exe);
        - disabled for PowerShell / focus assist under "Settings → System → Notifications";
        - Windows 10/11 shows it only in Action Center, not as a banner (depends on policy).
        """
        if sys.platform != "win32":
            return
        try:
            # BalloonTipText is limited to ~256 chars; line breaks break PS without escaping.
            safe_title = (title or "ДеклараторLM").strip()[:128]
            safe_body = " ".join((body or "").replace("\r", " ").split())[:240]
            t = self._ps_single_quoted_literal(safe_title)
            b = self._ps_single_quoted_literal(safe_body)
            tip_ms = 8000
            sleep_s = max(9, (tip_ms // 1000) + 1)
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms\n"
                "$n = New-Object System.Windows.Forms.NotifyIcon\n"
                "$n.Icon = [System.Drawing.SystemIcons]::Information\n"
                f"$n.BalloonTipTitle = '{t}'\n"
                f"$n.BalloonTipText = '{b}'\n"
                "$n.Visible = $True\n"
                f"$n.ShowBalloonTip({tip_ms})\n"
                f"Start-Sleep {sleep_s}; $n.Dispose()\n"
            )
            encoded = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
            ps_candidates = [
                str(
                    Path(os.environ.get("SystemRoot", r"C:\Windows"))
                    / "System32"
                    / "WindowsPowerShell"
                    / "v1.0"
                    / "powershell.exe"
                ),
                "powershell.exe",
                "powershell",
                "pwsh.exe",
                "pwsh",
            ]
            for exe in ps_candidates:
                exe_lower = Path(exe).name.lower()
                use_sta = exe_lower in ("powershell.exe", "powershell")
                args = [exe, "-NoProfile", "-NonInteractive"]
                if use_sta:
                    args.append("-STA")
                args.extend(["-WindowStyle", "Hidden", "-EncodedCommand", encoded])
                try:
                    subprocess.Popen(
                        args,
                        creationflags=0x08000000,  # CREATE_NO_WINDOW
                    )
                    return
                except OSError:
                    continue
        except Exception:
            pass

        # Fallback: Web Notification (only if the user already granted permission in WebView2).
        try:
            w = self._window
            if w is None:
                return
            payload = json.dumps(
                {"title": str(title or "ДеклараторLM")[:128], "body": str(body or "")[:512]},
                ensure_ascii=False,
            )
            w.evaluate_js(
                "(function(p){try{if(!window.Notification||Notification.permission!=='granted')"
                "return;new Notification(p.title,{body:p.body});}catch(e){}})("
                + payload
                + ");"
            )
        except Exception:
            pass

    # ── Pipeline ──────────────────────────────────────────────

    # ── System metrics ────────────────────────────────────────

    def _cpu_temp_c(self) -> float | None:
        # Best-effort on Windows (often unavailable on many systems/BIOS setups).
        if sys.platform != "win32":
            if psutil and hasattr(psutil, "sensors_temperatures"):
                try:
                    data = psutil.sensors_temperatures()  # type: ignore[attr-defined]
                    for entries in data.values():
                        if entries:
                            cur = getattr(entries[0], "current", None)
                            if isinstance(cur, (int, float)):
                                return float(cur)
                except Exception:  # noqa: BLE001
                    return None
            return None
        try:
            res = subprocess.run(
                [
                    "wmic",
                    "/namespace:\\\\root\\wmi",
                    "PATH",
                    "MSAcpi_ThermalZoneTemperature",
                    "get",
                    "CurrentTemperature",
                    "/value",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            for line in (res.stdout or "").splitlines():
                line = line.strip()
                if not line.startswith("CurrentTemperature="):
                    continue
                raw = line.split("=", 1)[1].strip()
                if raw.isdigit():
                    kelvin_tenths = int(raw)
                    return round((kelvin_tenths / 10.0) - 273.15, 1)
        except Exception:  # noqa: BLE001
            return None
        return None

    def _nvidia_metrics(self) -> dict:
        out = {"gpu_util_percent": None, "gpu_mem_used_mb": None, "gpu_temp_c": None}
        try:
            res = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode != 0:
                return out
            first = (res.stdout or "").strip().splitlines()
            if not first:
                return out
            parts = [p.strip() for p in first[0].split(",")]
            if len(parts) >= 3:
                out["gpu_util_percent"] = float(parts[0]) if parts[0] else None
                out["gpu_mem_used_mb"] = float(parts[1]) if parts[1] else None
                out["gpu_temp_c"] = float(parts[2]) if parts[2] else None
        except Exception:  # noqa: BLE001
            return out
        return out

    def get_system_metrics(self) -> dict:
        now = time.monotonic()
        if self._metrics_cache and (now - self._metrics_cache_ts) < 1.5:
            return self._metrics_cache

        metrics = {
            "timestamp": int(time.time()),
            "app_ram_mb": None,
            "ollama_ram_mb": None,
            "ollama_cpu_percent": None,
            "cpu_percent": None,
            "cpu_temp_c": None,
            "gpu_util_percent": None,
            "gpu_mem_used_mb": None,
            "gpu_temp_c": None,
        }

        if psutil:
            try:
                proc = psutil.Process(os.getpid())
                metrics["app_ram_mb"] = round(proc.memory_info().rss / (1024 * 1024), 1)
            except Exception:  # noqa: BLE001
                pass
            try:
                metrics["cpu_percent"] = float(psutil.cpu_percent(interval=None))
            except Exception:  # noqa: BLE001
                pass
            try:
                ollama_ram = 0.0
                ollama_cpu = 0.0
                matched = 0
                for p in psutil.process_iter(["name", "exe", "memory_info"]):
                    name = str((p.info.get("name") or "")).lower()
                    exe = str((p.info.get("exe") or "")).lower()
                    if "ollama" not in name and "ollama" not in exe:
                        continue
                    matched += 1
                    try:
                        ollama_ram += p.memory_info().rss / (1024 * 1024)
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        ollama_cpu += p.cpu_percent(interval=None)
                    except Exception:  # noqa: BLE001
                        pass
                if matched:
                    metrics["ollama_ram_mb"] = round(ollama_ram, 1)
                    metrics["ollama_cpu_percent"] = round(ollama_cpu, 1)
                else:
                    metrics["ollama_ram_mb"] = 0.0
                    metrics["ollama_cpu_percent"] = 0.0
            except Exception:  # noqa: BLE001
                pass

        metrics["cpu_temp_c"] = self._cpu_temp_c()
        metrics.update(self._nvidia_metrics())

        self._metrics_cache = metrics
        self._metrics_cache_ts = now
        return metrics

    def control_pipeline(self, command: str) -> None:
        try:
            _atomic_write_text(
                CONTROL_FILE,
                json.dumps({"command": command}),
            )
        except OSError:
            pass

    def pipeline_error_action(self, payload: dict) -> dict:
        """UI: retry / raise_limits / ignore for an error card during review."""
        if not isinstance(payload, dict):
            return {"ok": False, "error": "invalid_payload"}
        file_name = str(payload.get("file", "") or "").strip()
        action = str(payload.get("action", "") or "").strip().lower()
        if not file_name or action not in {"retry", "raise_limits", "ignore"}:
            return {"ok": False, "error": "missing_file_or_action"}
        body: dict = {
            "command": "error_action",
            "file": file_name,
            "action": action,
        }
        if payload.get("max_chars") is not None:
            try:
                body["max_chars"] = int(payload["max_chars"])
            except (TypeError, ValueError):
                pass
        if payload.get("num_predict") is not None:
            try:
                body["num_predict"] = int(payload["num_predict"])
            except (TypeError, ValueError):
                pass
        try:
            with self._lock:
                _atomic_write_text(
                    CONTROL_FILE,
                    json.dumps(body, ensure_ascii=False),
                )
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def run_pipeline(self, args: dict) -> str:
        # Reject overlapping invocations: without this, two concurrent js_api
        # calls would race on `_proc` and CONTROL_FILE, leaking subprocesses
        # and confusing the stop/pause control channel.
        with self._lock:
            if self._is_running:
                self._emit_log(
                    "[WARN] Пайплайн уже виконується. Запит ігноровано.\n"
                )
                return "busy"
            self._is_running = True
        try:
            return self._run_pipeline_impl(args)
        finally:
            with self._lock:
                self._is_running = False

    def _run_pipeline_impl(self, args: dict) -> str:
        coerced_paths, path_warnings = _coerce_pipeline_paths_from_args(args)
        args.update(coerced_paths)
        self.save_settings(args)
        try:
            _atomic_write_text(CONTROL_FILE, '{"command":"run"}')
        except OSError:
            pass

        input_dir_arg = str(args.get("input_dir", "") or "").strip()
        under_deep_research = _is_under_deep_research(input_dir_arg)
        out_jsonl = coerced_paths["output_jsonl"]
        err_jsonl = coerced_paths["errors_jsonl"]
        summary_csv = coerced_paths["summary_csv"]
        findings_csv = coerced_paths["findings_csv"]
        table_html = coerced_paths["table_html"]

        for msg in path_warnings:
            self._emit_log(f"[WARN] {msg}\n")

        if under_deep_research:
            self._emit_log(
                "[DEEP] Окремі JSONL/CSV/HTML для цього дослідження (без старих записів з кореня):\n"
                f"  аналіз: {out_jsonl}\n"
                f"  HTML:  {table_html}\n"
            )
            if args.get("move_processed"):
                self._emit_log(
                    "[DEEP] Переміщення у папку «оброблені» вимкнено — JSON декларацій лишаються в каталозі дослідження.\n"
                )

        def _count_existing_lines(path_str: str) -> int:
            p = Path(path_str)
            if not p.is_absolute():
                p = BASE_DIR / p
            if not p.exists():
                return 0
            try:
                with p.open("r", encoding="utf-8", errors="replace") as fh:
                    return sum(1 for _ in fh)
            except OSError:
                return 0

        err_lines_before = _count_existing_lines(err_jsonl)
        jsonl_lines_before = _count_existing_lines(out_jsonl)
        pipeline_t0 = time.monotonic()

        main_cmd = _subprocess_script_argv(
            "main",
            [
                "--input-dir", args.get("input_dir", ""),
                "--output", out_jsonl,
                "--errors-output", err_jsonl,
                "--model", args.get("model", "llama3.1"),
                "--host", args.get("host", "http://127.0.0.1:11434"),
                "--timeout", str(args.get("timeout", 600)),
                "--max-files", str(args.get("max_files", 0)),
                "--max-chars", str(args.get("max_chars", 64000)),
                "--retries", str(args.get("retries", 2)),
                "--retry-delay", str(args.get("retry_delay", 5)),
                "--num-predict", str(args.get("num_predict", 16000)),
                "--control-file", str(CONTROL_FILE),
                "--on-limit", "fail-run",
            ],
        )
        try:
            pconc = int(args.get("pipeline_max_concurrent", 1) or 1)
        except (TypeError, ValueError):
            pconc = 1
        pconc = max(1, min(8, pconc))
        if pconc > 1:
            main_cmd.extend(["--max-concurrent-declarations", str(pconc)])
        # Compact snapshots in UI are owned by debug-only "audit mode".
        # Keep normal runs isolated from debug diagnostics.
        main_cmd.append("--no-save-compact-declarations")
        sel_raw = args.get("selected_files") or []
        if isinstance(sel_raw, list):
            sel_parts = [str(x).strip() for x in sel_raw if str(x).strip()]
        elif isinstance(sel_raw, str):
            sel_parts = [s.strip() for s in sel_raw.split(",") if s.strip()]
        else:
            sel_parts = []
        if sel_parts:
            main_cmd.extend(["--selected-files", ",".join(sel_parts)])
        else:
            so = str(args.get("sort_order", "alpha") or "alpha").strip().lower()
            if so and so != "alpha":
                main_cmd.extend(["--sort-order", so])
        if args.get("cloud_mode"):
            cloud_provider = str(args.get("cloud_provider", "ollama") or "ollama").lower()
            if cloud_provider == "openrouter":
# Alternate path. --cloud-mode remains UX/logging only;
# the real router in main.py is --provider=openrouter.
                main_cmd.extend(
                    [
                        "--cloud-mode",
                        "--provider", "openrouter",
                        "--openrouter-host", args.get("openrouter_host", "https://openrouter.ai/api/v1"),
                        "--openrouter-model", args.get("openrouter_model", ""),
                    ]
                )
            else:
                main_cmd.extend(
                    [
                        "--cloud-mode",
                        "--host", args.get("cloud_host", "https://ollama.com"),
                        "--model", args.get("cloud_model", ""),
                        "--api-key", args.get("cloud_api_key", ""),
                    ]
                )
        if args.get("move_processed") and not under_deep_research:
            proc_dir = args.get("processed_dir", "")
            if proc_dir:
                main_cmd.extend(["--processed-dir", proc_dir])
        if REASONING_DEBUG:
            main_cmd.append("--reasoning-debug")
            self._emit_log("[INFO] Reasoning debug mode ON (webview session).\n")
        if bool(args.get("debug_mode_ui")) and bool(args.get("audit_mode_enabled")):
            main_cmd.extend(
                [
                    "--audit-mode",
                    "--audit-mode-dir",
                    str(args.get("audit_mode_dir", "audit")),
                ]
            )
            capture_flags = [
                ("audit_capture_raw_declaration", "--audit-capture-raw-declaration"),
                ("audit_capture_compact_declaration", "--audit-capture-compact-declaration"),
                ("audit_capture_request_payload", "--audit-capture-request-payload"),
                ("audit_capture_response_raw", "--audit-capture-response-raw"),
                ("audit_capture_response_parsed", "--audit-capture-response-parsed"),
                ("audit_capture_normalized_analysis", "--audit-capture-normalized-analysis"),
                ("audit_capture_attempt_meta", "--audit-capture-attempt-meta"),
            ]
            for key, flag in capture_flags:
                if bool(args.get(key)):
                    main_cmd.append(flag)
            self._emit_log(
                f"[DEBUG] Audit mode ON. Корінь артефактів: {args.get('audit_mode_dir', 'audit')}\n"
            )

        if bool(args.get("compact_legacy_payload")):
            main_cmd.append("--compact-legacy-payload")
            self._emit_log(
                "[INFO] Режим компактизації: Детальніше (all_nonempty_steps_payload у запиті).\n"
            )

        prompt_ov_path = self._write_session_prompt_overrides(args)
        if prompt_ov_path:
            main_cmd.extend(["--prompt-overrides", prompt_ov_path])
            self._emit_log(
                "[DEBUG] Активні перевизначення промптів сесії (не змінюють код проєкту).\n"
            )

        self._emit_log("\n=== Запуск аналізу ===\n")
        sub_env: dict[str, str] = {}
        if args.get("cloud_mode"):
            cloud_provider = str(args.get("cloud_provider", "ollama") or "ollama").lower()
            if cloud_provider == "openrouter":
                or_key = str(args.get("openrouter_api_key", "") or "").strip()
                if or_key:
                    sub_env["DECLARATOR_OPENROUTER_API_KEY"] = or_key
        code = self._run_subprocess(main_cmd, extra_env=sub_env or None)

        if code != 0:
            self._emit_log(f"\n[ПОМИЛКА] main.py завершився з кодом {code}\n")
            self._notify("ДеклараторLM", "Аналіз завершився з помилкою")
            return f"error:main:{code}"

        self._record_usage_session_after_pipeline(
            out_jsonl,
            jsonl_lines_before,
            pipeline_t0,
            args,
        )

        err_lines_after = _count_existing_lines(err_jsonl)
        had_partial_errors = err_lines_after > err_lines_before

        if args.get("make_report"):
            self._emit_log("\n=== Формування звітів ===\n")
            report_cmd = _subprocess_script_argv(
                "report",
                [
                    "--input", out_jsonl,
                    "--errors-input", err_jsonl,
                    "--summary-csv", summary_csv,
                    "--findings-csv", findings_csv,
                    "--table-html", table_html,
                ],
            )
            if args.get("no_dedupe"):
                report_cmd.append("--no-dedupe")
            if under_deep_research:
                report_cmd.append("--dossier-chronological")
            rcode = self._run_subprocess(report_cmd)
            if rcode != 0:
                self._emit_log(f"\n[ПОМИЛКА] report.py завершився з кодом {rcode}\n")
                self._notify("ДеклараторLM", "Формування звітів не вдалось")
                return f"error:report:{rcode}"

            if under_deep_research:
                th = Path(table_html)
                if not th.is_absolute():
                    th = BASE_DIR / th
                self._append_dossier_charts_after_report(args, th)

                from dossier_html_summary import run_dossier_table_summary_append

                cloud_provider = str(args.get("cloud_provider", "ollama") or "ollama").lower()
                if args.get("cloud_mode") and cloud_provider == "openrouter":
                    dr_provider = "openrouter"
                    dr_model = (args.get("openrouter_model") or "").strip() or "meta-llama/llama-3.3-70b-instruct"
                    dr_host = args.get("openrouter_host", "https://openrouter.ai/api/v1")
                    dr_key = str(args.get("openrouter_api_key", "") or "")
                    dr_cloud = True
                elif args.get("cloud_mode"):
                    dr_provider = "ollama"
                    dr_model = (args.get("cloud_model") or "").strip() or args.get(
                        "model", "llama3.1"
                    )
                    dr_host = args.get("cloud_host", "https://ollama.com")
                    dr_key = str(args.get("cloud_api_key", "") or "")
                    dr_cloud = True
                else:
                    dr_provider = "ollama"
                    dr_model = args.get("model", "llama3.1")
                    dr_host = args.get("host", "http://127.0.0.1:11434")
                    dr_key = ""
                    dr_cloud = False
                self._emit_log("\n=== Підсумок досьє (LLM по HTML-звіту) ===\n")
                dossier_po = self._load_session_prompt_overrides_dict()
                try:
                    dr_np = int(args.get("num_predict", -1))
                except (TypeError, ValueError):
                    dr_np = -1
                ok_dr, dr_msg = run_dossier_table_summary_append(
                    table_html_path=th,
                    model=str(dr_model),
                    host=str(dr_host),
                    timeout_sec=int(args.get("timeout", 600)),
                    num_predict=dr_np,
                    api_key=dr_key,
                    cloud_mode=dr_cloud,
                    prompt_overrides=dossier_po,
                    provider=dr_provider,
                )
                self._emit_log(dr_msg + "\n")
                if not ok_dr:
                    self._emit_log(
                        "[INFO] Табличний звіт лишається без змін; аналіз основного пайплайну успішний.\n"
                    )

        if had_partial_errors:
            self._emit_log(
                "\n[WARN] Пайплайн завершено з помилками в частині файлів. "
                "Перевірте analysis_errors.jsonl.\n"
            )
            self._notify(
                "ДеклараторLM",
                "Пайплайн завершено з помилками (частина файлів не оброблена).",
            )
            return "partial"
        self._emit_log("\n[OK] Пайплайн завершено успішно.\n")
        self._notify("ДеклараторLM", "Пайплайн завершено успішно!")
        return "ok"

    def _run_subprocess(
        self, cmd: list[str], *, extra_env: dict[str, str] | None = None
    ) -> int:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        if extra_env:
            for key, value in extra_env.items():
                if value:
                    env[key] = value
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert self._proc.stdout is not None
        line_queue: queue.Queue[str | None] = queue.Queue()

        def _stdout_reader() -> None:
            try:
                for line in self._proc.stdout:
                    line_queue.put(line)
            finally:
                line_queue.put(None)

        reader = threading.Thread(target=_stdout_reader, daemon=True)
        reader.start()
        while True:
            try:
                line = line_queue.get(timeout=0.25)
            except queue.Empty:
                if not reader.is_alive() and line_queue.empty():
                    break
                continue
            if line is None:
                while True:
                    try:
                        extra = line_queue.get_nowait()
                    except queue.Empty:
                        break
                    if extra is not None:
                        self._emit_log(extra)
                break
            self._emit_log(line)
        reader.join(timeout=30)
        code = self._proc.wait()
        self._proc = None
        return code

    # --- DEEP_RESEARCH_BEGIN
    def deep_research_download(self, user_declarant_id: int) -> dict:
        """Download all NAZK declarations for a subject into deep_research/<lastname>_<id>."""
        try:
            uid = int(user_declarant_id)
        except (TypeError, ValueError):
            return {"ok": False, "errors": ["Некоректний user_declarant_id."]}
        try:
            from deep_research_bridge import run_deep_research_download

            return run_deep_research_download(
                base_dir=BASE_DIR,
                user_declarant_id=uid,
                log_line=self._emit_log,
            )
        except Exception as exc:  # noqa: BLE001
            self._emit_log(f"[DEEP] Помилка: {exc}\n")
            return {"ok": False, "errors": [str(exc)]}

    def deep_research_download_one(self, declaration_id: str, target_input_dir: str) -> dict:
        """Download one declaration by declaration_id into the declarations folder (same as bulk NAZK parse)."""
        decl_id = str(declaration_id or "").strip()
        target_dir = str(target_input_dir or "").strip()
        if not decl_id:
            return {"ok": False, "errors": ["Некоректний declaration_id."]}
        if not target_dir:
            return {"ok": False, "errors": ["Не вказано папку декларацій."]}
        try:
            from deep_research_bridge import run_deep_research_download_one

            return run_deep_research_download_one(
                base_dir=BASE_DIR,
                declaration_id=decl_id,
                target_input_dir=target_dir,
                log_line=self._emit_log,
            )
        except Exception as exc:  # noqa: BLE001
            self._emit_log(f"[NAZK] Помилка: {exc}\n")
            return {"ok": False, "errors": [str(exc)]}

    def nazk_download_by_year(
        self,
        declaration_year: int,
        limit: int,
        target_dir: str,
        search_query: str = "",
        declaration_type: int = 0,
        document_type: int = 0,
    ) -> dict:
        """Download up to limit declarations using open NAZK API filters.
        declaration_year=-1 — do not filter by year (search only, if set).
        search_query — API query param (from 3 chars); may combine with year.
        declaration_type — 1–4 or 0 (all); document_type — 1–3 or 0 (all).
        """
        try:
            y = int(declaration_year)
            lim = int(limit)
            decl_t = int(declaration_type or 0)
            doc_t = int(document_type or 0)
        except (TypeError, ValueError):
            return {"ok": False, "errors": ["Некоректні рік або кількість."]}
        try:
            from deep_research_bridge import run_nazk_download_by_year

            year_arg = None if y == -1 else y
            return run_nazk_download_by_year(
                base_dir=BASE_DIR,
                declaration_year=year_arg,
                search_query=str(search_query or ""),
                limit=lim,
                target_input_dir=str(target_dir or "").strip(),
                log_line=self._emit_log,
                declaration_type=decl_t if decl_t > 0 else None,
                document_type=doc_t if doc_t > 0 else None,
            )
        except Exception as exc:  # noqa: BLE001
            self._emit_log(f"[NAZK] Помилка: {exc}\n")
            return {"ok": False, "errors": [str(exc)]}

    def deep_research_list_folders(self) -> dict:
        """deep_research subdirectories for picking without an API download."""
        try:
            from deep_research_bridge import list_deep_research_folders

            return list_deep_research_folders(base_dir=BASE_DIR)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "errors": [str(exc)], "folders": []}

    def deep_research_apply_folder(self, folder_name: str) -> dict:
        """Point input_dir at an existing deep_research folder (no NAZK download)."""
        try:
            from deep_research_bridge import apply_deep_research_folder

            return apply_deep_research_folder(
                base_dir=BASE_DIR,
                folder_name=str(folder_name or ""),
                log_line=self._emit_log,
            )
        except Exception as exc:  # noqa: BLE001
            self._emit_log(f"[DEEP] Помилка: {exc}\n")
            return {"ok": False, "errors": [str(exc)]}

    # --- DEEP_RESEARCH_END

    def shutdown(self) -> None:
        self._remove_session_prompt_overrides()
        if self._proc and self._proc.poll() is None:
            self.control_pipeline("stop")
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass


def _on_loaded(window: webview.Window) -> None:
    title = "DeclaratorLM" if _ui_lang() == "en" else "ДеклараторLM"
    window.evaluate_js(f"document.title = {json.dumps(title)}")


def _ui_lang() -> str:
    raw = (
        os.environ.get("DECLARATOR_UI_LANG")
        or os.environ.get("DECLARATOR_LANG")
        or ""
    ).strip().lower()
    if raw in ("en", "eng", "english"):
        return "en"
    if "--lang" in sys.argv:
        try:
            i = sys.argv.index("--lang")
            val = str(sys.argv[i + 1]).strip().lower()
            if val in ("en", "eng", "english"):
                return "en"
        except (IndexError, ValueError):
            pass
    if "--lang=en" in sys.argv or "--lang=english" in sys.argv:
        return "en"
    return "uk"


def _frontend_index_path() -> Path:
    if _ui_lang() == "en":
        en_path = DIST_DIR / "index.en.html"
        if en_path.exists():
            return en_path
    return DIST_DIR / "index.html"


def _webview_gui_choice() -> str | None:
    """pywebview backend: on Windows default to Edge/WebView2 (more stable than Qt in builds).

    Force Qt (heavy stack, frequent GPU/DirectComposition issues): set DECLARATOR_WEBVIEW_GUI=qt
    """
    raw = os.environ.get("DECLARATOR_WEBVIEW_GUI", "").strip().lower()
    allowed = ("qt", "edgechromium", "mshtml", "cef", "gtk")
    if raw in allowed:
        return raw
    if sys.platform == "win32":
        return "edgechromium"
    return None


def main() -> None:
    api = Api()
    index_path = _frontend_index_path()
    if not index_path.exists():
        print(f"Frontend not built. Expected: {index_path}")
        print("Run:  cd declarator-lm && npm run build")
        sys.exit(1)

    ui_lang = _ui_lang()
    window_title = "DeclaratorLM" if ui_lang == "en" else "ДеклараторLM"
    window = webview.create_window(
        title=window_title,
        url=str(index_path),
        js_api=api,
        width=1180,
        height=820,
        min_size=(960, 680),
    )
    api.set_window(window)
    window.events.loaded += _on_loaded
    window.events.closing += lambda: api.shutdown()
    gui = _webview_gui_choice()
    if gui:
        print(f"[INFO] pywebview GUI: {gui}")
    print(f"[INFO] UI language: {ui_lang} ({index_path.name})")
    webview.start(gui=gui)


if __name__ == "__main__":
    main()
