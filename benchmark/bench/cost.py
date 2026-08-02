"""Local (free) payload sizing and OpenRouter cost estimates before any real run."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import BenchConfig, ModelSpec, PROJECT_ROOT, PromptSpec

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Rough chars→tokens for mixed UA/JSON (conservative for cost upper-bound).
CHARS_PER_TOKEN = 2.5
# Assumed completion tokens per declaration when provider has no better signal.
DEFAULT_COMPLETION_TOKENS = 2500


@dataclass
class FilePayloadSize:
    name: str
    compact_chars: int
    over_limit: bool = False


@dataclass
class ModelCostEstimate:
    model_id: str
    provider: str
    prompt_tokens_est: int = 0
    completion_tokens_est: int = 0
    cost_usd: Optional[float] = None
    pricing_known: bool = False
    note: str = ""


@dataclass
class CostEstimate:
    file_sizes: List[FilePayloadSize] = field(default_factory=list)
    mean_compact_chars: float = 0.0
    max_compact_chars: int = 0
    over_limit_count: int = 0
    instruction_chars: int = 0
    per_model: List[ModelCostEstimate] = field(default_factory=list)
    total_cost_usd: Optional[float] = None
    declaration_count: int = 0
    cell_count: int = 0

    def summary_lines(self) -> List[str]:
        lines = [
            f"Декларацій: {self.declaration_count}",
            f"Клітинок (модель x промпт): {self.cell_count}",
            f"Середній розмір payload: {self.mean_compact_chars:.0f} симв.",
            f"Максимальний розмір payload: {self.max_compact_chars} симв.",
            f"Перевищують --max-chars: {self.over_limit_count}",
            f"Символів інструкцій промпту (найбільший): {self.instruction_chars}",
        ]
        if self.total_cost_usd is not None:
            lines.append(f"Оцінена сумарна вартість OpenRouter: ${self.total_cost_usd:.4f}")
        else:
            lines.append("Оцінена сумарна вартість OpenRouter: н/д (немає цін або лише локальні моделі)")
        return lines


def _compact_chars_for_file(path: Path, *, legacy: bool) -> int:
    from main import compact_declaration

    raw = json.loads(path.read_text(encoding="utf-8"))
    compact = compact_declaration(raw, legacy_payload=legacy)
    return len(json.dumps(compact, ensure_ascii=False))


def estimate_payloads(
    files: List[Path],
    *,
    max_chars: int,
    legacy: bool = False,
) -> List[FilePayloadSize]:
    out: List[FilePayloadSize] = []
    for path in files:
        try:
            n = _compact_chars_for_file(path, legacy=legacy)
            out.append(
                FilePayloadSize(
                    name=path.name,
                    compact_chars=n,
                    over_limit=n > max_chars,
                )
            )
        except Exception as exc:  # noqa: BLE001
            out.append(
                FilePayloadSize(
                    name=f"{path.name} (compact error: {exc})",
                    compact_chars=0,
                    over_limit=False,
                )
            )
    return out


def _instruction_chars(prompt: PromptSpec) -> int:
    return len(prompt.system_prompt) + len(
        prompt.user_prompt_template.replace("{declaration_payload}", "")
    )


def _estimate_model_cost(
    model: ModelSpec,
    *,
    n_decls: int,
    n_prompts: int,
    mean_payload_chars: float,
    instruction_chars: int,
    pricing_per_token: Dict[str, Dict[str, float]],
) -> ModelCostEstimate:
    est = ModelCostEstimate(model_id=model.model_id, provider=model.provider)
    chars_per_call = instruction_chars + mean_payload_chars
    prompt_tok = int(round(chars_per_call / CHARS_PER_TOKEN))
    completion_tok = DEFAULT_COMPLETION_TOKENS
    calls = n_decls * n_prompts
    est.prompt_tokens_est = prompt_tok * calls
    est.completion_tokens_est = completion_tok * calls

    if model.provider != "openrouter":
        est.note = "локальна/хмарна Ollama - оцінка USD недоступна"
        return est

    rates = pricing_per_token.get(model.model_id) or {}
    rp = rates.get("prompt")
    rc = rates.get("completion")
    if rp is None and rc is None:
        est.note = "ціна для цього ідентифікатора моделі невідома"
        return est

    cost = 0.0
    if rp is not None:
        cost += est.prompt_tokens_est * float(rp)
    if rc is not None:
        cost += est.completion_tokens_est * float(rc)
    est.cost_usd = cost
    est.pricing_known = True
    est.note = f"~{prompt_tok} вх. + ~{completion_tok} вих. токенів/декл. x {calls} викликів"
    return est


def build_cost_estimate(
    config: BenchConfig,
    files: List[Path],
    *,
    pricing_per_token: Optional[Dict[str, Dict[str, float]]] = None,
) -> CostEstimate:
    sizes = estimate_payloads(
        files,
        max_chars=config.max_chars,
        legacy=config.compact_legacy_payload,
    )
    compact_vals = [s.compact_chars for s in sizes if s.compact_chars > 0]
    mean_c = (sum(compact_vals) / len(compact_vals)) if compact_vals else 0.0
    max_c = max(compact_vals) if compact_vals else 0
    over = sum(1 for s in sizes if s.over_limit)

    instr = 0
    for p in config.prompts:
        instr = max(instr, _instruction_chars(p))

    pricing = pricing_per_token or {}
    # If any openrouter model and pricing empty, try fetch once.
    if any(m.provider == "openrouter" for m in config.models) and not pricing:
        try:
            from openrouter_client import fetch_openrouter_models_enriched

            or_models = [m for m in config.models if m.provider == "openrouter"]
            host = or_models[0].host
            key = or_models[0].api_key
            enriched = fetch_openrouter_models_enriched(host, key)
            pricing = enriched.get("pricing_per_token") or {}
        except Exception:  # noqa: BLE001
            pricing = {}

    n_prompts = max(1, len(config.prompts))
    per_model: List[ModelCostEstimate] = []
    total: Optional[float] = 0.0
    any_known = False
    for m in config.models:
        row = _estimate_model_cost(
            m,
            n_decls=len(files),
            n_prompts=n_prompts,
            mean_payload_chars=mean_c,
            instruction_chars=instr,
            pricing_per_token=pricing,
        )
        per_model.append(row)
        if row.pricing_known and row.cost_usd is not None:
            any_known = True
            total = (total or 0.0) + float(row.cost_usd)

    return CostEstimate(
        file_sizes=sizes,
        mean_compact_chars=mean_c,
        max_compact_chars=max_c,
        over_limit_count=over,
        instruction_chars=instr,
        per_model=per_model,
        total_cost_usd=total if any_known else None,
        declaration_count=len(files),
        cell_count=len(config.models) * len(config.prompts),
    )
