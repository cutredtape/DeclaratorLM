import argparse
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from uuid import uuid4
from urllib import error, request


FINDINGS_RETRY_MIN_RISK_SCORE = 30


class PayloadLimitExceededError(RuntimeError):
    def __init__(
        self,
        *,
        file_name: str,
        payload_chars: int,
        max_chars: int,
        recommended_max_chars: int = 32000,
    ) -> None:
        self.file_name = file_name
        self.payload_chars = payload_chars
        self.max_chars = max_chars
        self.recommended_max_chars = recommended_max_chars
        super().__init__(
            f"payload_limit_exceeded:file={file_name}:payload={payload_chars}:max={max_chars}:recommended={recommended_max_chars}"
        )


class IncompleteAnalysisError(RuntimeError):
    """Model returned a risk_score without findings (partial / salvaged JSON)."""


def analysis_incomplete_needs_retry(
    analysis: Any,
    *,
    min_risk_score: int = FINDINGS_RETRY_MIN_RISK_SCORE,
) -> bool:
    """True if the risk score is high but findings is empty — needs a retry."""
    if not isinstance(analysis, dict):
        return False
    findings = analysis.get("findings")
    if isinstance(findings, list) and len(findings) > 0:
        return False
    score = safe_float(analysis.get("risk_score"))
    if score is None:
        return False
    return score >= float(min_risk_score)


# LLM prompts stay Ukrainian on purpose: declarations and expected JSON analysis are UA-facing.
SYSTEM_PROMPT = """
Ти аналітик декларацій НАЗК. Працюй обережно, без вигадок, лише з наданих даних.
Твоя задача: виявити прямі та приховані корупційні ризики.

Правила:
1) Не вигадуй фактів, яких немає у вхідних даних.
2) Якщо даних не вистачає - прямо вкажи невизначеність.
3) Оцінюй ризики за шкалою 0..100.
4) Вихід ТІЛЬКИ у JSON, без пояснювального тексту поза JSON.
5) Пиши максимально конкретно: хто саме, який актив/дохід, яка сума, яка дата.
6) Заборонено оціночні фрази без фактів ("можливо занадто високо/низько") без прив'язки до чисел або подій.
7) Не вигадуй відсутні ПІБ/посади/джерела - використовуй лише надані поля.
8) Обов'язково враховуй контекст step_0 (тип декларації, період, службовий контекст).
9) Вважай, що structured-секції покривають основні кроки; рідкісні непокриті кроки — у `raw_extras`; якщо крок відсутній — він порожній або не застосовний.

Формат відповіді:
{
  "subject_profile": {
    "declaration_id": "",
    "user_declarant_id": "",
    "declarant_full_name": "",
    "position": "",
    "workplace": "",
    "declaration_year": 0
  },
  "risk_score": 0,
  "risk_level": "low|medium|high|critical",
  "findings": [
    {
      "title": "коротка назва ризику",
      "type": "income_assets_mismatch|unexplained_wealth|related_party|asset_valuation|transaction_pattern|other",
      "severity": "low|medium|high|critical",
      "confidence": 0.0,
      "evidence": ["факт 1", "факт 2"],
      "involved_persons": ["ПІБ або роль"],
      "related_assets_or_income": ["актив/дохід/операція"],
      "rationale": "чому це ризик"
    }
  ],
  "family_assets_overview": [
    {
      "person": "хто саме",
      "asset_count": 0,
      "asset_examples": ["1-3 приклади"]
    }
  ],
  "red_flags": ["список коротких red flags"],
  "needs_verification": ["що перевірити додатково"],
  "clear_facts": ["конкретні факти без інтерпретацій"],
  "final_assessment": "1-3 речення"
}
""".strip()


USER_PROMPT_TEMPLATE = """
Проаналізуй декларацію та поверни результат тільки у JSON-форматі згідно структури.

Важливо:
- Порівнюй доходи, грошові активи, майно, транспорт, суттєві зміни.
- Враховуй підозрілі патерни (придбання без джерела, занижена/відсутня вартість, багато операцій за короткий період, майно на членів сім'ї тощо).
- Якщо ризиків мало, все одно поверни коректний JSON з низькою оцінкою.
- Обов'язково включай конкретику: ПІБ, посада, хто саме власник/користувач активу, суми та дати (якщо є).
- Якщо щось НЕ підозріло - коротко поясни чому в полі clear_facts.
- Ключово: врахуй `step_0_interpreted` (тип/період декларації, службовий статус), `financial_institutions` (банки/установи) та `raw_extras` (рідкісні непокриті кроки, якщо є).

Дані декларації (стисла структура):
{declaration_payload}
""".strip()


