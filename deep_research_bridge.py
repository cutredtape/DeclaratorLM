# --- DEEP_RESEARCH_BEGIN
"""Bridge: DeclaratorLM ↔ download all NAZK declarations for a subject (webview only).

Remove this file and its call sites in webview_app.py to disable the feature.
"""

from __future__ import annotations

import json
import re
import secrets
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable


def _nazk_parser_dir(project_root: Path) -> Path:
    """nazk_parser directory: next to the exe/project, or inside PyInstaller onefile (sys._MEIPASS)."""
    cand = (project_root / "nazk_parser").resolve()
    if cand.is_dir():
        return cand
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        alt = (Path(sys._MEIPASS) / "nazk_parser").resolve()
        if alt.is_dir():
            return alt
    return cand


def deep_research_root(base_dir: Path) -> Path:
    """The `deep_research` directory at the project root."""
    return (base_dir / "deep_research").resolve()


def _safe_deep_research_subdir(root: Path, folder_name: str) -> Path | None:
    """Only direct subdirectories of `root`; no .. or path separators."""
    name = (folder_name or "").strip()
    if not name or name in (".", ".."):
        return None
    if name != Path(name).name:
        return None
    if "/" in name or "\\" in name:
        return None
    root_r = root.resolve()
    target = (root_r / name).resolve()
    try:
        target.relative_to(root_r)
    except ValueError:
        return None
    if not target.is_dir():
        return None
    return target


