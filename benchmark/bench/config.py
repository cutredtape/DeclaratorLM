"""Benchmark configuration models and path helpers."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


BENCHMARK_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCHMARK_ROOT.parent
CORPUS_DIR = BENCHMARK_ROOT / "corpus"
PROMPTS_DIR = BENCHMARK_ROOT / "prompts"
RUNS_DIR = BENCHMARK_ROOT / "runs"

# Safe filesystem slug: keep alnum, dash, underscore, dot; collapse the rest.
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify(value: str, *, max_len: int = 64) -> str:
    s = str(value or "").strip()
    s = s.replace("/", "_").replace("\\", "_").replace(":", "_")
    s = _SLUG_RE.sub("_", s).strip("._-")
    if not s:
        s = "unnamed"
    return s[:max_len]


def cell_key(model_id: str, prompt_name: str) -> str:
    return f"{slugify(model_id)}__{slugify(prompt_name)}"


@dataclass
class AuditCaptureFlags:
    raw_declaration: bool = True
    compact_declaration: bool = True
    request_payload: bool = True
    response_raw: bool = True
    response_parsed: bool = True
    normalized_analysis: bool = True
    attempt_meta: bool = True

    def as_cli_kwargs(self) -> Dict[str, bool]:
        return {
            "audit_capture_raw_declaration": self.raw_declaration,
            "audit_capture_compact_declaration": self.compact_declaration,
            "audit_capture_request_payload": self.request_payload,
            "audit_capture_response_raw": self.response_raw,
            "audit_capture_response_parsed": self.response_parsed,
            "audit_capture_normalized_analysis": self.normalized_analysis,
            "audit_capture_attempt_meta": self.attempt_meta,
        }

    def any_enabled(self) -> bool:
        return any(asdict(self).values())


@dataclass
class ModelSpec:
    model_id: str
    provider: str = "ollama"  # ollama | openrouter
    host: str = "http://127.0.0.1:11434"
    api_key: str = ""
    cloud_mode: bool = False

    def launch_mode(self) -> str:
        if self.provider == "openrouter":
            return "openrouter"
        if self.cloud_mode:
            return "ollama cloud"
        return "local"


@dataclass
class PromptSpec:
    name: str
    path: Path
    system_prompt: str
    user_prompt_template: str

    def as_overrides(self) -> Dict[str, str]:
        return {
            "pipeline_system_prompt": self.system_prompt,
            "pipeline_user_prompt_template": self.user_prompt_template,
            "pipeline_prompt_name": self.name,
        }


@dataclass
class BenchConfig:
    label: str = "bench"
    models: List[ModelSpec] = field(default_factory=list)
    prompts: List[PromptSpec] = field(default_factory=list)
    corpus_dir: Path = CORPUS_DIR
    max_chars: int = 64000
    timeout: int = 600
    retries: int = 2
    retry_delay: float = 5.0
    num_predict: int = 16000
    compact_legacy_payload: bool = False
    max_concurrent: int = 1  # only meaningful for openrouter
    circuit_breaker_failures: int = 5
    audit_enabled: bool = True
    audit_flags: AuditCaptureFlags = field(default_factory=AuditCaptureFlags)
    dry_run: bool = False
    max_files: int = 0  # 0 = all
    skip_smoke: bool = False
    skip_confirm: bool = False

    def cells(self) -> List[tuple[ModelSpec, PromptSpec]]:
        return [(m, p) for m in self.models for p in self.prompts]

    def to_manifest_dict(self) -> Dict[str, Any]:
        """Serializable snapshot without secrets."""
        return {
            "label": self.label,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "dry_run": self.dry_run,
            "max_chars": self.max_chars,
            "timeout": self.timeout,
            "retries": self.retries,
            "retry_delay": self.retry_delay,
            "num_predict": self.num_predict,
            "compact_legacy_payload": self.compact_legacy_payload,
            "max_concurrent": self.max_concurrent,
            "circuit_breaker_failures": self.circuit_breaker_failures,
            "audit_enabled": self.audit_enabled,
            "audit_flags": asdict(self.audit_flags),
            "max_files": self.max_files,
            "corpus_dir": str(self.corpus_dir),
            "models": [
                {
                    "model_id": m.model_id,
                    "provider": m.provider,
                    "host": m.host,
                    "cloud_mode": m.cloud_mode,
                    "launch_mode": m.launch_mode(),
                    "has_api_key": bool(str(m.api_key or "").strip()),
                }
                for m in self.models
            ],
            "prompts": [
                {
                    "name": p.name,
                    "path": str(p.path),
                    "system_chars": len(p.system_prompt),
                    "user_chars": len(p.user_prompt_template),
                }
                for p in self.prompts
            ],
        }


def make_run_dir(label: str, *, now: Optional[datetime] = None) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / f"{ts}_{slugify(label, max_len=40)}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "reports").mkdir()
    (run_dir / "artifacts").mkdir()
    (run_dir / "matrix").mkdir()
    return run_dir


def cell_report_dir(run_dir: Path, model_id: str, prompt_name: str) -> Path:
    d = run_dir / "reports" / cell_key(model_id, prompt_name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def cell_artifacts_dir(run_dir: Path, model_id: str, prompt_name: str) -> Path:
    d = run_dir / "artifacts" / cell_key(model_id, prompt_name)
    d.mkdir(parents=True, exist_ok=True)
    return d
