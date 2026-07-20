"""Client for the OpenRouter API (https://openrouter.ai/docs/quickstart).

OpenRouter is an OpenAI-compatible endpoint with access to hundreds of
models (Llama, Claude, Gemini, GPT, Qwen, etc.) through a single URL.

This module is intentionally NOT imported by anything on the "ollama path"
and does not change any existing functions (call_ollama, call_ollama_text,
helpers). It only provides a parallel set of calls with the same signatures
and return format, so the provider dispatcher can pick the implementation.

Uses only stdlib (urllib + json), no extra dependencies.

Endpoint: POST {host}/chat/completions (OpenAI-compatible)
Models:   GET  {host}/models
Docs: https://openrouter.ai/docs/quickstart#using-the-openrouter-api
"""

from __future__ import annotations

import json
import re
import socket
from typing import Any, Dict, List, Optional
from urllib import error, request


DEFAULT_OPENROUTER_HOST = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

# These headers show up in OpenRouter's rankings (optional, but recommended).
_OPENROUTER_HTTP_REFERER = "https://github.com/declarator-lm"
_OPENROUTER_SITE_TITLE = "DeclaratorLM"
_OPENROUTER_USER_AGENT = "DeclaratorLM/0.70 (+https://openrouter.ai)"


def _normalize_max_tokens(num_predict: int) -> Optional[int]:
    """Maps num_predict (Ollama-style) -> max_tokens (OpenRouter/OpenAI).

    -1 / <0 / invalid -> None (no artificial limit).
    """
    try:
        n = int(num_predict)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n


_CONTEXT_RESERVE_TOKENS = 384
_MIN_COMPLETION_TOKENS = 512


def _estimate_prompt_tokens(system_prompt: str, user_prompt: str) -> int:
    """Conservative estimate of input tokens (UA JSON is ~1.9 chars/token on OpenRouter)."""
    total = len(system_prompt or "") + len(user_prompt or "")
    est = (total * 10 + 9) // 19
    return max(est, 256)


def _parse_context_length_http_error(exc_text: str) -> Optional[tuple[int, int, int]]:
    """Returns (context_max, input_tokens, output_tokens) parsed from an HTTP 400 body."""
    ctx_m = re.search(r"maximum context length is (\d+)", exc_text, re.I)
    use_m = re.search(r"(\d+) of text input,\s*(\d+) in the output", exc_text)
    if not ctx_m or not use_m:
        return None
    try:
        return int(ctx_m.group(1)), int(use_m.group(1)), int(use_m.group(2))
    except (TypeError, ValueError):
        return None


def _parse_model_context_length(item: Dict[str, Any]) -> Optional[int]:
    for key in ("context_length", "max_context_length", "context_window"):
        raw = item.get(key)
        if raw is None:
            continue
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return None


def effective_max_tokens_for_openrouter(
    num_predict: int,
    *,
    model_context_length: Optional[int],
    system_prompt: str,
    user_prompt: str,
) -> Optional[int]:
    """Caps max_tokens so that input + output doesn't exceed the model's context window."""
    requested = _normalize_max_tokens(num_predict)
    if not model_context_length or model_context_length <= 0:
        return requested
    est_in = _estimate_prompt_tokens(system_prompt, user_prompt)
    room = model_context_length - est_in - _CONTEXT_RESERVE_TOKENS
    if room <= 0:
        room = _MIN_COMPLETION_TOKENS
    if requested is None:
        return max(_MIN_COMPLETION_TOKENS, room)
    capped = min(requested, room)
    return max(_MIN_COMPLETION_TOKENS, capped)


def _decode_json_response(raw_bytes: bytes, *, kind: str) -> Dict[str, Any]:
    """Decode a UTF-8 JSON HTTP body, surfacing failures as a clean RuntimeError.

    A truncated or non-UTF-8 body (proxy/CDN error page on a 200, byte cut by
    a flaky connection) used to abort a long batch with a raw exception. We
    convert that to a single RuntimeError that callers already know how to
    log and retry.
    """
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"OpenRouter повернув не-UTF-8 відповідь ({kind}, {len(raw_bytes)} байт)."
        ) from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        snippet = text[:200].replace("\n", " ").replace("\r", " ")
        raise RuntimeError(
            f"OpenRouter повернув не-JSON відповідь ({kind}, {len(text)} симв.): {snippet}"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"OpenRouter повернув несподіваний тип відповіді ({kind}): {type(parsed).__name__}."
        )
    return parsed


