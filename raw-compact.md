# Raw → Compact: інтерпретація кроків NAZK

Джерело логіки: `compact_declaration()` у [`main.py`](main.py) (рядки 183–434).

Корпус для частот: **14** пар `raw_declaration.json` ↔ `compact_declaration.json` у `./compact` (див. також [`compactplus_findings.md`](compactplus_findings.md)).

---

## Як влаштований compact

Compact — це **не стиснення** raw, а **два шари**:

| Шар | Ключі | Призначення |
|-----|--------|-------------|
| **Structured** | `meta`, `quick_totals`, `step_0_interpreted`, `family_members`, `real_estate`, … | Вручну відібрані поля для аналізу ШІ |
| **Extras** | `raw_extras` | Непокриті кроки (5,7,8,10,16): очищені від шуму + `person_resolved`, `holders_resolved`, `rights_summary` |
| **Legacy payload** | `all_nonempty_steps_payload` | Опційно (`--compact-legacy-payload`) |
| **Контекст** | `steps_context` | Булева карта наявності кроків |

Середній розмір: raw ~11 409 симв., compact ~14 182 симв. (~74% compact — payload).

---

## Зведена таблиця (кроки 0–17)

| Крок | Зміст (NAZK) | Structured-секція | Інтерпретується? | Деталізація | Стабільність | Непорожній у корпусі |
|------|--------------|-------------------|------------------|-------------|--------------|----------------------|
| **0** | Загальні відомості про декларацію | `step_0_interpreted` + частина `meta` | **Так** (коди → мітки) | Часткова | Середня | 14/14 |
| **1** | Особисті дані суб’єкта | `meta.declarant` | **Так** (5 полів) | Мінімальна | Висока для збережених полів | 14/14 |
| **2** | Члени сім’ї | `family_members` | **Так** (1:1 поля) | Повна | Висока | 14/14 |
| **3** | Нерухоме майно | `real_estate` | **Так** (rights → `owners_or_users`) | Часткова | Середня | 14/14 |
| **4** | Незавершене будівництво | `unfinished_construction` | **Так** | Часткова | Не перевірено* | 0/14 |
| **5** | Цінне рухоме майно | — | **Ні** | — | — | 0/14 |
| **6** | Транспорт | `vehicles` | **Так** | Часткова | Висока | 13/14 |
| **7** | Цінні папери | — | **Ні** | — | — | 0/14 |
| **8** | Корпоративні права (участь у капіталі) | — | **Ні** | — | — | 0/14 |
| **9** | Корпоративні права (бенефіціар) | `corporate_rights` | **Так** | Часткова | Не перевірено* | 0/14 |
| **10** | Нематеріальні активи | — | **Ні** | — | — | 0/14 |
| **11** | Дохід | `incomes` | **Так** | Повна / висока | Висока | 14/14 |
| **12** | Грошові активи | `cash_assets` | **Так** | Часткова | Обмежено перевірено | 1/14 |
| **13** | Фінансові зобов’язання | `liabilities` | **Так** | Часткова | Не перевірено* | 0/14 |
| **14** | Істотні зміни | `major_changes` | **Так** | Повна (обрані поля) | Не перевірено* | 0/14 |
| **15** | Витрати за угодами | `expenses` | **Так** | Часткова | Не перевірено* | 0/14 |
| **16** | Додатковий блок форми | — | **Ні** | — | — | 0/14 |
| **17** | Фінансові установи / рахунки | — | **Ні** | — | **Критичний прогалина** | **11/14** |

\* Код structured є, але у корпусі з 14 декларацій крок не зустрічався непорожнім — поведінка на реальних даних не верифікована.

Додатково з усіх кроків з доходами/майном будуються **`quick_totals`** (суми через `safe_float`).

---

## Інтерпретовані кроки (деталі)

### step_0 — загальні відомості

**Куди:** `step_0_interpreted`, дублікати кодів у `meta` (рік, тип з верхнього рівня raw).

**Що робиться:**
- `declarationType` → `declaration_type_code` + `declaration_type_label` (мапа: 1–4 + `changes` → «Декларація змін»).
- Якщо є `changesYear` (або `type=2` при змінах) — код `changes`; значення `declaration_type=0` ігнорується.
- Роки періоду: `declarationYear1`, `declarationYearFrom/To`, `declarationYear4`, `changesYear`.
- `continue_perform_functions` → код + мітка («продовжує / не продовжує…»).
- З верхнього рівня raw: `responsible_position`, `post_type`, `post_category`, `corruption_affected`.

**Втрати:** інші поля `step_0.data`, якщо є поза переліченим.

