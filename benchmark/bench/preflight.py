"""Three-layer preflight: host reachable → model listed → smoke call succeeds."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error, request

from .config import ModelSpec, PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class ModelPreflight:
    model_id: str
    provider: str
    host_ok: bool = False
    host_message: str = ""
    listed: bool = False
    listed_message: str = ""
    smoke_ok: bool = False
    smoke_message: str = ""
    skipped: bool = False
    available_models: List[str] = field(default_factory=list)
    credits_label: str = ""
    pricing_hint: str = ""

    @property
    def ok(self) -> bool:
        if self.skipped:
            return False
        return self.host_ok and self.listed and self.smoke_ok

    def status_label(self) -> str:
        if self.skipped:
            return "ПРОПУЩЕНО"
        if self.ok:
            return "OK"
        if not self.host_ok:
            return "ХОСТ НЕДОСТУПНИЙ"
        if not self.listed:
            return "НЕ ЗНАЙДЕНО"
        if not self.smoke_ok:
            return "SMOKE НЕ ПРОЙШОВ"
        return "ПОМИЛКА"


@dataclass
class PreflightReport:
    results: List[ModelPreflight] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        live = [r for r in self.results if not r.skipped]
        return bool(live) and all(r.ok for r in live)

    @property
    def ok_models(self) -> List[ModelPreflight]:
        return [r for r in self.results if r.ok]

    @property
    def failed_models(self) -> List[ModelPreflight]:
        return [r for r in self.results if not r.ok and not r.skipped]


def _http_get_json(url: str, *, timeout_sec: float = 8.0, headers: Optional[Dict[str, str]] = None) -> Any:
    req = request.Request(url, headers=headers or {}, method="GET")
    with request.urlopen(req, timeout=timeout_sec) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_ollama_host(host: str, api_key: str = "") -> tuple[bool, str, List[str]]:
    host_norm = str(host or "").rstrip("/")
    if not host_norm.startswith("http://") and not host_norm.startswith("https://"):
        return False, "Хост має починатися з http:// або https://", []
    headers: Dict[str, str] = {}
    if api_key and str(api_key).strip():
        headers["Authorization"] = f"Bearer {str(api_key).strip()}"
    try:
        data = _http_get_json(f"{host_norm}/api/tags", timeout_sec=8.0, headers=headers or None)
        models = [
            m.get("name")
            for m in (data.get("models") or [])
            if isinstance(m, dict) and isinstance(m.get("name"), str)
        ]
        models = [m for m in models if m.strip()]
        return True, f"Ollama OK - моделей: {len(models)}", models
    except error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return False, f"Ollama HTTP {exc.code}: {exc.reason}. {body}", []
    except Exception as exc:  # noqa: BLE001
        return False, f"Ollama недоступна: {exc}", []


def check_openrouter_host(
    host: str, api_key: str
) -> tuple[bool, str, List[str], str, Dict[str, Any]]:
    """Return (ok, message, model_ids, credits_label, enriched)."""
    from openrouter_client import (
        DEFAULT_OPENROUTER_HOST,
        fetch_openrouter_credits,
        fetch_openrouter_models_enriched,
    )

    host_norm = (host or DEFAULT_OPENROUTER_HOST).rstrip("/")
    key = str(api_key or "").strip()
    if not key:
        return False, "Потрібен ключ API OpenRouter", [], "", {}
    if not host_norm.startswith("http://") and not host_norm.startswith("https://"):
        return False, "Хост має починатися з http:// або https://", [], "", {}

    enriched = fetch_openrouter_models_enriched(host_norm, key)
    models = list(enriched.get("models") or [])
    if not models:
        return False, "OpenRouter /models повернув порожній список (невірний ключ чи мережа?)", [], "", enriched

    credits = fetch_openrouter_credits(host_norm, key)
    credits_label = ""
    if credits.get("ok"):
        credits_label = str(credits.get("balance_label") or "")
        msg = f"OpenRouter OK - моделей: {len(models)}"
        if credits_label:
            msg += f"; баланс {credits_label}"
    else:
        msg = f"OpenRouter /models OK ({len(models)}), кредити: {credits.get('message') or 'н/д'}"
    return True, msg, models, credits_label, enriched


def _model_listed(model_id: str, available: List[str]) -> bool:
    mid = str(model_id or "").strip()
    if not mid:
        return False
    if mid in available:
        return True
    # Ollama sometimes lists "name:tag" and users pass "name" or vice versa.
    base = mid.split(":", 1)[0]
    for a in available:
        if a == mid or a.split(":", 1)[0] == base or a.startswith(mid + ":"):
            return True
    return False


def smoke_ollama(model: ModelSpec, *, timeout_sec: int = 60) -> tuple[bool, str]:
    from main import call_ollama_text

    try:
        txt = call_ollama_text(
            model=model.model_id,
            system_prompt="Reply with exactly: OK",
            user_prompt="Say OK",
            host=model.host,
            timeout_sec=timeout_sec,
            num_predict=8,
            api_key=model.api_key,
            cloud_mode=model.cloud_mode,
        )
        preview = str(txt or "").strip()[:80]
        return True, f"smoke OK ({preview or 'порожня відповідь'})"
    except Exception as exc:  # noqa: BLE001
        return False, f"smoke не пройшов: {exc}"


def smoke_openrouter(model: ModelSpec, *, timeout_sec: int = 60) -> tuple[bool, str]:
    from openrouter_client import call_openrouter_text

    try:
        txt = call_openrouter_text(
            model=model.model_id,
            system_prompt="Reply with exactly: OK",
            user_prompt="Say OK",
            host=model.host,
            timeout_sec=timeout_sec,
            num_predict=8,
            api_key=model.api_key,
        )
        preview = str(txt or "").strip()[:80]
        return True, f"smoke OK ({preview or 'порожня відповідь'})"
    except Exception as exc:  # noqa: BLE001
        return False, f"smoke не пройшов: {exc}"


def run_preflight(
    models: List[ModelSpec],
    *,
    skip_smoke: bool = False,
    smoke_timeout: int = 60,
) -> PreflightReport:
    """Run L2+L3 checks for every model. Does not spend meaningful tokens unless smoke runs."""
    report = PreflightReport()
    # Cache host checks per (provider, host, key-presence)
    host_cache: Dict[str, tuple] = {}

    for spec in models:
        row = ModelPreflight(model_id=spec.model_id, provider=spec.provider)
        cache_key = f"{spec.provider}|{spec.host}|{bool(spec.api_key)}|{spec.cloud_mode}"

        if spec.provider == "openrouter":
            if cache_key not in host_cache:
                host_cache[cache_key] = check_openrouter_host(spec.host, spec.api_key)
            host_ok, host_msg, available, credits_label, enriched = host_cache[cache_key]
            row.host_ok = host_ok
            row.host_message = host_msg
            row.available_models = available
            row.credits_label = credits_label
            pricing = (enriched.get("pricing") or {}) if isinstance(enriched, dict) else {}
            row.pricing_hint = str(pricing.get(spec.model_id) or "")
        else:
            if cache_key not in host_cache:
                host_cache[cache_key] = check_ollama_host(spec.host, spec.api_key)
            host_ok, host_msg, available = host_cache[cache_key]
            row.host_ok = host_ok
            row.host_message = host_msg
            row.available_models = available

        if not row.host_ok:
            row.listed_message = "пропущено - хост недоступний"
            row.smoke_message = "пропущено - хост недоступний"
            report.results.append(row)
            continue

        row.listed = _model_listed(spec.model_id, row.available_models)
        if row.listed:
            row.listed_message = "знайдено в каталозі провайдера"
        else:
            sample = ", ".join(row.available_models[:6]) or "(порожньо)"
            row.listed_message = f"не знайдено. приклад: {sample}"

        if not row.listed:
            row.smoke_message = "пропущено - модель не в списку"
            report.results.append(row)
            continue

        if skip_smoke:
            row.smoke_ok = True
            row.smoke_message = "пропущено через --skip-smoke"
        else:
            if spec.provider == "openrouter":
                ok, msg = smoke_openrouter(spec, timeout_sec=smoke_timeout)
            else:
                ok, msg = smoke_ollama(spec, timeout_sec=smoke_timeout)
            row.smoke_ok = ok
            row.smoke_message = msg

        report.results.append(row)

    return report
