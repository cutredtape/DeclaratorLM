"""Клієнт TypeSafe Jev (System One) — типізовані рішення замість тексту.

Jev не генерує текст: на вхід іде `state` (у нас — compact v2 як JSON-об'єкт)
і набір питань, на вихід — ймовірності. Три примітиви:

  * **noul**  — так/ні → ймовірність, що твердження істинне;
  * **score** — 2-10 впорядкованих рівнів → бал, розподіл по рівнях, впевненість;
  * **choice** — вибір однієї опції → розподіл + впевненість (нами не
    використовується: жодне рішення в задачі тріажу не є вибором однієї опції).

Усі питання одного запиту рахуються за один прохід, тому шість питань коштують
майже стільки ж часу, скільки одне.

Модуль навмисно тримає **весь Jev-специфічний словник** — і транспорт, і
переклад відповіді у форму, яку очікує `normalize_analysis_payload()`. Завдяки
цьому гілка `jev` у `main.process_file()` лишається короткою, а решта пайплайну
про Jev не знає взагалі.

Лише stdlib, як і `openrouter_client.py`.

Опис інтеграції й шарів: docs/JEV.md.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# OpenRouter віддає Jev через окремий alpha-ендпоінт, а не /chat/completions:
# модальність у нього `text->decisions`, і chat-параметрів він не приймає.
# Тіло запиту те саме, що в рідному API TypeSafe (`POST /v1/systemone`), —
# різниця лише в шляху, тому URL задається цілком, а не збирається з host.
DEFAULT_JEV_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_JEV_MODEL = "typesafe/jev-1.13"

# Перевірено живими викликами 22.09.2026 (див. специфікацію, §6):
#   noul  → {"type":"noul","noul":0.56}
#   score → {"type":"score","score":1.3,
#            "legend":{"0":"low",...},"probabilities":{"0":0.25,...},
#            "confidence":0.12}
# `probabilities` ключується ІНДЕКСОМ рівня, а не назвою; назву дає `legend`.

# Межі рівнів ризику беруться з main.normalize_risk_level (<40 low, 40-74
# medium, >=75 high). Дублювати їх тут не можна — див. _risk_level_for_score().
LEVEL_MIDPOINTS: Dict[str, int] = {
    "low": 15,
    "medium": 50,
    "high": 80,
    "critical": 95,
}

# 52x — Cloudflare-проксі перед ендпоінтом (520 трапляється живцем:
# "Web Server Returned an Unknown Error"), так само транзієнтне,
# як 502/503, просто інший шар — вартий ретраю з тієї самої причини.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 520, 521, 522, 523, 524})


class JevError(RuntimeError):
    """Помилка виклику Jev (мережа, HTTP, або невпізнана форма відповіді)."""


# ---------------------------------------------------------------------------
# Транспорт
# ---------------------------------------------------------------------------


def _post_json(
    url: str,
    payload: Dict[str, Any],
    *,
    api_key: str,
    timeout_sec: int,
) -> Tuple[Dict[str, Any], int]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "DeclaratorLM/0.9 (+github.com/declarator-lm)",
        },
    )
    started = time.time()
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    latency_ms = int(round((time.time() - started) * 1000))
    try:
        return json.loads(raw), latency_ms
    except json.JSONDecodeError as exc:
        raise JevError(f"Jev повернув не-JSON ({len(raw)} симв.): {exc}") from exc


def call_jev(
    state: Any,
    questions: Dict[str, Dict[str, Any]],
    *,
    model: str = DEFAULT_JEV_MODEL,
    url: str = DEFAULT_JEV_URL,
    api_key: str = "",
    timeout_sec: int = 60,
    retries: int = 3,
    retry_delay: float = 2.0,
) -> Dict[str, Any]:
    """Виклик decision-моделі. Повертає сиру відповідь плюс `_latency_ms`.

    Ретраї на 429/5xx з повагою до `Retry-After`, за тим самим правилом, що і в
    `nazk_parser/nazk_client.py` (клемп 8-120с для 429).
    """
    if not api_key:
        raise JevError(
            "Немає ключа для Jev. Через OpenRouter підходить `openrouter_api_key` "
            "з .declarator_secrets.json."
        )
    payload = {"model": model, "state": state, "questions": questions}

    last_error: Optional[BaseException] = None
    for attempt in range(max(1, retries) + 1):
        try:
            data, latency_ms = _post_json(
                url, payload, api_key=api_key, timeout_sec=timeout_sec
            )
            data["_latency_ms"] = latency_ms
            return data
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in RETRY_STATUSES or attempt >= retries:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:400]
                except Exception:
                    pass
                raise JevError(f"Jev HTTP {exc.code}: {detail or exc.reason}") from exc
            delay = retry_delay * (attempt + 1)
            if exc.code == 429:
                hinted = exc.headers.get("Retry-After") if exc.headers else None
                if hinted:
                    try:
                        delay = max(8.0, min(120.0, float(hinted)))
                    except (TypeError, ValueError):
                        pass
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt >= retries:
                raise JevError(f"Jev недоступний: {exc}") from exc
            time.sleep(retry_delay * (attempt + 1))

    raise JevError(f"Jev не відповів після {retries + 1} спроб: {last_error}")


# ---------------------------------------------------------------------------
# Набори питань
# ---------------------------------------------------------------------------


def load_question_set(path: str) -> Dict[str, Any]:
    """Читає набір питань (jev/questions/*.json) і перевіряє форму.

    Набір питань — версіонований артефакт, не константа в коді: для Jev поле
    `instructions` виконує рівно ту роль, що промпт для LLM.
    """
    with open(path, "r", encoding="utf-8") as fh:
        qset = json.load(fh)

    questions = qset.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise JevError(f"{path}: порожній або відсутній блок `questions`.")

    for key, q in questions.items():
        if not isinstance(q, dict):
            raise JevError(f"{path}: питання `{key}` не є об'єктом.")
        qtype = str(q.get("type", "")).strip().lower()
        if qtype not in {"noul", "score", "choice"}:
            raise JevError(f"{path}: питання `{key}` має невідомий тип `{qtype}`.")
        if not str(q.get("instructions", "")).strip():
            raise JevError(f"{path}: питання `{key}` без `instructions`.")
        if qtype == "score":
            levels = q.get("levels")
            if not isinstance(levels, list) or not 2 <= len(levels) <= 10:
                raise JevError(
                    f"{path}: `{key}` типу score потребує 2-10 рівнів у `levels`."
                )

    risk_key = str((qset.get("mapping") or {}).get("risk_question") or "risk")
    if risk_key not in questions:
        raise JevError(f"{path}: немає score-питання `{risk_key}` (mapping.risk_question).")
    if questions[risk_key].get("type") != "score":
        raise JevError(f"{path}: `{risk_key}` має бути типу score.")

    for key in (qset.get("mapping") or {}).get("explanations") or []:
        if key not in questions:
            raise JevError(f"{path}: mapping.explanations посилається на `{key}`, якого немає.")
    for key in ((qset.get("mapping") or {}).get("observations") or {}):
        if key not in questions:
            raise JevError(f"{path}: mapping.observations посилається на `{key}`, якого немає.")
    return qset


def questions_payload(qset: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Витягує з набору тільки те, що йде в API (без нашого `mapping`).

    Форми полів перевірені живими викликами: у `score` поле `criteria`
    **обов'язкове й має бути масивом** рівнів; у `noul` воно необов'язкове, а
    якщо є — має бути **об'єктом**. Тому наш зручніший ключ `levels`
    перекладається тут на `criteria`, а не передається як є.
    """
    payload: Dict[str, Dict[str, Any]] = {}
    for key, q in qset["questions"].items():
        item: Dict[str, Any] = {
            "type": q["type"],
            "instructions": q["instructions"],
        }
        if q["type"] == "score":
            # `criteria` — рубрика: описи рівнів по порядку. Якщо описів немає,
            # відправляємо голі назви, але це помітно гірше: з рубрикою ризикові
            # й чисті декларації розходяться значно сильніше.
            item["criteria"] = list(q.get("criteria") or q["levels"])
        elif q["type"] == "choice":
            # Документація: у choice `criteria` — словник опція → опис, і серед
            # опцій обов'язково має бути «нічого з переліченого».
            item["criteria"] = dict(q["criteria"])
        elif isinstance(q.get("criteria"), dict) and q["criteria"]:
            item["criteria"] = q["criteria"]
        payload[key] = item
    return payload


# ---------------------------------------------------------------------------
# Групові виклики: свій зріз стану на кожну групу питань
# ---------------------------------------------------------------------------


def slice_state(compact: Dict[str, Any], paths: List[str]) -> Dict[str, Any]:
    """Підмножина компакту за списком шляхів (`meta.declarant`, `incomes`, ...).

    Задокументована слабкість: accuracy падає, коли стан наповнюється тим, що
    до питання не стосується. Питанню про посаду потрібні два поля, а воно
    отримувало всі вісімнадцять секцій.
    """
    out: Dict[str, Any] = {}
    for path in paths:
        parts = path.split(".")
        src: Any = compact
        for part in parts:
            if not isinstance(src, dict) or part not in src:
                src = None
                break
            src = src[part]
        if src is None:
            continue
        cursor = out
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = src
    return out


def clean_state(
    compact: Dict[str, Any],
    *,
    strip: Optional[List[str]] = None,
    drop_empty: bool = False,
) -> Dict[str, Any]:
    """Прибирає зі стану те, що для судження шкідливе або марне.

    Підстава подвійна. Jev читає стан буквально й страждає на context rot, тож
    нерелевантний вміст коштує точності. А `post_type`/`post_category`/
    `corruption_affected` — голі числа без довідника, які слід ігнорувати, —
    модель же сприймає їх як значущі.

    `drop_empty` прибирає порожні секції: на типовій декларації їх половина.
    """
    out = json.loads(json.dumps(compact))  # глибока копія без зовнішніх залежностей
    for path in strip or []:
        parts = path.split(".")
        cursor = out
        for part in parts[:-1]:
            if not isinstance(cursor, dict) or part not in cursor:
                cursor = None
                break
            cursor = cursor[part]
        if isinstance(cursor, dict):
            cursor.pop(parts[-1], None)
    if drop_empty:
        for key in [k for k, v in out.items() if isinstance(v, (list, dict)) and not v]:
            out.pop(key, None)
    return out


def call_jev_grouped(
    compact: Dict[str, Any],
    qset: Dict[str, Any],
    *,
    api_key: str,
    model: str = DEFAULT_JEV_MODEL,
    url: str = DEFAULT_JEV_URL,
    timeout_sec: int = 60,
    retries: int = 3,
    retry_delay: float = 2.0,
    with_derived: bool = False,
) -> Dict[str, Any]:
    """Кілька викликів — по одному на групу — злиті в одну відповідь.

    Форма результату така сама, як в одиночного `call_jev`, тому далі по
    ланцюгу нічого не змінюється. `usage` і латентність підсумовуються.
    """
    groups = qset.get("groups") or {}
    payload_all = questions_payload(qset)
    merged: Dict[str, Any] = {"answers": {}, "usage": {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}}
    latency = 0

    for name, spec in groups.items():
        keys = [k for k in payload_all if qset["questions"][k].get("group") == name]
        if not keys:
            continue
        paths = spec.get("state")
        state = compact if not paths else slice_state(compact, list(paths))
        if with_derived and spec.get("derived_ratios"):
            state = dict(state)
            state["derived_ratios"] = derived_ratios(compact)
        raw = call_jev(
            state,
            {k: payload_all[k] for k in keys},
            model=model, url=url, api_key=api_key,
            timeout_sec=timeout_sec, retries=retries, retry_delay=retry_delay,
        )
        merged["answers"].update(raw.get("answers") or {})
        usage = raw.get("usage") or {}
        for field, key in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"), ("cost", "cost")):
            try:
                merged["usage"][key] += float(usage.get(field) or 0)
            except (TypeError, ValueError):
                pass
        latency += int(raw.get("_latency_ms") or 0)
        merged.setdefault("model", raw.get("model"))
        merged.setdefault("id", raw.get("id"))

    merged["_latency_ms"] = latency
    merged["usage"]["input_tokens"] = int(merged["usage"]["input_tokens"])
    merged["usage"]["output_tokens"] = int(merged["usage"]["output_tokens"])
    return merged


# ---------------------------------------------------------------------------
# Похідні відношення (арифметика — у коді, не в моделі)
# ---------------------------------------------------------------------------


def as_list(value: Any) -> List[Any]:
    """Гарантує список: усе інше — порожній список (як main.as_list)."""
    return value if isinstance(value, list) else []


def _ratio(numerator: Any, denominator: Any) -> Optional[float]:
    """Відношення або None. None, а не 0: незадекларований дохід — це не нуль."""
    try:
        num = float(numerator)
        den = float(denominator)
    except (TypeError, ValueError):
        return None
    if den <= 0:
        return None
    return round(num / den, 2)


def derived_ratios(compact: Dict[str, Any]) -> Dict[str, Any]:
    """Готові відношення й лічильники для стану Jev.

    Задокументована слабкість 1.13: «Jev is not a calculator», помилки ростуть
    із розміром входу, а дати читаються як текст. Тому все, що є арифметикою,
    рахується тут, а модель лише судить про вже готове число.

    Усі вхідні дані вже є в компакті, тож ключ додається поруч із `quick_totals`, нічого не
    переформатовуючи — `dossier_charts` читає старі ключі за точними назвами.
    """
    totals = compact.get("quick_totals") or {}
    income = totals.get("income_total_uah_estimated")
    cash = totals.get("cash_assets_total_estimated")
    realty = totals.get("realty_declared_cost_total_estimated")
    vehicles = totals.get("vehicle_declared_cost_total_estimated")
    liabilities = totals.get("liabilities_total_estimated")

    assets = 0.0
    for value in (cash, realty, vehicles):
        try:
            assets += float(value or 0)
        except (TypeError, ValueError):
            continue

    institutions = as_list(compact.get("financial_institutions"))
    accounts = 0
    for item in institutions:
        if isinstance(item, dict):
            accounts += len(as_list(item.get("persons_has_accounts")))

    owners = set()
    for section in ("real_estate", "vehicles", "valuable_movable", "cash_assets"):
        for item in as_list(compact.get(section)):
            if isinstance(item, dict):
                for holder in as_list(item.get("owners_or_users")):
                    if isinstance(holder, str) and holder.strip():
                        owners.add(holder.strip())

    return {
        "assets_total_uah": round(assets, 2),
        "assets_to_income": _ratio(assets, income),
        "cash_to_income": _ratio(cash, income),
        "realty_to_income": _ratio(realty, income),
        "vehicles_to_income": _ratio(vehicles, income),
        "liabilities_to_assets": _ratio(liabilities, assets),
        "family_members_count": len(as_list(compact.get("family_members"))),
        "financial_institutions_count": len(institutions),
        "accounts_count": accounts,
        "distinct_asset_holders": len(owners),
        "note": "Відношення пораховані кодом. None означає, що знаменник не задекларовано.",
    }


def state_with_derived(compact: Dict[str, Any]) -> Dict[str, Any]:
    """Компакт + `derived_ratios`. Оригінал не змінюється."""
    state = dict(compact)
    state["derived_ratios"] = derived_ratios(compact)
    return state


# ---------------------------------------------------------------------------
# Відповідь Jev → форма відповіді LLM
# ---------------------------------------------------------------------------


def _answer_block(raw: Dict[str, Any], key: str) -> Dict[str, Any]:
    """Дістає відповідь на питання `key`, не прив'язуючись до однієї обгортки."""
    for container_key in ("answers", "questions", "results"):
        container = raw.get(container_key)
        if isinstance(container, dict) and key in container:
            block = container[key]
            return block if isinstance(block, dict) else {"value": block}
    if key in raw and isinstance(raw[key], dict):
        return raw[key]
    raise JevError(f"У відповіді Jev немає блоку для питання `{key}`.")


def _noul_probability(block: Dict[str, Any]) -> float:
    if "noul" not in block:
        raise JevError(f"Не знайдено поля `noul` у noul-блоці: {sorted(block)}")
    try:
        return max(0.0, min(1.0, float(block["noul"])))
    except (TypeError, ValueError) as exc:
        raise JevError(f"Поле `noul` не є числом: {block['noul']!r}") from exc


def _level_distribution(block: Dict[str, Any], levels: List[str]) -> Dict[str, float]:
    """`probabilities` за індексами → {наша назва рівня: p}.

    Зіставлення йде **за позицією**, а не за текстом: коли `criteria` містить
    описову рубрику, `legend` повертає саме описи, а не наші короткі назви
    рівнів. Порядок `criteria` за побудовою збігається з порядком `levels`,
    тому індекс — єдиний надійний ключ. Довжину звіряємо, щоб мовчазного
    зсуву не сталося.
    """
    probs = block.get("probabilities")
    if not isinstance(probs, dict) or not probs:
        raise JevError(f"Немає `probabilities` у score-блоці: {sorted(block)}")
    if len(probs) != len(levels):
        raise JevError(
            f"Jev повернув {len(probs)} рівнів, у наборі питань їх {len(levels)}"
        )

    out: Dict[str, float] = {}
    for idx, prob in probs.items():
        try:
            i = int(idx)
        except (TypeError, ValueError) as exc:
            raise JevError(f"Нечисловий індекс рівня: {idx!r}") from exc
        if not 0 <= i < len(levels):
            raise JevError(f"Індекс рівня {i} поза межами {levels}")
        try:
            out[levels[i]] = out.get(levels[i], 0.0) + max(0.0, float(prob))
        except (TypeError, ValueError):
            continue

    total = sum(out.values())
    if total <= 0:
        raise JevError(f"Сума ймовірностей по рівнях нульова: {probs}")
    return {name: prob / total for name, prob in out.items()}


def _risk_score_from_distribution(
    distribution: Dict[str, float], midpoints: Dict[str, int]
) -> int:
    """Матсподівання по розподілу, а не аргмакс.

    Розподіл використовується цілком, тому декларація, розділена навпіл між
    `medium` і `critical`, осідає у `high` — аргмакс таку річ втрачає.
    """
    expected = sum(
        prob * float(midpoints.get(level, 0)) for level, prob in distribution.items()
    )
    return int(max(0, min(100, round(expected))))


def _severity_for_probability(prob: float, bands: Dict[str, float]) -> str:
    """Найвища смуга, поріг якої не перевищено ймовірністю."""
    for level in ("critical", "high", "medium"):
        threshold = bands.get(level)
        if threshold is not None and prob >= float(threshold):
            return level
    return "low"


def jev_to_analysis(
    raw: Dict[str, Any],
    qset: Dict[str, Any],
    *,
    finding_titles: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Відповідь Jev → (dict у формі відповіді LLM, блок для run_meta).

    Перший елемент подається в наявну `normalize_analysis_payload()` без змін —
    саме тому решта ланцюга (JSONL, звіт, скорери) не знає про інше джерело.
    """
    mapping = qset.get("mapping", {}) or {}
    midpoints = {**LEVEL_MIDPOINTS, **(mapping.get("level_midpoints") or {})}
    threshold = float(mapping.get("finding_threshold", 0.50))
    bands = mapping.get("severity_bands") or {
        "medium": 0.65,
        "high": 0.80,
        "critical": 0.92,
    }
    titles = finding_titles or {}

    risk_key = str(mapping.get("risk_question") or "risk")
    risk_q = qset["questions"][risk_key]
    risk_block = _answer_block(raw, risk_key)
    distribution = _level_distribution(risk_block, list(risk_q["levels"]))
    risk_score = _risk_score_from_distribution(distribution, midpoints)

    noul_probs: Dict[str, float] = {}
    for key, q in qset["questions"].items():
        if q["type"] == "noul":
            noul_probs[key] = round(_noul_probability(_answer_block(raw, key)), 4)

    observations = mapping.get("observations")
    if observations:
        findings, refutation = _findings_two_axis(
            noul_probs, mapping, titles, threshold, bands
        )
        extra_meta = refutation
    else:
        findings, extra_meta = _findings_flat(noul_probs, titles, threshold, bands), {}

    findings.sort(key=lambda f: float(f["confidence"]), reverse=True)

    analysis = {
        "risk_score": risk_score,
        "risk_level": None,
        "findings": findings,
        "family_assets_overview": [],
        "red_flags": [],
        "needs_verification": [],
        "clear_facts": [],
        "final_assessment": "",
    }

    confidence = risk_block.get("confidence")
    try:
        confidence = round(float(confidence), 4)
    except (TypeError, ValueError):
        confidence = None

    aux: Dict[str, Any] = {}
    for key, q in qset["questions"].items():
        if q["type"] == "score" and key != risk_key:
            b = _answer_block(raw, key)
            d = _level_distribution(b, list(q["levels"]))
            aux[key] = {
                "argmax": max(d, key=d.get),
                "distribution": {k: round(v, 4) for k, v in d.items()},
                "confidence": b.get("confidence"),
            }
        elif q["type"] == "choice":
            b = _answer_block(raw, key)
            aux[key] = {
                "choice": b.get("choice") or b.get("value"),
                "confidence": b.get("confidence"),
                "probabilities": b.get("probabilities"),
            }

    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}

    jev_meta = {
        "model": raw.get("model") or qset.get("model") or DEFAULT_JEV_MODEL,
        "questions": qset.get("name", ""),
        "risk_distribution": {k: round(v, 4) for k, v in distribution.items()},
        "risk_confidence": confidence,
        "raw_score": risk_block.get("score"),
        "noul": noul_probs,
        "aux": aux,
        "finding_threshold": threshold,
        "latency_ms": raw.get("_latency_ms"),
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cost_usd": usage.get("cost"),
        },
        "generation_id": raw.get("id"),
        **extra_meta,
    }
    return analysis, jev_meta


def _rescale_hint_score(score: float, lo_to: float = 15.0, hi_to: float = 95.0) -> int:
    """Афінна перекалібровка risk_score ЛИШЕ для тексту підказки.

    НЕ чіпає analysis["risk_score"] — те значення йде в --provider jev
    (сортування каталогу) і має лишатись сирим, інакше пороги coreframe-13
    стають незіставними самі з собою.

    "Нічого" в Jev осідає біля ~47, а не ~15, як у LLM-рядках. Мапить
    47->lo_to, 100->hi_to, лінійно; нижче 47 — та сама пропорція вниз до 0.
    Серед протестованих варіантів підказки ця форма дала найменше хибних
    спрацювань при тій самій кількості уловів.
    """
    lo_from, hi_from = 47.0, 100.0
    if score >= lo_from:
        frac = (score - lo_from) / (hi_from - lo_from)
        return int(round(lo_to + frac * (hi_to - lo_to)))
    frac = score / lo_from
    return int(round(frac * lo_to))


def build_hint_text(
    analysis: Dict[str, Any],
    jev_meta: Dict[str, Any],
    *,
    max_findings: int = 5,
) -> str:
    """Короткий текстовий блок для jev-assistance (docs/JEV.md §3.3).

    Навмисно без доказів (у Jev їх немає) і з прямим застереженням про
    ненадійність — щоб LLM перевіряла патерн за фактами, а не підтверджувала
    підказку. Якщо модель просто копіює підказку в текст без власної
    перевірки, знахідок, підкріплених фактами, не побільшає.

    Число — перекаліброване (`_rescale_hint_score`), а список патернів — БЕЗ
    ймовірності біля кожного: голе число виявилось одночасно і єдиним
    джерелом сигналу, і єдиним джерелом хибної тривоги, тож переможна форма —
    перекалібр. число + список без чисел. Не змінювати одне без повторного
    заміру іншого.
    """
    rescaled = _rescale_hint_score(analysis.get("risk_score") or 0)
    lines = [
        "[Попередня оцінка допоміжної системи (Jev). Це НЕ висновок і НЕ факт — "
        "лише список патернів для перевірки. Довіряй лише тому, що сам "
        "підтвердиш конкретними цифрами й фактами з декларації нижче.]",
        f"Загальний рівень ризику за оцінкою Jev (0-100, орієнтир, не факт): {rescaled}",
    ]
    findings = sorted(
        (analysis.get("findings") or []),
        key=lambda f: float(f.get("confidence") or 0.0),
        reverse=True,
    )[:max_findings]
    if findings:
        lines.append("Патерни, які Jev вважає ймовірними (перевір кожен окремо):")
        for f in findings:
            lines.append(f"- {f.get('title', f.get('type', ''))}")
    else:
        lines.append("Jev не виділив жодного патерну з високою ймовірністю.")
    aux = jev_meta.get("aux") or {}
    main_concern = (aux.get("main_concern") or {}).get("choice")
    if main_concern:
        lines.append(f"Головний фокус за оцінкою Jev: {main_concern}")
    return "\n".join(lines)


def _finding(
    finding_type: str, title: str, prob: float, bands: Dict[str, float]
) -> Dict[str, Any]:
    """Знахідка з порожніми evidence/rationale.

    Порожні навмисно й непорушно: Jev не має тексту, а будь-який підставний
    рядок видавав би себе за доказ, якого немає.
    """
    return {
        "title": title,
        "type": finding_type,
        "severity": _severity_for_probability(prob, bands),
        "confidence": prob,
        "evidence": [],
        "involved_persons": [],
        "related_assets_or_income": [],
        "rationale": "",
    }


def _findings_flat(
    noul_probs: Dict[str, float],
    titles: Dict[str, str],
    threshold: float,
    bands: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Плоский набір (без груп obs_/h*): кожен noul сам по собі — тип знахідки."""
    return [
        _finding(key, titles.get(key, key), prob, bands)
        for key, prob in noul_probs.items()
        if prob >= threshold
    ]


def _findings_two_axis(
    noul_probs: Dict[str, float],
    mapping: Dict[str, Any],
    titles: Dict[str, str],
    threshold: float,
    bands: Dict[str, float],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Дві осі: спостереження + спростування H1-H5, **за кожною ознакою**.

    Принцип із CoreFrame: побачив непропорційний актив — перебери походження,
    перш ніж підозрювати. H6 («джерело поза декларацією») не питається, бо це
    залишок: він лишається тоді, коли жодна з доречних гіпотез не спрацювала.

    Ключове: доречні гіпотези **свої для кожної ознаки**. Майно на дружині
    спростовується її доходом, а не кредитом декларанта. Перша версія брала
    максимум по всіх п'яти гіпотезах на всю декларацію і через це глушила
    й правильні знахідки.

    Пороги теж свої на кожне питання: задокументовано, що пороги, підібрані на
    одному типі питань, не переносяться на інший.
    """
    observations = mapping.get("observations") or {}
    default_exp = list(mapping.get("explanations") or [])
    default_exp_threshold = float(mapping.get("explanation_threshold", 0.5))
    thresholds = mapping.get("thresholds") or {}

    findings: List[Dict[str, Any]] = []
    suppressed: List[Dict[str, Any]] = []
    detail: Dict[str, Any] = {}

    for key, spec in observations.items():
        prob = noul_probs.get(key, 0.0)
        own_threshold = float(thresholds.get(key, threshold))
        if prob < own_threshold:
            continue

        # Явний порожній список означає «ця ознака не спростовується нічим»,
        # тому саме `in spec`, а не `or`: [] — хибний, і провалився б на дефолт.
        exp_keys = list(
            spec["explained_by"] if "explained_by" in spec else default_exp
        )
        exp_threshold = float(spec.get("explanation_threshold", default_exp_threshold))
        exp_probs = {k: noul_probs.get(k, 0.0) for k in exp_keys}
        best = max(exp_probs.values(), default=0.0)
        explained = bool(exp_keys) and best >= exp_threshold

        detail[key] = {
            "p": round(prob, 4),
            "threshold": own_threshold,
            "explained_by": {k: round(v, 4) for k, v in exp_probs.items()},
            "best_explanation": round(best, 4),
            "explained": explained,
        }

        ftype = str(spec.get("type") or "other")
        if explained:
            # Ознака є, але походження пояснене — за CoreFrame це не знахідка,
            # а питання до перевірки.
            suppressed.append({"observation": key, "type": ftype, "p": round(prob, 4)})
            continue
        findings.append(_finding(ftype, titles.get(ftype, ftype), prob, bands))

    # Один тип — одна знахідка: лишаємо найвпевненішу.
    best_by_type: Dict[str, Dict[str, Any]] = {}
    for finding in findings:
        current = best_by_type.get(finding["type"])
        if current is None or finding["confidence"] > current["confidence"]:
            best_by_type[finding["type"]] = finding

    return list(best_by_type.values()), {
        "refutation": {"per_observation": detail, "suppressed": suppressed}
    }
