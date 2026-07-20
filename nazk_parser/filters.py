"""Local filtering of downloaded declaration JSON (after the API fetch)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class FilterCriteria:
    """All fields optional; with nothing set, any document matches."""

    declaration_year: Optional[int] = None
    declaration_year_from: Optional[int] = None
    declaration_year_to: Optional[int] = None
    workplace_contains: Optional[str] = None
    lastname_contains: Optional[str] = None
    firstname_contains: Optional[str] = None


def _doc_declaration_year(doc: dict[str, Any]) -> Optional[int]:
    raw = doc.get("declaration_year")
    if raw is not None and str(raw).strip() != "":
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    step0 = (
        (doc.get("data") or {})
        .get("step_0", {})
        .get("data", {})
    )
    if not isinstance(step0, dict):
        return None
    for key in ("declarationYear1", "declarationYear4", "changesYear"):
        val = step0.get(key)
        if val is not None and str(val).strip() != "":
            try:
                return int(str(val).strip()[:4])
            except (TypeError, ValueError):
                continue
    return None


def _step1(doc: dict[str, Any]) -> dict[str, Any]:
    s1 = (doc.get("data") or {}).get("step_1", {})
    data = s1.get("data") if isinstance(s1, dict) else None
    return data if isinstance(data, dict) else {}


def _contains(hay: str, needle: Optional[str]) -> bool:
    if not needle or not str(needle).strip():
        return True
    return needle.casefold().strip() in hay.casefold()


def matches_filters(doc: dict[str, Any], criteria: FilterCriteria) -> bool:
    has_any = any(
        getattr(criteria, f.name) not in (None, "")
        for f in criteria.__dataclass_fields__.values()
    )
    if not has_any:
        return True

    year = _doc_declaration_year(doc)
    if criteria.declaration_year is not None:
        if year != int(criteria.declaration_year):
            return False
    if criteria.declaration_year_from is not None:
        if year is None or year < int(criteria.declaration_year_from):
            return False
    if criteria.declaration_year_to is not None:
        if year is None or year > int(criteria.declaration_year_to):
            return False

    s1 = _step1(doc)
    workplace = str(s1.get("workPlace", "") or "")
    lastname = str(s1.get("lastname", "") or "")
    firstname = str(s1.get("firstname", "") or "")

    if not _contains(workplace, criteria.workplace_contains):
        return False
    if not _contains(lastname, criteria.lastname_contains):
        return False
    if not _contains(firstname, criteria.firstname_contains):
        return False

    return True


def row_preview(doc: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    s1 = _step1(doc)
    parts = [
        str(s1.get("lastname", "") or "").strip(),
        str(s1.get("firstname", "") or "").strip(),
        str(s1.get("middlename", "") or "").strip(),
    ]
    full_name = " ".join(p for p in parts if p)
    return {
        "source": source,
        "id": str(doc.get("id", "") or ""),
        "user_declarant_id": doc.get("user_declarant_id"),
        "declaration_year": _doc_declaration_year(doc),
        "declarant_full_name": full_name,
        "workplace": str(s1.get("workPlace", "") or "").strip(),
        "work_post": str(s1.get("workPost", "") or "").strip(),
    }