**Стабільність — покращена:** декларації змін (`changesYear`) отримують мітку «Декларація змін»; невалідний `declaration_type=0` не блокує fallback.

---

### step_1 — суб’єкт декларування

**Куди:** `meta.declarant`.

**Зберігаються:** `lastname`, `firstname`, `middlename`, `workPlace`, `workPost`.

**Втрати:** ~65 інших ключів raw (адреси, `*Path`, `taxNumber`, `passport`, `unzr`, `birthday`, `_extendedstatus` тощо). У корпусі більшість — плейсхолдери `[Конфіденційна інформація]` / `[Не застосовується]`.

**Стабільність — висока** для антикорупційно релевантних полів (`workPlace`, `workPost`); навмисне відсікання PII.

---

### step_2 — члени сім’ї

**Куди:** `family_members[]`.

**Поля:** `id`, `subjectRelation`, `lastname`, `firstname`, `middlename`.

**Також:** `id` → індекс для `resolve_right_holders()` (`person_index`).

**Стабільність — висока:** прямий перенос без трансформацій; дубль у payload.

---

### step_3 — нерухомість

**Куди:** `real_estate[]`.

**Поля:** `objectType`, `totalArea`, `owningDate`, `cost_date_assessment`, `owners_or_users`, `rights_summary[]`, `location` (region/district/city з `*_txt`, без конфіденційних адрес).

**Трансформація:** `rights[]` → `owners_or_users[]` + `rights_summary[]` (`holder`, `ownership_type`, `other_ownership`, `percent_ownership`). `rightBelongs=j` → ПІБ/назва з `ua_*` / `ua_company_name` в об’єкті права.

**Стабільність — висока** для власників і типу права; PII-адреси лишаються плейсхолдерами в raw.

---

### step_4 — незавершене будівництво

**Куди:** `unfinished_construction[]`.

**Поля:** `objectType`, `totalArea`, `owningDate`, `owners_or_users` (без `cost_date_assessment` на відміну від step_3).

**Стабільність:** та сама логіка прав, що step_3; **не перевірено на даних** (0/14 у корпусі).

---

### step_6 — транспорт

**Куди:** `vehicles[]`.

**Поля:** `objectType`, `brand`, `model`, `graduationYear`, `owningDate`, `costDate`, `owners_or_users`.

**Стабільність — висока** для основних атрибутів; права — як у step_3.

---

### step_9 — корпоративні права (бенефіціар)

**Куди:** `corporate_rights[]`.

**Поля:** `legalForm`, `company_name` (`company_name_beneficial_owner` або `name`), `company_code`, `country`, `owners` (з `person_who_care[]` або scalar `person` через `person_index`).

**Стабільність — висока** для обох форматів NAZK (старий `name`/`person` і новий beneficial_owner).

---

### step_11 — дохід

**Куди:** `incomes[]` + `quick_totals.income_total_uah_estimated`.

**Поля:** `objectType`, `sizeIncome`, `sources`, `person_who_care` (масив рядків ПІБ/ролей через `person_index`, не сирі `{person: id}`).

**Стабільність — висока:** ключові суми та джерела збережені; сума через `safe_float` (пробіли, коми нормалізуються).

---

### step_12 — грошові активи

**Куди:** `cash_assets[]` + `quick_totals.cash_assets_total_estimated`.

**Поля:** `objectType`, `assetsCurrency`, `sizeAssets`, `owners_or_users`.

**Стабільність:** логіка прав як у нерухомості; у корпусі **1/14**.

---

### step_13 — зобов’язання

**Куди:** `liabilities[]` + `quick_totals.liabilities_total_estimated`.

**Поля:** `objectType`, `sizeObligation`, `currency`, `owners` ← `person_who_care[].person`.

**Відмінність від step_3/6/12:** `owners`, не `owners_or_users`; без `resolve_right_holders`.

**Стабільність:** **0/14** у корпусі.

---

### step_14 — істотні зміни

**Куди:** `major_changes[]`.

**Поля:** `specExpenses`, `specExpensesSubject`, `transactionDate`, `specConsequencesSubject`, `expenses`.

**Стабільність:** **0/14** у корпусі.

---

### step_15 — витрати

**Куди:** `expenses[]`.

**Поля:** `description`, `paid`, `emitent` ← `emitent_ua_company_name` **або** `emitent_citizen`.

**Стабільність:** **0/14** у корпусі.

---

## Неінтерпретовані кроки (лише payload)

Якщо крок непорожній, він потрапляє **лише** в `all_nonempty_steps_payload.step_N` — byte-to-byte копія `data.step_N.data`.

