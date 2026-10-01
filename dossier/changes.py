"""Зміни між сусідніми деклараціями однієї особи (режим досьє, docs/JEV.md §3.5).

Однорічний аналіз бачить, що куплено у звітному році, але не бачить того, що
видно лише між роками: майно зникло без продажу, той самий об'єкт переписали
на родича, з'явився об'єкт, набутий давно, але раніше не задекларований.
Різницю рахує КОД (зіставлення об'єктів за класом, розміром, датою набуття,
місцем і власником) — Jev отримує лише різницю й оцінює, наскільки вона
варта перевірки (набір jev/questions/pairframe-N.json).

Кожна окрема секція стану закриває окремий клас хибних тривог: переоформлення,
майно, що прийшло чи вибуло з членом сім'ї, продаж, пропущені роки.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jev import client as jev_client

# Версія побудови стану: входить у підпис кешу dossier_changes.json, тож
# зміна логіки різниці перераховує кеш, а не тихо віддає старі оцінки.
STATE_VERSION = "5"

MAX_LISTED = 30
_UNKNOWN = ("[не відомо]", "[член сім'ї не надав інформацію]", "[конфіденційна інформація]",
            "[не застосовується]")


# ---------------------------------------------------------------------------
# Декларації досьє
# ---------------------------------------------------------------------------


def dossier_declarations(folder: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Одна декларація на (рік, тип), у хронологічному порядку.

    Повертає (декларації, імена файлів, які замінила виправлена версія)."""
    return declarations_from_files(sorted(folder.glob("decl_*.json")))


def declarations_from_files(files: List[Path]) -> Tuple[List[Dict[str, Any]], List[str]]:
    best: Dict[Tuple[int, int], Dict[str, Any]] = {}
    superseded: List[str] = []
    for f in files:
        raw = json.loads(f.read_text(encoding="utf-8"))
        key = (int(raw.get("declaration_year") or 0), int(raw.get("declaration_type") or 0))
        rank = (str(raw.get("date") or ""), int(raw.get("type") or 0))
        prev = best.get(key)
        if prev is None or rank > prev["rank"]:
            if prev is not None:
                superseded.append(prev["file"].name)
            best[key] = {"file": f, "raw": raw, "rank": rank, "year": key[0], "dtype": key[1]}
        else:
            superseded.append(f.name)
    from main import compact_declaration  # лінивий: main важкий і сам нас не імпортує

    decls = sorted(best.values(), key=lambda d: (d["year"], d["dtype"]))
    for d in decls:
        d["compact"] = compact_declaration(d["raw"])
    return decls, superseded


# ---------------------------------------------------------------------------
# Нормалізація об'єктів майна
# ---------------------------------------------------------------------------