def list_deep_research_folders(*, base_dir: Path) -> dict[str, Any]:
    """deep_research subdirs with decl_*.json counts for the UI."""
    root = deep_research_root(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    folders: list[dict[str, Any]] = []
    for p in sorted(root.iterdir(), key=lambda x: x.name.lower()):
        if p.is_dir():
            folders.append(
                {
                    "name": p.name,
                    "path": str(p.resolve()),
                    "decl_count": _count_decl_json(p),
                }
            )
    return {"ok": True, "folders": folders}


def apply_deep_research_folder(
    *,
    base_dir: Path,
    folder_name: str,
    log_line: Callable[[str], None],
) -> dict[str, Any]:
    """
    Enable no-download mode: declarations folder = an existing deep_research subdirectory.
    """
    root = deep_research_root(base_dir)
    target = _safe_deep_research_subdir(root, folder_name)
    if target is None:
        return {
            "ok": False,
            "errors": ["Некоректна назва папки або каталог не знайдено всередині deep_research."],
        }
    total = _count_decl_json(target)
    if total < 1:
        return {
            "ok": False,
            "errors": [
                "У цій папці немає файлів decl_*.json — оберіть інший каталог або спочатку завантажте декларації з API.",
            ],
            "dir": str(target),
        }
    log_line(
        f"[DEEP] Режим глибокого дослідження без завантаження: "
        f"{target.name} ({total} decl_*.json)\n"
    )
    return {
        "ok": True,
        "dir": str(target.resolve()),
        "saved": total,
    }


def _sanitize_folder_name(part: str, max_len: int = 80) -> str:
    part = (part or "").strip()
    for char in '<>:"/\\|?*':
        part = part.replace(char, "_")
    part = re.sub(r"\s+", "_", part)
    part = part.strip("._") or "declarant"
    return part[:max_len]


def _count_decl_json(target: Path) -> int:
    if not target.is_dir():
        return 0
    return len(list(target.glob("decl_*.json")))


def _resolve_target_dir(base_dir: Path, target_input_dir: str) -> Path | None:
    raw = str(target_input_dir or "").strip()
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = base_dir / p
    try:
        return p.resolve()
    except OSError:
        return None


def _output_dir_must_be_under_project(base_dir: Path, target_input_dir: str) -> Path | None:
    """Absolute destination dir; must stay inside base_dir (no escape from the project)."""
    target = _resolve_target_dir(base_dir, target_input_dir)
    if target is None:
        return None
    try:
        target.relative_to(base_dir.resolve())
    except ValueError:
        return None
    return target


def _format_nazk_diag(diag: dict[str, Any] | None, *, context: str) -> str:
    """Human-readable UI string from HTTP status and a response snippet."""
    if not diag:
        return (
            "Не вдалося з'єднатися з API НАЗК (мережа, тайм-аут або блокування). "
            f"Крок: {context}."
        )
    parts: list[str] = [f"НАЗК ({context})"]
    st = diag.get("http_status")
    if st is not None:
        parts.append(f"HTTP {st}")
    if diag.get("api_error") is not None:
        parts.append(f"API error: {diag.get('api_error')}")
    if diag.get("detail"):
        parts.append(str(diag.get("detail")))
    snip = (diag.get("body_snippet") or "").strip()
    if snip:
        parts.append(f"фрагмент відповіді: {snip}")
    u = diag.get("url")
    if u:
        parts.append(f"URL: {u}")
    return " — ".join(parts)


def run_deep_research_download(
    *,
    base_dir: Path,
    user_declarant_id: int,
    log_line: Callable[[str], None],
) -> dict[str, Any]:
    """
    Returns dict: ok, dir?, saved?, lastname?, slug?, errors?: list[str]
    """
    if int(user_declarant_id) < 1:
        return {"ok": False, "errors": ["user_declarant_id має бути додатним цілим числом."]}

    nazk_root = _nazk_parser_dir(base_dir)
    nazk_str = str(nazk_root.resolve())
    # append (not insert(0)): otherwise `nazk_parser/main.py` shadows root `main.py` in-process.
    if nazk_str not in sys.path:
        sys.path.append(nazk_str)

    from nazk_download import download_all_for_user_declarant, peek_first_lastname  # noqa: WPS433

    parent = deep_research_root(base_dir)
    parent.mkdir(parents=True, exist_ok=True)

    log_line(f"[DEEP] Перевірка API для user_declarant_id={user_declarant_id}…")

    lastname, raw, peek_diag = peek_first_lastname(int(user_declarant_id))
    if raw is None:
        err = _format_nazk_diag(peek_diag, context="запит списку декларацій")
        log_line(f"[DEEP] {err}\n")
        return {"ok": False, "errors": [err]}
    if isinstance(raw, dict) and raw.get("error") is not None:
        err = f"Помилка API НАЗК: {raw.get('error')}"
        log_line(f"[DEEP] {err}\n")
        return {"ok": False, "errors": [err]}
    if peek_diag is not None:
        err = _format_nazk_diag(peek_diag, context="завантаження першого документа")
        log_line(f"[DEEP] {err}\n")
        return {"ok": False, "errors": [err]}

    slug = _sanitize_folder_name(lastname) if lastname else "declarant"
    target = parent / f"{slug}_{int(user_declarant_id)}"
    target.mkdir(parents=True, exist_ok=True)

    log_line(f"[DEEP] Завантаження у каталог: {target}")

    def _emit_download_progress(info: dict[str, Any]) -> None:
        import json as _json

        payload = {
            "found": int(info.get("found") or 0),
            "downloaded": int(info.get("downloaded") or 0),
            "skipped": int(info.get("skipped") or 0),
            "page": int(info.get("page") or 0),
            "phase": str(info.get("phase") or ""),
        }
        if info.get("last_id"):
            payload["last_id"] = str(info.get("last_id"))
        log_line("DEEP_DOWNLOAD_PROGRESS|" + _json.dumps(payload, ensure_ascii=False))

    _emit_download_progress({"phase": "start", "found": 0, "downloaded": 0, "skipped": 0, "page": 0})

    last_skipped = 0

    def _progress(info: dict[str, Any]) -> None:
        nonlocal last_skipped
        if "skipped" in info:
            last_skipped = int(info.get("skipped") or 0)
        _emit_download_progress(info)
        if info.get("phase") == "item":
            skip = " (вже є)" if info.get("skipped_item") else ""
            log_line(
                f"[DEEP] стор. {info.get('page')} | знайдено: {info.get('found')} | "
                f"завантажено: {info.get('downloaded')} | id: {info.get('last_id')}{skip}"
            )

    newly_saved, found_total = download_all_for_user_declarant(
        str(target),
        int(user_declarant_id),
        delay_sec=2.5,
        max_pages=100,
        on_progress=_progress,
    )

    total_on_disk = _count_decl_json(target)
    if total_on_disk == 0:
        return {
            "ok": False,
            "errors": [
                "Не знайдено жодної декларації (порожній список або не вдалося зберегти файли).",
            ],
            "dir": str(target),
        }

    _emit_download_progress(
        {
            "phase": "done",
            "found": found_total,
            "downloaded": newly_saved,
            "skipped": last_skipped,
            "page": 0,
            "total_on_disk": total_on_disk,
        }
    )
    log_line(
        f"[DEEP] Готово. Знайдено в API: {found_total}, нових файлів: {newly_saved}, "
        f"усього у каталозі: {total_on_disk}."
    )

    return {
        "ok": True,
        "dir": str(target.resolve()),
        "saved": total_on_disk,
        "new_saved": newly_saved,
        "found": found_total,
        "lastname": lastname or "",
        "slug": slug,
    }


def run_deep_research_download_one(
    *,
    base_dir: Path,
    declaration_id: str,
    target_input_dir: str,
    log_line: Callable[[str], None],
) -> dict[str, Any]:
    """
    Download one declaration by declaration_id into the given input_dir.
    Returns dict: ok, dir?, saved_file?, declaration_id?, errors?: list[str]
    """
    decl_id = str(declaration_id or "").strip()
    if not decl_id:
        return {"ok": False, "errors": ["Некоректний declaration_id."]}

    target = _output_dir_must_be_under_project(base_dir, target_input_dir)
    if target is None:
        return {
            "ok": False,
            "errors": ["Некоректна папка декларацій або шлях поза каталогом проєкту."],
        }

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "errors": [f"Не вдалося створити папку: {exc}"]}

    nazk_root = _nazk_parser_dir(base_dir)
    nazk_str = str(nazk_root.resolve())
    if nazk_str not in sys.path:
        sys.path.append(nazk_str)

    from nazk_client import fetch_document, get_robust_session  # noqa: WPS433

    out_file = target / f"decl_{decl_id}.json"
    if out_file.is_file():
        log_line(
            f"[NAZK] Пропуск {decl_id}: файл уже є ({out_file.name}).\n"
        )
        log_line("[NAZK] Готово. Нових файлів: 0, пропущено (вже є): 1.\n")
        return {
            "ok": True,
            "dir": str(target),
            "saved_file": str(out_file),
            "declaration_id": decl_id,
            "new_saved": 0,
            "skipped_existing": 1,
        }

    log_line(f"[NAZK] Завантаження 1 декларації (id) у {target}\n")
    session = get_robust_session()
    doc, diag = fetch_document(session, decl_id)
    if doc is None:
        err = _format_nazk_diag(diag, context="завантаження декларації за id")
        log_line(f"[NAZK] {err}\n")
        return {"ok": False, "errors": [err], "dir": str(target)}

    try:
        out_file.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log_line(f"[NAZK] Не збережено {decl_id}: {exc}\n")
        return {"ok": False, "errors": [f"Не вдалося зберегти файл: {exc}"], "dir": str(target)}

    log_line(f"[NAZK] [1/1] збережено {out_file.name} (id)\n")
    log_line("[NAZK] Готово. Нових файлів: 1, пропущено (вже є): 0.\n")
    return {
        "ok": True,
        "dir": str(target),
        "saved_file": str(out_file),
        "declaration_id": decl_id,
        "new_saved": 1,
        "skipped_existing": 0,
    }