| Крок | Типовий зміст | Ризик при видаленні payload |
|------|---------------|-----------------------------|
| **5** | Цінне рухоме майно (коштовності, мистецтво тощо) | Втрата всього змісту, якщо з’явиться у декларації |
| **7** | Цінні папери | Те саме |
| **8** | Участь у статутному капіталі | Те саме |
| **10** | Нематеріальні активи | Те саме |
| **16** | Додатковий блок форми | Те саме |
| **17** | **Банки / фінустанови, рахунки** | **11/14** декларацій; **єдиний канал** для антикорупційного аналізу банків |

### step_17 — критична прогалина

Типові поля в payload (приклад з корпусу):

- `establishment_ua_company_name`, `establishment_ua_company_code`, `establishment_type`
- `person_open_account`, `person_who_care`, `persons_has_accounts`
- службові: `iteration`, `*_extendedstatus`

**Structured-аналога немає.** Рекомендація (з [`compactplus_findings.md`](compactplus_findings.md)): додати `financial_institutions[]` перед скороченням payload.

---

## Спільні механізми інтерпретації

### `resolve_right_holders(rights)`

```212:224:main.py
    def resolve_right_holders(rights: Any) -> List[str]:
        holders: List[str] = []
        for right in as_list(rights):
            ...
            if key in person_index:
                holders.append(person_index[key])
            elif key:
                holders.append(f"Особа id={key}")
            elif right.get("citizen"):
                holders.append(str(right.get("citizen")))
        return holders
```

| Умова | Результат | Стабільність |
|-------|-----------|--------------|
| `rightBelongs` ∈ person_index | «Стать: ПІБ» або «Суб'єкт декларування» | Стабільно |
| `rightBelongs` поза індексом | `"Особа id=…"` | Нестабільно для аналізу |
| лише `citizen` | рядок citizen | Залежить від формату NAZK |
| `ua_lastname` / інші ua_* без citizen | **ігноруються** | Втрата |

Застосовується: step_3, step_4, step_6, step_12. **Не** застосовується: step_13, step_9 (інша схема `person_who_care`).

### `safe_float` (quick_totals)

Нормалізує рядкові суми (пробіли, кома → крака). Невалідні значення → `None`, не ламають суму.

### `as_list`

Некоректний тип `data` (не масив) → порожній список → **крок вважається порожнім** у structured, але може бути dict у payload-логіці (рідко).

---

## Payload vs structured: що дублюється

| Крок | Structured | Дубль у payload | Безпечно прибрати payload? |
|------|------------|-----------------|------------------------------|
| 0 | частково (`step_0_interpreted`) | повний step_0 | Після канонізації step_0 — так |
| 1 | `meta.declarant` | step_1 | Так (втрати лише шум/PII) |
| 2 | `family_members` | step_2 | Так |
| 3 | `real_estate` | step_3 | **Ні без міграції** — structured втрачає `rights[]`, Path, otherOwnership |
| 6 | `vehicles` | step_6 | Частково — та сама проблема прав |
| 11 | `incomes` | step_11 | Так для основних полів |
| 12 | `cash_assets` | step_12 | Частково |
| 17 | **немає** | step_17 | **Ні** — єдине джерело |

---

## Оцінка стабільності (підсумок)

| Рівень | Кроки | Коментар |
|--------|-------|----------|
| **Висока** | 1 (обрані поля), 2, 11 | Прямий мапінг або навмисний мінімальний набір |
| **Середня** | 0, 3, 4, 6, 12 | Коди/права/старі формати; ризик втрати деталей ownership |
| **Невідома (код без даних)** | 4, 9, 13, 14, 15 | Потрібні декларації з непорожніми кроками |
| **Відсутня (не реалізовано)** | 5, 7, 8, 10, 16, **17** | Лише raw payload; **17 — масовий у корпусі** |

---

## Наслідки для compactplus

1. **Не видаляти весь `all_nonempty_steps_payload`** без міграції **step_17** → structured `financial_institutions[]`.
2. Дублі step_1/2/11 можна прибирати з payload, якщо structured — канон.
3. step_3/6/12: перед видаленням payload потрібно **розширити structured** (ownershipType, otherOwnership, повні дані третіх осіб) або залишити `rights[]` у structured.
4. Додати structured для step_5, 7, 8, 10, 16 — якщо ці кроки з’являться у production-корпусі.

Детальні правила cut/wipe: [`compactplus_findings.md`](compactplus_findings.md).

---

*Згенеровано на основі `main.py` та аналізу 14 пар у `./compact`.*