def _http_post_json(
    url: str,
    payload: Dict[str, Any],
    timeout_sec: int,
    *,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": _OPENROUTER_USER_AGENT,
        "HTTP-Referer": _OPENROUTER_HTTP_REFERER,
        "X-Title": _OPENROUTER_SITE_TITLE,
    }
    if extra_headers:
        headers.update(extra_headers)
    req = request.Request(url=url, data=body, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read()
    return _decode_json_response(raw, kind="POST")


def _http_get_json(
    url: str,
    timeout_sec: int,
    *,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers: Dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": _OPENROUTER_USER_AGENT,
    }
    if extra_headers:
        headers.update(extra_headers)
    req = request.Request(url=url, headers=headers, method="GET")
    with request.urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read()
    return _decode_json_response(raw, kind="GET")


def _build_chat_payload(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    num_predict: int,
    json_mode: bool,
    model_context_length: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    requested = _normalize_max_tokens(num_predict)
    mt = effective_max_tokens_for_openrouter(
        num_predict,
        model_context_length=model_context_length,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    if requested is not None and mt is not None and mt < requested:
        print(
            f"[INFO] OpenRouter: max_tokens {requested} -> {mt} "
            f"(context window ~{model_context_length} tokens).",
            flush=True,
        )
    if mt is not None:
        payload["max_tokens"] = mt
    # response_format is supported by most OpenRouter models; some (older ones)
    # ignore it — that's safe for them, the response is just plain-text JSON.
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _post_chat_completions(
    *,
    host: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_sec: int,
    api_key: str,
    num_predict: int,
    json_mode: bool,
    model_context_length: Optional[int] = None,
) -> Dict[str, Any]:
    chat_url = f"{host.rstrip('/')}/chat/completions"
    payload = _build_chat_payload(
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        num_predict=num_predict,
        json_mode=json_mode,
        model_context_length=model_context_length,
    )
    headers: Dict[str, str] = {}
    if str(api_key or "").strip():
        headers["Authorization"] = f"Bearer {str(api_key).strip()}"
    try:
        data = _http_post_json(
            chat_url, payload, timeout_sec, extra_headers=headers or None
        )
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"OpenRouter HTTPError {exc.code}: {exc.reason}. Body: {body}"
        ) from exc
    except error.URLError as exc:
        if "timed out" in str(exc).lower():
            raise RuntimeError(
                f"Запит завершився таймаутом ({timeout_sec}s) при зверненні до OpenRouter /chat/completions."
            ) from exc
        raise RuntimeError(
            "Немає з'єднання з OpenRouter. Перевірте мережу/доступність openrouter.ai."
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError(
            f"Запит завершився таймаутом ({timeout_sec}s) при зверненні до OpenRouter /chat/completions."
        ) from exc
    return {"payload": payload, "data": data}


def _structured_outputs_unsupported_http_error(exc_text: str) -> bool:
    """True if OpenRouter/the provider rejected the request due to unsupported JSON structured outputs."""
    low = exc_text.lower()
    if "httperror 400" not in low and " 400:" not in low and '"code":400' not in low:
        return False
    return "structured-output" in low or "structured_outputs" in low


def _extract_message_content(data: Dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    msg = first.get("message") or {}
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    return ""


def _get_first_message(data: Dict[str, Any]) -> Dict[str, Any]:
    choices = data.get("choices") or []
    if not isinstance(choices, list) or not choices:
        return {}
    first = choices[0]
    if not isinstance(first, dict):
        return {}
    msg = first.get("message") or {}
    return msg if isinstance(msg, dict) else {}


def _collect_reasoning_text(message: Dict[str, Any]) -> str:
    """Text from the reasoning / reasoning_details fields (Kimi and other reasoning models)."""
    parts: List[str] = []
    r = message.get("reasoning")
    if isinstance(r, str) and r.strip():
        parts.append(r.strip())
    details = message.get("reasoning_details")
    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "") in ("reasoning.text", "reasoning.summary"):
                t = item.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t.strip())
    return "\n\n".join(parts)


def _looks_like_compact_declaration(obj: Any) -> bool:
    """The model sometimes returns the compact declaration JSON (meta + quick_totals + steps) instead of a NAZK analysis."""
    return isinstance(obj, dict) and isinstance(obj.get("meta"), dict) and "quick_totals" in obj


def _looks_like_nazk_analysis(obj: Any) -> bool:
    """Expected root schema of the analysis (subject_profile + findings). Edge cases can be fixed up by normalization."""
    if not isinstance(obj, dict) or _looks_like_compact_declaration(obj):
        return False
    if not isinstance(obj.get("subject_profile"), dict):
        return False
    return isinstance(obj.get("findings"), list)


def _try_extract_json(text: str, extract_fn: Any) -> Optional[Dict[str, Any]]:
    if not (text or "").strip():
        return None
    try:
        out = extract_fn(text)
        return out if isinstance(out, dict) else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _analysis_richness(d: Dict[str, Any]) -> int:
    """Heuristic for "how complete" the analysis is (so we don't settle for a JSON fragment in content)."""
    findings = d.get("findings")
    n_find = len(findings) if isinstance(findings, list) else 0
    fa = len(str(d.get("final_assessment") or "").strip())
    reds = d.get("red_flags")
    n_red = len(reds) if isinstance(reds, list) else 0
    needs = d.get("needs_verification")
    n_need = len(needs) if isinstance(needs, list) else 0
    try:
        rs = float(d.get("risk_score") or 0)
    except (TypeError, ValueError):
        rs = 0.0
    return n_find * 50_000 + n_red * 2_000 + n_need * 500 + fa + int(rs)


def _try_extract_from_plain_reasoning(reasoning: str) -> Optional[Dict[str, Any]]:
    """Last-resort fallback: extract key analysis fields from plain-text reasoning.

    Handles the case where a reasoning model (e.g. Kimi via some providers) emits
    a structured plan in the reasoning field but never outputs a JSON code block.
    Extracts risk_score / risk_level and JSON-array fields (red_flags,
    needs_verification, clear_facts) via regex so the result is at least partially
    useful instead of raising RuntimeError.

    Returns None if nothing useful can be salvaged.
    """
    if not (reasoning or "").strip():
        return None

    def _find_scalar(pattern: str, text: str, cast: Any = str) -> Any:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            return None
        try:
            return cast(m.group(1).strip().strip("\"'"))
        except (ValueError, TypeError):
            return None

    def _find_json_array(label: str, text: str) -> List[str]:
        # Locate the opening "[" after the label, then find the matching "]"
        # by counting bracket depth so nested "[...]" inside strings don't
        # prematurely end the match.
        m = re.search(rf'{re.escape(label)}\s*[:\s]+\[', text, re.IGNORECASE)
        if not m:
            return []
        start = m.end() - 1  # position of "["
        depth = 0
        in_str = False
        esc = False
        for i, ch in enumerate(text[start:], start):
            if esc:
                esc = False
                continue
            if ch == "\\" and in_str:
                esc = True
                continue
            if ch == '"' and not esc:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    fragment = text[start : i + 1]
                    try:
                        result = json.loads(fragment)
                        if isinstance(result, list):
                            return [str(x) for x in result if x]
                    except (json.JSONDecodeError, TypeError):
                        pass
                    return []
        return []

    risk_score_raw = _find_scalar(r'risk[_\-]?score\s*[:\-]\s*(\d+)', reasoning, int)
    risk_score = int(max(0, min(100, risk_score_raw))) if risk_score_raw is not None else 0

    risk_level_raw = _find_scalar(r'risk[_\-]?level\s*[:\-]\s*["\']?(\w+)["\']?', reasoning)
    risk_level = str(risk_level_raw).lower() if risk_level_raw else "low"

    red_flags = _find_json_array("red_flags", reasoning)
    needs_verification = _find_json_array("needs_verification", reasoning)
    clear_facts = _find_json_array("clear_facts", reasoning)

    if not any([risk_score, red_flags, needs_verification, clear_facts]):
        return None

    print(
        f"[WARN] OpenRouter: salvaged partial analysis from plain-text reasoning "
        f"(risk_score={risk_score}, red_flags={len(red_flags)}, "
        f"needs_verification={len(needs_verification)}, clear_facts={len(clear_facts)}). "
        "findings/final_assessment will be empty — consider re-running with a different model."
    )
    return {
        "subject_profile": {},
        "risk_score": risk_score,
        "risk_level": risk_level,
        "findings": [],
        "family_assets_overview": [],
        "red_flags": red_flags,
        "needs_verification": needs_verification,
        "clear_facts": clear_facts,
        "final_assessment": "",
    }


def _parse_openrouter_analysis_dict(
    content: str, reasoning_blob: str, extract_fn: Any
) -> Dict[str, Any]:
    """Picks the best NAZK analysis JSON between message.content and reasoning (Kimi / reasoning models).

    Previously we returned as soon as the first "schema-valid" content was found — even if it
    was a fragment with empty findings, while reasoning held the full ```json``` block. Now both
    candidates are compared by "richness"; reasoning wins ties.
    """
    nazk_candidates: List[tuple[str, Dict[str, Any]]] = []
    for blob, label in ((content, "message.content"), (reasoning_blob, "message.reasoning")):
        parsed = _try_extract_json(blob, extract_fn)
        if parsed is not None and _looks_like_nazk_analysis(parsed):
            nazk_candidates.append((label, parsed))

    if nazk_candidates:
        best_label, best = max(
            nazk_candidates,
            key=lambda it: (_analysis_richness(it[1]), 1 if it[0] == "message.reasoning" else 0),
        )
        if len(nazk_candidates) > 1:
            print(
                f"[INFO] OpenRouter: picked {best_label} as analysis JSON "
                f"(compared {len(nazk_candidates)} NA-schema candidates by richness)."
            )
        elif best_label == "message.reasoning" and (content or "").strip():
            print(
                "[INFO] OpenRouter: using JSON analysis from message.reasoning "
                "(message.content was not NA-schema analysis)."
            )
        return best

    parsed_content = _try_extract_json(content, extract_fn)
    if parsed_content is not None and isinstance(parsed_content, dict):
        if not _looks_like_compact_declaration(parsed_content) and isinstance(
            parsed_content.get("findings"), list
        ):
            print(
                "[WARN] OpenRouter: accepted JSON from content with relaxed schema check "
                "(has findings list, not compact_declaration)."
            )
            return parsed_content

    parsed_reason = _try_extract_json(reasoning_blob, extract_fn)
    if parsed_reason is not None and isinstance(parsed_reason, dict):
        if not _looks_like_compact_declaration(parsed_reason) and isinstance(
            parsed_reason.get("findings"), list
        ):
            print(
                "[WARN] OpenRouter: accepted JSON from reasoning with relaxed schema check."
            )
            return parsed_reason

    partial = _try_extract_from_plain_reasoning(reasoning_blob)
    if partial is not None:
        return partial

    raise RuntimeError(
        "OpenRouter: не вдалося отримати валідний JSON аналізу НАЗК. "
        "message.content містить не ту структуру або злам, а в reasoning немає "
        "парсованого JSON (часто reasoning-моделі без ```json …```). "
        "Спробуйте іншу модель або повторіть запуск."
    )


def call_openrouter(
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    host: str = DEFAULT_OPENROUTER_HOST,
    timeout_sec: int = 180,
    api_key: str = "",
    num_predict: int = -1,
    model_context_length: Optional[int] = None,
    return_debug_trace: bool = False,
    usage_snapshots: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    """Calls OpenRouter /chat/completions in JSON mode and returns a parsed dict.

    The return shape matches call_ollama:
      - normal mode: returns a dict (analysis);
      - return_debug_trace=True: returns {"analysis", "request_payload", "response_raw"}.
    """
    print("[INFO] Cloud mode ON (OpenRouter)")

    def _invoke(*, json_mode: bool, predict: int) -> Dict[str, Any]:
        try:
            return _post_chat_completions(
                host=host,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                timeout_sec=timeout_sec,
                api_key=api_key,
                num_predict=predict,
                json_mode=json_mode,
                model_context_length=model_context_length,
            )
        except RuntimeError as exc:
            exc_text = str(exc)
            if _structured_outputs_unsupported_http_error(exc_text):
                raise
            parsed = _parse_context_length_http_error(exc_text)
            if parsed is None:
                raise
            ctx_max, input_tok, output_tok = parsed
            retry_mt = max(
                _MIN_COMPLETION_TOKENS,
                ctx_max - input_tok - _CONTEXT_RESERVE_TOKENS,
            )
            if retry_mt >= output_tok:
                raise
            print(
                f"[INFO] OpenRouter: context overflow (in={input_tok}, out={output_tok}); "
                f"retry max_tokens={retry_mt}.",
                flush=True,
            )
            return _post_chat_completions(
                host=host,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                timeout_sec=timeout_sec,
                api_key=api_key,
                num_predict=retry_mt,
                json_mode=json_mode,
                model_context_length=model_context_length,
            )

    try:
        posted = _invoke(json_mode=True, predict=num_predict)
    except RuntimeError as exc:
        if not _structured_outputs_unsupported_http_error(str(exc)):
            raise
        print(
            "[INFO] OpenRouter: модель/провайдер не підтримує structured outputs "
            "(response_format json_object); повтор запиту без цього режиму.",
            flush=True,
        )
        posted = _invoke(json_mode=False, predict=num_predict)
    if usage_snapshots is not None:
        usage_snapshots.append(extract_openrouter_usage_stats(posted["data"]))
    payload = posted["payload"]
    data = posted["data"]
    msg = _get_first_message(data)
    message_content = str(msg.get("content") or "").strip() if isinstance(msg.get("content"), str) else ""
    reasoning_blob = _collect_reasoning_text(msg)
    if not message_content and not reasoning_blob.strip():
        raise RuntimeError("Порожня відповідь від OpenRouter /chat/completions (content і reasoning).")

    from main import extract_json_from_model_output

    parsed = _parse_openrouter_analysis_dict(
        message_content, reasoning_blob, extract_json_from_model_output
    )
    if return_debug_trace:
        return {
            "analysis": parsed,
            "request_payload": payload,
            "response_raw": {"stream": False, "data": data},
        }
    return parsed


def call_openrouter_text(
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    host: str = DEFAULT_OPENROUTER_HOST,
    timeout_sec: int = 180,
    api_key: str = "",
    num_predict: int = -1,
    model_context_length: Optional[int] = None,
) -> str:
    """Calls OpenRouter /chat/completions without JSON mode and returns plain text."""
    print("[INFO] Cloud mode ON (OpenRouter, text)")
    posted = _post_chat_completions(
        host=host,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        timeout_sec=timeout_sec,
        api_key=api_key,
        num_predict=num_predict,
        json_mode=False,
        model_context_length=model_context_length,
    )
    message_content = _extract_message_content(posted["data"])
    if not message_content:
        raise RuntimeError("Порожня відповідь від OpenRouter /chat/completions.")
    return str(message_content).strip()


def _parse_price_per_token_usd(raw: Any) -> Optional[float]:
    """Price per single token in USD (string from /models or /chat/completions metadata)."""
    if raw is None:
        return None
    try:
        v = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if v < 0:
        return None
    return v


def extract_openrouter_usage_stats(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts usage/cost from the POST /chat/completions response body (OpenRouter/OpenAI-compatible)."""
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}

    def _i(key: str) -> int:
        try:
            return int(usage.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    pt = _i("prompt_tokens")
    ct = _i("completion_tokens")
    tt = _i("total_tokens")
    if tt <= 0:
        tt = pt + ct
    cost_raw = usage.get("cost")
    cost_f: Optional[float] = None
    if isinstance(cost_raw, (int, float)):
        cost_f = float(cost_raw)
    elif isinstance(cost_raw, str) and str(cost_raw).strip():
        try:
            cost_f = float(str(cost_raw).strip())
        except ValueError:
            cost_f = None
    mod = data.get("model")
    mid = str(mod).strip() if isinstance(mod, str) else ""
    return {
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_tokens": tt,
        "cost_usd": cost_f,
        "response_model": mid,
    }


def merge_openrouter_usage_snaps(snaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregates several HTTP responses (retry JSON mode, per-declaration retries)."""
    if not snaps:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "api_cost_usd": None,
            "cost_fully_from_api": False,
        }
    pt = sum(int(s.get("prompt_tokens") or 0) for s in snaps)
    ct = sum(int(s.get("completion_tokens") or 0) for s in snaps)
    tt_partial = sum(int(s.get("total_tokens") or 0) for s in snaps)
    tt = tt_partial if tt_partial > 0 else pt + ct
    parsed_costs: List[Optional[float]] = []
    for s in snaps:
        c = s.get("cost_usd")
        if c is None:
            parsed_costs.append(None)
        else:
            try:
                parsed_costs.append(float(c))
            except (TypeError, ValueError):
                parsed_costs.append(None)
    if parsed_costs and all(x is not None for x in parsed_costs):
        return {
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": tt,
            "api_cost_usd": sum(parsed_costs),
            "cost_fully_from_api": True,
        }
    return {
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_tokens": tt,
        "api_cost_usd": None,
        "cost_fully_from_api": False,
    }


def finalize_openrouter_billing(
    merged: Dict[str, Any],
    *,
    model_id: str,
    per_token_rates: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Builds the openrouter_usage field for JSONL: API cost, or an estimate from /models pricing."""
    out: Dict[str, Any] = {
        "prompt_tokens": int(merged.get("prompt_tokens") or 0),
        "completion_tokens": int(merged.get("completion_tokens") or 0),
        "total_tokens": int(merged.get("total_tokens") or 0),
    }
    if merged.get("api_cost_usd") is not None:
        out["cost_usd"] = round(float(merged["api_cost_usd"]), 6)
        out["cost_estimated"] = False
        return out
    rates = (per_token_rates or {}).get(model_id) or {}
    rp = rates.get("prompt")
    rc = rates.get("completion")
    if rp is not None or rc is not None:
        est = 0.0
        if rp is not None:
            est += out["prompt_tokens"] * float(rp)
        if rc is not None:
            est += out["completion_tokens"] * float(rc)
        out["cost_usd"] = round(est, 6)
        out["cost_estimated"] = True
    else:
        out["cost_usd"] = None
        out["cost_estimated"] = False
    return out


def format_openrouter_usage_log_suffix(usage: Dict[str, Any]) -> str:
    """Text after the "OpenRouter: " prefix (without mentioning internal API fields)."""
    if not isinstance(usage, dict):
        return ""
    pt = int(usage.get("prompt_tokens") or 0)
    ct = int(usage.get("completion_tokens") or 0)
    cost = usage.get("cost_usd")
    est = bool(usage.get("cost_estimated"))
    if cost is not None:
        cstr = f"{float(cost):.4f}"
        if est:
            return f"вартість~=${cstr} USD (оцінка), токени in={pt} out={ct}"
        return f"вартість~=${cstr} USD, токени in={pt} out={ct}"
    if pt or ct:
        return (
            f"токени in={pt} out={ct} "
            f"(вартість недоступна: немає даних у відповіді та ставок у /models)"
        )
    return ""


def format_openrouter_run_totals_footer(
    ptot: Dict[str, Any],
    *,
    unit_label: str = "декларацій",
    scope_title: str = "цей пайплайн",
) -> str:
    """Summary line of tokens and cost for the end of a run (pipeline or compare)."""
    n = int(ptot.get("n") or 0)
    if n <= 0:
        return ""
    known = int(ptot.get("cost_known_n") or 0)
    sum_cost = float(ptot.get("cost_usd") or 0.0)
    pt = int(ptot.get("prompt_tokens") or 0)
    ct = int(ptot.get("completion_tokens") or 0)
    tt = int(ptot.get("total_tokens") or 0)
    if known == n:
        cost_msg = f"сума вартості~=${sum_cost:.4f} USD"
    elif known > 0:
        cost_msg = (
            f"часткова сума вартості~=${sum_cost:.4f} USD "
            f"({known} з {n} з відомою вартістю)"
        )
    else:
        cost_msg = "вартість недоступна (немає даних у відповіді ні оцінки за прайсом /models)"
    return (
        f"OpenRouter за {scope_title}: {unit_label}={n}, "
        f"токени in={pt} out={ct} total={tt}, {cost_msg}."
    )


def _parse_price_per_token_to_per_million_usd(raw: Any) -> Optional[float]:
    """OpenRouter /models usually gives a price per 1 token in USD (string). Returns $/1M tokens."""
    if raw is None:
        return None
    try:
        v = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if v < 0:
        return None
    return v * 1_000_000.0


def _format_per_million_usd(amount: Optional[float]) -> str:
    if amount is None:
        return ""
    if amount >= 100:
        return f"${amount:.0f}/M"
    if amount >= 10:
        return f"${amount:.1f}/M"
    if amount >= 1:
        return f"${amount:.2f}/M"
    if amount >= 0.01:
        return f"${amount:.3f}/M"
    return f"${amount:.4f}/M"


def _openrouter_pricing_hint(pricing: Any) -> str:
    """Short string for the UI: "in $.../M · out $.../M"."""
    if not isinstance(pricing, dict):
        return ""
    pin = _parse_price_per_token_to_per_million_usd(pricing.get("prompt"))
    pout = _parse_price_per_token_to_per_million_usd(pricing.get("completion"))
    # Some responses have request / image pricing too — for chat we only care about prompt/completion.
    if pin is None and pout is None:
        return ""
    left = _format_per_million_usd(pin) if pin is not None else "—"
    right = _format_per_million_usd(pout) if pout is not None else "—"
    return f"in {left} · out {right}"


def fetch_openrouter_models_enriched(
    host: str = DEFAULT_OPENROUTER_HOST, api_key: str = ""
) -> Dict[str, Any]:
    """GET {host}/models -> list of ids + a map id -> short pricing hint for a dropdown.

    OpenRouter: {"data": [{"id": "...", "pricing": {"prompt": "...", "completion": "..."}}]}
    """
    url = f"{host.rstrip('/')}/models"
    headers: Dict[str, str] = {}
    if str(api_key or "").strip():
        headers["Authorization"] = f"Bearer {str(api_key).strip()}"
    try:
        data = _http_get_json(url, timeout_sec=15, extra_headers=headers or None)
    except Exception:  # noqa: BLE001
        return {"models": [], "pricing": {}, "pricing_per_token": {}, "context_length": {}}

    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return {"models": [], "pricing": {}, "pricing_per_token": {}, "context_length": {}}

    ids: List[str] = []
    pricing: Dict[str, str] = {}
    pricing_per_token: Dict[str, Dict[str, float]] = {}
    context_length: Dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        mid = item.get("id")
        if not isinstance(mid, str) or not mid.strip():
            continue
        clean = mid.strip()
        ids.append(clean)
        ctx = _parse_model_context_length(item)
        if ctx is not None:
            context_length[clean] = ctx
        hint = _openrouter_pricing_hint(item.get("pricing"))
        if hint:
            pricing[clean] = hint
        raw_p = item.get("pricing")
        if isinstance(raw_p, dict):
            rp = _parse_price_per_token_usd(raw_p.get("prompt"))
            rc = _parse_price_per_token_usd(raw_p.get("completion"))
            rate: Dict[str, float] = {}
            if rp is not None:
                rate["prompt"] = rp
            if rc is not None:
                rate["completion"] = rc
            if rate:
                pricing_per_token[clean] = rate

    sorted_ids = sorted(set(ids), key=lambda x: x.lower())
    return {
        "models": sorted_ids,
        "pricing": pricing,
        "pricing_per_token": pricing_per_token,
        "context_length": context_length,
    }


def fetch_openrouter_models(
    host: str = DEFAULT_OPENROUTER_HOST, api_key: str = ""
) -> List[str]:
    """GET {host}/models -> sorted list of model ids (chat-compatible)."""
    return list(fetch_openrouter_models_enriched(host, api_key).get("models") or [])


def fetch_openrouter_credits(
    host: str = DEFAULT_OPENROUTER_HOST, api_key: str = ""
) -> Dict[str, Any]:
    """GET {host}/credits — remaining credits (USD). Needs a Bearer API key.

    Response: {"data": {"total_credits": float, "total_usage": float}}.
    Remaining ≈ total_credits - total_usage (per OpenRouter's docs).
    """
    key = str(api_key or "").strip()
    if not key:
        return {
            "ok": False,
            "message": "Потрібен OpenRouter API key.",
            "balance_label": "",
        }
    url = f"{host.rstrip('/')}/credits"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        data = _http_get_json(url, timeout_sec=10, extra_headers=headers)
    except error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return {
            "ok": False,
            "message": f"OpenRouter HTTP {exc.code}: {exc.reason}. {body[:280]}",
            "balance_label": "",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "message": str(exc),
            "balance_label": "",
        }

    inner = data.get("data") if isinstance(data, dict) else None
    if not isinstance(inner, dict):
        return {
            "ok": False,
            "message": "Некоректна відповідь /credits.",
            "balance_label": "",
        }
    try:
        total = float(inner.get("total_credits") or 0)
        used = float(inner.get("total_usage") or 0)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "message": "Некоректні числа у відповіді /credits.",
            "balance_label": "",
        }
    remaining = total - used
    return {
        "ok": True,
        "message": "",
        "balance_label": f"${remaining:.2f}",
        "total_credits": total,
        "total_usage": used,
        "remaining": remaining,
    }
