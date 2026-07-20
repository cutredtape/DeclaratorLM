"""Download declarations from the API with filtering, plus local-folder scanning."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Iterator, Optional

from filters import FilterCriteria, matches_filters, row_preview
from nazk_client import fetch_document, fetch_list_page, get_robust_session


def download_professional_dataset(
    limit: int = 500,
    save_dir: str = "dataset_declarations",
    delay_sec: float = 1.5,
    list_params: Optional[dict[str, Any]] = None,
) -> int:
    """Download the first `limit` new files (like the old main), with no field filters."""
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    session = get_robust_session()
    lp = dict(list_params or {})

    current_page = 1
    total_saved = len([f for f in os.listdir(save_dir) if f.endswith(".json")])

    while total_saved < limit:
        try:
            items, raw, _transport_err = fetch_list_page(session, current_page, **lp)
            if raw is None:
                print(f"Сервер відповів з помилкою на сторінці {current_page}. Чекаємо 10 сек...")
                time.sleep(10)
                continue
            if not items:
                break

            for item in items:
                if total_saved >= limit:
                    break

                decl_id = item["id"]
                file_path = os.path.join(save_dir, f"decl_{decl_id}.json")
                if os.path.exists(file_path):
                    continue

                try:
                    doc, _doc_err = fetch_document(session, decl_id)
                    if doc is None:
                        continue
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(doc, f, ensure_ascii=False, indent=4)
                    total_saved += 1
                    if total_saved % 5 == 0:
                        print(f"Успішно зібрано: {total_saved}/{limit}")
                    time.sleep(delay_sec)
                except Exception as e:
                    print(f"Пропуск ID {decl_id} через помилку: {e}")
                    continue

            current_page += 1
        except Exception as e:
            print(f"Помилка з'єднання на сторінці {current_page}: {e}. Спробуємо через 30 сек.")
            time.sleep(30)

    return total_saved


def _lastname_from_doc(doc: dict[str, Any]) -> str:
    s1 = (doc.get("data") or {}).get("step_1", {})
    data = s1.get("data") if isinstance(s1, dict) else None
    if not isinstance(data, dict):
        return ""
    return str(data.get("lastname", "") or "").strip()


def peek_first_lastname(
    user_declarant_id: int,
    *,
    delay_sec: float = 1.5,
) -> tuple[Optional[str], Optional[Any], Optional[dict[str, Any]]]:
    """
    First list page for user_declarant_id + full document for the first id.
    Returns (lastname or None, raw list response, diag).
    diag — HTTP detail dict only if the list or first document could not be fetched;
    otherwise None.
    """
    session = get_robust_session()
    items, raw, list_err = fetch_list_page(session, 1, user_declarant_id=int(user_declarant_id))
    if raw is None:
        return None, None, list_err
    if isinstance(raw, dict) and raw.get("error") is not None:
        return None, raw, None
    if not items:
        return None, raw, None
    decl_id = items[0]["id"]
    doc, doc_err = fetch_document(session, decl_id)
    if doc is None:
        return None, raw, doc_err
    time.sleep(delay_sec)
    ln = _lastname_from_doc(doc)
    return (ln if ln else None), raw, None


def download_all_for_user_declarant(
    save_dir: str,
    user_declarant_id: int,
    *,
    delay_sec: float = 2.5,
    max_pages: int = 100,
    on_progress: Optional[Callable[[dict[str, Any]], None]] = None,
) -> tuple[int, int]:
    """
    All available declarations for a subject (pages while the list is non-empty or max_pages).
    save_dir must exist. Files: decl_<uuid>.json (skip existing).
    Returns (new saves count, number of ids found in API lists).
    """
    save_dir = os.path.abspath(save_dir)
    if not os.path.isdir(save_dir):
        os.makedirs(save_dir, exist_ok=True)

    session = get_robust_session()
    lp: dict[str, Any] = {"user_declarant_id": int(user_declarant_id)}

    saved = 0
    found = 0
    skipped = 0
    page = 1
    while page <= max_pages:
        try:
            items, raw, _transport_err = fetch_list_page(session, page, **lp)
            if raw is None:
                print(f"[NAZK] Немає відповіді списку, сторінка {page}. Пауза 10 с.")
                time.sleep(10)
                continue
            if isinstance(raw, dict) and raw.get("error") is not None:
                print(f"[NAZK] Помилка API на сторінці {page}: {raw.get('error')}")
                break
            if not items:
                break

            if on_progress:
                on_progress(
                    {
                        "phase": "page",
                        "page": page,
                        "found": found,
                        "downloaded": saved,
                        "skipped": skipped,
                        "page_items": len(items),
                    }
                )

            for item in items:
                found += 1
                decl_id = item["id"]
                file_path = os.path.join(save_dir, f"decl_{decl_id}.json")
                if os.path.exists(file_path):
                    skipped += 1
                    if on_progress:
                        on_progress(
                            {
                                "phase": "item",
                                "page": page,
                                "found": found,
                                "downloaded": saved,
                                "skipped": skipped,
                                "last_id": decl_id,
                                "skipped_item": True,
                            }
                        )
                    continue
                try:
                    doc, _doc_err = fetch_document(session, decl_id)
                    if doc is None:
                        if on_progress:
                            on_progress(
                                {
                                    "phase": "item",
                                    "page": page,
                                    "found": found,
                                    "downloaded": saved,
                                    "skipped": skipped,
                                    "last_id": decl_id,
                                    "failed": True,
                                }
                            )
                        continue
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(doc, f, ensure_ascii=False, indent=4)
                    saved += 1
                    if on_progress:
                        on_progress(
                            {
                                "phase": "item",
                                "page": page,
                                "found": found,
                                "downloaded": saved,
                                "skipped": skipped,
                                "last_id": decl_id,
                                "skipped_item": False,
                            }
                        )
                    time.sleep(delay_sec)
                except Exception as exc:
                    print(f"[NAZK] Пропуск {decl_id}: {exc}")
                    continue

            page += 1
        except Exception as exc:
            print(f"[NAZK] Помилка на сторінці {page}: {exc}. Пауза 30 с.")
            time.sleep(30)

    return saved, found


def download_with_filters(
    criteria: FilterCriteria,
    *,
    match_limit: int,
    save_dir: str = "dataset_declarations",
    delay_sec: float = 1.5,
    max_pages: int = 100,
    list_params: Optional[dict[str, Any]] = None,
    on_progress: Optional[Callable[[dict[str, Any]], None]] = None,
) -> tuple[int, int]:
    """
    Walk list pages, download full JSON, save only documents that pass matches_filters.
    Returns (saved matches count, documents inspected).
    """
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    session = get_robust_session()
    lp = dict(list_params or {})

    saved = 0
    examined = 0
    page = 1

    while saved < match_limit and page <= max_pages:
        items, raw, _transport_err = fetch_list_page(session, page, **lp)
        if raw is None:
            time.sleep(10)
            continue
        if not items:
            break

        for item in items:
            if saved >= match_limit:
                break

            decl_id = item["id"]
            file_path = os.path.join(save_dir, f"decl_{decl_id}.json")

            try:
                if os.path.exists(file_path):
                    with open(file_path, encoding="utf-8") as f:
                        doc = json.load(f)
                else:
                    doc, _doc_err = fetch_document(session, decl_id)
                    if doc is None:
                        continue
                    time.sleep(delay_sec)

                examined += 1
                if matches_filters(doc, criteria):
                    if not os.path.exists(file_path):
                        with open(file_path, "w", encoding="utf-8") as f:
                            json.dump(doc, f, ensure_ascii=False, indent=4)
                    saved += 1
                    if on_progress:
                        on_progress(
                            {
                                "saved": saved,
                                "examined": examined,
                                "last_id": decl_id,
                                "page": page,
                            }
                        )
            except (OSError, json.JSONDecodeError):
                continue

        page += 1

    return saved, examined


def scan_local_folder(
    folder: str,
    criteria: FilterCriteria,
) -> Iterator[dict[str, Any]]:
    """Iterate JSON files in a folder; yield row_preview for each match."""
    if not os.path.isdir(folder):
        return
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if matches_filters(doc, criteria):
            yield row_preview(doc, source=path)
