# --- DEEP_RESEARCH_BEGIN
"""Bridge: DeclaratorLM ↔ download all NAZK declarations for a subject (webview only).

Remove this file and its call sites in webview_app.py to disable the feature.
"""

from __future__ import annotations

import json
import re
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
    log_line("NAZK_DOWNLOAD_PROGRESS|" + json.dumps(payload, ensure_ascii=False))


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
) -> dict[str, Any]:
    """
    Page through /documents/list with NAZK API filters; save up to limit new decl_*.json.
    Year only, search only (query from 3 chars), or both together are allowed.
    declaration_type (1–4) and document_type (1–3) are optional API filters.
    Files already on disk are skipped.
    """
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

    filter_bits: list[str] = []
    if y is not None:
        filter_bits.append(f"рік {y}")
    if q:
        filter_bits.append("пошук")
    if decl_t is not None:
        filter_bits.append(_NAZK_DECLARATION_TYPE_LABELS.get(decl_t, f"вид {decl_t}"))
    if doc_t is not None:
        filter_bits.append(_NAZK_DOCUMENT_TYPE_LABELS.get(doc_t, f"тип {doc_t}"))
    log_line(
        f"[NAZK] Завантаження до {lim} декларацій ({', '.join(filter_bits)}) у {target}\n"
    )
    _emit_nazk_download_progress(
        log_line,
        {"phase": "start", "target": lim, "saved": 0, "skipped": 0, "page": 0},
    )

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
            doc, diag = fetch_document(session, decl_id)
            if doc is None:
                err = _format_nazk_diag(diag, context=f"документ {decl_id}")
                log_line(f"[NAZK] Пропуск {decl_id}: {err}\n")
                time.sleep(delay_sec)
                continue
            try:
                out_file.write_text(
                    json.dumps(doc, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as exc:
                log_line(f"[NAZK] Не збережено {decl_id}: {exc}\n")
                time.sleep(delay_sec)
                continue
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
            time.sleep(delay_sec)

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
    return {
        "ok": True,
        "dir": str(target),
        "new_saved": new_saved,
        "skipped_existing": skipped_existing,
        "declaration_year": y,
        "search_query": q or None,
    }


# --- DEEP_RESEARCH_END