def _emit_nazk_download_progress(
    log_line: Callable[[str], None], info: dict[str, Any]
) -> None:
    payload = {
        "target": int(info.get("target") or 0),
        "saved": int(info.get("saved") or 0),
        "skipped": int(info.get("skipped") or 0),
        "page": int(info.get("page") or 0),
        "phase": str(info.get("phase") or ""),
    }
    if info.get("pool") is not None:
        payload["pool"] = int(info.get("pool") or 0)
    log_line("NAZK_DOWNLOAD_PROGRESS|" + json.dumps(payload, ensure_ascii=False))


def _try_save_nazk_document(
    session: Any,
    target: Path,
    decl_id: str,
    *,
    fetch_document: Any,
    delay_sec: float,
    log_line: Callable[[str], None],
) -> bool:
    """Download one document from the API and save decl_{id}.json. Returns True on success."""
    doc, diag = fetch_document(session, decl_id)
    if doc is None:
        err = _format_nazk_diag(diag, context=f"документ {decl_id}")
        log_line(f"[NAZK] Пропуск {decl_id}: {err}\n")
        time.sleep(delay_sec)
        return False
    out_file = target / f"decl_{decl_id}.json"
    try:
        out_file.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log_line(f"[NAZK] Не збережено {decl_id}: {exc}\n")
        time.sleep(delay_sec)
        return False
    time.sleep(delay_sec)
    return True