def _owner_label(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return "невідомо"
    if s.startswith("Суб'єкт декларування"):
        return "декларант"
    if ":" in s:
        return s.split(":", 1)[0].strip()
    return "інша особа"


def _owners(item: Dict[str, Any]) -> str:
    labels = sorted({_owner_label(o) for o in (item.get("owners_or_users") or [])})
    return " + ".join(labels) if labels else "невідомо"


def _place(loc: Any) -> str:
    if not isinstance(loc, dict):
        return ""
    raw = str(loc.get("city_type") or loc.get("district") or loc.get("region") or "")
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    return " / ".join(parts[:2])


def _cost(item: Dict[str, Any]) -> str:
    for key in ("cost_date_assessment", "costDate", "cost"):
        v = str(item.get(key) or "").strip()
        if v and v.lower() not in _UNKNOWN:
            return v
    return "не вказано"


def _date_str(value: Any) -> str:
    s = str(value or "").strip()
    return "не вказано" if not s or s.lower() in _UNKNOWN else s


def _year_of(date_str: str) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", date_str or "")
    return int(m.group(0)) if m else None


def _kind_key(kind: str) -> str:
    """«Мотоцикл (мопед)» і «Мотоцикл» — той самий клас: НАЗК перейменовує класи
    між версіями форми (схема 2 → 5), і без цього ті самі мотоцикли виглядали
    б як «зникли + з'явились раніше не задекларовані»."""
    return re.sub(r"\s*\(.*?\)", "", kind or "").strip().lower()


def _area_m2(kind_key: str, raw: str) -> Optional[float]:
    """Площа в м². Землю часто пишуть у гектарах у полі для м² («6.1787»,
    «0.24») або без коми («02429» = 0,2429 га) — переводимо, інакше та сама
    ділянка між роками «змінює розмір» у тисячі разів."""
    s = (raw or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        v = float("0." + s[1:]) if re.fullmatch(r"0\d+", s) else float(s)
    except ValueError:
        return None
    if "земельна" in kind_key and v < 100:
        v *= 10000
    return v


def _size_key(kind_key: str, raw: str) -> str:
    """Ключ для зіставлення: площа до 2 значущих цифр (поглинає округлення й
    уточнення в межах відсотків), модель авто — без пробілів і пунктуації."""
    area = _area_m2(kind_key, raw)
    if area is not None and area > 0:
        return f"{float(f'{area:.2g}'):g}"
    return re.sub(r"[^0-9a-zа-яіїєґ]", "", (raw or "").lower())


def _same_size(kind_key: str, a: str, b: str) -> bool:
    x, y = _area_m2(kind_key, a), _area_m2(kind_key, b)
    if x is not None and y is not None and max(x, y) > 0:
        return abs(x - y) / max(x, y) <= 0.02
    return _size_key(kind_key, a) == _size_key(kind_key, b)


def asset_items(c: Dict[str, Any]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for r in c.get("real_estate") or []:
        if not isinstance(r, dict):
            continue
        kind = str(r.get("objectType") or "нерухомість")
        size = str(r.get("totalArea") or "").strip()
        items.append({
            "cls": "realty",
            "kind": kind, "kind_key": _kind_key(kind),
            "size": size, "size_key": _size_key(_kind_key(kind), size),
            "acquired": _date_str(r.get("owningDate")),
            "place": _place(r.get("location")),
            "owner": _owners(r),
            "cost": _cost(r),
        })
    for v in c.get("vehicles") or []:
        if not isinstance(v, dict):
            continue
        kind = str(v.get("objectType") or "транспорт")
        size = " ".join(str(v.get(k) or "").strip() for k in ("brand", "model", "graduationYear")).strip()
        items.append({
            "cls": "vehicle",
            "kind": kind, "kind_key": _kind_key(kind),
            "size": size, "size_key": _size_key(_kind_key(kind), size),
            "acquired": _date_str(v.get("owningDate")),
            "place": "",
            "owner": _owners(v),
            "cost": _cost(v),
        })
    return items


# Проходи від найсуворішого до найслабшого. Місце — лише в перших: у різні
# роки НАЗК віддає його по-різному (або не віддає зовсім), і суворе порівняння
# місця давало б фантомні «зникло + з'явилось» для того самого об'єкта.
_MATCH_PASSES = (
    ("kind_key", "size_key", "acquired", "place", "owner"),
    ("kind_key", "size_key", "acquired", "owner"),
    ("kind_key", "acquired", "place", "owner"),   # змінився розмір (уточнення площі)
    ("kind_key", "size_key", "acquired", "place"),    # змінився власник
    ("kind_key", "size_key", "acquired"),
    ("kind_key", "acquired", "place"),
)


def match_assets(before: List[Dict[str, str]], after: List[Dict[str, str]]):
    b_left = list(range(len(before)))
    a_left = list(range(len(after)))
    pairs: List[Tuple[int, int]] = []
    for fields in _MATCH_PASSES:
        buckets: Dict[tuple, List[int]] = {}
        for bi in b_left:
            buckets.setdefault(tuple(before[bi][f] for f in fields), []).append(bi)
        still_a: List[int] = []
        for ai in a_left:
            lst = buckets.get(tuple(after[ai][f] for f in fields))
            if lst:
                pairs.append((lst.pop(0), ai))
            else:
                still_a.append(ai)
        used = {bi for bi, _ in pairs}
        b_left = [bi for bi in b_left if bi not in used]
        a_left = still_a
    return pairs, b_left, a_left


# ---------------------------------------------------------------------------
# Стан пари для Jev
# ---------------------------------------------------------------------------


def _reregistration_twin(item: Dict[str, str], before: List[Dict[str, str]]) -> str:
    """Новий об'єкт, чия НЕОКРУГЛА площа до 0,01% збігається з уже
    задекларованим об'єктом того ж класу з іншою датою набуття, — найімовірніше
    та сама ділянка з новою датою реєстрації (переоформлення паю), а не купівля.
    Круглі площі (20 000 м²) виключені: збіг там випадковий. Висновок — за Jev,
    тут лише факт збігу."""
    area = _area_m2(item["kind_key"], item["size"])
    if area is None or area <= 0 or abs(area - round(area, -2)) < 1e-6:
        return ""
    for b in before:
        if b["kind_key"] != item["kind_key"] or b["acquired"] == item["acquired"]:
            continue
        other = _area_m2(b["kind_key"], b["size"])
        if other and abs(other - area) / max(other, area) <= 1e-4:
            return f"площа збігається з {b['kind'].lower()} {b['size']}, набутою {b['acquired']}"
    return ""


def _public(item: Dict[str, str]) -> Dict[str, str]:
    out = {"об'єкт": item["kind"], "розмір": item["size"], "набуто": item["acquired"],
           "власник": item["owner"], "вартість": item["cost"]}
    if item["place"]:
        out["місце"] = item["place"]
    return out


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _family(c: Dict[str, Any]) -> List[str]:
    out = []
    for m in c.get("family_members") or []:
        if isinstance(m, dict):
            out.append(f"{str(m.get('subjectRelation') or '').strip()}: "
                       f"{str(m.get('firstname') or '').strip().title()}")
    return out


def _income_items(c: Dict[str, Any]) -> List[Dict[str, str]]:
    rows = []
    for i in c.get("incomes") or []:
        if not isinstance(i, dict):
            continue
        rows.append({
            "вид": str(i.get("objectType") or ""),
            "сума": str(i.get("sizeIncome") or ""),
            "отримувач": _owners({"owners_or_users": i.get("person_who_care") or []}),
        })
    rows.sort(key=lambda r: -(_num(r["сума"]) or 0))
    return rows[:8]


def _relation(member: str) -> str:
    return member.split(":", 1)[0].strip()


def _owner_parts(owner: str) -> set:
    return {p.strip() for p in owner.split("+") if p.strip()}


def _sale_incomes(c: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for i in c.get("incomes") or []:
        if isinstance(i, dict) and "відчуж" in str(i.get("objectType") or "").lower():
            out.append({"вид": str(i.get("objectType") or ""), "сума": str(i.get("sizeIncome") or "")})
    return out


def _sale_covers(item: Dict[str, str], sales: List[Dict[str, str]]) -> bool:
    """Чи є в доходах нового року продаж відповідного класу майна. Лише факт
    наявності такого доходу — суму з вартістю не звіряємо (вартість зниклого
    об'єкта здебільшого не вказана)."""
    for s in sales:
        kind = s["вид"].lower()
        if item["cls"] == "realty" and "нерухом" in kind:
            return True
        if item["cls"] == "vehicle" and (("рухом" in kind and "нерухом" not in kind) or "транспорт" in kind):
            return True
    return False


def pair_state(prev: Dict[str, Any], cur: Dict[str, Any]) -> Dict[str, Any]:
    """Стан пари: лише різниця, і лише те, що код може встановити як факт.

    Кожна окрема секція закриває окремий клас хибних тривог: майно, що прийшло чи вибуло разом із членом сім'ї, — не набуття й
    не зникнення; зникнення при задекларованому доході від продажу — продаж;
    пропущені роки означають, що доходів і продажів за них ми не бачимо."""
    pc, cc = prev["compact"], cur["compact"]
    before, after = asset_items(pc), asset_items(cc)
    pairs, removed_idx, new_idx = match_assets(before, after)
    y0, y1 = prev["year"], cur["year"]

    fam0, fam1 = _family(pc), _family(cc)
    added_rel = {_relation(m) for m in fam1 if m not in fam0}
    removed_rel = {_relation(m) for m in fam0 if m not in fam1}
    sales = _sale_incomes(cc)

    new_assets, reregistered, came_with_member = [], [], []
    for i in new_idx:
        a = after[i]
        item = _public(a)
        # Двійник — окремою секцією, не «новим майном» із позначкою: позначка
        # поруч із «набуто між деклараціями» програє — Jev читає це як купівлю.
        twin = _reregistration_twin(a, before)
        if twin:
            item["збіг"] = twin
            reregistered.append(item)
            continue
        yr = _year_of(a["acquired"])
        # Майно нового члена сім'ї, набуте ДО попередньої декларації, прийшло
        # разом із ним, а не куплене (наприклад, квартири й авто дочки, що
        # додалась до декларації).
        if added_rel and _owner_parts(a["owner"]) <= added_rel and yr is not None and yr <= y0:
            came_with_member.append(item)
            continue
        if yr is None:
            item["коли"] = "дата набуття не вказана"
        elif yr > y0:
            item["коли"] = "набуто між деклараціями"
        else:
            item["коли"] = f"набуто в {yr}, у попередній декларації відсутній"
        new_assets.append(item)

    gone, left_with_member, sold = [], [], []
    for i in removed_idx:
        b = before[i]
        item = _public(b)
        if removed_rel and _owner_parts(b["owner"]) <= removed_rel:
            left_with_member.append(item)
        elif _sale_covers(b, sales):
            sold.append(item)
        else:
            gone.append(item)

    owner_changes, owner_relabeled, size_changes = [], [], []
    for bi, ai in pairs:
        b, a = before[bi], after[ai]
        if b["owner"] != a["owner"]:
            change = {"об'єкт": a["kind"], "розмір": a["size"], "набуто": a["acquired"],
                      "власник_був": b["owner"], "власник_став": a["owner"]}
            bp, ap = _owner_parts(b["owner"]), _owner_parts(a["owner"])
            # «Інша особа» стала щойно доданим членом сім'ї (чи навпаки) — та
            # сама людина, змінився лише її статус у декларації, майно не
            # переходило (співвласниця квартири — дочка, що додалась до сім'ї;
            # як «перехід до члена сім'ї» це давало хибну високу оцінку).
            joined = bp - ap == {"інша особа"} and bool(ap - bp) and (ap - bp) <= added_rel
            left = ap - bp == {"інша особа"} and bool(bp - ap) and (bp - ap) <= removed_rel
            (owner_relabeled if joined or left else owner_changes).append(change)
        # Для транспорту «розмір» — це марка й модель: розбіжність там завжди
        # друкарська («VOLKSWAGEN» / «VOLKSVAGEN»), бо той самий об'єкт уже
        # зіставлено за датою набуття й власником.
        if a["cls"] == "realty" and not _same_size(a["kind_key"], b["size"], a["size"]):
            size_changes.append({"об'єкт": a["kind"], "набуто": a["acquired"],
                                 "розмір_був": b["size"], "розмір_став": a["size"]})

    d0 = (pc.get("meta") or {}).get("declarant") or {}
    d1 = (cc.get("meta") or {}).get("declarant") or {}
    q0, q1 = pc.get("quick_totals") or {}, cc.get("quick_totals") or {}
    work = {"посада": d1.get("work_post"), "місце_роботи": d1.get("work_place")}
    # Зміна роботи — лише коли змінилася посада або місця роботи не мають
    # жодного спільного значущого слова. Інакше це різне написання того самого:
    # «ДП Сарненське…» / «ДЕРЖАВНЕ ПІДПРИЄМСТВО "САРНЕНСЬКЕ…"», «ВІЙСЬКОВА
    # ЧАСТИНА А7032» / «Військова служба» — у хронології для підсумку такі
    # фантоми дали LLM хибний факт «у 2021 змінив посаду» (A/B 26.09.2026).
    def _norm(v: Any) -> str:
        return re.sub(r"[^0-9a-zа-яіїєґ]", "", str(v or "").lower())

    def _words(v: Any) -> set:
        return {w for w in re.findall(r"[0-9a-zа-яіїєґ]+", str(v or "").lower()) if len(w) >= 4}

    post_changed = _norm(d0.get("work_post")) != _norm(d1.get("work_post"))
    w0, w1 = _words(d0.get("work_place")), _words(d1.get("work_place"))
    place_changed = bool(w0) and bool(w1) and not (w0 & w1)
    if post_changed or place_changed:
        work["попередня_посада"] = d0.get("work_post")
        work["попереднє_місце_роботи"] = d0.get("work_place")

    period = f"{y0} → {y1}"
    if cur["dtype"] == 2:
        period += " (декларація перед звільненням)"
    state: Dict[str, Any] = {"період": period}
    if y1 - y0 > 1:
        state["пропущені_роки"] = {
            "роки": list(range(y0 + 1, y1)),
            "примітка": "декларацій за ці роки немає — доходи й продажі за них невідомі",
        }
    state.update({
        "декларант": work,
        "сім'я": {"склад": fam1,
                  "додалися": [m for m in fam1 if m not in fam0],
                  "вибули": [m for m in fam0 if m not in fam1]},
        "дохід_родини_грн": {"попередній": q0.get("income_total_uah_estimated"),
                             "новий": q1.get("income_total_uah_estimated")},
        "доходи_нового_року": _income_items(cc),
        "дохід_від_продажу_майна": sales,
        "кошти_грн": {"попередні": q0.get("cash_assets_total_estimated"),
                      "нові": q1.get("cash_assets_total_estimated")},
        "зобов'язання_грн": {"попередні": q0.get("liabilities_total_estimated"),
                             "нові": q1.get("liabilities_total_estimated")},
        # Лічильників майна «було/стало» тут свідомо НЕМАЄ: сире зведення
        # ігнорує пояснені зміни (майно, що прийшло з членом сім'ї) і
        # суперечить поштучним секціям, тож Jev переоцінює пару. Та сама
        # пастка, що з derived_ratios (docs/JEV.md §2.3).
        "нове_майно": new_assets[:MAX_LISTED],
        # Будинок і ділянка під ним однією датою — одна покупка, а не «кілька
        # об'єктів»: окремі набуття рахуємо як різні пари (дата, власник).
        "окремих_набуттів": len({(x["набуто"], x["власник"]) for x in new_assets}),
        "майно_нового_члена_сім'ї_набуте_раніше": came_with_member[:MAX_LISTED],
        "ймовірно_переоформлене_майно_з_новою_датою_реєстрації": reregistered[:MAX_LISTED],
        "зникле_майно": gone[:MAX_LISTED],
        "ймовірно_продане_майно": sold[:MAX_LISTED],
        "майно_члена_сім'ї_що_вибув": left_with_member[:MAX_LISTED],
        "зміна_власника": owner_changes[:MAX_LISTED],
        "співвласник_змінив_статус_через_склад_сім'ї": owner_relabeled[:MAX_LISTED],
        "зміна_розміру": size_changes[:MAX_LISTED],
    })
    if not new_assets:
        state.pop("окремих_набуттів")
    if len(new_assets) > MAX_LISTED:
        state["нове_майно_всього"] = len(new_assets)
    # Порожнє прибираємо: відсутність секції для Jev — теж сигнал «змін немає»,
    # а порожні масиви лише роздувають стан (context rot, docs/JEV.md §2.3).
    for k in [k for k, v in state.items() if v in ([], {}, None)]:
        state.pop(k)
    fam = state.get("сім'я") or {}
    for k in [k for k, v in fam.items() if not v and k != "склад"]:
        fam.pop(k)
    return state


# ---------------------------------------------------------------------------
# Виклики Jev
# ---------------------------------------------------------------------------


def score_pair(state: Dict[str, Any], qset: Dict[str, Any], api_key: str) -> Dict[str, Any]:
    raw = jev_client.call_jev(state, jev_client.questions_payload(qset),
                              model=qset.get("model") or jev_client.DEFAULT_JEV_MODEL,
                              api_key=api_key)
    out: Dict[str, Any] = {"_latency_ms": raw.get("_latency_ms")}
    risk_key = qset["mapping"]["risk_question"]
    for key, q in qset["questions"].items():
        block = jev_client._answer_block(raw, key)
        if q["type"] == "noul":
            out[key] = round(jev_client._noul_probability(block), 3)
        elif q["type"] == "score":
            dist = jev_client._level_distribution(block, list(q["levels"]))
            out[key] = {lvl: round(p, 3) for lvl, p in dist.items()}
            if key == risk_key:
                out["risk_score"] = jev_client._risk_score_from_distribution(
                    dist, jev_client.LEVEL_MIDPOINTS)
    return out


# ---------------------------------------------------------------------------
# Досьє цілком: аналіз із кешем, факти, HTML, текст для підсумку
# ---------------------------------------------------------------------------

CACHE_FILE_NAME = "dossier_changes.json"
SECTION_ID = "declarator-dossier-changes"
SUMMARY_SECTION_ID = "declarator-dossier-summary"

LEVEL_LABELS = {"low": "низький", "medium": "середній", "high": "високий"}


def change_level(risk_score: int) -> str:
    """Пороги рівня змін: ≥60 — високий, ≥35 — середній, інакше низький.
    Переходи без подій зазвичай лягають нижче 40, справжні події — вище 60."""
    if risk_score >= 60:
        return "high"
    if risk_score >= 35:
        return "medium"
    return "low"


def _files_signature(folder: Path, qset_path: Path) -> str:
    parts = [f"{qset_path.name}:{qset_path.stat().st_mtime_ns}:{qset_path.stat().st_size}",
             f"state:{STATE_VERSION}"]
    for f in sorted(folder.glob("decl_*.json")):
        st = f.stat()
        parts.append(f"{f.name}:{st.st_mtime_ns}:{st.st_size}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def load_cached(folder: Path) -> Optional[Dict[str, Any]]:
    p = folder / CACHE_FILE_NAME
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def analyze_dossier(folder: Path, api_key: str, qset_path: Path, *, max_workers: int = 5) -> Dict[str, Any]:
    """Пари сусідніх декларацій досьє → факти + оцінка Jev. Кеш у теці досьє
    за підписом файлів декларацій і набору питань: повторне формування звіту
    не платить за Jev удруге."""
    sig = _files_signature(folder, qset_path)
    cached = load_cached(folder)
    if cached and cached.get("signature") == sig:
        cached["from_cache"] = True
        return cached

    qset = jev_client.load_question_set(str(qset_path))
    decls, superseded = dossier_declarations(folder)
    states = [pair_state(decls[i - 1], decls[i]) for i in range(1, len(decls))]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        scored = list(ex.map(lambda s: score_pair(s, qset, api_key), states))
    pairs = []
    for i, (st, jev) in enumerate(zip(states, scored), start=1):
        risk = int(jev.get("risk_score") or 0)
        pairs.append({
            "from_year": decls[i - 1]["year"],
            "to_year": decls[i]["year"],
            "to_source_file": decls[i]["file"].name,
            "period": st.get("період", ""),
            "risk_score": risk,
            "level": change_level(risk),
            "facts": pair_facts(st),
            "state": st,
            "jev": jev,
        })
    result = {
        "signature": sig,
        "question_set": qset.get("name"),
        "superseded": superseded,
        "pairs": pairs,
    }
    (folder / CACHE_FILE_NAME).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    result["from_cache"] = False
    return result


def change_scores_by_source(folder: Path) -> Dict[str, int]:
    """source_file декларації → бал зміни, що нею завершується (для графіка).
    Лише читання кешу: графіки не мають права викликати Jev самі."""
    cached = load_cached(folder) or {}
    return {p["to_source_file"]: int(p["risk_score"]) for p in cached.get("pairs") or []
            if p.get("to_source_file")}


_OBJ = "об'єкт"


def _size_text(obj: str, size: str) -> str:
    """Розмір з одиницею. Для землі — як записано (га чи м²), без перерахунку:
    звіт показує декларацію, а не нашу нормалізацію."""
    n = _num((size or "").replace(",", "."))
    if n is None:
        return size  # марка/модель транспорту
    if "ділянк" in obj.lower() and n < 100:
        return f"{size} га"
    return f"{size} м²"


def _describe(x: Dict[str, str]) -> str:
    obj = x.get(_OBJ, "")
    text = f"{obj} {_size_text(obj, x.get('розмір', ''))}".strip()
    cost = x.get("вартість", "")
    if cost and cost != "не вказано":
        text += f", {cost} грн"
    acq = x.get("набуто", "")
    tail = ", ".join(v for v in (acq if acq != "не вказано" else "", x.get("власник", "")) if v)
    return f"{text} ({tail})" if tail else text


def _list(items: List[Dict[str, str]], limit: int = 5) -> str:
    # Однакові рядки групуємо: десять однакових ділянок — це «×10», а не
    # десять повторів, через які не видно решти.
    groups: Dict[str, int] = {}
    for x in items:
        d = _describe(x)
        groups[d] = groups.get(d, 0) + 1
    parts = [f"{d} ×{c}" if c > 1 else d for d, c in groups.items()]
    shown = "; ".join(parts[:limit])
    rest = sum(list(groups.values())[limit:])
    return shown + (f"; і ще {rest}" if rest > 0 else "")


def _money(v: Any) -> str:
    n = _num(v)
    return "—" if n is None else f"{n:,.0f}".replace(",", " ")


def pair_facts(st: Dict[str, Any]) -> List[str]:
    """Людською мовою те саме, що бачить Jev, — для звіту й для підсумку."""
    facts: List[str] = []
    gap = st.get("пропущені_роки")
    if gap:
        yrs = ", ".join(str(y) for y in gap.get("роки") or [])
        facts.append(f"Декларацій за {yrs} у досьє немає — доходи й продажі за ці роки невідомі.")
    work = st.get("декларант") or {}
    if work.get("попередня_посада") is not None or work.get("попереднє_місце_роботи") is not None:
        facts.append(
            f"Посада: {work.get('попередня_посада') or '—'} ({work.get('попереднє_місце_роботи') or '—'}) → "
            f"{work.get('посада') or '—'} ({work.get('місце_роботи') or '—'})."
        )
    fam = st.get("сім'я") or {}
    if fam.get("додалися"):
        facts.append("До складу сім'ї додались: " + ", ".join(fam["додалися"]) + ".")
    if fam.get("вибули"):
        facts.append("Зі складу сім'ї вибули: " + ", ".join(fam["вибули"]) + ".")

    asset_sections = (
        ("нове_майно", "Нове майно"),
        ("майно_нового_члена_сім'ї_набуте_раніше", "Прийшло разом із новим членом сім'ї"),
        ("ймовірно_переоформлене_майно_з_новою_датою_реєстрації", "Ймовірно переоформлене (площа збігається з уже задекларованим)"),
        ("зникле_майно", "Зникло без видимого продажу"),
        ("ймовірно_продане_майно", "Ймовірно продане (є дохід від відчуження)"),
        ("майно_члена_сім'ї_що_вибув", "Вибуло разом із членом сім'ї"),
    )
    any_asset = False
    for key, label in asset_sections:
        items = st.get(key) or []
        if items:
            any_asset = True
            extra = ""
            if key == "нове_майно" and st.get("окремих_набуттів"):
                extra = f", окремих набуттів: {st['окремих_набуттів']}"
            total = st.get("нове_майно_всього") if key == "нове_майно" else None
            facts.append(f"{label} ({total or len(items)}{extra}): {_list(items)}.")
    for ch in st.get("зміна_власника") or []:
        any_asset = True
        facts.append(
            f"Змінився власник: {ch.get(_OBJ, '')} {ch.get('розмір', '')} — "
            f"{ch.get('власник_був')} → {ch.get('власник_став')}."
        )
    for ch in st.get("зміна_розміру") or []:
        any_asset = True
        facts.append(
            f"Змінено розмір: {ch.get(_OBJ, '')} (набуто {ch.get('набуто')}) — "
            f"{ch.get('розмір_був')} → {ch.get('розмір_став')}."
        )
    if not any_asset:
        facts.append("Змін у майні немає.")
    inc = st.get("дохід_родини_грн") or {}
    facts.append(f"Дохід родини: {_money(inc.get('попередній'))} → {_money(inc.get('новий'))} грн.")
    return facts


def timeline_text(result: Dict[str, Any]) -> str:
    """Блок для промпта підсумку досьє. Бал Jev свідомо НЕ числом, а словом:
    число в промпті LLM заякорює оцінку (docs/JEV.md §4)."""
    pairs = result.get("pairs") or []
    if not pairs:
        return ""
    lines = [
        "Хронологія змін між сусідніми деклараціями. Факти пораховано програмою з "
        "самих декларацій; «пріоритет» — оцінка моделі Jev, наскільки зміни варті "
        "перевірки, а не висновок про порушення."
    ]
    for p in pairs:
        lines.append(
            f"- {p['period']} [пріоритет: {LEVEL_LABELS.get(p['level'], p['level'])}]: "
            + " ".join(p.get("facts") or [])
        )
    return "\n".join(lines)


_LEVEL_STYLE = {
    "low": "background:#dcfce7;color:#14532d;border:1px solid #86efac;",
    "medium": "background:#fde68a;color:#92400e;border:1px solid #fbbf24;",
    "high": "background:#fecaca;color:#7f1d1d;border:1px solid #f87171;",
}


def render_section_html(result: Dict[str, Any]) -> str:
    pairs = result.get("pairs") or []
    if not pairs:
        return ""
    rows = []
    for p in pairs:
        lvl = p.get("level", "low")
        badge = (
            f'<span style="display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;'
            f'font-weight:700;letter-spacing:.03em;text-transform:uppercase;{_LEVEL_STYLE.get(lvl, "")}">'
            f"{html.escape(LEVEL_LABELS.get(lvl, lvl))}</span>"
        )
        facts = "".join(f"<li>{html.escape(f)}</li>" for f in p.get("facts") or [])
        rows.append(
            "<tr>"
            f'<td style="padding:8px 10px;border-top:1px solid #e2e8f0;white-space:nowrap;vertical-align:top;'
            f'font-variant-numeric:tabular-nums;">{html.escape(p.get("period", ""))}</td>'
            f'<td style="padding:8px 10px;border-top:1px solid #e2e8f0;vertical-align:top;">{badge}</td>'
            f'<td style="padding:8px 10px;border-top:1px solid #e2e8f0;vertical-align:top;">'
            f'<ul style="margin:0;padding-left:18px;">{facts}</ul></td>'
            "</tr>"
        )
    sup = result.get("superseded") or []
    sup_note = (
        f" Виправлені декларації враховано замість оригіналів ({len(sup)})."
        if sup else ""
    )
    return f"""  <section id="{SECTION_ID}" style="margin-top:28px;padding:14px 16px;border:1px solid #cbd5e1;border-radius:8px;background:#fff;max-width:100%;">
    <h2 style="margin:0 0 6px 0;font-size:17px;color:#0f172a;">Зміни між роками</h2>
    <p style="margin:0 0 10px 0;font-size:13px;color:#475569;line-height:1.5;">Різницю між сусідніми деклараціями рахує програма; пріоритет — оцінка моделі Jev, наскільки ці зміни варті перевірки. Це не висновок про порушення.{html.escape(sup_note)}</p>
    <table style="width:100%;border-collapse:collapse;font-size:13px;line-height:1.5;color:#1e293b;">
      <thead><tr>
        <th style="text-align:left;padding:6px 10px;color:#64748b;font-weight:600;">Період</th>
        <th style="text-align:left;padding:6px 10px;color:#64748b;font-weight:600;">Пріоритет</th>
        <th style="text-align:left;padding:6px 10px;color:#64748b;font-weight:600;">Що змінилося</th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </section>
"""


def append_section_to_html(path: Path, block: str) -> None:
    """Вставити/замінити розділ перед підсумком досьє (або перед </body>)."""
    raw = path.read_text(encoding="utf-8")
    body = re.sub(rf'<section\s+id="{re.escape(SECTION_ID)}"[^>]*>.*?</section>\s*', "",
                  raw, flags=re.DOTALL | re.IGNORECASE)
    m = re.search(rf'<section\s+id="{re.escape(SUMMARY_SECTION_ID)}"', body, re.IGNORECASE)
    if m:
        pos = m.start()
    else:
        idx = body.lower().rfind("</body>")
        pos = idx if idx != -1 else len(body)
    out = body[:pos] + block + body[pos:]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(out, encoding="utf-8")
    os.replace(tmp, path)
