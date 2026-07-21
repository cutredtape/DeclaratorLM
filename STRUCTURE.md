# DeclaratorLM — детальна архітектура проєкту

*English version: [STRUCTURE.en.md](STRUCTURE.en.md)*

## Зміст

1. [Загальна архітектура](#1-загальна-архітектура)
2. [Бекенд: main.py](#2-бекенд-mainpy)
3. [Compact v2: алгоритм стиснення декларацій](#3-compact-v2-алгоритм-стиснення-декларацій)
4. [LLM-провайдери](#4-llm-провайдери)
5. [Webview API: webview_app.py](#5-webview-api-webview_apppy)
6. [Допоміжні модулі](#6-допоміжні-модулі)
7. [Фронтенд: declarator-lm/](#7-фронтенд-declarator-lm)
8. [Формати даних](#8-формати-даних)
9. [Режими роботи](#9-режими-роботи)
10. [Файлова структура](#10-файлова-структура)
11. [Збірка та розгортання](#11-збірка-та-розгортання)

---

## 1. Загальна архітектура

```
┌──────────────────────────────────────────────────────────────┐
│  PyWebView Window (Edge Chromium)                            │
│  ┌─────────────────────┐    ┌──────────────────────────────┐ │
│  │  React App (dist/)  │◄──►│  Python API (webview_app.py) │ │
│  │  declarator-lm/src  │    │  js → window.pywebview.api   │ │
│  └─────────────────────┘    └──────────────┬───────────────┘ │
└────────────────────────────────────────────│─────────────────┘
                                             │ subprocess
                                             ▼
                              ┌──────────────────────────┐
                              │       main.py (CLI)       │
                              │  compact_declaration()    │
                              │  call_ollama()            │
                              │  normalize_analysis()     │
                              │  report generation        │
                              └──────────┬───────────────┘
                                         │
                              ┌──────────┴───────────────┐
                              │                          │
                    ┌─────────▼──────┐      ┌───────────▼────────┐
                    │  Ollama API    │      │  OpenRouter API    │
                    │  /api/chat     │      │  /chat/completions │
                    │  (local/cloud) │      │  (openrouter_client│
                    └───────────────-┘      └────────────────────┘
```

**Принцип роботи:**
1. Користувач взаємодіє через React UI у PyWebView-вікні (українською через `webview_app.py`, англійською — через `webview_app_en.py`, той самий код з іншим прапорцем мови).
2. React викликає Python-методи через `window.pywebview.api.*`.
3. `webview_app.py` будує команду та запускає `main.py` як subprocess з `--control-file` для pause/resume/cancel.
4. `main.py` читає JSON-декларації, будує compact v2, викликає LLM, нормалізує відповідь, пише JSONL.
5. Після завершення `webview_app.py` запускає `report.py` для CSV/HTML, а для Deep Research — додатково вбудовує графіки (`dossier_charts_html.py`) і LLM-резюме (`dossier_html_summary.py`) у той самий HTML-файл.
6. React відображає результати через `run_extra_report` / `open_report_table`, а стан "простою" — через дашборд використання (`get_usage_dashboard_stats`) або живий досьє-вигляд (`get_dossier_chart_data`) у режимі Deep Research.

---

## 2. Бекенд: main.py

**Розмір:** 3075 рядків. Єдина точка входу як для GUI (через subprocess), так і для прямого CLI.

### 2.1 Промпти

```python
SYSTEM_PROMPT   # Роль аналітика, формат JSON-відповіді, 9 правил
USER_PROMPT_TEMPLATE  # Шаблон з {declaration_payload}
```

`SYSTEM_PROMPT` (рядки 61–~100): роль аналітика декларацій НАЗК; 9 пронумерованих правил — не вигадувати фактів, явно позначати невизначеність, оцінювати ризик 0–100, віддавати лише JSON (без тексту поза ним), бути максимально конкретним (імена/активи/суми/дати), не робити розпливчастих суджень без прив'язки до фактів, не вигадувати відсутні імена/посади/джерела, враховувати контекст `step_0` (тип декларації/період/статус), а структуровані секції розглядати як покриття основних кроків, тоді як рідкісні непокриті — у `raw_extras`. Далі вбудована точна очікувана JSON-схема відповіді.

`USER_PROMPT_TEMPLATE` (рядки ~100–128): просить порівняти доходи/готівку/майно/транспорт/істотні зміни, зважати на підозрілі патерни (непояснені придбання, занижена/відсутня оцінка вартості, багато операцій за короткий строк, активи на членів родини), повертати коректний JSON з низьким скором навіть якщо підозрілого немає, завжди включати конкретні імена/посади/власників/суми/дати, пояснювати у `clear_facts`, чому щось *не* підозріле, і явно враховувати `step_0_interpreted`, `financial_institutions` та `raw_extras`. Завершується єдиним плейсхолдером `{declaration_payload}`.

Промпти можна перевизначити на рівні сесії через `--prompt-overrides` (JSON-файл з ключами `pipeline_system_prompt`, `pipeline_user_prompt_template`, `dossier_system_prompt`, `dossier_user_prompt_template`) — завантажується один раз при старті (`load_prompt_overrides_file`) і застосовується для кожного файлу (`pipeline_prompts_for_process`). Файл генерується `webview_app.py` (`.debug_session_prompt_overrides.json`) з редактора промптів у DEBUG-панелі; `main.py` читає з нього лише `pipeline_*`-ключі, `dossier_*` призначені для окремої фічі досьє-резюме.

### 2.2 Утиліти

| Функція | Призначення |
|---------|-------------|
| `safe_float(v)` | Парсить числа з рядків (пробіли, коми → крапки), повертає `float\|None` |
| `as_list(v)` | Гарантує список (dict чи non-list → `[]`) |
| `as_str_list(v)` | Список рядків |
| `normalize_risk_level(v, score)` | Валідує рівень ризику або виводить з числового score |
| `normalize_confidence(v)` | Нормалізує 0–100 → 0–1 (підтримка старих відповідей) |

### 2.3 Пайплайн (process_file)

```
JSON-файл
   │
   ▼
compact_declaration(raw, legacy_payload=False)
   │   → compact v2 JSON
   │
   ▼
user_prompt = USER_PROMPT_TEMPLATE.format(declaration_payload=compact_str)
   │
   ▼
call_ollama() або openrouter_client.call_openrouter()  [retries, timeout]
   │   → сира текстова відповідь моделі
   │
   ▼
extract_json_from_model_output(text)
   │   → знімає ```json-огорожі, знаходить перший «{», json.JSONDecoder().raw_decode
   │     (не rfind('}') — стійко до "сміття"/обрізки в кінці відповіді);
   │     при невдачі — одна спроба ремонту (_repair_common_json_issues: trailing commas)
   │
   ▼
normalize_analysis_payload(analysis_raw, ...)
   │   → нормалізований dict з гарантованими типами
   │
   ▼
append_jsonl(output_path, result)
   │
   ▼
[якщо audit mode] → зберегти артефакти у ./{audit_mode_dir}/{decl_stem}/
```

**Retry-логіка:**
- `--retries N` (default 2) → максимум N+1 спроб; при будь-якому винятку — затримка `retry_delay*(attempt+1)`.
- Спеціальний `IncompleteAnalysisError` ретраїться окремо: якщо `risk_score >= 30`, але `findings` порожній — це ознака "врятованої" неповної відповіді моделі, а не легітимного результату.
- При `PayloadLimitExceededError` (payload > `--max-chars`): `--on-limit` вибирає поведінку:
  - `auto-raise-32000` (default): автопідвищення ліміту до ≥32000 і одна повторна спроба
  - `ask`: чекає рішення через `--control-file` (до 180с, потім за замовчуванням — підняти ліміт)
  - `skip`: пропустити декларацію
  - `fail-run`: зупинити пайплайн

**Паралельна обробка (тільки OpenRouter):**
- `--max-concurrent-declarations N` (1–8), дозволено лише коли `--provider openrouter` **і** `--on-limit` дорівнює `skip` або `fail-run` (щоб уникнути гонки за спільний `args.max_chars` під `ask`/`auto-raise-32000`).
- `ThreadPoolExecutor` + ручний цикл `wait(FIRST_COMPLETED)`.
- Ollama завжди послідовно (`"model bottleneck"` — одна модель у пам'яті).

**Прогрес і телеметрія для UI:** окремий структурований лог-канал `VISUAL_LOG|{json}` (стани `PROCESSING`/`OK`/`ERR`/`LIMIT_EXCEEDED` по кожному файлу), плюс `PIPELINE_TOTAL|N`, `PIPELINE_ERR_REVIEW|{...}`, `VISUAL_RUN_TOTALS|{...}` — саме це споживає `VisualLogPanel.jsx` для карткового живого логу. Наприкінці прогону, якщо задано `--control-file`, є інтерактивна фаза розгляду помилок (`_run_error_review_phase`): `retry` / `raise_limits` / `ignore` / `stop` для файлів, що не вдалося обробити.

**Reasoning debug (`--reasoning-debug`):** стрімить Ollama `/api/chat` з `think:true`, буферизує дельти й емітить `THINK_EVENT|<текст>` у stdout з дебаунсом (флаш при ≥80 символів, розділовому знаку, або таймауті 0.7с). При збої стрімінгу — резервний нестрімінговий виклик. Для OpenRouter — ігнорується з попередженням (модель отримує звичайний запит).

**OpenRouter pricing/usage:** перед запуском `main()` тягне живі ціни й контекстні ліміти моделей (`fetch_openrouter_models_enriched`), використовує їх і для обмеження розміру payload на конкретну модель, і для розрахунку вартості/токенів по кожному результату (`openrouter_usage` у виході), і для підсумкового футера вартості прогону.

### 2.4 Resume (відновлення)

`load_processed_filenames()` читає JSONL і повертає вже оброблені файли для поточної моделі. Ключ порівняння — `(model_id, launch_mode)`: перемикання моделі чи провайдера означає повторну обробку всіх файлів; старі рядки з простим рядком `model` (без суфікса режиму) трактуються як `local` для зворотної сумісності.

### 2.5 Сортування файлів

| `--sort-order` | Логіка |
|----------------|--------|
| `alpha` (default) | за іменем A→Z |
| `alpha-desc` | за іменем Z→A |
| `mtime` | нові спочатку |
| `mtime-asc` | старі спочатку |
| `size` | великі спочатку |
| `size-asc` | малі спочатку |

`--selected-files` (CSV-список імен) повністю перевизначає порядок і ігнорує `--max-files`. Якщо `--input-dir` розташований усередині `deep_research/` проєкту, файли замість цього сортуються хронологічно за `declaration_year`+`date` (найстаріші спочатку) — саме так працює режим Deep Research.

### 2.6 normalize_analysis_payload

Нормалізує сиру відповідь LLM у стабільний формат:
- `subject_profile`: declaration_id, user_declarant_id, ПІБ, посада, місце роботи, рік і тип декларації
- `risk_score`: int 0–100
- `risk_level`: `low|medium|high|critical`
- `findings[]`: нормалізований масив (title, type, severity, confidence 0–1, evidence, involved_persons, related_assets_or_income, rationale)
- `family_assets_overview[]`: person, asset_count, asset_examples
- `red_flags[]`, `needs_verification[]`, `clear_facts[]`
- `final_assessment`: рядок
- `run_meta`: model, launch_mode, source_file, declaration_id, chars_sent, attempt_count тощо

### 2.7 Повний список CLI-аргументів (build_parser)

| Прапорець | За замовчуванням | Призначення |
|---|---|---|
| `--input-dir` | `dataset_declarations` | Папка з JSON-деклараціями |
| `--output` | `analysis_results.jsonl` | JSONL-файл успішних аналізів |
| `--errors-output` | `analysis_errors.jsonl` | JSONL-файл помилок обробки |
| `--model` | `llama3.1` | Назва моделі Ollama |
| `--host` | `http://127.0.0.1:11434` | URL Ollama API |
| `--timeout` | `600` | Секунди очікування відповіді на декларацію |
| `--num-predict` | `16000` | Ollama `num_predict`; від'ємне значення = без штучного ліміту |
| `--max-files` | `0` | Максимум файлів за запуск (0 = усі) |
| `--selected-files` | `""` | CSV-список конкретних файлів; зберігає порядок, ігнорує `--max-files` |
| `--sort-order` | `alpha` | `alpha \| alpha-desc \| mtime \| mtime-asc \| size \| size-asc` |
| `--max-chars` | `64000` | Ліміт символів compact-payload, що надсилається моделі |
| `--retries` | `2` | Повторні спроби на файл при транзиєнтних збоях |
| `--retry-delay` | `5` | Базова затримка (с) між повторами |
| `--debug-payload-dir` | `""` | Опційно: зберегти точний payload, надісланий моделі, для діагностики |
| `--control-file` | `""` | JSON-файл управління (pause/resume/stop, error-review, on-limit `ask`) |
| `--processed-dir` | `""` | Якщо задано — успішно оброблений JSON переноситься сюди з `--input-dir` (сам факт заданого шляху вмикає перенесення; окремого прапорця `--move-processed` немає) |
| `--save-compact-declarations` / `--no-save-compact-declarations` | `False` | Зберігати компактний JSON у `--compact-declarations-dir` перед запитом до моделі |
| `--compact-legacy-payload` / `--no-compact-legacy-payload` | `False` | Додати `all_nonempty_steps_payload` (повна сира копія кроків) поряд із compact v2 |
| `--compact-declarations-dir` | `оброблені декларації/compact` | Каталог для збереження компактних декларацій (відносно кореня проєкту) |
| `--audit-mode` | вимкнено | Режим збереження debug-артефактів (ізольований від звичайних виходів) |
| `--audit-mode-dir` | `audit` | Коренева папка артефактів аудиту |
| `--audit-capture-raw-declaration` та ще 6 аналогічних прапорців | усі `False` | Точковий контроль, які саме артефакти зберігати: `-compact-declaration`, `-request-payload`, `-response-raw`, `-response-parsed`, `-normalized-analysis`, `-attempt-meta` |
| `--on-limit` | `auto-raise-32000` | `auto-raise-32000 \| ask \| skip \| fail-run` — поведінка при перевищенні `--max-chars` |
| `--reasoning-debug` | вимкнено | Стрімінг reasoning-токенів моделі як `THINK_EVENT` у stdout |
| `--api-key` | `""` | Bearer-токен для хмарного Ollama-хосту |
| `--cloud-mode` | вимкнено | Прапорець хмарного режиму (лише для логів/UX) |
| `--provider` | `ollama` | `ollama \| openrouter` |
| `--openrouter-host` | `https://openrouter.ai/api/v1` | Базовий URL OpenRouter |
| `--openrouter-model` | `""` | Ідентифікатор моделі OpenRouter |
| `--openrouter-api-key` | `""` | API-ключ OpenRouter (`sk-or-v1-...`) |
| `--prompt-overrides` | `""` | JSON-файл з `pipeline_system_prompt` / `pipeline_user_prompt_template` / `dossier_*` |
| `--max-concurrent-declarations` | `1` | Паралельність (лише `--provider openrouter`, максимум 8; ігнорується для Ollama та при `--on-limit ask`/`auto-raise-32000`) |

---

## 3. Compact v2: алгоритм стиснення декларацій

### 3.1 Вхідні дані

Raw JSON НАЗК (~11k симв. середнє):
```json
{
  "id": "uuid",
  "declaration_year": 2024,
  "declaration_type": 1,
  "type": 1,
  "date": "2025-03-27T14:29:03+02:00",
  "responsible_position": 0,
  "post_type": 2,
  "post_category": 10,
  "corruption_affected": 2,
  "data": {
    "step_0": { "data": { "declarationType": "1", ... } },
    "step_1": { "data": { "lastname": "...", "workPlace": "...", ... } },
    "step_2": { "data": [{ "id": "2", "subjectRelation": "дружина", ... }] },
    "step_3": { "data": [{ "objectType": "Квартира", "rights": [...], ... }] },
    ...
    "step_17": { "data": [{ "establishment_ua_company_name": "...", ... }] }
  }
}
```

### 3.2 Крок 1: person_index

```python
person_index = {"1": "Суб'єкт декларування"}
# + для кожного члена сім'ї з step_2:
# person_index["2"] = "дружина: Іваненко Марія Петрівна"
```

Використовується для розв'язання власників активів.

### 3.3 Крок 2: Structured mapping (13/18 кроків)

`COMPACT_COVERED_STEP_NUMBERS = {0, 1, 2, 3, 4, 6, 9, 11, 12, 13, 14, 15, 17}`.

| Крок | Секція compact v2 | Поля |
|------|--------------------|------|
| 0 | `step_0_interpreted` | declaration_type_code/label (fallback → raw.type), period, public_service_context |
| 1 | `meta.declarant` | lastname, firstname, middlename, work_place, work_post |
| 2 | `family_members[]` | id, subjectRelation, ПІБ |
| 3 | `real_estate[]` | objectType, totalArea, owningDate, cost_date_assessment, owners_or_users |
| 4 | `unfinished_construction[]` | objectType, totalArea, owningDate, owners_or_users |
| 6 | `vehicles[]` | objectType, brand, model, graduationYear, owningDate, costDate, owners_or_users |
| 9 | `corporate_rights[]` | legalForm, company_name, country, owners |
| 11 | `incomes[]` | objectType, sizeIncome, sources, person_who_care |
| 12 | `cash_assets[]` | objectType, assetsCurrency, sizeAssets, owners_or_users |
| 13 | `liabilities[]` | objectType, sizeObligation, currency, owners |
| 14 | `major_changes[]` | specExpenses, specExpensesSubject, transactionDate, expenses |
| 15 | `expenses[]` | description, paid, emitent |
| 17 | `financial_institutions[]` | establishment_ua_company_name, code, type, person_who_care, persons_has_accounts |

**5 неінтерпретованих:** step_5, 7, 8, 10, 16 → у `raw_extras` (якщо непорожні).

> `step_17` (банки/фінустанови) від початку виглядав як «критична прогалина» без структурованого аналога (див. історичний розбір у [raw-compact.md](raw-compact.md)) — це вже виправлено: `compact_financial_institutions()` будує `financial_institutions[]` як повноцінну структуровану секцію, і `USER_PROMPT_TEMPLATE` явно посилається на неї.

### 3.4 Крок 3: _resolve_right_holders

Перетворює масив `rights[]` у список рядків власників:

```
rightBelongs ∈ person_index  →  "дружина: Марія Іваненко"
rightBelongs поза індексом   →  "Особа id=1477..."
citizen є                    →  рядок citizen
ua_lastname/firstname є      →  "Іваненко Марія Петрівна"
відсутні rights, є item.person →  fallback через person_index
```

### 3.5 Крок 4: quick_totals

Агрегати через `safe_float`:
- `income_total_uah_estimated` — сума incomes
- `cash_assets_total_estimated` — сума cash_assets
- `vehicle_declared_cost_total_estimated` — сума vehicles
- `realty_declared_cost_total_estimated` — сума real_estate
- `liabilities_total_estimated` — сума liabilities

### 3.6 Крок 5: noise stripping (raw_extras)

`strip_compact_noise()` — рекурсивне очищення непокритих кроків:

**Drop keys:** `*_extendedstatus`, `*Path` (KOATUU), `iteration`, `*_id`, `hash*`, `object_identificationNumber`

**Drop placeholders:** `[Конфіденційна інформація]`, `[Не застосовується]`, `""`

**Protected (ніколи не видаляти):** `id`, `rightBelongs`, `ownershipType`, `otherOwnership`, `owningDate`, `currency`, `sources`, `person_who_care`, `workPlace`, `workPost`, `establishment_ua_company_name`, `establishment_ua_company_code`, `establishment_type`, `person_open_account`, `persons_has_accounts`, `citizen`, все що починається з `size*`/`cost*`, закінчується на `Date`

### 3.7 Вихід compact v2

```json
{
  "meta": { "id", "declaration_year", "declaration_type", "date", "declarant": {...} },
  "quick_totals": { income/cash/vehicle/realty/liabilities totals },
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
  "raw_extras": { "step_5": {...}, ... }  // тільки якщо є непорожні непокриті кроки
}
```

**Legacy режим (`--compact-legacy-payload`):** додатково `all_nonempty_steps_payload` — повна сира копія (для аудиту/дебагу).

Детальний покроковий розбір, оцінка стабільності інтерпретації по кожному кроку і відомі обмеження — у [raw-compact.md](raw-compact.md).

---

## 4. LLM-провайдери

### 4.1 Ollama (локальна та хмарна)

`call_ollama(model, system, user, host, timeout, ...)` → POST `/api/chat`

```json
{
  "model": "llama3.1",
  "stream": false,
  "format": "json",
  "options": { "temperature": 0, "num_predict": 16000 },
  "messages": [{"role": "system", ...}, {"role": "user", ...}]
}
```

- Локальна: `http://127.0.0.1:11434`
- Cloud Ollama: будь-який host + Bearer token (`--api-key`)
- Reasoning debug: `_http_post_chat_stream_with_reasoning()` — стримінг з виведенням THINK_EVENT

`call_ollama_text()` — те саме без `format=json` (для dossier summary).

### 4.2 OpenRouter (`openrouter_client.py`)

POST `{host}/chat/completions` (OpenAI-сумісний):

```json
{
  "model": "meta-llama/llama-3.3-70b-instruct",
  "temperature": 0,
  "response_format": { "type": "json_object" },
  "messages": [...]
}
```

- `call_openrouter()` → повна відповідь JSON
- `call_openrouter_text()` → те саме без `response_format=json_object`, використовується `dossier_html_summary.py` для резюме досьє через OpenRouter
- `stream_openrouter_with_reasoning()` → SSE-стримінг з think-блоками
- `fetch_openrouter_models()` → GET `/models` → список model id
- `fetch_openrouter_models_enriched()` → + контекст, ціна, провайдер
- `fetch_openrouter_credits()` → GET `/credits` → залишок балансу
- `test_openrouter_connection()` → мінімальний тест-запит

Заголовки: `HTTP-Referer`, `X-Title`, `Authorization: Bearer`, `User-Agent`.

---

## 5. Webview API: webview_app.py

**2884 рядки.** Запускає PyWebView-вікно (1180×820, resizable) з вбудованим React SPA. Клас `Api` (рядок 731) — усі його публічні (без підкреслення) методи автоматично стають доступні в JS як `window.pywebview.api.*`.

### 5.1 Запуск

```python
webview.create_window(title, url="dist/index.html" | "dist/index.en.html", js_api=Api(), ...)
webview.start(gui="edgechromium", ...)
```

При першому `window.loaded` → `_createApi(api)` відправляється в JS, React розуміє що pywebview готовий.

### 5.2 API-методи (js → python)

**Налаштування / lifecycle:**
| Метод | Призначення |
|-------|-------------|
| `load_settings()` | Читає `settings.json` + секрети, мерджить з `DEFAULTS`, мігрує застарілі deep_research-шляхи |
| `save_settings(settings)` | Записує `settings.json`; секрети (`openrouter_api_key`, `cloud_api_key`) окремо у `.declarator_secrets.json`; шляхи deep_research — в окремі `deep_*`-ключі |
| `dismiss_welcome_modal()` | Позначає перше вітальне вікно як переглянуте |
| `unlock_debug_ui_mode()` | Вмикає DEBUG UI для поточної сесії (жест на логотипі, без перезапуску) |
| `copy_to_clipboard(text)` | Копіювання в буфер через сирі виклики Win32 `user32`/`kernel32` (обхід ненадійного JS-clipboard у pywebview) |
| `shutdown()` | Прибирає файл сесійних промпт-оверрайдів і зупиняє subprocess пайплайну при закритті вікна |

**Валідація / тест з'єднання:**
| Метод | Призначення |
|-------|-------------|
| `validate(args)` | Перевіряє форму (паралельність 1–8, існування input_dir, хмарні креденшли); для локальної Ollama пінгує `/api/tags` |
| `fetch_models(host, api_key)` | GET Ollama `/api/tags` → список моделей |
| `fetch_openrouter_models(host, api_key)` | GET OR `/models` → список |
| `fetch_openrouter_models_enriched(...)` | + ціна ($/1M токенів), контекст, провайдер |
| `fetch_openrouter_credits(...)` | Залишок балансу OR |
| `test_openrouter_connection(...)` | Debug: тест-запит до OpenRouter |
| `test_ollama_connection(...)` | Debug: тест-запит до Ollama |

**Файлова система:**
| Метод | Призначення |
|-------|-------------|
| `pick_folder()` / `pick_file()` / `pick_html_file_open()` | Нативні діалоги вибору папки/файлу |
| `declaration_folders_snapshot(input_dir, processed_dir)` | Дешевий підрахунок+fingerprint `*.json` в обох папках (без повного парсингу) |
| `list_declaration_files(input_dir)` | Список `*.json` з іменем/роком/посадою/місцем роботи/mtime/розміром по кожній декларації |
| `open_file_path` / `open_report_table` / `open_extra_report` / `open_declarations_folder` | Відкриття файлів/папок через системний обробник (`os.startfile`/`open`/`xdg-open`) |

**Пайплайн:**
| Метод | Призначення |
|-------|-------------|
| `run_pipeline(args)` | Головна точка входу; блокує паралельні запуски; запускає `main.py` subprocess з `--control-file .run_control.json` |
| `control_pipeline(command)` | Пише `{"command": "pause"\|"resume"\|"stop"}` у `.run_control.json` |
| `pipeline_error_action(payload)` | Пише `{"command":"error_action","action":"retry"\|"raise_limits"\|"ignore",...}` для інтерактивного розбору помилок наприкінці прогону |
| `run_extra_report(args)` | Перегенеровує `report_table.html`+CSV з наявного JSONL; для Deep Research — довставляє графіки досьє |

**Звіти / досьє / використання:**
| Метод | Призначення |
|-------|-------------|
| `get_usage_dashboard_stats(args)` | Агрегована статистика для дашборду простою (`usage_dashboard.aggregate_dashboard`) |
| `get_dossier_chart_data(args)` | Часові ряди для живих графіків досьє під час Deep Research (`dossier_charts.build_dossier_chart_series`; лише коли `input_dir` усередині `deep_research/`) |

**Моделі та з'єднання, Deep Research / завантаження з НАЗК:**
| Метод | Призначення |
|-------|-------------|
| `deep_research_download(user_declarant_id)` | Завантаження всіх декларацій суб'єкта → `deep_research/{прізвище}_{id}/` |
| `deep_research_download_one(declaration_id, target)` | Окрема декларація |
| `nazk_download_by_year(...)` | Пакетне завантаження за рік (з фільтрами) через відкритий пошук НАЗК |
| `deep_research_list_folders()` | Список підкаталогів `deep_research/` |
| `deep_research_apply_folder(folder_name)` | Встановити наявну папку як input_dir без нового завантаження |

**Debug:**
| Метод | Призначення |
|-------|-------------|
| `get_builtin_prompts()` | Повертає вбудовані промпти pipeline/dossier для редактора промптів (файлів проєкту не змінює) |
| `debug_run_dossier_html_summary(args)` | Запуск LLM-резюме досьє без повного пайплайну |
| `debug_compare_models_html(args)` | Одна декларація через **2–4** обрані моделі → `compare/<timestamp>_<file>/` |
| `debug_wipe_usage_traces(args)` | Видалення слідів використання (заблоковано під час активного прогону) |
| `get_system_metrics()` | CPU/RAM (застосунок + процес Ollama через psutil), температура CPU, GPU NVIDIA (через `nvidia-smi`), кеш 1.5с |

### 5.3 run_pipeline → subprocess

```python
main_cmd = [sys.executable, "main.py",
  "--input-dir", ..., "--model", ..., "--host", ...,
  "--timeout", ..., "--retries", ..., "--max-chars", ...,
  "--num-predict", ..., "--output", ...,
  ...всі інші прапорці з розділу 2.7...
]
subprocess.Popen(main_cmd, stdout=PIPE, stderr=STDOUT, text=True)
```

Stdout читається рядок за рядком у окремому потоці → `_emit_log()` → `window.evaluate_js("window._onLogLine(...)")` → React лог/картки.

### 5.4 .run_control.json

Файл для управління поточним пайплайном без IPC:
```json
{ "command": "pause" | "resume" | "stop" | "error_action", ... }
```

`main.py` перевіряє файл між деклараціями (`read_control_command`), блокується на паузі (`wait_if_paused`, опитування кожні 0.5с), і так само реалізовані очікування рішення при перевищенні ліміту (`wait_for_limit_decision`) та розгляді помилок (`wait_for_error_action`), з підтвердженням через `write_control_ack`.

### 5.5 settings.json

Зберігає стан усіх налаштувань між сесіями. `DEFAULTS` (webview_app.py, ~48 ключів) містить значення за замовчуванням, згруповані так:

- **Пайплайн:** `input_dir`, `processed_dir`, `move_processed`, `save_compact_declarations`, `max_files`, `model`, `host`, `timeout`, `retries`, `retry_delay`, `max_chars`, `num_predict`, `make_report`, `no_dedupe`, `compact_legacy_payload`, `pipeline_max_concurrent`, `sort_order`, `selected_files`, `file_queue_mode`
- **Вихідні шляхи:** `output_jsonl`, `errors_jsonl`, `summary_csv`, `findings_csv`, `table_html`
- **Аудит:** `audit_mode_enabled`, `audit_mode_dir`, сім прапорців `audit_capture_*` (усі `True` за замовчуванням)
- **Cloud / OpenRouter:** `cloud_mode`, `cloud_provider`, `cloud_host`, `cloud_model`, `cloud_api_key`, `openrouter_host`, `openrouter_model`, `openrouter_api_key`, `compare_enabled`, `compare_count`, `compare_models`
- **UI:** `show_system_metrics`, `play_completion_sound`, `think_event_debug`, `welcome_modal_seen`, `show_header_taglines`
- **Deep Research:** окремий набір `DEEP_PATH_KEYS` (`deep_input_dir`, `deep_output_jsonl`, `deep_errors_jsonl`, `deep_summary_csv`, `deep_findings_csv`, `deep_table_html`), який з'являється у `settings.json` лише коли користувач працює в папці `deep_research/`

Секрети (`openrouter_api_key`, `cloud_api_key`) не пишуться у `settings.json` — окремий файл `.declarator_secrets.json`.

Мова інтерфейсу (UA/EN) — **не** налаштування з `settings.json**; вона визначається один раз при старті процесу через `--lang`/`DECLARATOR_UI_LANG`/`DECLARATOR_LANG` (`_ui_lang()`), і відповідно обирається `dist/index.html` чи `dist/index.en.html` (`_frontend_index_path()`). У класі `Api` немає жодного методу на кшталт `set_language` — перемикач мови в самому вікні відсутній.

---

## 6. Допоміжні модулі

### 6.1 report.py (1701 рядок)

Генерація звітів з JSONL. Імпортує лише `report_i18n` — з `dossier_charts_html.py`/`dossier_html_summary.py` не пов'язаний напряму (композицію HTML "таблиця → графіки → резюме" виконує `webview_app.py`, а не сам `report.py`).

- `read_jsonl(path)` → список рядків
- `dedupe_by_latest(rows)` → дедублікація за (declaration_id, model), останній запис виграє
- `build_summary_rows()` / `build_findings_rows()` + генеричний `write_csv()` → summary CSV та findings CSV
- `write_filterable_html()` → інтерактивний HTML-звіт (наступник старого `make_table_html`): master/detail таблиця з розгортанням по декларації, картки знахідок із severity-бейджами й доказами, блок сім'ї/активів, фільтри та сортування, показ/приховування стовпців, позначки рядків (localStorage), посилання на оригінал декларації через `nazk_public_declaration_url()` (`https://public.nazk.gov.ua/documents/{uuid}`), блок помилок прогону, і хронологічне сортування для режиму досьє (`sort_rows_dossier_chronological`, активне при `--dossier-chronological` або коли вхідний шлях усередині `deep_research/`)
- `write_extras_html()` / `--extras-only` — **позначено як deprecated**, тепер лише викликає `write_filterable_html` з попередженням

### 6.2 report_i18n.py (92 рядки)

**Не** мовний перемикач UI — це таблиця відповідників англ.-кодів → українських підписів для значень з JSON-аналізу LLM (`FINDING_TYPE_UK`, `RISK_LEVEL_UK`/`SEVERITY_UK`, `PROFILE_FIELD_UK`), плюс сортувальні хелпери (`severity_sort_rank`, `RISK_LEVEL_FILTER_ORDER`). Використовується `report.py` та `usage_dashboard.py`, щоб показувати `finding.type`/`risk_level`/ключі профілю українською в HTML/дашборді. Виходу англійською не додає — це суто локалізація підписів для звітів.

### 6.3 dossier_charts.py (287 рядків) і dossier_charts_html.py (412 рядків)

Чіткий поділ дані/рендер:

- **`dossier_charts.py`** — чиста агрегація без HTML. `build_dossier_chart_series()` проходить `deep_research/{особа}_{id}/decl_*.json` хронологічно й рахує по кожному року: risk score/рівень, кількість знахідок і red flags, фінанси (дохід/активи/зобов'язання), кількість нерухомості/транспорту/земельних ділянок. У графіки потрапляють лише декларації типу «щорічна» та «перед звільненням» (декларації змін виключені). Повертає JSON-придатний payload (`person`, `years`, `records`, `processed_count`, `avg_duration_sec`).
- **`dossier_charts_html.py`** — вставляє той самий набір даних як інлайн SVG + vanilla-JS графіки прямо у `report_table.html` (без бібліотек графіків). Три графіки: **«Індикатори ризику»** (risk score + знахідки + red flags), **«Фінанси (грн)»** (дохід/активи/борги), **«Майно (кількість)»** (нерухомість/авто/земля) — з ховер-тултипами й перемикачем легенди. `append_dossier_charts_to_html()` вставляє/замінює секцію `<section id="declarator-dossier-charts">` атомарно (через `.tmp` + `os.replace`).

Конфігурація графіків (назви, кольори, серії) продубльована на фронтенді у `declarator-lm/src/dossierChartConfig.js` — той самий набір графіків рендериться і живим React-компонентом (`DossierCharts.jsx`, під час обробки), і статичним HTML-звітом (`dossier_charts_html.py`, після завершення); обидва споживають одну й ту саму функцію `build_dossier_chart_series()`.

### 6.4 dossier_html_summary.py (336 рядків)

Генерує текстовий підсумок-досьє, дописуючи його в HTML-звіт:
- Зчитує `report_table.html` (уже після вставки графіків) → `prepare_html_for_prompt()`: знімає `<script>`-теги, обрізає до 250 000 символів
- Будує system/user промпти (з опційними оверрайдами сесії)
- Викликає LLM — `main.call_ollama_text()` або, якщо задано `provider="openrouter"`, `openrouter_client.call_openrouter_text()`
- Вставляє результат у `<section id="declarator-dossier-summary">` перед `</body>`, атомарно перезаписуючи HTML

Підтримує також **порівняння кількох моделей на рівні досьє**: `build_dossier_models_comparison_report()` запускає той самий досьє-промпт через 2–4 обрані моделі й рендерить окремий HTML із картками відповідей поряд (`<section id="declarator-dossier-model-compare">`) — окремо від однодекларативного `debug_compare_models_html` у `webview_app.py`.

### 6.5 usage_dashboard.py (387 рядків)

Обчислює агрегований payload для дашборду використання (простій головного вікна, `UsageDashboard.jsx`). Два джерела даних:
- **`analysis_results.jsonl`** (через `report.read_jsonl`/`dedupe_by_latest`) → `aggregate_dashboard()`: розподіл за рівнем ризику, середній/медіанний risk score, сума red flags, топ типів знахідок, кількість по моделях/роках, декларація з найвищим ризиком, загальний час аналізу, середній час на декларацію, і оцінка "заощадженого часу" порівняно з ручною перевіркою (константа `MANUAL_REVIEW_MINUTES = 10` — це оцінка людино-часу, не облік вартості в грошах).
- **`settings.json` → `usage_aggregate`** — персистентна історія сесій (не по декларації): сукупний час роботи й останні 50 сесій (дата, тривалість, к-сть оброблених, к-сть критичних, модель); поповнюється `append_usage_session()` після кожного прогону пайплайну.

Повертає звичайний dict (не HTML) — рендер робить `UsageDashboard.jsx` на фронтенді.

### 6.6 webview_app_en.py (13 рядків)

```python
"""Launch DeclaratorLM with the English UI (index.en.html)."""
import os, sys
os.environ["DECLARATOR_UI_LANG"] = "en"
import webview_app
if __name__ == "__main__":
    sys.exit(webview_app.main() or 0)
```

Тонка обгортка, не окремий застосунок: виставляє змінну середовища **до** імпорту `webview_app`, після чого викликає той самий `webview_app.main()`. Еквівалент з боку batch-файлу — `run_en.bat` (`set DECLARATOR_UI_LANG=en && python webview_app.py`).

### 6.7 deep_research_bridge.py (643 рядки)

Місток між `webview_app.py` і незалежним модулем `nazk_parser/`. Огорнутий маркерами `# --- DEEP_RESEARCH_BEGIN/END` — за задумом автора, всю фічу Deep Research можна вимкнути, видаливши цей файл і його виклики в `webview_app.py`. Динамічно додає `nazk_parser/` у `sys.path` при кожному виклику (а не імпортує як пакет).

- `run_deep_research_download(user_declarant_id)` — валідація id → `peek_first_lastname()` (перевірка, що API відповідає, і отримання прізвища) → `download_all_for_user_declarant()` у `deep_research/{slug}_{id}/`; емітить прогрес як `DEEP_DOWNLOAD_PROGRESS|{json}`.
- `run_deep_research_download_one(declaration_id, target_input_dir)` — одна декларація за id в довільну (валідовану) директорію.
- `run_nazk_download_by_year(...)` — валідація року (2015…поточний), довжини пошукового запиту (3–255 символів), типу декларації (1–4) й типу документа (1–3); ліміт до 500 файлів за прогін; емітить `NAZK_DOWNLOAD_PROGRESS|{json}`.
- `apply_deep_research_folder(folder_name)` / `list_deep_research_folders()` — "без завантаження": перевикористати вже наявну папку `deep_research/<...>` як input_dir, або перелічити наявні папки з кількістю декларацій.
- `_format_nazk_diag(...)` — спільний людський формат помилки (HTTP-статус, текст, URL) для всіх трьох сценаріїв завантаження.
- Захист від виходу за межі проєкту — дві незалежні перевірки: `_safe_deep_research_subdir()` (для списку/застосування папки: без `..`, без роздільників шляху) і `_output_dir_must_be_under_project()` (для завантаження: цільова папка повинна лишатись під коренем проєкту після `resolve()`).

### 6.8 openrouter_client.py (986 рядків)

OpenAI-сумісний клієнт тільки на stdlib:
- `call_openrouter(model, system, user, host, api_key, ...)` → dict з аналізом
- `call_openrouter_text(...)` → те саме без `response_format=json_object`, для résumé досьє
- `stream_openrouter_with_reasoning(...)` → SSE-потік з think-блоками
- `fetch_openrouter_models()` / `fetch_openrouter_models_enriched()`
- `fetch_openrouter_credits()`
- `test_openrouter_connection()`
- Заголовки: `HTTP-Referer: github.com/declarator-lm`, `X-Title: DeclaratorLM`

### 6.9 nazk_parser/ — клієнт відкритого API НАЗК

Окремий модуль (своя `main.py`, своя структура), який спілкується напряму з відкритим API [Національного агентства з питань запобігання корупції](https://public.nazk.gov.ua/public_api) і **не** використовує ключі авторизації (публічний API, захищений лише браузероподібними заголовками проти WAF).

- **Базовий URL:** `https://public-api.nazk.gov.ua/v2`
  - `GET /documents/list?page=...&user_declarant_id=...&declaration_type=...&declaration_year=...` — сторінкований список
  - `GET /documents/{document_id}` — повна декларація за id
  - Публічна картка декларації для людини (не API): `https://public.nazk.gov.ua/documents/{uuid}`
- `nazk_client.py` (259 рядків): `urllib`-обгортка з ретраями (до 8 спроб) на 429/500/502/503/504, honoring `Retry-After` для 429 (клемп 8–120с); `fetch_list_page()`, `fetch_document()`.
- `nazk_download.py` (308 рядків): `download_professional_dataset()` (пейджинг до ліміту файлів), `peek_first_lastname()` (перше прізвище за user_declarant_id — щоб назвати папку до повного завантаження), `download_all_for_user_declarant()` (усі декларації суб'єкта, з `on_progress`-колбеком), `download_with_filters()` (фільтрована вибірка з локальним застосуванням критеріїв), `scan_local_folder()` (без мережі — пошук у вже завантажених файлах).
- `filters.py` (107 рядків): `FilterCriteria` (рік/діапазон років/підрядок місця роботи/прізвища/імені), `matches_filters()`, `row_preview()` для попереднього перегляду в UI.
- `nazk_parser/main.py` (82 рядки) — самостійний CLI (`python main.py` з теки `nazk_parser/`): `--save-dir`, `--limit`, `--delay`, `--query`, `--user-declarant-id`, `--declaration-year`, `--declaration-type`, `--document-type`. Не є частиною основного пайплайну — підключається через `deep_research_bridge.py`.

### 6.10 launcher_gui.py (1029 рядків)

**Не є точкою входу зібраного EXE** (це виправлення до попередньої версії цього документа — `DeclaratorLM.spec` збирає `webview_app.py`, `launcher_gui.py` у спеку не входить і ніде більше в проєкті не імпортується). Це самостійний, повністю незалежний від pywebview/React **Tkinter-лаунчер**: власне вікно `Tk`/`ttk` з тими самими полями налаштувань, що й `DEFAULTS` у `webview_app.py`, читає/пише той самий `settings.json`, запускає `main.py` через `subprocess.Popen` і стрімить stdout у текстовий віджет, керує тим самим `.run_control.json` (пауза/стоп), а після прогону також викликає `dossier_html_summary`/`dossier_charts_html`. Придатний як легка альтернатива GUI без npm/Vite/pywebview — наприклад, для середовищ, де немає .NET/EdgeChromium.

### 6.11 tools/

| Скрипт | Призначення |
|--------|-------------|
| `analyze_compactplus.py` | Аналіз корпусу compact-пар (noise, дублікати, захищені поля) |
| `generate_compactplus_report.py` | Генерує звіт-знахідки з цього аналізу |
| `validate_compact_v2.py` | Валідація compact v2: savings, coverage, банки, власники |
| `regenerate_compact_corpus.py` | Перегенерація всіх compact-снімків з raw |
| `compare_test_corpus_reports.py` | Разовий скрипт: порівнює два прогони аналізу тестового досьє «Тестовий_10001» (наприклад, до/після зміни compact-формату) за risk-score, кількістю знахідок і тематичним покриттям — регресійна перевірка при зміні промпту чи compact-логіки |
| `verify_test_corpus_compact.py` | Лінтер `compact_declaration()` на тому ж тестовому корпусі: шукає нерозв'язані `"Особа id=..."`, невідомі коди типу декларації, корпоративні права без назви/власників, нерозв'язаний `person_who_care`, биті рядки власників — виходить з кодом 1 при знайдених проблемах |
| `_ua_ui_strings*.txt`, `_en_ui_strings*.txt`, `*_clean_added.txt`, `_ua_ui_added.txt` | Робочі артефакти вилучення UI-рядків при додаванні англійської версії інтерфейсу (снепшоти списків рядків укр./англ. на різних етапах перекладу) — не код і не завантажуються програмою в рантаймі; безпечно прибрати перед релізом, якщо вони більше не потрібні для довірки перекладу |

---

## 7. Фронтенд: declarator-lm/

**Стек:** React 18 + Vite 5 + Geist шрифт. `App.jsx` — 7247 рядків, один головний компонент без роутера й без бібліотеки керування станом (тільки `useState`/`useEffect`).

### 7.1 Структура

```
declarator-lm/
├── src/
│   ├── App.jsx               # Головний UI, 7247 рядків
│   ├── DossierPanel.jsx      # Живий вигляд "досьє" під час Deep Research (415 рядків)
│   ├── DossierCharts.jsx     # Три анімовані SVG-графіки досьє (320 рядків)
│   ├── UsageDashboard.jsx    # Дашборд "Зведення за весь час" (535 рядків)
│   ├── VisualLogPanel.jsx    # Картковий живий лог обробки (859 рядків)
│   ├── dossierChartConfig.js # Спільна конфігурація графіків досьє (126 рядків)
│   ├── index.css             # Стилі (~3900 рядків)
│   ├── main.jsx / main.en.jsx # Дві точки входу Vite (українська/англійська)
│   └── i18n/
│       ├── index.jsx         # React-контекст I18nProvider/useI18n/useT
│       ├── enCatalog.js      # Словник укр.→англ. точних відповідників (558 рядків)
│       └── domTranslate.js   # DOM-перекладач на основі MutationObserver (58 рядків)
├── index.html / index.en.html # Дві HTML-точки входу (lang="uk" / lang="en")
├── dist/                     # Зібраний SPA (включається в PyInstaller EXE)
├── package.json              # declarator-lm@0.3.0, React 18, Vite 5, @fontsource/geist(-mono)
└── vite.config.js            # rollupOptions.input = { main: index.html, en: index.en.html }
```

### 7.2 Базові компоненти

| Компонент | Призначення |
|-----------|-------------|
| `Toggle` | Перемикач on/off з tooltip, compact-варіант |
| `FilePathInput` | Лейбл + текстове поле + кнопка вибору папки (іконка) |
| `TooltipWrap` | Обгортка з tooltip на hover |
| `LabelWithTooltip` | Лейбл з іконкою підказки |
| `ModelCombobox` | Комбобокс вибору моделі з пошуком |
| `DossierPanel` | `NowCard` (поточна особа, risk-гейдж, статус обробки), `DossierProgressStrip` — верхній прогрес-бар режиму досьє; вбудовує `DossierCharts` знизу |
| `DossierCharts` | Три графіки (risk/фінанси/майно) по роках, з тултипами й легендою, що вмикається/вимикається; єдиний компонент, що явно використовує `useI18n` |
| `UsageDashboard` | Плитки з підсумками (час аналізу, заощаджений час, red flags, середній risk, найризикованіша декларація, останній сеанс), автоперегортання кожні 10с |
| `VisualLogPanel` | Картки обробки (`OkCard`/`ErrorCard`/`LimitCard`/`ProcessingCard`) з risk-гейджем, тегами знахідок, вартістю/тривалістю, FLIP-анімацією, перемиканням "картки/текст", інлайновими діями розбору помилок (retry/ignore/raise-limits) |

### 7.3 Стан (useState) — основні групи

**Пайплайн (~40 змінних):** `inputDir`, `processedDir`, `moveProcessed`, `model`, `host`, `timeout`, `retries`, `retryDelay`, `maxChars`, `numPredict`, `maxFiles`, `outputJsonl`, `errorsJsonl`, `summaryCsv`, `findingsCsv`, `tableHtml`, `makeReport`, `noDedupe`, `sortOrder`, `selectedFiles`, `fileQueueMode`, `showSystemMetrics`, `playCompletionSound`.

**Cloud/OpenRouter:** `cloudMode`, `cloudProvider`, `cloudHost`, `cloudModel`, `cloudApiKey`, `openrouterHost`, `openrouterModel`, `openrouterApiKey`, `openrouterModels[]`, `openrouterModelPricing`, `pipelineMaxConcurrent`.

**UI/виконання:** `isRunning`, `ready`, `progress`, `logLines[]` (останні 2000), `logViewMode` (картки/текст, персистентний у localStorage), `visualEntries`, `visualRunTotals`, `pendingThink`, `debugUiMode`.

**Досьє / дашборд (нове):** `usageStats`/`usageStatsLoading`/`usageStatsError` — дані `UsageDashboard`; `dossierChartData`/`dossierChartLoading`/`dossierChartError`/`dossierMainView` — дані й перемикач вкладки «Досьє/Лог» у Deep Research; `showDossierLive`/`showUsageDashboard` — які з трьох станів простою показувати (досьє-лайв, дашборд використання, чи типовий порожній лог).

**Розбір помилок (нове):** `errorActionBusy`, `errorActionTargetFile` + `handlePipelineErrorAction`/`handleErrorRaiseLimits` — інлайнові кнопки retry/ignore/підняти ліміти прямо в картці помилки, надсилають `api().pipeline_error_action(...)`.

**Debug/Audit:** `auditModeEnabled`, `auditModeDir`, сім прапорців `auditCapture*`, `compactLegacyPayload`.

**Модальні вікна:** `showWelcomeModal`, `promptEditorOpen`/`promptEditorTab`/`promptDraft`/`sessionPromptOverrides`, `showCloudComparisonModal`, `wipeModalOpen`.

**Deep Research:** `deepResearchMode`, `deepResearchUserId`, `deepResearchFolders[]`, `deepResearchBusy`, `deepResearchDownloadBusy`.

**File picker:** `filesToProcess[]`, `filePickerOpen`, `fileFolderSnapshot`, `filePickerSearch`, `filePickerSort`.

### 7.4 Основні функції

| Функція | Призначення |
|---------|-------------|
| `applySettings(s)` | Застосовує об'єкт налаштувань до всіх state-змінних |
| `buildPipelineArgs()` | Збирає args-об'єкт для `run_pipeline` |
| `runPipeline()` | Виклик `api().run_pipeline(args)`, підписка на логи через `_onLogLine` |
| `handleControlPipeline(cmd)` | pause/resume/stop через `api().control_pipeline` |
| `handlePipelineErrorAction` / `handleErrorRaiseLimits` | Інлайнові дії розбору помилок з картки |
| `refreshUsageStats()` | `api().get_usage_dashboard_stats(...)` → стан `UsageDashboard` |
| `refreshDossierCharts()` (дебаунснуто) | `api().get_dossier_chart_data(...)` → стан `DossierCharts` |
| `loadOpenrouterModels(host, key)` | Завантаження + кешування списку моделей OR |
| `pickFolder(setter)` | Діалог → setter(path) |
| `openPromptEditor()` | Завантажує вбудовані промпти + відкриває модалку |
| `runDebugDossierHtmlSummary()` / `runDebugCompareModels()` | Debug-запити резюме/порівняння |
| `runDeepResearchDownload()` | Завантаження через НАЗК API |

### 7.5 Секції UI

**Sidebar (налаштування):** шлях до декларацій, File Queue, модель (Ollama/OpenRouter), Cloud-секція (host/model/key/кредити/тест), параметри запиту, шляхи виходу, переміщення оброблених, звіти, системні метрики, звук, редактор промпту.

**Основна область — три стани простою (нове):**
- типовий порожній лог (нічого не запущено, немає Deep Research)
- **Дашборд використання** (`UsageDashboard`) — показується за замовчуванням, коли нічого не виконується і лог порожній
- **Живий вигляд «Досьє»** (`DossierPanel` + `DossierCharts`) — коли активний Deep Research по вхідній папці `deep_research/...`

Під час виконання — прогрес-бар, кнопки Запустити/Пауза/Скасувати/Відкрити звіт, і лог у вигляді карток (`VisualLogPanel`) або звичайного тексту, перемикається кнопкою «Картки/Текст».

**DEBUG sidebar (після unlock):** Compact v2 (legacy payload toggle), режим аудиту, підсумок досьє, порівняння моделей, перегенерувати звіт, видалити сліди використання, редагування промптів сесії.

**Deep Research вкладка:** поле НАЗК `user_declarant_id`, кнопки «Завантажити всі»/«по роках», список папок `deep_research/`, застосування папки як `input_dir`.

### 7.6 Мультимовність (детально)

Мова — властивість процесу, не React-стану: обирається прапорцем/змінною середовища при запуску Python-сервера (див. §6.6, §5.5), який віддає одну з двох статичних HTML-точок входу, зібраних Vite (`vite.config.js`: `rollupOptions.input = { main: "index.html", en: "index.en.html" }`).

- `main.jsx` та `main.en.jsx` обидва обгортають `<App/>` у `<I18nProvider locale="uk"|"en">`, але лише `main.en.jsx` додатково викликає `installDomTranslator(document.body)`.
- `App.jsx` **не використовує** `useI18n`/`useT` — увесь його текст жорстко захардкожений українською.
- Переклад забезпечує `domTranslate.js`: початковий рекурсивний обхід DOM + `MutationObserver` (childList/subtree/characterData/attributes), який підмінює будь-який текстовий вузол чи атрибут (`title`/`aria-label`/`placeholder`/`alt`), що **точно** збігається з ключем у `enCatalog.js` — включно з вузлами, доданими пізніше (лог-картки, модалки).
- Виняток — `DossierCharts.jsx`, єдиний компонент, що по-справжньому інтегрований з `useI18n`/`t()` і додатково гілкується за `locale` для форматування грошей/одиниць (`"млн"/"тис"` проти `"M"/"k"`, `"грн"` проти `"UAH"`).

### 7.7 Потік даних React ↔ Python

```
React                         pywebview API
  │                               │
  ├─ load_settings() ────────────► load_settings()
  │ ◄── settings dict ───────────┤
  │ applySettings(s)             │
  │                               │
  ├─ run_pipeline(args) ─────────► run_pipeline(args)
  │                               │  → subprocess main.py
  │                               │  → stdout line by line
  │ ◄── window._onLogLine(line) ──┤  → _emit_log(line)
  │ → visualEntries/logLines     │
  │                               │
  ├─ get_usage_dashboard_stats ──► usage_dashboard.aggregate_dashboard()
  ├─ get_dossier_chart_data ─────► dossier_charts.build_dossier_chart_series()
  ├─ run_extra_report(args) ─────► report.py subprocess (+ графіки досьє)
  │                               │
  └─ save_settings(settings) ────► save_settings(settings)
```

---

## 8. Формати даних

### 8.1 Вхідний JSON (raw НАЗК)

```json
{
  "id": "uuid-v4",
  "user_declarant_id": 10001,
  "declaration_year": 2024,
  "declaration_type": 1,
  "type": 1,
  "date": "ISO-8601",
  "schema_version": 5,
  "responsible_position": 0,
  "post_type": 2,
  "post_category": 10,
  "corruption_affected": 2,
  "data": {
    "step_0": { "data": { "declarationType": "1", "declarationYear1": 2024, ... } },
    "step_1": { "data": { "lastname": "...", "workPlace": "...", ... } },
    "step_2": { "data": [ { "id": "2", "subjectRelation": "дружина", ... } ] },
    "step_3": { "data": [ { "objectType": "Квартира", "totalArea": "52", "rights": [ { "rightBelongs": "1", "ownershipType": "Спільна сумісна" } ] } ] },
    "step_4" – "step_17": { "data": [...] | {} | isNotApplicable: 1 }
  }
}
```

**Кроки НАЗК:**
- `step_0` — загальні відомості про декларацію
- `step_1` — персональні дані суб'єкта (~70 полів, більшість плейсхолдери)
- `step_2` — члени сім'ї
- `step_3` — нерухоме майно
- `step_4` — незавершене будівництво
- `step_5` — цінне рухоме майно
- `step_6` — транспортні засоби
- `step_7` — цінні папери
- `step_8` — участь у статутному капіталі
- `step_9` — корпоративні права (бенефіціар)
- `step_10` — нематеріальні активи
- `step_11` — доходи
- `step_12` — грошові активи
- `step_13` — фінансові зобов'язання
- `step_14` — істотні зміни у майновому стані
- `step_15` — витрати за угодами
- `step_16` — додатковий блок форми
- `step_17` — фінансові установи / банківські рахунки

### 8.2 Вихідний JSONL (рядок)

```json
{
  "declaration_id": "uuid",
  "user_declarant_id": "10001",
  "source_file": "decl_xxx.json",
  "subject_profile": {
    "declaration_id", "user_declarant_id",
    "declarant_full_name", "position", "workplace", "declaration_year"
  },
  "risk_score": 42,
  "risk_level": "medium",
  "findings": [
    {
      "title", "type", "severity", "confidence",
      "evidence", "involved_persons", "related_assets_or_income", "rationale"
    }
  ],
  "family_assets_overview": [{ "person", "asset_count", "asset_examples" }],
  "red_flags": ["..."],
  "needs_verification": ["..."],
  "clear_facts": ["..."],
  "final_assessment": "...",
  "run_meta": {
    "model", "model_id", "launch_mode",
    "source_file", "declaration_id",
    "chars_sent", "attempt_count",
    "duration_sec", "started_at_utc",
    "run_id"
  },
  "openrouter_usage": { "prompt_tokens", "completion_tokens", "cost_usd" },
  "created_at": "ISO-8601"
}
```

### 8.3 Аудит-артефакти (`{audit_mode_dir}/{decl_stem}/`)

| Файл | Умова | Зміст |
|------|-------|-------|
| `raw_declaration.json` | `--audit-capture-raw-declaration` | Оригінал raw |
| `compact_declaration.json` | `--audit-capture-compact-declaration` | Compact v2 |
| `request_payload.attempt{N}.json` | `--audit-capture-request-payload` | Що надіслано в LLM |
| `response_raw.attempt{N}.json` | `--audit-capture-response-raw` | Сира відповідь |
| `response_parsed.attempt{N}.json` | `--audit-capture-response-parsed` | Розпарсений JSON |
| `normalized_analysis.json` | `--audit-capture-normalized-analysis` | Нормалізований результат |
| `attempt_meta.json` | `--audit-capture-attempt-meta` | Таймінги, статуси спроб |

---

## 9. Режими роботи

### 9.1 Звичайний пайплайн

1. Обрати папку з JSON деклараціями
2. Обрати модель (Ollama / OpenRouter)
3. Натиснути «Запустити»
4. Результати → JSONL → CSV + HTML

### 9.2 Deep Research

- Завантаження всіх декларацій особи за НАЗК `user_declarant_id` → `deep_research/{ПІБ}_{id}/`, або застосування вже наявної папки без нового звернення до API
- Хронологічна обробка (найстаріші → найновіші)
- Живий вигляд «Досьє» під час обробки (графіки оновлюються по мірі надходження результатів)
- HTML-звіт з графіками динаміки по роках + LLM-резюме досьє в кінці

### 9.3 Dossier Summary (DEBUG)

- Без повного пайплайну
- Бере існуючий `report_table.html`
- LLM (`dossier_html_summary.py`) генерує текстовий підсумок і вставляє в HTML
- Або — порівняння 2–4 моделей на рівні всього досьє, окремим HTML-файлом

### 9.4 Compare Models (DEBUG)

- Обробляє ту саму декларацію 2–4 різними моделями (`webview_app.py: debug_compare_models_html`)
- Виводить порівняльний HTML з результатами всіх моделей поряд, у `compare/<timestamp>_<file>/`

### 9.5 Audit Mode (DEBUG)

- Кожна декларація → окремий кейс-каталог у `{audit_mode_dir}/`
- Зберігаються вибрані артефакти (налаштовується через toggle-и)

### 9.6 Usage Dashboard (простій)

- За замовчуванням показується, коли нічого не виконується і лог порожній
- Зведена статистика по всій історії `analysis_results.jsonl` + персистентні сесії з `settings.json`

### 9.7 CLI режим

```bash
python main.py \
  --input-dir dataset_declarations \
  --model llama3.1 \
  --host http://127.0.0.1:11434 \
  --max-files 5 \
  --output results.jsonl
```

---

## 10. Файлова структура

```
DeclaratorLM/
│
├── main.py                       # 3075 рядків: compact v2, LLM, пайплайн, CLI
├── webview_app.py                # 2884 рядки: PyWebView API (UA), subprocess-міст
├── webview_app_en.py             # 13 рядків: той самий сервер англійською
├── openrouter_client.py          # 986 рядків: OpenRouter API клієнт
├── deep_research_bridge.py       # 643 рядки: НАЗК API, завантаження декларацій
├── report.py                     # 1701 рядок: CSV, інтерактивний HTML-звіт
├── report_i18n.py                # 92 рядки: українські підписи значень аналізу
├── dossier_charts.py             # 287 рядків: часові ряди для графіків досьє
├── dossier_charts_html.py        # 412 рядків: вбудовування графіків у HTML-звіт
├── dossier_html_summary.py       # 336 рядків: LLM-резюме досьє + порівняння моделей
├── usage_dashboard.py            # 387 рядків: агрегована статистика використання
├── launcher_gui.py               # 1029 рядків: незалежний Tkinter-лаунчер (не EXE-точка входу)
│
├── requirements.txt              # pywebview>=4,<6; psutil>=5.9,<8; pythonnet>=3.0.1,<4
├── DeclaratorLM.spec             # PyInstaller onefile spec (entry point: webview_app.py)
├── settings.json                 # Збережені налаштування (auto-generated, у .gitignore)
├── .run_control.json             # Файл управління pipeline (у .gitignore)
├── .declarator_secrets.json      # OpenRouter/Cloud API-ключі окремо від settings.json (.gitignore)
│
├── declarator-lm/                # React SPA
│   ├── src/
│   │   ├── App.jsx               # 7247 рядків: основний UI
│   │   ├── DossierPanel.jsx      # 415 рядків: живий вигляд досьє
│   │   ├── DossierCharts.jsx     # 320 рядків: графіки досьє
│   │   ├── UsageDashboard.jsx    # 535 рядків: дашборд використання
│   │   ├── VisualLogPanel.jsx    # 859 рядків: картковий лог обробки
│   │   ├── dossierChartConfig.js # 126 рядків: конфігурація графіків
│   │   ├── i18n/                 # index.jsx, enCatalog.js, domTranslate.js
│   │   └── index.css             # ~3900 рядків: стилі
│   ├── index.html / index.en.html # Дві точки входу Vite
│   ├── dist/                     # Зібраний SPA (include у PyInstaller)
│   └── package.json              # declarator-lm@0.3.0
│
├── nazk_parser/                  # Окремий модуль НАЗК (base URL: public-api.nazk.gov.ua/v2)
│   ├── main.py                   # CLI завантаження декларацій
│   ├── nazk_client.py            # HTTP-клієнт з ретраями
│   ├── nazk_download.py          # Оркестрація пейджингу/збереження
│   └── filters.py                # Локальна фільтрація завантаженого
│
├── dataset_declarations/         # Вхідна папка JSON (за замовчуванням, .gitignore)
├── dataset_declarations_done/    # Оброблені, якщо задано --processed-dir (.gitignore)
├── deep_research/                # Завантажені набори для Deep Research (.gitignore)
│   └── {ПІБ}_{user_id}/          # Папка особи, decl_*.json
├── оброблені декларації/compact/ # Компактні декларації, якщо --save-compact-declarations (.gitignore)
├── audit/                        # Артефакти аудиту, --audit-mode-dir (.gitignore)
├── compare/                      # Виводи порівняння моделей, --debug-compare-models-html (.gitignore)
│
├── tools/                        # Аналіз/валідація compact-корпусу (див. §6.11)
├── docs/screenshots/             # Скріншоти для README
├── assets/                       # Іконки (.ico), звуки (.wav/.mp3)
├── build/, dist/, venv/          # Артефакти збірки/EXE/віртуальне середовище (.gitignore)
│
├── README.md / README.en.md      # Загальний огляд і дорожня карта (укр./англ.)
├── STRUCTURE.md / STRUCTURE.en.md # Цей файл (укр./англ.)
└── raw-compact.md                # Покроковий розбір мапінгу кроків НАЗК → compact v2
```

> Файли `compactplus_findings.md` і `compact_v2_test_report.md`, на які раніше посилався цей документ, у поточному робочому дереві відсутні (можливо, існували лише локально під час розробки, у `.gitignore` їх також немає). Якщо їх немає й у вас — посилання на них варто вважати історичними.

---

## 11. Збірка та розгортання

### 11.1 Фронтенд

```bash
cd declarator-lm
npm install
npm run build    # → dist/index.html + dist/index.en.html + dist/assets/
```

`vite.config.js` визначає два входи (`rollupOptions.input`), тож одна збірка одразу дає обидві мовні версії. `dist/` копіюється в PyInstaller-пакунок через `datas` у `DeclaratorLM.spec`. Також є `BUILD_FRONTEND.bat` — те саме одним подвійним кліком (з перевіркою наявності `package.json` і кодом виходу).

### 11.2 EXE (PyInstaller)

```bash
pyinstaller DeclaratorLM.spec
# → dist/DeclaratorLM.exe (onefile, console=False)
```

`DeclaratorLM.spec`:
- **Точка входу:** `webview_app.py` (**не** `launcher_gui.py` — див. виправлення у §6.10).
- **Datas:** `declarator-lm/dist` → `declarator-lm/dist`; `nazk_parser/` → `nazk_parser`; плюс копії `main.py`, `report.py`, `openrouter_client.py`, `dossier_html_summary.py`, `deep_research_bridge.py` у корінь бандла.
- **Hidden imports:** `clr`, `main`, `openrouter_client`, `deep_research_bridge`, `dossier_html_summary`, `report`, `collect_submodules("webview")`.
- **collect_all:** `webview`, `pythonnet`, `clr_loader`, `bottle`, `proxy_tools`, `psutil`, `cffi` (без цього — падає при `import webview`, коментар автора).
- **Іконка:** `assets/app.ico`. Onefile, `console=False`, `upx=False`.

### 11.3 Допоміжні batch-скрипти

| Скрипт | Призначення |
|--------|-------------|
| `BUILD_FRONTEND.bat` | Збірка фронтенду (`npm run build`) |
| `run_en.bat` | Запуск застосунку з англійським інтерфейсом (`DECLARATOR_UI_LANG=en`) |
| `reasoning.bat` | Запуск із увімкненим reasoning/THINK-стрімінгом (`DECLARATOR_REASONING_DEBUG=1`) |

### 11.4 Python-залежності

```
pywebview>=4.0,<6   — GUI через Edge Chromium (Windows)
psutil>=5.9,<8      — системні метрики (CPU, RAM)
pythonnet>=3.0.1,<4 — .NET інтеграція для edgechromium backend (import clr)
```

Решта — стандартна бібліотека (urllib, json, threading, pathlib, argparse, csv, re, time, uuid). `nazk_parser/` не має жодних зовнішніх залежностей.