def load_prompt_overrides_file(path_str: str) -> Dict[str, Any]:
    """Reads JSON with pipeline_* / dossier_* keys (webview debug session only)."""
    raw_p = (path_str or "").strip()
    if not raw_p:
        return {}
    try:
        data = json.loads(Path(raw_p).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Не вдалося прочитати --prompt-overrides ({raw_p}): {exc}")
        return {}


def pipeline_prompts_for_process(args: argparse.Namespace) -> tuple[str, str]:
    system = SYSTEM_PROMPT
    user_tmpl = USER_PROMPT_TEMPLATE
    po = getattr(args, "prompt_overrides", None) or {}
    if isinstance(po, dict):
        ps = po.get("pipeline_system_prompt")
        if isinstance(ps, str) and ps.strip():
            system = ps.strip()
        pu = po.get("pipeline_user_prompt_template")
        if isinstance(pu, str) and pu.strip():
            user_tmpl = pu.strip()
    return system, user_tmpl


RISK_LEVELS = {"low", "medium", "high", "critical"}


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    normalized = value.replace(" ", "").replace(",", ".")
    filtered = "".join(ch for ch in normalized if ch.isdigit() or ch in ".-")
    if not filtered or filtered in {"-", ".", "-."}:
        return None
    try:
        return float(filtered)
    except ValueError:
        return None


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def as_str_list(value: Any) -> List[str]:
    return [str(item).strip() for item in as_list(value) if str(item).strip()]


def normalize_risk_level(value: Any, score: float) -> str:
    raw = str(value or "").strip().lower()
    if raw in RISK_LEVELS:
        return raw
    if score >= 75:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def normalize_confidence(value: Any) -> float:
    num = safe_float(value)
    if num is None:
        return 0.0
    # Older responses may contain 0..100; keep one scale 0..1.
    if num > 1:
        num = num / 100.0
    return max(0.0, min(1.0, num))


DECLARATION_TYPE_MAP = {
    "1": "Щорічна",
    "2": "Перед звільненням",
    "3": "Після звільнення",
    "4": "Кандидата на посаду",
    "changes": "Декларація змін",
}
CONTINUE_SERVICE_MAP = {
    "1": "Продовжує виконувати функції держави/місцевого самоврядування",
    "0": "Не продовжує виконувати функції держави/місцевого самоврядування",
}
COMPACT_PLACEHOLDER_VALUES = frozenset(
    {"", "[Конфіденційна інформація]", "[Не застосовується]"}
)
COMPACT_PROTECTED_KEYS = frozenset(
    {
        "id",
        "rightBelongs",
        "ownershipType",
        "otherOwnership",
        "owningDate",
        "currency",
        "sources",
        "person_who_care",
        "workPlace",
        "workPost",
        "establishment_ua_company_name",
        "establishment_ua_company_code",
        "establishment_type",
        "person_open_account",
        "persons_has_accounts",
        "citizen",
        "person",
        "name",
        "percent-ownership",
    }
)
COMPACT_COVERED_STEP_NUMBERS = frozenset({0, 1, 2, 3, 4, 6, 9, 11, 12, 13, 14, 15, 17})


def _is_compact_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in COMPACT_PLACEHOLDER_VALUES
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _is_compact_protected_key(key: str) -> bool:
    if key in COMPACT_PROTECTED_KEYS:
        return True
    if key.startswith(("size", "cost")):
        return True
    if key.endswith("Date"):
        return True
    return False


def _is_compact_noise_key(key: str) -> bool:
    if _is_compact_protected_key(key):
        return False
    if key in {"iteration", "object_identificationNumber", "uid"}:
        return True
    if key.endswith("_extendedstatus"):
        return True
    if key.endswith("Path"):
        return True
    if key.endswith("_id") and key != "id":
        return True
    if key.startswith("hash"):
        return True
    return False


def strip_compact_noise(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            if _is_compact_noise_key(key):
                continue
            stripped = strip_compact_noise(item)
            if _is_compact_protected_key(key):
                cleaned[key] = stripped
            elif not _is_compact_placeholder(stripped):
                cleaned[key] = stripped
        return cleaned
    if isinstance(value, list):
        cleaned_list = [strip_compact_noise(item) for item in value]
        return [item for item in cleaned_list if not _is_compact_placeholder(item)]
    return value


def _build_person_index(family: List[Any]) -> Dict[str, str]:
    person_index: Dict[str, str] = {"1": "Суб'єкт декларування"}
    for item in family:
        if not isinstance(item, dict):
            continue
        person_id = str(item.get("id", "")).strip()
        relation = str(item.get("subjectRelation", "")).strip()
        lastname = str(item.get("lastname", "")).strip()
        firstname = str(item.get("firstname", "")).strip()
        middlename = str(item.get("middlename", "")).strip()
        full_name = " ".join(part for part in [lastname, firstname, middlename] if part).strip()
        if full_name:
            label = f"{relation}: {full_name}" if relation else full_name
        else:
            label = relation if relation else "Член сім'ї"
        if person_id:
            person_index[person_id] = label
    return person_index


def _resolve_person_label(person_key: Any, person_index: Dict[str, str]) -> str:
    key = str(person_key or "").strip()
    if not key:
        return ""
    if key in person_index:
        return person_index[key]
    return f"Особа id={key}"


def _describe_inline_right_holder(right: Dict[str, Any]) -> str:
    """Full name/title of a third party described inline in the `rights` object.

    NAZK marks such holders with the code `rightBelongs == "j"` (instead of a
    family member id). The actual data lives in `ua_company_name` (legal
    entity), `ua_lastname/firstname/middlename` (individual), or `citizen`
    (person type).
    """
    company = str(right.get("ua_company_name", "")).strip()
    if company and not _is_compact_placeholder(company):
        code = str(right.get("ua_company_code", "")).strip()
        if code and not _is_compact_placeholder(code):
            return f"{company} (код {code})"
        return company

    ua_name = " ".join(
        part
        for part in [
            str(right.get("ua_lastname", "")).strip(),
            str(right.get("ua_firstname", "")).strip(),
            str(right.get("ua_middlename", "")).strip(),
        ]
        if part and not _is_compact_placeholder(part)
    ).strip()
    if ua_name:
        return ua_name

    citizen = str(right.get("citizen", "")).strip()
    if citizen and not _is_compact_placeholder(citizen):
        return citizen
    return ""


def _resolve_right_holders(
    rights: Any,
    person_index: Dict[str, str],
    item: Optional[Dict[str, Any]] = None,
) -> List[str]:
    holders: List[str] = []
    for right in as_list(rights):
        if not isinstance(right, dict):
            continue
        key = str(right.get("rightBelongs", "")).strip()
        if key and key in person_index:
            holders.append(person_index[key])
            continue
        # Third party: data is described inline in the right object itself,
        # not via a family id (NAZK typically sets rightBelongs="j"). Use the real name.
        inline = _describe_inline_right_holder(right)
        if inline:
            holders.append(inline)
        elif key:
            holders.append(f"Особа id={key}")
    if holders:
        return holders
    if isinstance(item, dict):
        for field in ("person", "personWhoHaveRights"):
            label = _resolve_person_label(item.get(field), person_index)
            if label:
                return [label]
    return holders


def _resolve_person_who_care(value: Any, person_index: Dict[str, str]) -> List[str]:
    if value is None or value == "":
        return []
    if not isinstance(value, list):
        label = _resolve_person_label(value, person_index)
        return [label] if label else []
    resolved: List[str] = []
    for entry in as_list(value):
        if isinstance(entry, dict):
            label = _resolve_person_label(entry.get("person"), person_index)
        else:
            label = _resolve_person_label(entry, person_index)
        if label:
            resolved.append(label)
    return resolved


def _is_valid_declaration_type_code(code: str) -> bool:
    return bool(code) and code in DECLARATION_TYPE_MAP


def _resolve_declaration_type_code(step0: Dict[str, Any], raw: Dict[str, Any]) -> str:
    if not isinstance(step0, dict):
        step0 = {}
    code = str(step0.get("declarationType", "")).strip()
    if _is_valid_declaration_type_code(code):
        return code

    changes_year = str(step0.get("changesYear", "")).strip()
    if changes_year:
        return "changes"

    decl_type = raw.get("declaration_type")
    if decl_type is not None:
        decl_s = str(decl_type).strip()
        if decl_s and decl_s != "0" and _is_valid_declaration_type_code(decl_s):
            return decl_s

    doc_type = raw.get("type")
    if doc_type is not None:
        doc_s = str(doc_type).strip()
        if doc_s and doc_s != "0":
            if changes_year and doc_s == "2":
                return "changes"
            if _is_valid_declaration_type_code(doc_s):
                return doc_s

    return ""


def _resolve_right_holder_single(
    right: Dict[str, Any],
    person_index: Dict[str, str],
) -> str:
    key = str(right.get("rightBelongs", "")).strip()
    if key and key in person_index:
        return person_index[key]
    inline = _describe_inline_right_holder(right)
    if inline:
        return inline
    if key:
        return f"Особа id={key}"
    return ""


def _summarize_rights(
    rights: Any,
    person_index: Dict[str, str],
) -> List[Dict[str, Any]]:
    summary: List[Dict[str, Any]] = []
    for right in as_list(rights):
        if not isinstance(right, dict):
            continue
        entry: Dict[str, Any] = {}
        holder = _resolve_right_holder_single(right, person_index)
        if holder:
            entry["holder"] = holder
        ownership_type = str(right.get("ownershipType", "")).strip()
        if ownership_type and not _is_compact_placeholder(ownership_type):
            entry["ownership_type"] = ownership_type
        other_ownership = str(right.get("otherOwnership", "")).strip()
        if other_ownership and not _is_compact_placeholder(other_ownership):
            entry["other_ownership"] = other_ownership
        percent = str(right.get("percent-ownership", "")).strip()
        if percent and not _is_compact_placeholder(percent):
            entry["percent_ownership"] = percent
        if entry:
            summary.append(entry)
    return summary


def _asset_rights_fields(
    item: Dict[str, Any],
    person_index: Dict[str, str],
) -> Dict[str, Any]:
    rights = item.get("rights")
    fields: Dict[str, Any] = {
        "owners_or_users": _resolve_right_holders(rights, person_index, item),
    }
    rights_summary = _summarize_rights(rights, person_index)
    if rights_summary:
        fields["rights_summary"] = rights_summary
    return fields


def _resolve_location_labels(item: Dict[str, Any]) -> Dict[str, str]:
    location: Dict[str, str] = {}
    for key, raw_key in (
        ("region", "region_txt"),
        ("district", "district_txt"),
        ("city", "city_txt"),
        ("city_type", "ua_cityType"),
    ):
        value = str(item.get(raw_key, "")).strip()
        if value and not _is_compact_placeholder(value):
            location[key] = value
    return location


def _resolve_company_name(item: Dict[str, Any]) -> Optional[str]:
    for field in ("company_name_beneficial_owner", "name"):
        value = item.get(field)
        if value is not None and not _is_compact_placeholder(value):
            return str(value).strip()
    return None


def _resolve_country(item: Dict[str, Any]) -> Optional[str]:
    for field in ("country_beneficial_owner", "country"):
        value = item.get(field)
        if value is not None and not _is_compact_placeholder(value):
            return str(value).strip()
    return None


def _resolve_company_code(item: Dict[str, Any]) -> Optional[str]:
    for field in ("beneficial_owner_company_code", "ua_company_code_beneficial_owner"):
        value = item.get(field)
        if value is not None and not _is_compact_placeholder(value):
            return str(value).strip()
    return None


def _resolve_corporate_owners(
    item: Dict[str, Any],
    person_index: Dict[str, str],
) -> List[str]:
    owners = _resolve_person_who_care(item.get("person_who_care"), person_index)
    if owners:
        return owners
    person = item.get("person")
    if person is not None and str(person).strip():
        label = _resolve_person_label(person, person_index)
        if label:
            return [label]
    return []


def _enrich_raw_extras_item(
    item: Any,
    person_index: Dict[str, str],
) -> None:
    if not isinstance(item, dict):
        return
    person = item.get("person")
    if person is not None and str(person).strip():
        label = _resolve_person_label(person, person_index)
        if label:
            item["person_resolved"] = label
    rights = item.get("rights")
    if isinstance(rights, list):
        for right in rights:
            if not isinstance(right, dict):
                continue
            holders = _resolve_right_holders([right], person_index, item)
            if holders:
                right["holders_resolved"] = holders
            right_summary = _summarize_rights([right], person_index)
            if right_summary:
                right["rights_summary"] = right_summary


def _enrich_raw_extras(
    raw_extras: Dict[str, Any],
    person_index: Dict[str, str],
) -> Dict[str, Any]:
    if not raw_extras:
        return raw_extras
    for payload in raw_extras.values():
        if isinstance(payload, list):
            for item in payload:
                _enrich_raw_extras_item(item, person_index)
        elif isinstance(payload, dict):
            for value in payload.values():
                if isinstance(value, list):
                    for item in value:
                        _enrich_raw_extras_item(item, person_index)
    return raw_extras


def compact_corporate_rights(
    items: List[Any],
    person_index: Dict[str, str],
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry: Dict[str, Any] = {
            "legalForm": item.get("legalForm"),
            "company_name": _resolve_company_name(item),
            "country": _resolve_country(item),
            "owners": _resolve_corporate_owners(item, person_index),
        }
        company_code = _resolve_company_code(item)
        if company_code:
            entry["company_code"] = company_code
        if any(
            entry.get(key)
            for key in ("legalForm", "company_name", "country", "owners", "company_code")
        ):
            result.append(entry)
    return result


def _step_payload_nonempty(payload: Any) -> bool:
    if isinstance(payload, list):
        return len(payload) > 0
    if isinstance(payload, dict):
        return len(payload) > 0
    return payload not in (None, "", [])


def _collect_step_payloads(data: Dict[str, Any]) -> tuple[Dict[str, bool], Dict[str, Any]]:
    steps_present: Dict[str, bool] = {}
    all_nonempty_steps: Dict[str, Any] = {}
    for i in range(18):
        key = f"step_{i}"
        node = data.get(key, {})
        payload = node.get("data") if isinstance(node, dict) else None
        is_nonempty = _step_payload_nonempty(payload)
        steps_present[key] = is_nonempty
        if is_nonempty:
            all_nonempty_steps[key] = payload
    return steps_present, all_nonempty_steps


def _build_raw_extras(
    all_nonempty_steps: Dict[str, Any],
    covered_step_numbers: frozenset[int],
) -> Dict[str, Any]:
    raw_extras: Dict[str, Any] = {}
    for step_key, payload in all_nonempty_steps.items():
        try:
            step_num = int(step_key.split("_", 1)[1])
        except (IndexError, ValueError):
            step_num = -1
        if step_num in covered_step_numbers:
            continue
        cleaned = strip_compact_noise(payload)
        if _step_payload_nonempty(cleaned):
            raw_extras[step_key] = cleaned
    return raw_extras


def compact_financial_institutions(
    items: List[Any],
    person_index: Dict[str, str],
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry: Dict[str, Any] = {}
        for field in (
            "establishment_ua_company_name",
            "establishment_ua_company_code",
            "establishment_type",
            "person_open_account",
        ):
            value = item.get(field)
            if not _is_compact_placeholder(value):
                entry[field] = value
        persons = _resolve_person_who_care(item.get("person_who_care"), person_index)
        if persons:
            entry["person_who_care"] = persons
        has_accounts = item.get("persons_has_accounts")
        if isinstance(has_accounts, dict) and has_accounts:
            cleaned_accounts: Dict[str, Any] = {}
            for account_id, account in has_accounts.items():
                if not isinstance(account, dict):
                    continue
                account_entry = strip_compact_noise(account)
                if account_entry:
                    cleaned_accounts[str(account_id)] = account_entry
            if cleaned_accounts:
                entry["persons_has_accounts"] = cleaned_accounts
        if entry:
            result.append(entry)
    return result


def compact_declaration(
    raw: Dict[str, Any],
    *,
    legacy_payload: bool = False,
) -> Dict[str, Any]:
    data = raw.get("data", {})
    step1 = data.get("step_1", {}).get("data", {})
    family = as_list(data.get("step_2", {}).get("data"))
    realty = as_list(data.get("step_3", {}).get("data"))
    unfinished = as_list(data.get("step_4", {}).get("data"))
    vehicles = as_list(data.get("step_6", {}).get("data"))
    incomes = as_list(data.get("step_11", {}).get("data"))
    cash_assets = as_list(data.get("step_12", {}).get("data"))
    liabilities = as_list(data.get("step_13", {}).get("data"))
    major_changes = as_list(data.get("step_14", {}).get("data"))
    expenses = as_list(data.get("step_15", {}).get("data"))
    corporate_rights = as_list(data.get("step_9", {}).get("data"))
    financial_institution_items = as_list(data.get("step_17", {}).get("data"))

    person_index = _build_person_index(family)

    income_values = [safe_float(item.get("sizeIncome")) for item in incomes]
    income_total = sum(v for v in income_values if v is not None)

    cash_values = [safe_float(item.get("sizeAssets")) for item in cash_assets]
    cash_total = sum(v for v in cash_values if v is not None)

    vehicle_costs = [safe_float(item.get("costDate")) for item in vehicles]
    vehicle_total = sum(v for v in vehicle_costs if v is not None)

    realty_costs = [safe_float(item.get("cost_date_assessment")) for item in realty]
    realty_total = sum(v for v in realty_costs if v is not None)

    liability_values = [safe_float(item.get("sizeObligation")) for item in liabilities]
    liability_total = sum(v for v in liability_values if v is not None)

    step0 = data.get("step_0", {}).get("data", {})
    if not isinstance(step0, dict):
        step0 = {}
    declaration_type_code = _resolve_declaration_type_code(step0, raw)

    step0_interpreted = {
        "declaration_type_code": declaration_type_code,
        "declaration_type_label": DECLARATION_TYPE_MAP.get(
            declaration_type_code,
            "Невідомий тип",
        ),
        "period": {
            "declaration_year": step0.get("declarationYear1"),
            "from_year": step0.get("declarationYearFrom"),
            "to_year": step0.get("declarationYearTo"),
            "year_special": step0.get("declarationYear4"),
            "changes_year": step0.get("changesYear"),
        },
        "public_service_context": {
            "continue_perform_functions_code": str(
                step0.get("continue_perform_functions", "")
            ).strip(),
            "continue_perform_functions_label": CONTINUE_SERVICE_MAP.get(
                str(step0.get("continue_perform_functions", "")).strip(),
                "Невідомо",
            ),
            "responsible_position": raw.get("responsible_position"),
            "post_type": raw.get("post_type"),
            "post_category": raw.get("post_category"),
            "corruption_affected": raw.get("corruption_affected"),
        },
    }

    steps_present, all_nonempty_steps = _collect_step_payloads(data)
    raw_extras = _enrich_raw_extras(
        _build_raw_extras(all_nonempty_steps, COMPACT_COVERED_STEP_NUMBERS),
        person_index,
    )
    financial_institutions = compact_financial_institutions(
        financial_institution_items,
        person_index,
    )

    compact: Dict[str, Any] = {
        "meta": {
            "id": raw.get("id"),
            "declaration_year": raw.get("declaration_year"),
            "declaration_type": raw.get("declaration_type"),
            "date": raw.get("date"),
            "declarant": {
                "lastname": step1.get("lastname"),
                "firstname": step1.get("firstname"),
                "middlename": step1.get("middlename"),
                "work_place": step1.get("workPlace"),
                "work_post": step1.get("workPost"),
            },
        },
        "quick_totals": {
            "income_total_uah_estimated": income_total,
            "cash_assets_total_estimated": cash_total,
            "vehicle_declared_cost_total_estimated": vehicle_total,
            "realty_declared_cost_total_estimated": realty_total,
            "liabilities_total_estimated": liability_total,
        },
        "step_0_interpreted": step0_interpreted,
        "steps_context": {
            "nonempty_steps_count": sum(1 for v in steps_present.values() if v),
            "nonempty_steps": [k for k, v in steps_present.items() if v],
        },
        "family_members": [
            {
                "id": item.get("id"),
                "subjectRelation": item.get("subjectRelation"),
                "lastname": item.get("lastname"),
                "firstname": item.get("firstname"),
                "middlename": item.get("middlename"),
            }
            for item in family
        ],
        "real_estate": [
            {
                "objectType": item.get("objectType"),
                "totalArea": item.get("totalArea"),
                "owningDate": item.get("owningDate"),
                "cost_date_assessment": item.get("cost_date_assessment"),
                **(
                    {"location": loc}
                    if (loc := _resolve_location_labels(item))
                    else {}
                ),
                **_asset_rights_fields(item, person_index),
            }
            for item in realty
        ],
        "vehicles": [
            {
                "objectType": item.get("objectType"),
                "brand": item.get("brand"),
                "model": item.get("model"),
                "graduationYear": item.get("graduationYear"),
                "owningDate": item.get("owningDate"),
                "costDate": item.get("costDate"),
                **_asset_rights_fields(item, person_index),
            }
            for item in vehicles
        ],
        "incomes": [
            {
                "objectType": item.get("objectType"),
                "sizeIncome": item.get("sizeIncome"),
                "sources": item.get("sources"),
                "person_who_care": _resolve_person_who_care(
                    item.get("person_who_care"),
                    person_index,
                ),
            }
            for item in incomes
        ],
        "cash_assets": [
            {
                "objectType": item.get("objectType"),
                "assetsCurrency": item.get("assetsCurrency"),
                "sizeAssets": item.get("sizeAssets"),
                **_asset_rights_fields(item, person_index),
            }
            for item in cash_assets
        ],
        "major_changes": [
            {
                "specExpenses": item.get("specExpenses"),
                "specExpensesSubject": item.get("specExpensesSubject"),
                "transactionDate": item.get("transactionDate"),
                "specConsequencesSubject": item.get("specConsequencesSubject"),
                "expenses": item.get("expenses"),
            }
            for item in major_changes
        ],
        "unfinished_construction": [
            {
                "objectType": item.get("objectType"),
                "totalArea": item.get("totalArea"),
                "owningDate": item.get("owningDate"),
                **(
                    {"location": loc}
                    if (loc := _resolve_location_labels(item))
                    else {}
                ),
                **_asset_rights_fields(item, person_index),
            }
            for item in unfinished
        ],
        "liabilities": [
            {
                "objectType": item.get("objectType"),
                "sizeObligation": item.get("sizeObligation"),
                "currency": item.get("currency"),
                "owners": _resolve_person_who_care(item.get("person_who_care"), person_index),
            }
            for item in liabilities
        ],
        "corporate_rights": compact_corporate_rights(corporate_rights, person_index),
        "expenses": [
            {
                "description": item.get("description"),
                "paid": item.get("paid"),
                "emitent": item.get("emitent_ua_company_name") or item.get("emitent_citizen"),
            }
            for item in expenses
        ],
        "financial_institutions": financial_institutions,
    }
    if raw_extras:
        compact["raw_extras"] = raw_extras
    if legacy_payload:
        compact["all_nonempty_steps_payload"] = all_nonempty_steps
    return compact


def _strip_markdown_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.lstrip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].lstrip()
        cleaned = cleaned.rstrip("`").strip()
    return cleaned


def _repair_common_json_issues(fragment: str) -> str:
    """Best-effort fixes for LLM JSON glitches (trailing commas, etc.)."""
    s = fragment
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


def extract_json_from_model_output(text: str) -> Dict[str, Any]:
    """Parse first top-level JSON object from model text.

    Uses JSONDecoder.raw_decode so we stop at the real end of the object
    (rfind('}') often grabs too much/little when the model adds trailing junk
    or truncates mid-stream).
    """
    cleaned = _strip_markdown_json_fence(text)
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("Model did not return JSON object.")

    decoder = json.JSONDecoder()
    fragment = cleaned[start:]

    for attempt in (fragment, _repair_common_json_issues(fragment)):
        try:
            obj, _end = decoder.raw_decode(attempt)
            if isinstance(obj, dict):
                return obj
            raise ValueError("Model JSON root must be an object.")
        except json.JSONDecodeError:
            continue

    # Last error for a clear message
    try:
        decoder.raw_decode(fragment)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Model returned invalid or truncated JSON (often: output token limit too low "
            "for a 1B–3B model, or the reply was cut mid-object). "
            f"JSON error: {exc}"
        ) from exc
    raise ValueError("Model did not return valid JSON object.")


def _stringify_user_declarant_id(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return ""
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        if val != val:  # NaN
            return ""
        iv = int(val)
        return str(iv) if float(iv) == val else str(val).strip()
    return str(val).strip()


def _declaration_type_fields_from_compact(compact: Dict[str, Any]) -> tuple[str, str]:
    """Declaration type code and label from the compact payload (same as the model sees)."""
    step0 = compact.get("step_0_interpreted")
    if isinstance(step0, dict):
        code = str(step0.get("declaration_type_code", "")).strip()
        label = str(step0.get("declaration_type_label", "")).strip()
        if code or label:
            if not label:
                label = DECLARATION_TYPE_MAP.get(code, "Невідомий тип")
            return code, label
    meta = compact.get("meta")
    if isinstance(meta, dict):
        raw_code = meta.get("declaration_type")
        if raw_code is not None:
            code = str(raw_code).strip()
            if code and code != "0":
                return code, DECLARATION_TYPE_MAP.get(code, "Невідомий тип")
    return "", ""


def normalize_analysis_payload(
    analysis_raw: Dict[str, Any],
    *,
    declaration_id: Any,
    user_declarant_id: Any = None,
    declarant_full_name: str,
    position: str,
    workplace: str,
    declaration_year: Any,
    declaration_type_code: str = "",
    declaration_type_label: str = "",
) -> Dict[str, Any]:
    score = safe_float(analysis_raw.get("risk_score"))
    risk_score = int(max(0, min(100, round(score if score is not None else 0.0))))
    risk_level = normalize_risk_level(analysis_raw.get("risk_level"), risk_score)

    findings_normalized: List[Dict[str, Any]] = []
    for finding in as_list(analysis_raw.get("findings")):
        if not isinstance(finding, dict):
            continue
        findings_normalized.append(
            {
                "title": str(finding.get("title", "")).strip(),
                "type": str(finding.get("type", "other")).strip() or "other",
                "severity": str(finding.get("severity", "low")).strip().lower() or "low",
                "confidence": normalize_confidence(finding.get("confidence")),
                "evidence": as_str_list(finding.get("evidence")),
                "involved_persons": as_str_list(finding.get("involved_persons")),
                "related_assets_or_income": as_str_list(
                    finding.get("related_assets_or_income")
                ),
                "rationale": str(finding.get("rationale", "")).strip(),
            }
        )

    profile = analysis_raw.get("subject_profile", {})
    if not isinstance(profile, dict):
        profile = {}

    return {
        "subject_profile": {
            "declaration_id": str(
                profile.get("declaration_id") or declaration_id or ""
            ).strip(),
            "user_declarant_id": _stringify_user_declarant_id(
                profile.get("user_declarant_id") or user_declarant_id
            ),
            "declarant_full_name": str(
                profile.get("declarant_full_name") or declarant_full_name
            ).strip(),
            "position": str(profile.get("position") or position).strip(),
            "workplace": str(profile.get("workplace") or workplace).strip(),
            "declaration_year": int(
                safe_float(profile.get("declaration_year") or declaration_year) or 0
            ),
            "declaration_type_code": str(
                profile.get("declaration_type_code") or declaration_type_code or ""
            ).strip(),
            "declaration_type_label": str(
                profile.get("declaration_type_label") or declaration_type_label or ""
            ).strip(),
        },
        "risk_score": risk_score,
        "risk_level": risk_level,
        "findings": findings_normalized,
        "family_assets_overview": as_list(analysis_raw.get("family_assets_overview")),
        "red_flags": as_str_list(analysis_raw.get("red_flags")),
        "needs_verification": as_str_list(analysis_raw.get("needs_verification")),
        "clear_facts": as_str_list(analysis_raw.get("clear_facts")),
        "final_assessment": str(analysis_raw.get("final_assessment", "")).strip(),
    }


def _http_post_json(
    url: str,
    payload: Dict[str, Any],
    timeout_sec: int,
    *,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    req = request.Request(
        url=url,
        data=body,
        headers=headers,
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_sec) as resp:
        raw_resp = resp.read().decode("utf-8")
    return json.loads(raw_resp)


def _extract_think_fragments(text: str) -> List[str]:
    fragments: List[str] = []
    if not text:
        return fragments
    for match in re.finditer(r"<think>(.*?)</think>", text, flags=re.DOTALL | re.IGNORECASE):
        chunk = match.group(1).strip()
        if chunk:
            fragments.append(chunk)
    return fragments


def _extract_think_from_event(evt: Any) -> List[str]:
    if not isinstance(evt, dict):
        return []
    fragments: List[str] = []
    message = evt.get("message")
    candidate_nodes = [evt]
    if isinstance(message, dict):
        candidate_nodes.append(message)

    direct_reasoning_keys = (
        "thinking",
        "reasoning",
        "reasoning_content",
        "think",
        "thought",
    )
    for node in candidate_nodes:
        if not isinstance(node, dict):
            continue
        for key in direct_reasoning_keys:
            val = node.get(key)
            if isinstance(val, str) and val.strip():
                fragments.append(val.strip())
        content = node.get("content")
        if isinstance(content, str) and content:
            fragments.extend(_extract_think_fragments(content))
    return fragments


def _emit_think_event(chunk: str) -> None:
    normalized = " ".join(str(chunk).split())
    if normalized:
        print(f"THINK_EVENT|{normalized}", flush=True)


def _http_post_chat_stream_with_reasoning(
    *,
    url: str,
    payload: Dict[str, Any],
    timeout_sec: int,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Tuple[str, List[Any]]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    req = request.Request(
        url=url,
        data=body,
        headers=headers,
        method="POST",
    )
    chunks: List[str] = []
    think_buffer = ""
    last_emit_ts = time.monotonic()
    last_full_reasoning = ""

    def _emit_buffer_if_needed(*, force: bool = False) -> None:
        nonlocal think_buffer, last_emit_ts
        compact = " ".join(think_buffer.split()).strip()
        if not compact:
            return
        if not force:
            long_enough = len(compact) >= 80
            punct_break = (
                len(compact) >= 20 and compact[-1] in {".", "!", "?", ":", ";", ","}
            )
            timed_break = (time.monotonic() - last_emit_ts) >= 0.7 and len(compact) >= 20
            if not (long_enough or punct_break or timed_break):
                return
        _emit_think_event(compact)
        think_buffer = ""
        last_emit_ts = time.monotonic()

    raw_events: List[Any] = []
    with request.urlopen(req, timeout=timeout_sec) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_events.append(evt)
            message = evt.get("message", {}) if isinstance(evt, dict) else {}
            content = str(message.get("content", "") or "")
            if content:
                chunks.append(content)
            for frag in _extract_think_from_event(evt):
                text = str(frag or "")
                if not text.strip():
                    continue
                if text.startswith(last_full_reasoning):
                    delta = text[len(last_full_reasoning):]
                else:
                    delta = text
                last_full_reasoning = text
                if not delta.strip():
                    continue
                think_buffer += delta
                _emit_buffer_if_needed(force=False)
    _emit_buffer_if_needed(force=True)
    return "".join(chunks), raw_events


def resolve_audit_mode_dir(path_str: str) -> Path:
    """Relative path — from the main.py directory (project root)."""
    raw = (path_str or "").strip() or "audit"
    p = Path(raw)
    if p.is_absolute():
        return p
    return Path(__file__).resolve().parent / p


def _audit_case_dir(audit_root: Path, source_file: Path) -> Path:
    case_dir = audit_root / source_file.stem
    case_dir.mkdir(parents=True, exist_ok=True)
    return case_dir


def _write_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_audit_config(args: argparse.Namespace) -> Dict[str, Any]:
    enabled = bool(getattr(args, "audit_mode", False))
    if not enabled:
        return {"enabled": False}
    return {
        "enabled": True,
        "root_dir": resolve_audit_mode_dir(str(getattr(args, "audit_mode_dir", "") or "")),
        "raw_declaration": bool(getattr(args, "audit_capture_raw_declaration", False)),
        "compact_declaration": bool(getattr(args, "audit_capture_compact_declaration", False)),
        "request_payload": bool(getattr(args, "audit_capture_request_payload", False)),
        "response_raw": bool(getattr(args, "audit_capture_response_raw", False)),
        "response_parsed": bool(getattr(args, "audit_capture_response_parsed", False)),
        "normalized_analysis": bool(getattr(args, "audit_capture_normalized_analysis", False)),
        "attempt_meta": bool(getattr(args, "audit_capture_attempt_meta", False)),
    }


def _ollama_num_predict_for_options(num_predict: int, *, positive_floor: int) -> int:
    """Ollama: num_predict < 0 means no length limit (usually -1)."""
    try:
        n = int(num_predict)
    except (TypeError, ValueError):
        return -1
    if n < 0:
        return -1
    return max(positive_floor, n)


def call_ollama(
    model: str,
    system_prompt: str,
    user_prompt: str,
    host: str = "http://127.0.0.1:11434",
    timeout_sec: int = 180,
    *,
    num_predict: int = 16000,
    reasoning_debug: bool = False,
    api_key: str = "",
    cloud_mode: bool = False,
    return_debug_trace: bool = False,
) -> Any:
    host = host.rstrip("/")
    chat_url = f"{host}/api/chat"
    options: Dict[str, Any] = {
        "temperature": 0,
        # num_predict < 0 -> no artificial token limit (Ollama; actual max depends on num_ctx).
        "num_predict": _ollama_num_predict_for_options(
            num_predict, positive_floor=256
        ),
    }
    if reasoning_debug:
        # Keep in debug-only mode to avoid affecting stable production runs.
        pass
    chat_payload: Dict[str, Any] = {
        "model": model,
        "stream": reasoning_debug,
        "format": "json",
        "options": options,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if reasoning_debug:
        # Official Ollama switch for thinking models (keep isolated to debug mode).
        chat_payload["think"] = True
    extra_headers: Dict[str, str] = {}
    if api_key.strip():
        extra_headers["Authorization"] = f"Bearer {api_key.strip()}"
    if cloud_mode:
        print("[INFO] Cloud mode ON")

    try:
        if reasoning_debug:
            print("[INFO] Reasoning debug mode ON")
            try:
                message_content, stream_events = _http_post_chat_stream_with_reasoning(
                    url=chat_url,
                    payload=chat_payload,
                    timeout_sec=timeout_sec,
                    extra_headers=extra_headers or None,
                )
                raw_response = {
                    "stream": True,
                    "events": stream_events,
                    "assembled_message_content": message_content,
                }
            except Exception as stream_exc:  # noqa: BLE001
                print(
                    f"[INFO] Reasoning stream failed, fallback to stable non-stream call: {stream_exc}"
                )
                fallback_payload = dict(chat_payload)
                fallback_payload["stream"] = False
                data = _http_post_json(
                    chat_url,
                    fallback_payload,
                    timeout_sec,
                    extra_headers=extra_headers or None,
                )
                message_content = data.get("message", {}).get("content", "")
                raw_response = {
                    "stream": False,
                    "data": data,
                    "fallback_after_stream_error": str(stream_exc),
                }
        else:
            data = _http_post_json(
                chat_url,
                chat_payload,
                timeout_sec,
                extra_headers=extra_headers or None,
            )
            message_content = data.get("message", {}).get("content", "")
            raw_response = {
                "stream": False,
                "data": data,
            }
        if not message_content:
            raise RuntimeError("Empty /api/chat response from Ollama.")
        parsed = extract_json_from_model_output(message_content)
        if return_debug_trace:
            return {
                "analysis": parsed,
                "request_payload": chat_payload,
                "response_raw": raw_response,
            }
        return parsed
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Ollama HTTPError {exc.code}: {exc.reason}. Body: {body}"
        ) from exc
    except error.URLError as exc:
        if "timed out" in str(exc).lower():
            raise RuntimeError(
                f"Request timed out after {timeout_sec}s when calling /api/chat."
            ) from exc
        raise RuntimeError(
            "Cannot connect to Ollama. Ensure `ollama serve` is running."
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"Request timed out after {timeout_sec}s when calling /api/chat."
        ) from exc
    except socket.timeout as exc:
        raise RuntimeError(
            f"Request timed out after {timeout_sec}s when calling /api/chat."
        ) from exc


def call_ollama_text(
    model: str,
    system_prompt: str,
    user_prompt: str,
    host: str = "http://127.0.0.1:11434",
    timeout_sec: int = 180,
    *,
    num_predict: int = -1,
    api_key: str = "",
    cloud_mode: bool = False,
) -> str:
    """Calls /api/chat without format=json — response as plain text (not JSON)."""
    host = host.rstrip("/")
    chat_url = f"{host}/api/chat"
    options: Dict[str, Any] = {
        "temperature": 0,
        "num_predict": _ollama_num_predict_for_options(
            num_predict, positive_floor=128
        ),
    }
    chat_payload: Dict[str, Any] = {
        "model": model,
        "stream": False,
        "options": options,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    extra_headers: Dict[str, str] = {}
    if api_key.strip():
        extra_headers["Authorization"] = f"Bearer {api_key.strip()}"
    if cloud_mode:
        print("[INFO] Cloud mode ON (call_ollama_text)")

    try:
        data = _http_post_json(
            chat_url,
            chat_payload,
            timeout_sec,
            extra_headers=extra_headers or None,
        )
        message_content = data.get("message", {}).get("content", "")
        if not message_content:
            raise RuntimeError("Empty /api/chat response from Ollama.")
        return str(message_content).strip()
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Ollama HTTPError {exc.code}: {exc.reason}. Body: {body}"
        ) from exc
    except error.URLError as exc:
        if "timed out" in str(exc).lower():
            raise RuntimeError(
                f"Request timed out after {timeout_sec}s when calling /api/chat."
            ) from exc
        raise RuntimeError(
            "Cannot connect to Ollama. Ensure `ollama serve` is running."
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"Request timed out after {timeout_sec}s when calling /api/chat."
        ) from exc
    except socket.timeout as exc:
        raise RuntimeError(
            f"Request timed out after {timeout_sec}s when calling /api/chat."
        ) from exc


def iter_json_files(input_dir: Path) -> List[Path]:
    return sorted(input_dir.glob("*.json"))


_PROJECT_ROOT = Path(__file__).resolve().parent
_DEEP_RESEARCH_ROOT = _PROJECT_ROOT / "deep_research"


def is_under_project_deep_research(input_dir: Path) -> bool:
    """True if the declarations directory is inside the project's deep_research/ (deep research mode)."""
    try:
        resolved = input_dir.expanduser().resolve()
        return resolved.is_relative_to(_DEEP_RESEARCH_ROOT.resolve())
    except (OSError, ValueError):
        return False


def sort_declaration_files_chronologically(files: List[Path]) -> List[Path]:
    """Oldest -> newest by declaration_year and date from JSON; stable tie-break by filename."""

    def sort_key(path: Path) -> tuple:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return (0, "", path.name)
        yr_raw = raw.get("declaration_year")
        try:
            year = int(yr_raw) if yr_raw is not None else 0
        except (TypeError, ValueError):
            year = 0
        date_raw = raw.get("date") or ""
        date_key = ""
        if isinstance(date_raw, str) and date_raw.strip():
            ds = date_raw.strip().replace("Z", "+00:00")
            try:
                date_key = datetime.fromisoformat(ds).isoformat()
            except ValueError:
                date_key = date_raw
        return (year, date_key, path.name)

    return sorted(files, key=sort_key)


def resolve_openrouter_api_key(cli_value: str = "") -> str:
    """CLI -> env (DECLARATOR_OPENROUTER_API_KEY / OPENROUTER_API_KEY) -> empty."""
    for env_name in ("DECLARATOR_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"):
        from_env = str(os.environ.get(env_name, "") or "").strip()
        if from_env:
            return from_env
    return str(cli_value or "").strip()


def run_meta_host(args: argparse.Namespace) -> str:
    if str(getattr(args, "provider", "ollama") or "ollama").lower() == "openrouter":
        return str(
            getattr(args, "openrouter_host", "")
            or "https://openrouter.ai/api/v1"
        ).strip()
    return str(getattr(args, "host", "") or "").strip()


def openrouter_model_context_length(
    args: argparse.Namespace, model_id: str
) -> Optional[int]:
    ctx_map = getattr(args, "_openrouter_context_length", None)
    if not isinstance(ctx_map, dict):
        return None
    mid = str(model_id or "").strip()
    if not mid:
        return None
    raw = ctx_map.get(mid)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def resolve_effective_model_and_mode(args: argparse.Namespace) -> Tuple[str, str]:
    """Return effective model id and launch mode for current run."""
    provider = str(getattr(args, "provider", "ollama") or "ollama").strip().lower()
    if provider == "openrouter":
        model_id = str(
            getattr(args, "openrouter_model", "") or getattr(args, "model", "")
        ).strip()
        return model_id or "unknown-model", "openrouter"
    model_id = str(getattr(args, "model", "")).strip() or "unknown-model"
    if bool(getattr(args, "cloud_mode", False)):
        return model_id, "ollama cloud"
    return model_id, "local"


def build_model_label(args: argparse.Namespace) -> str:
    model_id, launch_mode = resolve_effective_model_and_mode(args)
    return f"{model_id} ({launch_mode})"


def _split_model_label_suffix(full: str) -> Tuple[str, Optional[str]]:
    """Parse 'id (mode)' from run_meta.model; strips optional quotes around mode."""
    s = str(full or "").strip()
    if not s:
        return "", None
    if s.endswith(")") and " (" in s:
        base, rest = s.rsplit(" (", 1)
        inner = rest[:-1].strip().strip('"').strip("'")
        return base.strip(), inner or None
    return s, None


def _run_identity_for_resume(meta: Any) -> Tuple[str, Optional[str]]:
    if not isinstance(meta, dict):
        return "", None
    mid = str(meta.get("model_id") or "").strip()
    lm = str(meta.get("launch_mode") or "").strip().strip('"').strip("'")
    if mid and lm:
        return mid, lm
    return _split_model_label_suffix(str(meta.get("model") or ""))


def _same_model_for_resume(meta: Any, want_mid: str, want_lm: str) -> bool:
    """True if JSONL row counts as same model+launch for resume/skip logic."""
    want_mid = str(want_mid or "").strip()
    want_lm = str(want_lm or "").strip()
    mid, lm = _run_identity_for_resume(meta)
    lm_n = (lm or "").strip()
    if mid != want_mid:
        return False
    if lm_n == want_lm:
        return True
    raw_model = str((meta or {}).get("model", "")).strip()
    legacy_plain = " (" not in raw_model and not str((meta or {}).get("launch_mode") or "").strip()
    if legacy_plain and want_lm == "local":
        return True
    return False


def load_processed_filenames(
    output_path: Path, want_model_id: str, want_launch_mode: str
) -> set:
    """Return source_file names already successfully processed with the given model.

    Only entries whose run_meta.model matches the current model are skipped.
    This allows re-running the same declarations with a different model.
    """
    processed: set = set()
    if not output_path.exists():
        return processed
    try:
        with output_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    meta = item.get("run_meta") or {}
                    if not _same_model_for_resume(meta, want_model_id, want_launch_mode):
                        continue
                    name = item.get("source_file", "")
                    if name:
                        processed.add(name)
                except Exception:  # noqa: BLE001
                    continue
    except OSError:
        pass
    return processed


def process_file(path: Path, args: argparse.Namespace) -> Dict[str, Any]:
    raw_data = json.loads(path.read_text(encoding="utf-8"))
    compact = compact_declaration(
        raw_data,
        legacy_payload=bool(getattr(args, "compact_legacy_payload", False)),
    )
    compact_str_full = json.dumps(compact, ensure_ascii=False)

    analysis: Optional[Dict[str, Any]] = None
    last_error: Optional[Exception] = None
    sent_chars = 0
    was_truncated = False
    audit_cfg = _build_audit_config(args)
    audit_case_dir: Optional[Path] = None
    attempt_meta: List[Dict[str, Any]] = []
    file_usage_snaps: List[Dict[str, Any]] = []
    if audit_cfg.get("enabled"):
        audit_case_dir = _audit_case_dir(audit_cfg["root_dir"], path)
        if audit_cfg.get("raw_declaration"):
            _write_json_file(audit_case_dir / "raw_declaration.json", raw_data)
        if audit_cfg.get("compact_declaration"):
            _write_json_file(audit_case_dir / "compact_declaration.json", compact)
    for attempt in range(args.retries + 1):
        current_limit = int(args.max_chars)
        compact_str = compact_str_full
        if len(compact_str) > current_limit:
            raise PayloadLimitExceededError(
                file_name=path.name,
                payload_chars=len(compact_str),
                max_chars=current_limit,
            )
        sent_chars = len(compact_str)
        system_prompt, user_tmpl = pipeline_prompts_for_process(args)
        attempt_started = time.time()
        attempt_info: Dict[str, Any] = {
            "attempt": attempt + 1,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "chars_sent": len(compact_str),
            "status": "started",
        }
        try:
            user_prompt = user_tmpl.format(declaration_payload=compact_str)
        except KeyError as exc:
            raise ValueError(
                "Шаблон user-промпта пайплайну має містити плейсхолдер {declaration_payload}: "
                f"{exc}"
            ) from exc

        if getattr(args, "save_compact_declarations", False) and not audit_cfg.get(
            "enabled"
        ):
            cdir = resolve_compact_declarations_dir(
                str(getattr(args, "compact_declarations_dir", "") or "")
            )
            try:
                write_compact_declaration_snapshot(cdir, path, compact)
            except OSError as exc:
                print(
                    f"Warning: could not save compact declaration ({path.name}): {exc}"
                )

        try:
            if args.debug_payload_dir:
                debug_dir = Path(args.debug_payload_dir)
                debug_dir.mkdir(parents=True, exist_ok=True)
                debug_item = {
                    "source_file": path.name,
                    "declaration_id": raw_data.get("id"),
                    "user_declarant_id": raw_data.get("user_declarant_id"),
                    "attempt": attempt,
                    "chars_sent": len(compact_str),
                    "is_truncated": False,
                    "model": args.model,
                    "payload": compact,
                }
                debug_path = debug_dir / f"{path.stem}.attempt{attempt + 1}.json"
                debug_path.write_text(
                    json.dumps(debug_item, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            provider = str(getattr(args, "provider", "ollama") or "ollama").lower()
            if provider == "openrouter":
                # Alternative (isolated) path: neither Ollama functions nor /api/chat are involved.
                if bool(getattr(args, "reasoning_debug", False)):
                    print(
                        "[INFO] --reasoning-debug ignored: OpenRouter не підтримує Ollama-стрім reasoning."
                    )
                from openrouter_client import call_openrouter  # локальний імпорт, щоб не тягнути модуль на ollama-шляху

                or_model = str(
                    getattr(args, "openrouter_model", "") or args.model
                ).strip()
                model_result = call_openrouter(
                    model=or_model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    host=str(
                        getattr(args, "openrouter_host", "")
                        or "https://openrouter.ai/api/v1"
                    ),
                    timeout_sec=args.timeout,
                    api_key=str(getattr(args, "openrouter_api_key", "") or ""),
                    num_predict=args.num_predict,
                    model_context_length=openrouter_model_context_length(
                        args, or_model
                    ),
                    return_debug_trace=bool(audit_cfg.get("enabled")),
                    usage_snapshots=file_usage_snaps,
                )
            else:
                model_result = call_ollama(
                    model=args.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    host=args.host,
                    timeout_sec=args.timeout,
                    num_predict=args.num_predict,
                    reasoning_debug=bool(getattr(args, "reasoning_debug", False)),
                    api_key=str(getattr(args, "api_key", "") or ""),
                    cloud_mode=bool(getattr(args, "cloud_mode", False)),
                    return_debug_trace=bool(audit_cfg.get("enabled")),
                )
            if audit_cfg.get("enabled") and isinstance(model_result, dict):
                analysis = model_result.get("analysis")
                if audit_case_dir is not None:
                    if audit_cfg.get("request_payload"):
                        _write_json_file(
                            audit_case_dir / f"request_payload.attempt{attempt + 1}.json",
                            model_result.get("request_payload", {}),
                        )
                    if audit_cfg.get("response_raw"):
                        _write_json_file(
                            audit_case_dir / f"response_raw.attempt{attempt + 1}.json",
                            model_result.get("response_raw", {}),
                        )
                    if audit_cfg.get("response_parsed") and analysis is not None:
                        _write_json_file(
                            audit_case_dir / f"response_parsed.attempt{attempt + 1}.json",
                            analysis,
                        )
            else:
                analysis = model_result
            if analysis_incomplete_needs_retry(analysis):
                score = analysis.get("risk_score")
                raise IncompleteAnalysisError(
                    f"Порожній findings при risk_score={score} "
                    f"(>= {FINDINGS_RETRY_MIN_RISK_SCORE}); "
                    "ймовірно уривок відповіді або fallback reasoning-моделі."
                )
            attempt_info["status"] = "ok"
            attempt_info["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            attempt_info["duration_sec"] = round(time.time() - attempt_started, 3)
            attempt_meta.append(attempt_info)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            attempt_info["status"] = "error"
            attempt_info["error"] = str(exc)
            attempt_info["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            attempt_info["duration_sec"] = round(time.time() - attempt_started, 3)
            attempt_meta.append(attempt_info)
            if attempt >= args.retries:
                raise
            wait_sec = args.retry_delay * (attempt + 1)
            print(
                f"Retry {attempt + 1}/{args.retries} for {path.name}: {exc}. "
                f"Waiting {wait_sec}s and retrying."
            )
            time.sleep(wait_sec)

    if analysis is None:
        raise RuntimeError(f"Failed after retries: {last_error}")

    meta = compact.get("meta", {})
    declarant = meta.get("declarant", {})
    full_name = " ".join(
        str(part).strip()
        for part in [
            declarant.get("lastname", ""),
            declarant.get("firstname", ""),
            declarant.get("middlename", ""),
        ]
        if str(part).strip()
    )

    decl_type_code, decl_type_label = _declaration_type_fields_from_compact(compact)

    normalized_analysis = normalize_analysis_payload(
        analysis,
        declaration_id=raw_data.get("id"),
        user_declarant_id=raw_data.get("user_declarant_id"),
        declarant_full_name=full_name,
        position=str(declarant.get("work_post", "")).strip(),
        workplace=str(declarant.get("work_place", "")).strip(),
        declaration_year=meta.get("declaration_year"),
        declaration_type_code=decl_type_code,
        declaration_type_label=decl_type_label,
    )

    model_id, launch_mode = resolve_effective_model_and_mode(args)
    run_model_label = f"{model_id} ({launch_mode})"

    result = {
        "run_meta": {
            "run_id": args.run_id,
            "model": run_model_label,
            "model_id": model_id,
            "launch_mode": launch_mode,
            "host": run_meta_host(args),
            "started_at_utc": args.started_at_utc,
        },
        "source_file": path.name,
        "declaration_id": raw_data.get("id"),
        "user_declarant_id": raw_data.get("user_declarant_id"),
        "context_snapshot": {
            "declarant_full_name": full_name,
            "position": declarant.get("work_post", ""),
            "workplace": declarant.get("work_place", ""),
            "declaration_year": meta.get("declaration_year"),
            "declaration_type_code": decl_type_code,
            "declaration_type_label": decl_type_label,
            "payload_chars_sent": sent_chars,
            "payload_was_truncated": was_truncated,
        },
        "analysis": normalized_analysis,
        "processing_duration_sec": round(
            float(attempt_info.get("duration_sec") or 0.0), 3
        ),
    }
    if (
        str(getattr(args, "provider", "ollama") or "ollama").lower() == "openrouter"
        and file_usage_snaps
    ):
        from openrouter_client import finalize_openrouter_billing, merge_openrouter_usage_snaps

        bill_id = str(getattr(args, "openrouter_model", "") or args.model).strip()
        rates_map = getattr(args, "_openrouter_pricing_per_token", None) or {}
        merged = merge_openrouter_usage_snaps(file_usage_snaps)
        ou = finalize_openrouter_billing(
            merged, model_id=bill_id, per_token_rates=rates_map
        )
        if ou.get("cost_usd") is None and (
            int(ou.get("prompt_tokens") or 0) + int(ou.get("completion_tokens") or 0) > 0
        ):
            alt = str(file_usage_snaps[-1].get("response_model") or "").strip()
            if alt and alt != bill_id:
                ou = finalize_openrouter_billing(
                    merged, model_id=alt, per_token_rates=rates_map
                )
        result["openrouter_usage"] = ou
    if audit_cfg.get("enabled") and audit_case_dir is not None:
        if audit_cfg.get("normalized_analysis"):
            _write_json_file(audit_case_dir / "normalized_analysis.json", normalized_analysis)
        if audit_cfg.get("attempt_meta"):
            _write_json_file(
                audit_case_dir / "attempt_meta.json",
                {
                    "source_file": path.name,
                    "declaration_id": raw_data.get("id"),
                    "user_declarant_id": raw_data.get("user_declarant_id"),
                    "run_id": getattr(args, "run_id", ""),
                    "attempts": attempt_meta,
                },
            )
    return result


def append_jsonl(path: Path, item: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
        f.flush()


def _pipeline_log(message: str) -> None:
    """Stdout for the UI; no threading.Lock — otherwise a blocked pipe would stall the whole parallel queue."""
    print(message, flush=True)


_PROGRESS_TAG_RE = re.compile(r"^\[(\d+)/(\d+)\]$")


def _parse_progress_tag(progress_line: str) -> Tuple[int, int]:
    m = _PROGRESS_TAG_RE.match(str(progress_line or "").strip())
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2))


def _declaration_id_from_filename(name: str) -> str:
    base = Path(name).stem
    if base.startswith("decl_"):
        return base[5:]
    return base[:32]


def _emit_visual_log(payload: Dict[str, Any]) -> None:
    payload.setdefault("v", 1)
    _pipeline_log("VISUAL_LOG|" + json.dumps(payload, ensure_ascii=False))


def _emit_visual_run_totals(ptot: Dict[str, Any], args: argparse.Namespace) -> None:
    _pipeline_log(
        "VISUAL_RUN_TOTALS|"
        + json.dumps(
            {
                "n": int(ptot.get("n") or 0),
                "prompt_tokens": int(ptot.get("prompt_tokens") or 0),
                "completion_tokens": int(ptot.get("completion_tokens") or 0),
                "total_tokens": int(ptot.get("total_tokens") or 0),
                "cost_usd": float(ptot.get("cost_usd") or 0.0),
                "cost_known_n": int(ptot.get("cost_known_n") or 0),
                "model": build_model_label(args),
            },
            ensure_ascii=False,
        )
    )


def _visual_log_ok(
    file_path: Path,
    result: Dict[str, Any],
    progress_line: str,
    *,
    moved: bool = False,
) -> None:
    idx, tot = _parse_progress_tag(progress_line)
    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    profile = analysis.get("subject_profile") if isinstance(analysis.get("subject_profile"), dict) else {}
    findings = analysis.get("findings")
    findings_count = len(findings) if isinstance(findings, list) else 0
    usage = result.get("openrouter_usage")
    tokens: Optional[Dict[str, int]] = None
    cost_usd: Optional[float] = None
    if isinstance(usage, dict):
        pt = usage.get("prompt_tokens")
        ct = usage.get("completion_tokens")
        tt = usage.get("total_tokens")
        if pt is not None or ct is not None or tt is not None:
            tokens = {
                "prompt_tokens": int(pt or 0),
                "completion_tokens": int(ct or 0),
                "total_tokens": int(tt or 0),
            }
        c2 = usage.get("cost_usd")
        if c2 is not None:
            cost_usd = float(c2)
    decl_id = str(profile.get("declaration_id") or "").strip() or _declaration_id_from_filename(
        file_path.name
    )
    year_raw = profile.get("declaration_year")
    year = int(year_raw) if year_raw not in (None, "", 0) else None
    _emit_visual_log(
        {
            "status": "OK",
            "index": idx,
            "total": tot,
            "source_file": file_path.name,
            "declaration_id": decl_id,
            "name": str(profile.get("declarant_full_name") or "").strip(),
            "position": str(profile.get("position") or "").strip(),
            "workplace": str(profile.get("workplace") or "").strip(),
            "year": year,
            "score": analysis.get("risk_score"),
            "findings_count": findings_count,
            "cost_usd": cost_usd,
            "tokens": tokens,
            "moved": bool(moved),
            "duration_sec": result.get("processing_duration_sec"),
        }
    )


def _error_kind_for_exc(exc: Exception) -> str:
    return "limit" if isinstance(exc, PayloadLimitExceededError) else "err"


def _visual_log_err(
    file_path: Path,
    exc: Exception,
    progress_line: str,
    *,
    action_required: bool = False,
    resolution: Optional[str] = None,
    preview: Optional[Dict[str, Any]] = None,
) -> None:
    idx, tot = _parse_progress_tag(progress_line)
    prev = preview or {}
    payload: Dict[str, Any] = {
        "status": "ERR",
        "index": idx,
        "total": tot,
        "source_file": file_path.name,
        "declaration_id": str(prev.get("declaration_id") or "").strip()
        or _declaration_id_from_filename(file_path.name),
        "name": str(prev.get("name") or "").strip(),
        "position": str(prev.get("position") or "").strip(),
        "workplace": str(prev.get("workplace") or "").strip(),
        "year": prev.get("year"),
        "moved": False,
        "error": str(exc),
        "error_kind": _error_kind_for_exc(exc),
    }
    if action_required:
        payload["action_required"] = True
    if resolution:
        payload["resolution"] = resolution
        payload["action_required"] = False
    _emit_visual_log(payload)


def _subject_preview_from_declaration_file(
    file_path: Path, args: argparse.Namespace
) -> Dict[str, Any]:
    raw_data = json.loads(file_path.read_text(encoding="utf-8"))
    compact = compact_declaration(
        raw_data,
        legacy_payload=bool(getattr(args, "compact_legacy_payload", False)),
    )
    meta = compact.get("meta", {}) if isinstance(compact.get("meta"), dict) else {}
    declarant = meta.get("declarant", {}) if isinstance(meta.get("declarant"), dict) else {}
    full_name = " ".join(
        str(part).strip()
        for part in [
            declarant.get("lastname", ""),
            declarant.get("firstname", ""),
            declarant.get("middlename", ""),
        ]
        if str(part).strip()
    )
    year_raw = meta.get("declaration_year")
    year = int(year_raw) if year_raw not in (None, "", 0) else None
    decl_id = str(raw_data.get("id") or "").strip() or _declaration_id_from_filename(
        file_path.name
    )
    return {
        "source_file": file_path.name,
        "declaration_id": decl_id,
        "name": full_name,
        "position": str(declarant.get("work_post", "")).strip(),
        "workplace": str(declarant.get("work_place", "")).strip(),
        "year": year,
    }


def _visual_log_processing(
    file_path: Path, progress_line: str, args: argparse.Namespace
) -> None:
    idx, tot = _parse_progress_tag(progress_line)
    try:
        preview = _subject_preview_from_declaration_file(file_path, args)
    except Exception:  # noqa: BLE001
        preview = {
            "source_file": file_path.name,
            "declaration_id": _declaration_id_from_filename(file_path.name),
            "name": "",
            "position": "",
            "workplace": "",
            "year": None,
        }
    _emit_visual_log(
        {
            "status": "PROCESSING",
            "index": idx,
            "total": tot,
            "moved": False,
            **preview,
        }
    )


def _visual_log_limit(
    file_path: Path,
    progress_line: str,
    limit_exc: PayloadLimitExceededError,
    *,
    action_required: bool = False,
    resolution: Optional[str] = None,
    preview: Optional[Dict[str, Any]] = None,
) -> None:
    idx, tot = _parse_progress_tag(progress_line)
    prev = preview or {}
    payload: Dict[str, Any] = {
        "status": "LIMIT_EXCEEDED",
        "index": idx,
        "total": tot,
        "source_file": file_path.name,
        "declaration_id": str(prev.get("declaration_id") or "").strip()
        or _declaration_id_from_filename(file_path.name),
        "name": str(prev.get("name") or "").strip(),
        "position": str(prev.get("position") or "").strip(),
        "workplace": str(prev.get("workplace") or "").strip(),
        "year": prev.get("year"),
        "moved": False,
        "error_kind": "limit",
        "limit": {
            "payload_chars": int(limit_exc.payload_chars),
            "max_chars": int(limit_exc.max_chars),
            "recommended_max_chars": int(limit_exc.recommended_max_chars),
        },
    }
    if action_required:
        payload["action_required"] = True
    if resolution:
        payload["resolution"] = resolution
        payload["action_required"] = False
    _emit_visual_log(payload)


def _effective_max_concurrent_declarations(args: argparse.Namespace) -> int:
    """Parallelism only for OpenRouter and only with --on-limit skip|fail-run (avoids a race on args.max_chars)."""
    try:
        raw = int(getattr(args, "max_concurrent_declarations", 1) or 1)
    except (TypeError, ValueError):
        raw = 1
    if raw < 1:
        raw = 1
    if raw > 8:
        raw = 8
    provider = str(getattr(args, "provider", "ollama") or "ollama").lower()
    if provider != "openrouter":
        if raw > 1:
            print(
                "[INFO] Паралельна обробка декларацій ігнорується "
                "(доступна лише з --provider=openrouter)."
            )
        return 1
    if str(getattr(args, "on_limit", "") or "") not in ("skip", "fail-run"):
        if raw > 1:
            print(
                "[WARN] Паралельна обробка вимкнена: для --on-limit ask або auto-raise-32000 "
                "потрібна послідовна обробка (спільний --max-chars)."
            )
        return 1
    return raw


def _try_process_file_with_limits(
    file_path: Path,
    args: argparse.Namespace,
    io_lock: threading.Lock,
    progress_tag: str,
) -> Tuple[str, Optional[Dict[str, Any]], Optional[Exception]]:
    """One file: process_file + PayloadLimitExceeded branches. Prints under io_lock where needed."""
    _visual_log_processing(file_path, progress_tag, args)
    try:
        try:
            result = process_file(file_path, args)
        except PayloadLimitExceededError as limit_exc:
            _pipeline_log(
                f"{progress_tag} LIMIT_EXCEEDED {file_path.name} "
                f"payload={limit_exc.payload_chars} max={limit_exc.max_chars} "
                f"recommended={limit_exc.recommended_max_chars}"
            )
            _pipeline_log(
                "LIMIT_EXCEEDED_EVENT|"
                f"{file_path.name}|{limit_exc.payload_chars}|"
                f"{limit_exc.max_chars}|{limit_exc.recommended_max_chars}"
            )
            if args.on_limit == "auto-raise-32000":
                old_max = args.max_chars
                args.max_chars = max(int(args.max_chars), 32000)
                _pipeline_log(
                    f"Auto-raise max_chars {old_max} -> {args.max_chars} "
                    f"for {file_path.name}, retrying."
                )
                result = process_file(file_path, args)
            elif args.on_limit == "skip":
                _pipeline_log(f"Skipping {file_path.name} due to payload limit.")
                _visual_log_limit(file_path, progress_tag, limit_exc)
                return ("skip", None, None)
            elif args.on_limit == "fail-run":
                return ("error", None, limit_exc)
            else:
                _pipeline_log(
                    f"Awaiting decision for {file_path.name}: "
                    "limit_raise_32000 or limit_skip (via control file)."
                )
                decision = wait_for_limit_decision(
                    str(getattr(args, "control_file", "") or ""), timeout_sec=180
                )
                if decision == "stop":
                    _pipeline_log("Stop requested. Finishing run safely.")
                    return ("stop", None, None)
                if decision == "skip":
                    _pipeline_log(f"Skipping {file_path.name} by user decision.")
                    _visual_log_limit(file_path, progress_tag, limit_exc)
                    return ("skip", None, None)
                if decision == "timeout":
                    _pipeline_log(
                        "No UI decision received in time. "
                        "Auto-raising max_chars to 32000."
                    )
                old_max = args.max_chars
                args.max_chars = max(int(args.max_chars), 32000)
                _pipeline_log(
                    f"Decision: raise max_chars {old_max} -> {args.max_chars} "
                    f"for {file_path.name}, retrying."
                )
                result = process_file(file_path, args)
        return ("ok", result, None)
    except Exception as exc:  # noqa: BLE001
        return ("error", None, exc)


def resolve_compact_declarations_dir(path_str: str) -> Path:
    """Relative path — from the main.py directory (project root during a normal run)."""
    raw = (path_str or "").strip() or "оброблені декларації/compact"
    p = Path(raw)
    if p.is_absolute():
        return p
    return Path(__file__).resolve().parent / p


def write_compact_declaration_snapshot(
    dest_root: Path,
    source_file: Path,
    compact: Dict[str, Any],
) -> None:
    dest_root.mkdir(parents=True, exist_ok=True)
    out_path = dest_root / source_file.name
    out_path.write_text(
        json.dumps(compact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def move_processed_declaration(
    source: Path,
    *,
    input_dir: Path,
    processed_dir: Path,
) -> Optional[Path]:
    """
    Move a successfully analyzed JSON out of input_dir into processed_dir.
    Returns the destination path, or None if the move was skipped.
    """
    try:
        dest_root = processed_dir.expanduser().resolve()
        in_root = input_dir.expanduser().resolve()
        src_parent = source.resolve().parent
    except OSError as exc:
        print(f"Warning: cannot resolve paths for move: {exc}")
        return None

    if dest_root == in_root:
        print(
            "Warning: --processed-dir is the same as --input-dir; "
            "skipping move to avoid clobbering sources."
        )
        return None

    if src_parent != in_root:
        print(
            f"Warning: {source.name} is not a direct child of --input-dir; "
            "skipping move."
        )
        return None

    try:
        dest_root.mkdir(parents=True, exist_ok=True)
        target = dest_root / source.name
        if target.exists():
            target = dest_root / f"{source.stem}_{uuid4().hex[:8]}{source.suffix}"
        shutil.move(str(source), str(target))
    except OSError as exc:
        print(f"Warning: could not move {source.name} to {dest_root}: {exc}")
        return None

    return target


def read_control_payload(control_file: str) -> Dict[str, Any]:
    if not control_file:
        return {}
    path = Path(control_file)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def read_control_command(control_file: str) -> str:
    return str(read_control_payload(control_file).get("command", "")).strip().lower()


def write_control_ack(control_file: str) -> None:
    if not control_file:
        return
    try:
        Path(control_file).write_text(
            json.dumps({"command": "run"}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def wait_for_error_action(
    control_file: str, pending_names: set[str]
) -> Dict[str, Any]:
    """Waits for error_action on one of the pending files. Returns the payload or stop."""
    while True:
        data = read_control_payload(control_file)
        cmd = str(data.get("command", "")).strip().lower()
        if cmd == "stop":
            return {"action": "stop"}
        if cmd == "error_action":
            file_name = str(data.get("file", "")).strip()
            action = str(data.get("action", "")).strip().lower()
            if file_name in pending_names and action in {
                "retry",
                "raise_limits",
                "ignore",
            }:
                out: Dict[str, Any] = {
                    "action": action,
                    "file": file_name,
                }
                if data.get("max_chars") is not None:
                    out["max_chars"] = int(data["max_chars"])
                if data.get("num_predict") is not None:
                    out["num_predict"] = int(data["num_predict"])
                return out
        time.sleep(0.35)


def wait_if_paused(control_file: str) -> bool:
    # Returns False when stop was requested.
    while True:
        cmd = read_control_command(control_file)
        if cmd == "stop":
            return False
        if cmd != "pause":
            return True
        time.sleep(0.5)


def wait_for_limit_decision(control_file: str, timeout_sec: int = 180) -> str:
    # Returns one of: raise_32000, skip, stop, timeout
    started = time.monotonic()
    while True:
        if time.monotonic() - started >= max(1, int(timeout_sec)):
            return "timeout"
        cmd = read_control_command(control_file)
        if cmd == "stop":
            return "stop"
        if cmd in {"limit_raise_32000", "raise_32000"}:
            return "raise_32000"
        if cmd in {"limit_skip", "skip"}:
            return "skip"
        time.sleep(0.5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze NACP declarations with local Llama via Ollama."
    )
    parser.add_argument(
        "--input-dir",
        default="dataset_declarations",
        help="Directory with declaration JSON files.",
    )
    parser.add_argument(
        "--output",
        default="analysis_results.jsonl",
        help="Output JSONL file for successful analyses.",
    )
    parser.add_argument(
        "--errors-output",
        default="analysis_errors.jsonl",
        help="Output JSONL file for processing errors.",
    )
    parser.add_argument(
        "--model",
        default="llama3.1",
        help="Ollama model name (example: llama3.1:8b, mistral:7b).",
    )
    parser.add_argument(
        "--host",
        default="http://127.0.0.1:11434",
        help="Ollama host URL.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Timeout per declaration in seconds.",
    )
    parser.add_argument(
        "--num-predict",
        type=int,
        default=16000,
        help=(
            "Ollama num_predict: max tokens in the model reply; "
            "<0 (наприклад -1) — без штучного ліміту в застосунку. "
            "Малі позитивні значення часто обрізають JSON і дають помилки парсингу."
        ),
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Limit number of files to process (0 = all).",
    )
    parser.add_argument(
        "--selected-files",
        default="",
        help=(
            "Comma-separated filenames under --input-dir to process; "
            "order is preserved; ignores --max-files cap."
        ),
    )
    parser.add_argument(
        "--sort-order",
        default="alpha",
        choices=["alpha", "alpha-desc", "mtime", "mtime-asc", "size", "size-asc"],
        help=(
            "File order when --selected-files is empty. "
            "alpha/alpha-desc — by name asc/desc; "
            "mtime/mtime-asc — newest/oldest first; "
            "size/size-asc — largest/smallest first."
        ),
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=64000,
        help="Max characters of compact declaration payload sent to model.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Retries per file on transient failures (timeout/network).",
    )
    parser.add_argument(
        "--retry-delay",
        type=int,
        default=5,
        help="Base delay in seconds between retries.",
    )
    parser.add_argument(
        "--debug-payload-dir",
        default="",
        help=(
            "Optional directory to save exact payload sent to model for each file "
            "(for diagnostics)."
        ),
    )
    parser.add_argument(
        "--control-file",
        default="",
        help="Optional JSON control file for pause/resume/stop.",
    )
    parser.add_argument(
        "--processed-dir",
        default="",
        help=(
            "If set, each successfully analyzed JSON is moved from --input-dir "
            "into this directory so it is not picked up on the next run."
        ),
    )
    parser.add_argument(
        "--save-compact-declarations",
        dest="save_compact_declarations",
        action="store_true",
        help="Зберігати компактний JSON у каталозі --compact-declarations-dir перед запитом до моделі.",
    )
    parser.add_argument(
        "--no-save-compact-declarations",
        dest="save_compact_declarations",
        action="store_false",
        help="Не зберігати компактний JSON перед відправкою до моделі.",
    )
    parser.add_argument(
        "--compact-legacy-payload",
        dest="compact_legacy_payload",
        action="store_true",
        help="Додати all_nonempty_steps_payload (повна сира копія кроків) поряд із compact v2.",
    )
    parser.add_argument(
        "--no-compact-legacy-payload",
        dest="compact_legacy_payload",
        action="store_false",
        help="Не додавати all_nonempty_steps_payload (default compact v2).",
    )
    parser.add_argument(
        "--compact-declarations-dir",
        default="оброблені декларації/compact",
        help=(
            "Каталог для збереження компактних декларацій "
            "(відносний — від кореня проєкту, поруч із main.py)."
        ),
    )
    parser.add_argument(
        "--audit-mode",
        action="store_true",
        help="Enable debug-only audit capture artifacts (isolated from normal outputs).",
    )
    parser.add_argument(
        "--audit-mode-dir",
        default="audit",
        help="Root directory for per-declaration audit artifacts.",
    )
    parser.set_defaults(
        save_compact_declarations=False,
        compact_legacy_payload=False,
        audit_capture_raw_declaration=False,
        audit_capture_compact_declaration=False,
        audit_capture_request_payload=False,
        audit_capture_response_raw=False,
        audit_capture_response_parsed=False,
        audit_capture_normalized_analysis=False,
        audit_capture_attempt_meta=False,
    )
    parser.add_argument("--audit-capture-raw-declaration", dest="audit_capture_raw_declaration", action="store_true")
    parser.add_argument("--audit-capture-compact-declaration", dest="audit_capture_compact_declaration", action="store_true")
    parser.add_argument("--audit-capture-request-payload", dest="audit_capture_request_payload", action="store_true")
    parser.add_argument("--audit-capture-response-raw", dest="audit_capture_response_raw", action="store_true")
    parser.add_argument("--audit-capture-response-parsed", dest="audit_capture_response_parsed", action="store_true")
    parser.add_argument("--audit-capture-normalized-analysis", dest="audit_capture_normalized_analysis", action="store_true")
    parser.add_argument("--audit-capture-attempt-meta", dest="audit_capture_attempt_meta", action="store_true")
    parser.add_argument(
        "--on-limit",
        default="auto-raise-32000",
        choices=["auto-raise-32000", "ask", "skip", "fail-run"],
        help=(
            "Behavior when payload exceeds --max-chars: auto-raise-32000 (default), "
            "ask (wait control file decision), skip (skip file), fail-run (abort run)."
        ),
    )
    parser.add_argument(
        "--reasoning-debug",
        action="store_true",
        help=(
            "Debug mode: request streaming reasoning from compatible models and "
            "emit THINK_EVENT lines to stdout. Keeps normal mode unchanged."
        ),
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Optional bearer API key for cloud Ollama endpoints.",
    )
    parser.add_argument(
        "--cloud-mode",
        action="store_true",
        help="Flag for cloud endpoint mode (logging/UX only; local flow unchanged).",
    )
    # ── Alternative provider (OpenRouter). Does not change the Ollama path in any way:
    # when --provider=ollama (default), everything below works as before. When
    # --provider=openrouter — the pipeline calls openrouter_client.call_openrouter
    # instead of call_ollama. Both paths are fully isolated.
    parser.add_argument(
        "--provider",
        default="ollama",
        choices=["ollama", "openrouter"],
        help="LLM провайдер: ollama (default) або openrouter (OpenAI-сумісний альтернативний шлях).",
    )
    parser.add_argument(
        "--openrouter-host",
        default="https://openrouter.ai/api/v1",
        help="OpenRouter API base URL. Використовується лише при --provider=openrouter.",
    )
    parser.add_argument(
        "--openrouter-model",
        default="",
        help="OpenRouter model id (наприклад meta-llama/llama-3.3-70b-instruct). Використовується лише при --provider=openrouter.",
    )
    parser.add_argument(
        "--openrouter-api-key",
        default="",
        help="OpenRouter API key (sk-or-v1-...). Використовується лише при --provider=openrouter.",
    )
    parser.add_argument(
        "--prompt-overrides",
        dest="prompt_overrides_file",
        default="",
        help=(
            "JSON file with optional keys pipeline_system_prompt, "
            "pipeline_user_prompt_template, dossier_* (debug session only)."
        ),
    )
    parser.add_argument(
        "--max-concurrent-declarations",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Скільки декларацій обробляти паралельно (лише --provider=openrouter; "
            "1 як раніше; макс. 8). Ігнорується для Ollama та при --on-limit ask або auto-raise-32000."
        ),
    )
    return parser


def main() -> None:
    # Windows + pipe to webview: default cp1251 — print() fails on characters like "≈" in OpenRouter logs.
    if sys.platform == "win32":
        for _stream in (sys.stdout, sys.stderr):
            try:
                if _stream is not None and hasattr(_stream, "reconfigure"):
                    _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    parser = build_parser()
    args = parser.parse_args()
    if str(getattr(args, "provider", "ollama") or "ollama").lower() == "openrouter":
        args.openrouter_api_key = resolve_openrouter_api_key(
            str(getattr(args, "openrouter_api_key", "") or "")
        )
    args.run_id = uuid4().hex[:12]
    args.started_at_utc = datetime.now(timezone.utc).isoformat()

    args.prompt_overrides = load_prompt_overrides_file(
        str(getattr(args, "prompt_overrides_file", "") or "")
    )
    if args.prompt_overrides:
        print(
            "[INFO] Промпти сесії (перевизначення): "
            + ", ".join(sorted(args.prompt_overrides.keys()))
        )

    input_dir = Path(args.input_dir)
    output_path = Path(args.output)
    errors_path = Path(args.errors_output)

    if not input_dir.exists():
        raise SystemExit(f"Input directory does not exist: {input_dir}")

    files = iter_json_files(input_dir)

    resume_mid, resume_lm = resolve_effective_model_and_mode(args)
    already_done = load_processed_filenames(output_path, resume_mid, resume_lm)
    if already_done:
        before = len(files)
        files = [f for f in files if f.name not in already_done]
        skipped = before - len(files)
        if skipped:
            print(f"Resume: skipping {skipped} already-processed file(s).")

    selected_spec = (getattr(args, "selected_files", None) or "").strip()
    if selected_spec:
        order_list = [n.strip() for n in selected_spec.split(",") if n.strip()]
        names_set = set(order_list)
        files = [f for f in files if f.name in names_set]
        order_map = {n: i for i, n in enumerate(order_list)}
        files.sort(key=lambda f: order_map.get(f.name, 9999))
    elif is_under_project_deep_research(input_dir):
        files = sort_declaration_files_chronologically(files)
        print("Deep research: порядок обробки — за declaration_year та date (найстаріші спочатку).")
    elif args.sort_order == "alpha-desc":
        files.sort(key=lambda f: f.name, reverse=True)
    elif args.sort_order == "mtime":
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    elif args.sort_order == "mtime-asc":
        files.sort(key=lambda f: f.stat().st_mtime)
    elif args.sort_order == "size":
        files.sort(key=lambda f: f.stat().st_size, reverse=True)
    elif args.sort_order == "size-asc":
        files.sort(key=lambda f: f.stat().st_size)

    if not selected_spec and args.max_files > 0:
        files = files[: args.max_files]

    if not files:
        raise SystemExit(f"No JSON files found in {input_dir} (or all already processed).")

    print(f"Run {args.run_id}: found {len(files)} declaration files.", flush=True)
    _pipeline_log(f"PIPELINE_TOTAL|{len(files)}")
    started = time.time()
    success = 0
    failed = 0

    io_lock = threading.Lock()
    control_file = str(getattr(args, "control_file", "") or "")
    max_workers = _effective_max_concurrent_declarations(args)
    total_n = len(files)

    from openrouter_client import (
        format_openrouter_run_totals_footer,
        format_openrouter_usage_log_suffix,
    )

    setattr(args, "_openrouter_pricing_per_token", {})
    setattr(args, "_openrouter_context_length", {})
    setattr(args, "_openrouter_pipeline_totals", None)
    if str(getattr(args, "provider", "ollama") or "ollama").lower() == "openrouter":
        setattr(
            args,
            "_openrouter_pipeline_totals",
            {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "cost_known_n": 0,
                "n": 0,
            },
        )
        try:
            from openrouter_client import fetch_openrouter_models_enriched

            enr = fetch_openrouter_models_enriched(
                str(
                    getattr(args, "openrouter_host", "")
                    or "https://openrouter.ai/api/v1"
                ),
                str(getattr(args, "openrouter_api_key", "") or ""),
            )
            setattr(
                args,
                "_openrouter_pricing_per_token",
                enr.get("pricing_per_token") or {},
            )
            setattr(
                args,
                "_openrouter_context_length",
                enr.get("context_length") or {},
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"[WARN] Не вдалося завантажити прайс OpenRouter /models: {exc}",
                flush=True,
            )

    pending_errors: List[Dict[str, Any]] = []
    interactive_review = bool(control_file)

    def _preview_for_path(fp: Path) -> Dict[str, Any]:
        try:
            return _subject_preview_from_declaration_file(fp, args)
        except Exception:  # noqa: BLE001
            return {}

    def _emit_ignored_visual(pe: Dict[str, Any]) -> None:
        fp = pe["path"]
        tag = pe["progress_line"]
        exc = pe["exc"]
        preview = pe.get("preview") or _preview_for_path(fp)
        if pe.get("kind") == "limit":
            _visual_log_limit(
                fp,
                tag,
                exc,
                resolution="ignored",
                preview=preview,
            )
        else:
            _visual_log_err(
                fp,
                exc,
                tag,
                resolution="ignored",
                preview=preview,
            )

    def _queue_pending_error(
        file_path: Path, exc: Exception, progress_line: str
    ) -> None:
        kind = _error_kind_for_exc(exc)
        preview = _preview_for_path(file_path)
        pending_errors.append(
            {
                "path": file_path,
                "progress_line": progress_line,
                "exc": exc,
                "kind": kind,
                "preview": preview,
            }
        )
        if kind == "limit":
            _visual_log_limit(
                file_path,
                progress_line,
                exc,
                action_required=True,
                preview=preview,
            )
        else:
            _visual_log_err(
                file_path,
                exc,
                progress_line,
                action_required=True,
                preview=preview,
            )

    def _commit_error(file_path: Path, exc: Exception, progress_line: str) -> None:
        nonlocal failed
        err_model_id, err_launch_mode = resolve_effective_model_and_mode(args)
        error_item = {
            "run_meta": {
                "run_id": args.run_id,
                "model": build_model_label(args),
                "model_id": err_model_id,
                "launch_mode": err_launch_mode,
                "host": run_meta_host(args),
                "started_at_utc": args.started_at_utc,
            },
            "source_file": file_path.name,
            "error": str(exc),
            "failed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        with io_lock:
            failed += 1
            append_jsonl(errors_path, error_item)
        _pipeline_log(f"{progress_line} ERR {file_path.name}: {exc}")
        if interactive_review:
            _queue_pending_error(file_path, exc, progress_line)
        else:
            _visual_log_err(file_path, exc, progress_line)

    def _run_error_review_phase() -> None:
        if not interactive_review or not pending_errors:
            return
        _pipeline_log(
            "PIPELINE_ERR_REVIEW|"
            + json.dumps(
                {
                    "count": len(pending_errors),
                    "files": [pe["path"].name for pe in pending_errors],
                },
                ensure_ascii=False,
            )
        )
        _pipeline_log(
            "[INFO] Потрібні рішення по помилках — перемкніть на «Картки» у візуальному лозі."
        )
        while pending_errors:
            pending_names = {pe["path"].name for pe in pending_errors}
            action = wait_for_error_action(control_file, pending_names)
            if action.get("action") == "stop":
                _pipeline_log("Stop requested during error review.")
                break
            file_name = str(action.get("file", "")).strip()
            pe = next(
                (p for p in pending_errors if p["path"].name == file_name),
                None,
            )
            if pe is None:
                write_control_ack(control_file)
                continue
            act = str(action.get("action", "")).strip().lower()
            if act == "ignore":
                _emit_ignored_visual(pe)
                pending_errors.remove(pe)
                write_control_ack(control_file)
                continue
            if act in {"retry", "raise_limits"}:
                if pe.get("kind") == "limit" and act == "retry":
                    write_control_ack(control_file)
                    continue
                if action.get("max_chars") is not None:
                    args.max_chars = max(
                        int(args.max_chars),
                        int(action["max_chars"]),
                    )
                if action.get("num_predict") is not None:
                    args.num_predict = max(
                        int(args.num_predict),
                        int(action["num_predict"]),
                    )
                if act == "raise_limits" and isinstance(
                    pe["exc"], PayloadLimitExceededError
                ):
                    rec = int(pe["exc"].recommended_max_chars)
                    args.max_chars = max(int(args.max_chars), rec)
                _pipeline_log(
                    f"[INFO] Повторна спроба для {file_name} "
                    f"(max_chars={args.max_chars}, num_predict={args.num_predict})."
                )
                kind, result, err = _try_process_file_with_limits(
                    pe["path"], args, io_lock, pe["progress_line"]
                )
                write_control_ack(control_file)
                if kind == "ok" and result is not None:
                    pending_errors.remove(pe)
                    _commit_success(pe["path"], result, pe["progress_line"])
                elif kind == "skip":
                    pending_errors.remove(pe)
                else:
                    new_exc = err or pe["exc"]
                    pe["exc"] = new_exc
                    preview = pe.get("preview") or _preview_for_path(pe["path"])
                    if isinstance(new_exc, PayloadLimitExceededError):
                        pe["kind"] = "limit"
                        _visual_log_limit(
                            pe["path"],
                            pe["progress_line"],
                            new_exc,
                            action_required=True,
                            preview=preview,
                        )
                    else:
                        pe["kind"] = "err"
                        _visual_log_err(
                            pe["path"],
                            new_exc,
                            pe["progress_line"],
                            action_required=True,
                            preview=preview,
                        )

    def _commit_success(file_path: Path, result: Dict[str, Any], progress_line: str) -> None:
        nonlocal success
        with io_lock:
            append_jsonl(output_path, result)
            success += 1
        score = result.get("analysis", {}).get("risk_score")
        usage = result.get("openrouter_usage")
        extra = ""
        if isinstance(usage, dict):
            suffix = format_openrouter_usage_log_suffix(usage)
            if suffix:
                extra = f" | OpenRouter: {suffix}"
        with io_lock:
            tot = getattr(args, "_openrouter_pipeline_totals", None)
            if isinstance(tot, dict) and isinstance(usage, dict):
                tot["prompt_tokens"] = int(tot.get("prompt_tokens") or 0) + int(
                    usage.get("prompt_tokens") or 0
                )
                tot["completion_tokens"] = int(tot.get("completion_tokens") or 0) + int(
                    usage.get("completion_tokens") or 0
                )
                tot["total_tokens"] = int(tot.get("total_tokens") or 0) + int(
                    usage.get("total_tokens") or 0
                )
                c2 = usage.get("cost_usd")
                if c2 is not None:
                    tot["cost_usd"] = float(tot.get("cost_usd") or 0.0) + float(c2)
                    tot["cost_known_n"] = int(tot.get("cost_known_n") or 0) + 1
                tot["n"] = int(tot.get("n") or 0) + 1
        _pipeline_log(f"{progress_line} OK {file_path.name} risk_score={score}{extra}")
        moved = False
        proc_arg = str(getattr(args, "processed_dir", "") or "").strip()
        if proc_arg:
            moved_to = move_processed_declaration(
                file_path,
                input_dir=input_dir,
                processed_dir=Path(proc_arg),
            )
            if moved_to is not None:
                moved = True
                _pipeline_log(f"    moved -> {moved_to}")
        _visual_log_ok(file_path, result, progress_line, moved=moved)

    if max_workers <= 1:
        for index, file_path in enumerate(files, start=1):
            if not wait_if_paused(control_file):
                print("Stop requested. Finishing run safely.", flush=True)
                break
            tag = f"[{index}/{total_n}]"
            kind, result, err = _try_process_file_with_limits(file_path, args, io_lock, tag)
            if kind == "stop":
                break
            if kind == "skip":
                continue
            if kind == "error":
                _commit_error(file_path, err or RuntimeError("unknown"), tag)
                continue
            assert result is not None
            _commit_success(file_path, result, tag)
    else:
        from collections import deque

        print(
            f"[INFO] Паралельна обробка: до {max_workers} декларацій одночасно (OpenRouter).",
            flush=True,
        )
        queue: deque[Tuple[int, Path]] = deque((i, p) for i, p in enumerate(files, start=1))
        in_flight: dict = {}
        stop_submitting = False
        completed_fin = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            def submit_jobs() -> None:
                nonlocal stop_submitting
                while len(in_flight) < max_workers and queue and not stop_submitting:
                    if not wait_if_paused(control_file):
                        stop_submitting = True
                        queue.clear()
                        return
                    job_index, fp = queue.popleft()
                    fut = executor.submit(
                        _try_process_file_with_limits,
                        fp,
                        args,
                        io_lock,
                        f"[{job_index}/{total_n}]",
                    )
                    in_flight[fut] = (job_index, fp)

            while in_flight or (queue and not stop_submitting):
                submit_jobs()
                if not in_flight:
                    if not queue:
                        break
                    continue
                done, _ = wait(list(in_flight.keys()), return_when=FIRST_COMPLETED)
                for fut in done:
                    pair = in_flight.pop(fut, None)
                    if pair is None:
                        continue
                    job_index, fp = pair
                    try:
                        kind, result, err = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        kind, result, err = ("error", None, exc)
                    with io_lock:
                        completed_fin += 1
                        cur = completed_fin
                    tag = f"[{cur}/{total_n}]"
                    if kind == "stop":
                        with io_lock:
                            stop_submitting = True
                            queue.clear()
                    elif kind == "skip":
                        pass
                    elif kind == "error":
                        _commit_error(fp, err or RuntimeError("unknown"), tag)
                    else:
                        assert result is not None
                        _commit_success(fp, result, tag)
                submit_jobs()

    _run_error_review_phase()

    elapsed = time.time() - started
    print(
        f"Done in {elapsed:.1f}s. success={success}, failed={failed}, "
        f"output={output_path}, errors={errors_path}"
    )
    ptot = getattr(args, "_openrouter_pipeline_totals", None)
    if isinstance(ptot, dict) and int(ptot.get("n") or 0) > 0:
        print(
            format_openrouter_run_totals_footer(
                ptot,
                unit_label="декларацій",
                scope_title="цей пайплайн",
            ),
            flush=True,
        )
        _emit_visual_run_totals(ptot, args)


if __name__ == "__main__":
    main()