def _download_nazk_ids(
    session: Any,
    target: Path,
    decl_ids: list[str],
    *,
    lim: int,
    skipped_existing: int,
    fetch_document: Any,
    delay_sec: float,
    log_line: Callable[[str], None],
    page: int = 0,
) -> int:
    """Download a list of ids in the given order. Returns the number of new saves."""
    new_saved = 0
    for decl_id in decl_ids:
        if _try_save_nazk_document(
            session,
            target,
            decl_id,
            fetch_document=fetch_document,
            delay_sec=delay_sec,
            log_line=log_line,
        ):
            new_saved += 1
            _emit_nazk_download_progress(
                log_line,
                {
                    "phase": "item",
                    "target": lim,
                    "saved": new_saved,
                    "skipped": skipped_existing,
                    "page": page,
                },
            )
            log_line(f"[NAZK] [{new_saved}/{lim}] збережено decl_{decl_id}.json\n")
    return new_saved


def _nazk_random_mode_label(mode: str) -> str:
    return {
        "full": "повний пул API",
        "pool_cap": "швидкий пул",
        "pages_cap": "обмежено сторінками",
        "random_pages": "випадкові сторінки",
    }.get(mode, mode)


def _collect_random_sample_ids(
    session: Any,
    target: Path,
    list_params: dict[str, Any],
    *,
    lim: int,
    fetch_list_page: Any,
    log_line: Callable[[str], None],
    rng: secrets.SystemRandom,
    mode: str = "pool_cap",
    pool_cap: int = 500,
    pages_cap: int = 15,
    random_pages_count: int = 5,
    api_max_pages: int = 100,
) -> tuple[list[str], int, int, dict[str, Any] | None]:
    """
    Collects eligible ids (not already on disk) and returns a random sample of up to lim.
    mode: full | pool_cap | pages_cap | random_pages
    """
    mode = str(mode or "pool_cap").strip().lower()
    if mode not in ("full", "pool_cap", "pages_cap", "random_pages"):
        mode = "pool_cap"
    pool_cap = max(lim, min(int(pool_cap or 500), 10_000))
    pages_cap = max(1, min(int(pages_cap or 15), api_max_pages))
    random_pages_count = max(1, min(int(random_pages_count or 5), api_max_pages))

    skipped_existing = 0
    eligible_seen = 0

    def _emit_collect(page: int, pool: int) -> None:
        _emit_nazk_download_progress(
            log_line,
            {
                "phase": "collect",
                "target": lim,
                "saved": 0,
                "skipped": skipped_existing,
                "page": page,
                "pool": pool,
            },
        )

    def _process_page_items(
        items: list[dict[str, Any]],
        page: int,
        reservoir: list[str],
    ) -> bool:
        """Adds eligible ids to the reservoir. Returns True if collection should stop (pool_cap)."""
        nonlocal eligible_seen, skipped_existing
        for item in items:
            decl_id = str(item.get("id") or "").strip()
            if not decl_id:
                continue
            out_file = target / f"decl_{decl_id}.json"
            if out_file.is_file():
                skipped_existing += 1
                continue
            eligible_seen += 1
            if len(reservoir) < lim:
                reservoir.append(decl_id)
            else:
                j = rng.randrange(eligible_seen)
                if j < lim:
                    reservoir[j] = decl_id
            if mode == "pool_cap" and eligible_seen >= pool_cap:
                return True
        return False

    def _fetch_page(page: int) -> tuple[list[dict[str, Any]], Any, dict[str, Any] | None]:
        items, raw, transport_err = fetch_list_page(session, page, **list_params)
        if transport_err is not None:
            err = _format_nazk_diag(transport_err, context=f"список документів, стор. {page}")
            log_line(f"[NAZK] {err}\n")
            return [], None, {"ok": False, "errors": [err], "new_saved": 0}
        if raw is None:
            log_line(f"[NAZK] Порожня відповідь API на сторінці {page}. Зупинка.\n")
            return [], raw, None
        if isinstance(raw, dict) and raw.get("error") is not None:
            msg = f"Помилка API НАЗК: {raw.get('error')}"
            log_line(f"[NAZK] {msg}\n")
            return [], raw, {"ok": False, "errors": [msg], "new_saved": 0}
        return items, raw, None

    if mode == "random_pages":
        page_pool = list(range(1, api_max_pages + 1))
        pages_to_fetch = sorted(rng.sample(page_pool, min(random_pages_count, len(page_pool))))
        collected: list[str] = []
        log_line(
            f"[NAZK] Випадкові сторінки API: {', '.join(str(p) for p in pages_to_fetch)}\n"
        )
        for idx, page in enumerate(pages_to_fetch, start=1):
            _emit_collect(page, len(collected))
            items, _raw, err = _fetch_page(page)
            if err is not None:
                return [], skipped_existing, eligible_seen, err
            if not items:
                log_line(f"[NAZK] Сторінка {page}: елементів немає.\n")
                continue
            for item in items:
                decl_id = str(item.get("id") or "").strip()
                if not decl_id:
                    continue
                if (target / f"decl_{decl_id}.json").is_file():
                    skipped_existing += 1
                    continue
                eligible_seen += 1
                collected.append(decl_id)
        sample = rng.sample(collected, lim) if len(collected) > lim else list(collected)
        return sample, skipped_existing, eligible_seen, None

    reservoir: list[str] = []
    if mode == "full":
        max_scan = api_max_pages
    elif mode == "pages_cap":
        max_scan = pages_cap
    else:
        max_scan = api_max_pages

    for page in range(1, max_scan + 1):
        _emit_collect(page, eligible_seen)
        items, _raw, err = _fetch_page(page)
        if err is not None:
            return [], skipped_existing, eligible_seen, err
        if not items:
            log_line(f"[NAZK] Сторінка {page}: елементів немає. Кінець списку.\n")
            break
        if _process_page_items(items, page, reservoir):
            log_line(f"[NAZK] Досягнуто ліміт пулу кандидатів ({pool_cap}). Зупинка збору.\n")
            break

    return reservoir, skipped_existing, eligible_seen, None


