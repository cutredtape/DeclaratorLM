"""Ukrainian labels for analysis JSON values (report/CSV/HTML). Pipeline logic unchanged."""

from __future__ import annotations

from typing import Any, Dict

# Finding types (enum from main.py / prompt).
FINDING_TYPE_UK: Dict[str, str] = {
    "income_assets_mismatch": "Невідповідність доходів і активів",
    "unexplained_wealth": "Необґрунтоване збагачення",
    "related_party": "Майно на членів сім'ї / третіх осіб",
    "asset_valuation": "Відсутність / заниження вартості активів",
    "transaction_pattern": "Патерни операцій / відчуження",
    "other": "Інше",
}

RISK_LEVEL_UK: Dict[str, str] = {
    "critical": "Критичний",
    "high": "Високий",
    "medium": "Середній",
    "low": "Низький",
    "unknown": "Невідомий",
}

# Sort order for findings CSV (higher = more severe).
SEVERITY_SORT_RANK: Dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}

RISK_LEVEL_FILTER_ORDER = ("critical", "high", "medium", "low")

# severity in findings uses the same codes as risk_level.
SEVERITY_UK = RISK_LEVEL_UK

# subject_profile fields (JSON keys) when they appear in the report.
PROFILE_FIELD_UK: Dict[str, str] = {
    "user_declarant_id": "ID декларанта",
    "declarant_full_name": "ПІБ",
    "position": "Посада",
    "workplace": "Місце роботи",
    "declaration_year": "Рік декларації",
    "declaration_type_code": "Код типу декларації",
    "declaration_type_label": "Тип декларації",
}


def _norm_code(raw: Any) -> str:
    return str(raw or "").strip().lower().replace(" ", "_")


def translate_finding_type(raw: Any) -> str:
    code = _norm_code(raw)
    if not code:
        return ""
    if code in FINDING_TYPE_UK:
        return FINDING_TYPE_UK[code]
    return str(raw).strip().replace("_", " ")


def translate_risk_level(raw: Any) -> str:
    code = _norm_code(raw)
    if not code:
        return ""
    return RISK_LEVEL_UK.get(code, str(raw).strip())


def translate_severity(raw: Any) -> str:
    return translate_risk_level(raw)


def translate_profile_field(key: Any) -> str:
    k = str(key or "").strip()
    if not k:
        return ""
    if k in PROFILE_FIELD_UK:
        return PROFILE_FIELD_UK[k]
    return k.replace("_", " ")


def severity_sort_rank(raw: Any) -> int:
    return SEVERITY_SORT_RANK.get(_norm_code(raw), 0)


def risk_level_css_class(raw: Any) -> str:
    """CSS class (English code) — for styling only, not for display text."""
    code = _norm_code(raw)
    if code in ("critical", "high", "medium", "low"):
        return code
    return "unknown"
