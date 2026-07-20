"""HTTP client for the open NAZK API v2 (documents list + document by id).

Docs: https://public.nazk.gov.ua/public_api
Base URL: https://public-api.nazk.gov.ua/v2
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

BASE_URL = "https://public-api.nazk.gov.ua/v2"

# Some networks/WAFs return 403 without browser-like headers (as used by public.nazk.gov.ua).
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://public.nazk.gov.ua/",
    "Origin": "https://public.nazk.gov.ua",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


def get_robust_session() -> dict[str, Any]:
    """Return a session-like config (headers + timeout) for fetch_*.

    Compatible with nazk_download: the object is passed as the first argument.
    """
    return {
        "headers": dict(DEFAULT_HEADERS),
        "timeout": 60,
        # NAZK 429: several attempts with longer backoff (see _request_json_with_retries)
        "retries": 8,
        "retry_delay_sec": 3.0,
    }


def _merge_headers(session: Mapping[str, Any]) -> dict[str, str]:
    h = dict(session.get("headers") or {})
    return {str(k): str(v) for k, v in h.items()}


def _parse_retry_after(headers: Any) -> float | None:
    """Seconds from the Retry-After header (numeric form only)."""
    if headers is None:
        return None
    raw = headers.get("Retry-After")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        sec = float(str(raw).strip())
        if sec >= 0:
            return min(sec, 600.0)
    except ValueError:
        pass
    return None


def _request_json(
    url: str,
    session: Mapping[str, Any],
) -> tuple[Any | None, int | None, str, float | None]:
    """Returns (parsed_json, http_status, raw_text_snippet, retry_after_sec)."""
    timeout = float(session.get("timeout") or 60)
    headers = _merge_headers(session)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = getattr(resp, "status", None) or resp.getcode()
            if not raw.strip():
                return None, int(code) if code is not None else None, "", None
            try:
                return (
                    json.loads(raw),
                    int(code) if code is not None else None,
                    raw[:500],
                    None,
                )
            except json.JSONDecodeError:
                return None, int(code) if code is not None else None, raw[:500], None
    except urllib.error.HTTPError as exc:
        ra = _parse_retry_after(exc.headers)
        code = int(exc.code)
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except OSError:
            body = ""
        # 429/5xx with a JSON body must still be retried, not treated as success
        retryable_http = code in (429, 500, 502, 503, 504)
        if body.strip():
            try:
                parsed = json.loads(body)
                if not retryable_http:
                    return parsed, code, body[:500], ra
                return None, code, body[:500], ra
            except json.JSONDecodeError:
                pass
        return None, code, body[:500] if body else str(exc), ra
    except urllib.error.URLError as exc:
        return None, None, str(exc.reason) if getattr(exc, "reason", None) else str(exc), None
    except TimeoutError:
        return None, None, "timeout", None
    except OSError as exc:
        return None, None, str(exc), None


def _snippet(text: str, max_len: int = 480) -> str:
    t = text.replace("\r", " ").replace("\n", " ").strip()
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def _request_json_with_retries(
    url: str,
    session: Mapping[str, Any],
) -> tuple[Any | None, dict[str, Any] | None]:
    """Returns (parsed_json, transport_diag). transport_diag only when parsed_json is None."""
    retries = max(1, int(session.get("retries") or 1))
    delay = float(session.get("retry_delay_sec") or 2.0)
    last_diag: dict[str, Any] | None = None
    for attempt in range(retries):
        data, status, hint, retry_after_hdr = _request_json(url, session)
        if data is not None:
            return data, None
        hint_s = hint if isinstance(hint, str) else ""
        last_diag = {
            "http_status": status,
            "body_snippet": _snippet(hint_s) if hint_s else "",
            "url": url,
        }
        # Transient errors — retry (429: longer wait, honoring Retry-After)
        if status in (429, 500, 502, 503, 504) or status is None:
            if status == 429:
                backoff = delay * (2**attempt)
                wait = max(8.0, retry_after_hdr or 0.0, backoff)
                wait = min(wait, 120.0)
            else:
                wait = delay * (attempt + 1)
            time.sleep(wait)
            continue
        break
    return None, last_diag


def _extract_list_items(payload: Any) -> list[dict[str, Any]]:
    """Extract the item list from a /documents/list response."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if not isinstance(payload, dict):
        return []

    if "error" in payload:
        return []

    # Typical shape: {"data": [ {...}, ... ]}
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "documents", "list", "results"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]

    for key in ("items", "documents", "results"):
        inner = payload.get(key)
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]

    return []


def _normalize_list_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Ensure the document id (UUID) key is present."""
    decl_id = item.get("id") or item.get("document_id") or item.get("uuid")
    if not decl_id:
        return None
    out = dict(item)
    out["id"] = str(decl_id).strip()
    return out


def fetch_list_page(
    session: Mapping[str, Any],
    page: int,
    **params: Any,
) -> tuple[list[dict[str, Any]], Any | None, dict[str, Any] | None]:
    """GET /v2/documents/list?page=…&…

    params: query, user_declarant_id, document_type, declaration_type,
            declaration_year, start_date, end_date, … per the API.

    Returns (items, raw_response, transport_error).
    transport_error — dict (http_status, body_snippet, url) only if JSON was not obtained
    after retries; otherwise None. If the API returned JSON with an error field — raw dict, transport_error None.
    """
    qp: dict[str, Any] = {"page": int(page)}
    for k, v in params.items():
        if v is None:
            continue
        if v == "":
            continue
        qp[k] = v

    query_string = urllib.parse.urlencode(qp, doseq=True)
    url = f"{BASE_URL}/documents/list?{query_string}"
    raw, transport_err = _request_json_with_retries(url, session)
    if raw is None:
        return [], None, transport_err

    items_in = _extract_list_items(raw)
    items: list[dict[str, Any]] = []
    for it in items_in:
        norm = _normalize_list_item(it)
        if norm:
            items.append(norm)

    return items, raw, None


def fetch_document(
    session: Mapping[str, Any],
    decl_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """GET /v2/documents/{document_id} — full declaration JSON.

    Returns (document_or_none, diag_or_none). diag is a transport or api_error.
    """
    decl_id = str(decl_id).strip()
    if not decl_id:
        return None, {"detail": "empty_document_id"}
    safe_id = urllib.parse.quote(decl_id, safe="-")
    url = f"{BASE_URL}/documents/{safe_id}"
    raw, transport_err = _request_json_with_retries(url, session)
    if raw is None:
        return None, transport_err
    if not isinstance(raw, dict):
        return None, {
            "detail": "response_not_json_object",
            "body_snippet": _snippet(str(raw)),
            "url": url,
        }
    if raw.get("error"):
        return None, {"api_error": raw.get("error"), "url": url}
    return raw, None