def _parse_nazk_random_options(raw: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "mode": "pool_cap",
        "pool_cap": 500,
        "pages_cap": 15,
        "random_pages_count": 5,
    }
    if not isinstance(raw, dict):
        return dict(defaults)
    mode = str(raw.get("mode") or defaults["mode"]).strip().lower()
    if mode not in ("full", "pool_cap", "pages_cap", "random_pages"):
        mode = defaults["mode"]
    out = dict(defaults)
    out["mode"] = mode
    try:
        out["pool_cap"] = max(1, min(int(raw.get("pool_cap", defaults["pool_cap"])), 10_000))
    except (TypeError, ValueError):
        out["pool_cap"] = defaults["pool_cap"]
    try:
        out["pages_cap"] = max(1, min(int(raw.get("pages_cap", defaults["pages_cap"])), 100))
    except (TypeError, ValueError):
        out["pages_cap"] = defaults["pages_cap"]
    try:
        out["random_pages_count"] = max(
            1, min(int(raw.get("random_pages_count", defaults["random_pages_count"])), 100)
        )
    except (TypeError, ValueError):
        out["random_pages_count"] = defaults["random_pages_count"]
    return out


_NAZK_DECLARATION_TYPE_LABELS = {
    1: "щорічна",
    2: "перед звільненням",
    3: "після звільнення",
    4: "кандидата на посаду",
}
_NAZK_DOCUMENT_TYPE_LABELS = {
    1: "декларація",
    2: "повідомлення про зміни",
    3: "виправлена декларація",
}


