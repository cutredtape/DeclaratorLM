# Raw → Compact v2: як інтерпретуються кроки НАЗК

Джерело істини — `compact_declaration()` і сусідні функції у [`main.py`](main.py) (приблизно рядки 246–908). Цей документ пояснює, **що саме код робить** із сирою декларацією, крок за кроком. Якщо ви адаптуєте проєкт під інший формат даних — почніть звідси (див. [«Адаптація під іншу країну»](#adaptation) в кінці).

---

## 1. Що таке compact v2

Сира декларація НАЗК — це ~11 тис. символів технічного JSON: 18 «кроків» форми, внутрішні коди, службові поля, PII-плейсхолдери, посилання на осіб через числові `id`. Compact v2 — **не просто стиснення**, а перепакування в кілька шарів, зручних для мовної моделі:

| Шар | Ключі | Призначення |
|-----|-------|-------------|
| **Structured** | `meta`, `quick_totals`, `step_0_interpreted`, `family_members`, `real_estate`, `vehicles`, … | 13 кроків, розкладені на вручну відібрані, значущі для аналізу поля |
| **Raw extras** | `raw_extras` | 5 непокритих кроків (5, 7, 8, 10, 16), очищені від шуму й **збагачені** (розв'язані імена/права) — додаються **лише якщо непорожні** |
| **Steps context** | `steps_context` | Скільки й які кроки декларації непорожні |
| **Legacy payload** | `all_nonempty_steps_payload` | Опційно (режим **«Детальніше»** / `--compact-legacy-payload`): повна сира копія всіх непорожніх кроків «як є» |

Результат — компактний, читабельний JSON, де зміст декларації збережено, а технічне сміття прибране.

---

## 2. Покриття кроків (0–17)

Множина покритих кроків задана прямо в коді:

```python
COMPACT_COVERED_STEP_NUMBERS = frozenset({0, 1, 2, 3, 4, 6, 9, 11, 12, 13, 14, 15, 17})
```

**13 із 18 кроків** мають окрему структуровану секцію. Решта 5 (кроки 5, 7, 8, 10, 16) потрапляють у `raw_extras`, якщо непорожні.

| Крок | Зміст (НАЗК) | Структуровано? | Куди в compact |
|------|--------------|:--------------:|----------------|
| **0** | Загальні відомості про декларацію | ✅ | `step_0_interpreted` + `meta` |
| **1** | Особисті дані суб'єкта | ✅ | `meta.declarant` (5 полів) |
| **2** | Члени сім'ї | ✅ | `family_members` |
| **3** | Нерухоме майно | ✅ | `real_estate` |
| **4** | Незавершене будівництво | ✅ | `unfinished_construction` |
| **5** | Цінне рухоме майно | ⬜ | `raw_extras` |
| **6** | Транспортні засоби | ✅ | `vehicles` |
| **7** | Цінні папери | ⬜ | `raw_extras` |
| **8** | Участь у статутному капіталі | ⬜ | `raw_extras` |
| **9** | Корпоративні права (бенефіціар) | ✅ | `corporate_rights` |
| **10** | Нематеріальні активи | ⬜ | `raw_extras` |
| **11** | Доходи | ✅ | `incomes` |
| **12** | Грошові активи | ✅ | `cash_assets` |
| **13** | Фінансові зобов'язання | ✅ | `liabilities` |
| **14** | Істотні зміни в майновому стані | ✅ | `major_changes` |
| **15** | Витрати за угодами | ✅ | `expenses` |
| **16** | Додатковий блок форми | ⬜ | `raw_extras` |
| **17** | Фінансові установи / рахунки | ✅ | `financial_institutions` |

> ✅ **Крок 17 (банки/рахунки) реалізовано.** В ранніх версіях проєкту він був відомою прогалиною (тільки сирий payload, без структурованого аналога). Тепер `compact_financial_institutions()` будує повноцінну секцію `financial_institutions`, а промпт аналізу явно на неї посилається.

---

## 3. Структуровані кроки — деталі

Для кожного кроку нижче — цільова секція compact і поля, які код відбирає (назви полів — точно з `compact_declaration()`).

### Крок 0 — загальні відомості → `step_0_interpreted` (+ `meta`)

- `declaration_type_code` + `declaration_type_label` — код типу декларації розв'язується через `_resolve_declaration_type_code()`: спершу `step_0.declarationType`, далі fallback на `changesYear` (→ «зміни»), потім на `declaration_type`/`type` верхнього рівня raw. Невалідний `0` не блокує fallback.
- `period` — `declaration_year`, `from_year`, `to_year`, `year_special`, `changes_year`.
- `public_service_context` — `continue_perform_functions` (код + мітка), а також `responsible_position`, `post_type`, `post_category`, `corruption_affected` з верхнього рівня raw.

### Крок 1 — суб'єкт декларування → `meta.declarant`

Зберігаються рівно **5 полів**: `lastname`, `firstname`, `middlename`, `work_place` (`workPlace`), `work_post` (`workPost`).

Решта ~65 полів кроку 1 (податковий номер, паспорт, `unzr`, дата народження, адреси, `*Path`, `*_extendedstatus` тощо) **навмисно не переносяться**. Здебільшого у відкритих деклараціях це вже плейсхолдери `[Конфіденційна інформація]` — тобто відсікаються і законом, і кодом.

### Крок 2 — члени сім'ї → `family_members`

Поля: `id`, `subjectRelation`, `lastname`, `firstname`, `middlename`. Крім секції, `id` кожного члена йде в `person_index` для розв'язання власників активів (див. §5).

### Крок 3 — нерухомість → `real_estate`

Поля: `objectType`, `totalArea`, `owningDate`, `cost_date_assessment`, опційно `location` (регіон/район/місто з `*_txt`, **без конфіденційних адрес**), плюс власники через `_asset_rights_fields()` → `owners_or_users` (+ `rights_summary`, якщо є).

### Крок 4 — незавершене будівництво → `unfinished_construction`

Як крок 3, але без `cost_date_assessment`: `objectType`, `totalArea`, `owningDate`, `location?`, `owners_or_users` (+ `rights_summary`).

### Крок 6 — транспорт → `vehicles`

Поля: `objectType`, `brand`, `model`, `graduationYear`, `owningDate`, `costDate`, власники (`owners_or_users` + `rights_summary`).

### Крок 9 — корпоративні права → `corporate_rights`

Через `compact_corporate_rights()`: `legalForm`, `company_name` (з `company_name_beneficial_owner` або `name`), `country`, `owners`, опційно `company_code`. Підтримує і старий, і новий формати НАЗК.

### Крок 11 — доходи → `incomes`

Поля: `objectType`, `sizeIncome`, `sources`, `person_who_care` (список ПІБ/ролей, розв'язаних через `person_index`, а не сирі `{person: id}`).

### Крок 12 — грошові активи → `cash_assets`

Поля: `objectType`, `assetsCurrency`, `sizeAssets`, власники (`owners_or_users` + `rights_summary`).

### Крок 13 — зобов'язання → `liabilities`

Поля: `objectType`, `sizeObligation`, `currency`, `owners` (← `person_who_care`, розв'язані через `person_index`). Відмінність від кроків 3/6/12: тут `owners`, а не `owners_or_users`.

### Крок 14 — істотні зміни → `major_changes`

Поля: `specExpenses`, `specExpensesSubject`, `transactionDate`, `specConsequencesSubject`, `expenses`.

### Крок 15 — витрати → `expenses`

Поля: `description`, `paid`, `emitent` (← `emitent_ua_company_name` **або** `emitent_citizen`).

### Крок 17 — фінансові установи / рахунки → `financial_institutions`

Через `compact_financial_institutions()`: `establishment_ua_company_name`, `establishment_ua_company_code`, `establishment_type`, `person_open_account`, `person_who_care` (розв'язані імена), і `persons_has_accounts` (очищені записи рахунків).

---

## 4. Непокриті кроки → `raw_extras`

Кроки **5, 7, 8, 10, 16** не мають окремої структурованої секції. Якщо крок непорожній, він проходить через `strip_compact_noise()` (§5) і додається в `raw_extras[step_N]`. Додатково `_enrich_raw_extras()` дописує розв'язані посилання прямо в об'єкти:

- `person_resolved` — ПІБ/роль замість числового `person`;
- `holders_resolved` — власники по кожному запису `rights`;
- `rights_summary` — стислий опис прав (тип власності, частка тощо).

Тобто навіть «неструктуровані» кроки йдуть до моделі **очищеними й з розв'язаними іменами**, а не сирими. Якщо в конкретній декларації ці кроки критично важливі — режим **«Детальніше»** (§7) додасть ще й повну сиру копію.

---

## 5. Спільні механізми

### `person_index` (`_build_person_index`)

```python
person_index = {"1": "Суб'єкт декларування"}
# + кожен член сім'ї з кроку 2:
# person_index["2"] = "дружина: Іваненко Марія Петрівна"
```

Основа для розв'язання того, кому належить кожен актив.

### Розв'язання власників (`_resolve_right_holders`)

Для масиву `rights[]`:

| Умова | Результат |
|-------|-----------|
| `rightBelongs` ∈ `person_index` | мітка з індексу («дружина: …» / «Суб'єкт декларування») |
| третя особа (НАЗК ставить `rightBelongs="j"`) | реальні дані з самого об'єкта права: `ua_company_name` (+ код), або `ua_lastname/firstname/middlename`, або `citizen` |
| є `rightBelongs`, але поза індексом і без inline-даних | `"Особа id=<key>"` |
| немає `rights`, але є `item.person` / `personWhoHaveRights` | fallback через `person_index` |

### Очищення шуму (`strip_compact_noise`)

Рекурсивно проходить структуру й:
- **відкидає ключі-шум:** `iteration`, `object_identificationNumber`, `uid`, будь-що на `*_extendedstatus`, `*Path` (коди адміністративного поділу), `*_id` (окрім `id`), `hash*`;
- **відкидає плейсхолдери:** `[Конфіденційна інформація]`, `[Не застосовується]`, порожні значення;
- **захищає (ніколи не викидає):** ключі з `COMPACT_PROTECTED_KEYS`, а також усе, що починається на `size`/`cost` чи закінчується на `Date`.

### Мітки локації (`_resolve_location_labels`)

З полів `region_txt`/`district_txt`/`city_txt`/`ua_cityType` будує `location` = регіон/район/місто/тип. Точні адреси (конфіденційні за ст. 47 закону) не переносяться.

### Підсумки (`quick_totals`, `safe_float`)

`safe_float` нормалізує рядкові суми (пробіли, коми → крапки; невалідне → `None`, не ламає суму). З цього рахуються п'ять агрегатів:

- `income_total_uah_estimated` ← сума `sizeIncome`;
- `cash_assets_total_estimated` ← сума `sizeAssets`;
- `vehicle_declared_cost_total_estimated` ← сума `costDate`;
- `realty_declared_cost_total_estimated` ← сума `cost_date_assessment`;
- `liabilities_total_estimated` ← сума `sizeObligation`.

---

## 6. Повний вихід compact v2 (структура)

```json
{
  "meta": { "id", "declaration_year", "declaration_type", "date",
            "declarant": { "lastname", "firstname", "middlename", "work_place", "work_post" } },
  "quick_totals": { income / cash / vehicle / realty / liabilities totals },
  "step_0_interpreted": { "declaration_type_code", "declaration_type_label", "period", "public_service_context" },
  "steps_context": { "nonempty_steps_count", "nonempty_steps": ["step_0", ...] },
  "family_members": [...],
  "real_estate": [...],
  "vehicles": [...],
  "incomes": [...],
  "cash_assets": [...],
  "major_changes": [...],
  "unfinished_construction": [...],
  "liabilities": [...],
  "corporate_rights": [...],
  "expenses": [...],
  "financial_institutions": [...],
  "raw_extras": { "step_5": {...}, ... }         // лише якщо є непорожні непокриті кроки
  // "all_nonempty_steps_payload": {...}          // лише в режимі «Детальніше»
}
```

---

## 7. Режим «Детальніше» (legacy payload)

Прапорець `--compact-legacy-payload` (перемикач **«Економніше / Детальніше»** в UI) додає до compact ключ `all_nonempty_steps_payload` — **повну сиру копію** всіх непорожніх кроків, точно як в оригінальному JSON реєстру. Модель тоді бачить геть усі поля й формулювання, нічого не «згублено» при стисканні. Запит стає в кілька разів більшим (повільніше й дорожче), тож типово вмикається лише для складних декларацій або коли є підозра, що модель щось не побачила.

---

<a id="adaptation"></a>

## 8. Адаптація під іншу країну

Compact v2 жорстко заточений під схему НАЗК (18 кроків, назви полів, коди зв'язків). Щоб адаптувати проєкт під декларації іншої юрисдикції, змінювати треба переважно **логіку інтерпретації, а не пайплайн**. Ключові точки:

1. **`nazk_parser/`** — клієнт завантаження. Замініть на клієнт вашого джерела даних (API/дамп). Пайплайн (`main.py`), звіти й GUI від джерела не залежать.
2. **`COMPACT_COVERED_STEP_NUMBERS` + білдери секцій** у `compact_declaration()` — перепишіть під розділи *вашої* форми декларації (нерухомість, доходи, рахунки тощо). Це серце адаптації.
3. **`_build_person_index` / `_resolve_right_holders`** — під те, як *ваш* формат кодує членів сім'ї та власників активів.
4. **`strip_compact_noise` (`COMPACT_PROTECTED_KEYS`, ключі-шум)** — під ваші назви полів і те, які поля службові/чутливі.
5. **`DECLARATION_TYPE_MAP`, `CONTINUE_SERVICE_MAP`** та інші довідники кодів — під ваші коди.
6. **Промпти (`SYSTEM_PROMPT`, `USER_PROMPT_TEMPLATE`)** — назви секцій у промпті мають збігатися з тими, що ви створюєте в compact; мову аналізу теж можна змінити.

Що адаптувати **не** треба: виклик LLM (Ollama/OpenRouter), нормалізацію відповіді, звіти (`report.py`), графіки, дашборд, GUI — вони працюють з уже нормалізованим результатом і від країни не залежать.

---

*Згенеровано з коду `main.py` (`compact_declaration` та сусідні функції).*