def run_nazk_download_by_year(
    *,
    base_dir: Path,
    declaration_year: int | None,
    search_query: str,
    limit: int,
    target_input_dir: str,
    log_line: Callable[[str], None],
    delay_sec: float = 1.5,
    declaration_type: int | None = None,
    document_type: int | None = None,
    random_sample: bool = False,
    random_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Page through /documents/list with NAZK API filters; save up to limit new decl_*.json.
    Year only, search only (query from 3 chars), or both together are allowed.
    declaration_type (1–4) and document_type (1–3) are optional API filters.
    Files already on disk are skipped.
    random_sample=True — random selection within the year filter; random_options sets
    the collection mode and limits.
    """
    if random_sample and declaration_year is None:
        return {
            "ok": False,
            "errors": ["Випадкова вибірка потребує фільтра за роком декларації."],
        }

    rand_opts = _parse_nazk_random_options(random_options if random_sample else None)

    max_year = date.today().year
    y: int | None = None
    if declaration_year is not None:
        y = int(declaration_year)
        if y < 2015 or y > max_year:
            return {
                "ok": False,
                "errors": [f"Рік має бути в діапазоні 2015–{max_year} (API НАЗК)."],
            }

    q = str(search_query or "").strip()
    if q:
        if len(q) < 3:
            return {
                "ok": False,
                "errors": ["Пошуковий запит має бути від 3 до 255 символів (API НАЗК)."],
            }
        if len(q) > 255:
            return {
                "ok": False,
                "errors": ["Пошуковий запит не довший за 255 символів (API НАЗК)."],
            }

    if y is None and not q:
        return {
            "ok": False,
            "errors": [
                "Задайте рік декларації і/або пошуковий запит (мінімум 3 символи).",
            ],
        }

    decl_t: int | None = None
    if declaration_type is not None:
        dt = int(declaration_type)
        if dt < 0 or dt > 4:
            return {
                "ok": False,
                "errors": ["Вид декларації має бути від 1 до 4 (API НАЗК)."],
            }
        if dt > 0:
            decl_t = dt

    doc_t: int | None = None
    if document_type is not None:
        dct = int(document_type)
        if dct < 0 or dct > 3:
            return {
                "ok": False,
                "errors": ["Тип документа має бути від 1 до 3 (API НАЗК)."],
            }
        if dct > 0:
            doc_t = dct

    lim = int(limit)
    if lim < 1:
        return {"ok": False, "errors": ["Кількість має бути не менше 1."]}
    max_batch = 500
    if lim > max_batch:
        lim = max_batch
        log_line(f"[NAZK] Обмежуємо кількість до {max_batch} за один запуск.\n")

    target = _output_dir_must_be_under_project(base_dir, target_input_dir)
    if target is None:
        return {
            "ok": False,
            "errors": ["Некоректна папка призначення або шлях поза каталогом проєкту."],
        }

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "errors": [f"Не вдалося створити папку: {exc}"]}

    nazk_root = _nazk_parser_dir(base_dir)
    nazk_str = str(nazk_root.resolve())
    if nazk_str not in sys.path:
        sys.path.append(nazk_str)

    from nazk_client import fetch_document, fetch_list_page, get_robust_session  # noqa: WPS433

    session = get_robust_session()
    list_params: dict[str, Any] = {}
    if y is not None:
        list_params["declaration_year"] = y
    if q:
        list_params["query"] = q
    if decl_t is not None:
        list_params["declaration_type"] = decl_t
    if doc_t is not None:
        list_params["document_type"] = doc_t
    page = 1
    max_pages = 100
    new_saved = 0
    skipped_existing = 0
    eligible_count: int | None = None

    filter_bits: list[str] = []
    if y is not None:
        filter_bits.append(f"рік {y}")
    if q:
        filter_bits.append("пошук")
    if decl_t is not None:
        filter_bits.append(_NAZK_DECLARATION_TYPE_LABELS.get(decl_t, f"вид {decl_t}"))
    if doc_t is not None:
        filter_bits.append(_NAZK_DOCUMENT_TYPE_LABELS.get(doc_t, f"тип {doc_t}"))
    mode_label = "випадкова вибірка" if random_sample else "завантаження"
    log_line(
        f"[NAZK] {mode_label.capitalize()} до {lim} декларацій ({', '.join(filter_bits)}) у {target}\n"
    )
    _emit_nazk_download_progress(
        log_line,
        {"phase": "start", "target": lim, "saved": 0, "skipped": 0, "page": 0},
    )

    if random_sample:
        rng = secrets.SystemRandom()
        rand_mode = str(rand_opts.get("mode") or "pool_cap")
        log_line(
            f"[NAZK] Режим випадкової вибірки: {_nazk_random_mode_label(rand_mode)} "
            f"(ціль завантаження: {lim})\n"
        )
        sample_ids, skipped_existing, eligible_count, collect_err = _collect_random_sample_ids(
            session,
            target,
            list_params,
            lim=lim,
            fetch_list_page=fetch_list_page,
            log_line=log_line,
            rng=rng,
            mode=rand_mode,
            pool_cap=int(rand_opts.get("pool_cap") or 500),
            pages_cap=int(rand_opts.get("pages_cap") or 15),
            random_pages_count=int(rand_opts.get("random_pages_count") or 5),
        )
        if collect_err is not None:
            return {**collect_err, "dir": str(target), "skipped_existing": skipped_existing}
        if not sample_ids:
            return {
                "ok": False,
                "errors": [
                    "Не вдалося зберегти жодної нової декларації "
                    "(порожній список за фільтром, усі файли вже є або помилки завантаження).",
                ],
                "dir": str(target),
                "new_saved": 0,
                "skipped_existing": skipped_existing,
                "eligible_count": eligible_count,
                "random_sample": True,
            }
        log_line(
            f"[NAZK] Випадкова вибірка: {len(sample_ids)} з {eligible_count} кандидатів "
            f"({', '.join(filter_bits)})\n"
        )
        new_saved = _download_nazk_ids(
            session,
            target,
            sample_ids,
            lim=lim,
            skipped_existing=skipped_existing,
            fetch_document=fetch_document,
            delay_sec=delay_sec,
            log_line=log_line,
        )
    else:
        while new_saved < lim and page <= max_pages:
            _emit_nazk_download_progress(
                log_line,
                {
                    "phase": "list",
                    "target": lim,
                    "saved": new_saved,
                    "skipped": skipped_existing,
                    "page": page,
                },
            )
            items, raw, transport_err = fetch_list_page(session, page, **list_params)
            if transport_err is not None:
                err = _format_nazk_diag(transport_err, context=f"список документів, стор. {page}")
                log_line(f"[NAZK] {err}\n")
                return {
                    "ok": False,
                    "errors": [err],
                    "dir": str(target),
                    "new_saved": new_saved,
                }
            if raw is None:
                log_line(f"[NAZK] Порожня відповідь API на сторінці {page}. Зупинка.\n")
                break
            if isinstance(raw, dict) and raw.get("error") is not None:
                msg = f"Помилка API НАЗК: {raw.get('error')}"
                log_line(f"[NAZK] {msg}\n")
                return {"ok": False, "errors": [msg], "dir": str(target), "new_saved": new_saved}
            if not items:
                log_line(f"[NAZK] Сторінка {page}: елементів немає. Кінець списку.\n")
                break

            for item in items:
                if new_saved >= lim:
                    break
                decl_id = str(item.get("id") or "").strip()
                if not decl_id:
                    continue
                out_file = target / f"decl_{decl_id}.json"
                if out_file.is_file():
                    skipped_existing += 1
                    _emit_nazk_download_progress(
                        log_line,
                        {
                            "phase": "item",
                            "target": lim,
                            "saved": new_saved,
                            "skipped": skipped_existing,
                            "page": page,
                        },
                    )
                    continue
                if _try_save_nazk_document(
                    session,
                    target,
                    decl_id,
                    fetch_document=fetch_document,
                    delay_sec=delay_sec,
                    log_line=log_line,
                ):
                    new_saved += 1
                    _emit_nazk_download_progress(
                        log_line,
                        {
                            "phase": "item",
                            "target": lim,
                            "saved": new_saved,
                            "skipped": skipped_existing,
                            "page": page,
                        },
                    )
                    log_line(f"[NAZK] [{new_saved}/{lim}] збережено {out_file.name} (стор. {page})\n")

            page += 1

    if new_saved == 0:
        return {
            "ok": False,
            "errors": [
                "Не вдалося зберегти жодної нової декларації "
                "(порожній список за фільтром, усі файли вже є або помилки завантаження).",
            ],
            "dir": str(target),
            "new_saved": 0,
            "skipped_existing": skipped_existing,
        }

    _emit_nazk_download_progress(
        log_line,
        {
            "phase": "done",
            "target": lim,
            "saved": new_saved,
            "skipped": skipped_existing,
            "page": page,
        },
    )
    log_line(
        f"[NAZK] Готово. Нових файлів: {new_saved}, пропущено (вже є): {skipped_existing}.\n"
    )
    result: dict[str, Any] = {
        "ok": True,
        "dir": str(target),
        "new_saved": new_saved,
        "skipped_existing": skipped_existing,
        "declaration_year": y,
        "search_query": q or None,
        "random_sample": bool(random_sample),
    }
    if random_sample:
        result["eligible_count"] = eligible_count
        result["random_mode"] = str(rand_opts.get("mode") or "pool_cap")
        result["random_options"] = rand_opts
    return result


# --- DEEP_RESEARCH_END
