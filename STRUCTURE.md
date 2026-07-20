# DeclaratorLM — детальна архітектура проєкту

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
1. Користувач взаємодіє через React UI у PyWebView-вікні
2. React викликає Python-методи через `window.pywebview.api.*`
3. `webview_app.py` будує команду та запускає `main.py` як subprocess
4. `main.py` читає JSON-декларації, будує compact v2, викликає LLM, нормалізує відповідь, пише JSONL
5. Після завершення `webview_app.py` запускає `report.py` для CSV/HTML
6. React відображає результати через `run_extra_report` / `open_report_table`

---

## 2. Бекенд: main.py

**Розмір:** ~2100 рядків. Єдина точка входу як для GUI (через subprocess), так і для прямого CLI.

### 2.1 Промпти

```python
SYSTEM_PROMPT   # Роль аналітика, формат JSON-відповіді, 9 правил
USER_PROMPT_TEMPLATE  # Шаблон з {declaration_payload}
```

Промпти можна перевизначити на рівні сесії через `--prompt-overrides` (JSON-файл з ключами `pipeline_system_prompt`, `pipeline_user_prompt_template`, `dossier_system_prompt`, `dossier_user_prompt_template`).

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
   │   → compact v2 JSON (~3.6k симв. середнє)
   │
   ▼
user_prompt = USER_PROMPT_TEMPLATE.format(declaration_payload=compact_str)
   │
   ▼
call_ollama() або call_openrouter()  [retries, timeout]
   │   → raw text відповідь моделі
   │
   ▼
extract_json_from_model_output(text)
   │   → очищення ```json ```, ремонт json (trailing commas тощо)
   │
   ▼
normalize_analysis_payload(analysis_raw, ...)
   │   → нормалізований dict з гарантованими типами
   │
   ▼
append_jsonl(output_path, result)
   │
   ▼
[якщо audit mode] → зберегти артефакти у ./audit/{decl_id}/
```

**Retry-логіка:**
- `--retries N` (default 2) → максимум N+1 спроб
- При `PayloadLimitExceededError` (payload > `--max-chars`): `--on-limit` вибирає поведінку:
  - `auto-raise-32000` (default): автопідвищення ліміту до 32000
  - `ask`: чекає файл-контрол
  - `skip`: пропустити декларацію
  - `fail-run`: зупинити пайплайн

**Паралельна обробка (OpenRouter):**
- `--max-concurrent-declarations N` (1–8)
- `ThreadPoolExecutor` + `wait(FIRST_COMPLETED)`
- Для Ollama завжди послідовно (model bottleneck)

### 2.4 Resume (відновлення)

`load_processed_filenames()` читає JSONL і повертає вже оброблені файли для поточної моделі. При наступному запуску вони пропускаються. Модель-ключ: `(model_id, launch_mode)`.

### 2.5 Сортування файлів

| `--sort-order` | Логіка |
|----------------|--------|
| `alpha` (default) | за іменем A→Z |
| `alpha-desc` | за іменем Z→A |
| `mtime` | нові спочатку |
| `mtime-asc` | старі спочатку |
| `size` | великі спочатку |
| `size-asc` | малі спочатку |
| Deep Research | хронологічно за `declaration_year`/`date` |

### 2.6 normalize_analysis_payload

Нормалізує raw відповідь LLM у стабільний формат:
- `risk_score`: int 0–100
- `risk_level`: `low|medium|high|critical`
- `findings[]`: нормалізований масив (title, type, severity, confidence 0–1, evidence, involved_persons, related_assets_or_income, rationale)
- `family_assets_overview[]`: person, asset_count, asset_examples
- `red_flags[]`, `needs_verification[]`, `clear_facts[]`
- `final_assessment`: рядок
- `run_meta`: model, launch_mode, source_file, declaration_id, chars_sent, attempt_count тощо

### 2.7 Основні CLI аргументи

```
--input-dir           Папка з JSON-деклараціями
--output              JSONL-файл результатів (default: analysis_results.jsonl)
--errors-output       JSONL-файл помилок
--model               Назва моделі Ollama
--host                URL Ollama API
--timeout             Секунди очікування відповіді (default: 600)
--retries             Кількість повторних спроб (default: 2)
--max-chars           Ліміт символів compact (default: 64000)
--num-predict         Ліміт токенів відповіді (default: 16000)
--max-files           Максимум файлів за запуск (0 = усі)
--provider            ollama | openrouter
--openrouter-*        host, model, api-key для OpenRouter
--audit-mode          Режим збереження артефактів
--audit-mode-dir      Папка артефактів (default: audit)
--compact-legacy-payload  Додати all_nonempty_steps_payload до compact
--on-limit            auto-raise-32000 | ask | skip | fail-run
--sort-order          Порядок обробки файлів
--selected-files      CSV-список конкретних файлів для обробки
--max-concurrent-declarations  Паралельність (OpenRouter, 1–8)
--reasoning-debug     Стримінг THINK_EVENT-рядків
--move-processed      Переносити оброблені у --processed-dir
```

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

**5 неінтерпретованих:** step_5, 7, 8, 10, 16 → у `raw_extras` (якщо непорожні)

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

### 3.7 Вихід compact v2 (~3.6k симв. середнє, −74% vs raw)

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

POST `{host}/chat/completions` (OpenAI-compatible):

```json
{
  "model": "meta-llama/llama-3.3-70b-instruct",
  "temperature": 0,
  "response_format": { "type": "json_object" },
  "messages": [...]
}
```

- `call_openrouter()` → повна відповідь JSON
- `stream_openrouter_with_reasoning()` → SSE-стримінг з think-блоками
- `fetch_openrouter_models()` → GET `/models` → список model id
- `fetch_openrouter_models_enriched()` → + контекст, ціна, провайдер
- `fetch_openrouter_credits()` → GET `/credits` → залишок балансу
- `test_openrouter_connection()` → мінімальний тест-запит

Заголовки: `HTTP-Referer`, `X-Title`, `Authorization: Bearer`, `User-Agent`.

---

## 5. Webview API: webview_app.py

**~2300 рядків.** Запускає PyWebView-вікно (1180×820, resizable) з вбудованим React SPA.

### 5.1 Запуск

```python
webview.create_window(title, url="dist/index.html", js_api=DeclaratorApi(), ...)
webview.start(gui="edgechromium", ...)
```

При першому `window.loaded` → `_createApi(api)` відправляється в JS, React розуміє що pywebview готовий.

### 5.2 API-методи (js → python)

**Налаштування:**
| Метод | Призначення |
|-------|-------------|
| `load_settings()` | Читає `settings.json`, мерджить з DEFAULTS |
| `save_settings(settings)` | Записує `settings.json`, нормалізує шляхи |
| `dismiss_welcome_modal()` | Встановлює `welcome_dismissed: true` |
| `unlock_debug_ui_mode()` | Розблоковує DEBUG UI (жест на логотипі) |
| `get_builtin_prompts()` | Повертає вбудовані промпти pipeline/dossier |
| `validate(args)` | Перевіряє налаштування перед запуском |

**Пайплайн:**
| Метод | Призначення |
|-------|-------------|
| `run_pipeline(args)` | Запускає main.py через subprocess, читає stdout, emits log-рядки |
| `control_pipeline(command)` | `pause` / `resume` / `cancel` (через .run_control.json) |
| `list_declaration_files(input_dir)` | Список JSON з папки + fingerprint (hash) |
| `declaration_folders_snapshot()` | Стан папок для File Picker |

**Звіти:**
| Метод | Призначення |
|-------|-------------|
| `run_extra_report(args)` | Запускає report.py, повертає шлях до HTML |
| `open_report_table(input_dir, table_html)` | Відкриває HTML у браузері |
| `open_extra_report(args)` | Відкриває CSV/HTML у провіднику/браузері |
| `open_declarations_folder(input_dir)` | Відкриває папку в Explorer |
| `open_file_path(path)` | Відкриває будь-який файл |

**Моделі та з'єднання:**
| Метод | Призначення |
|-------|-------------|
| `fetch_models(host, api_key)` | GET Ollama `/api/tags` → список моделей |
| `fetch_openrouter_models(host, api_key)` | GET OR `/models` → список |
| `fetch_openrouter_models_enriched(...)` | + ціна, контекст, провайдер |
| `fetch_openrouter_credits(...)` | Залишок балансу OR |
| `test_openrouter_connection(...)` | Тест-запит до OR |
| `test_ollama_connection(...)` | Тест-запит до Ollama |

**Файлова система:**
| Метод | Призначення |
|-------|-------------|
| `pick_folder()` | Діалог вибору папки |
| `pick_file()` | Діалог вибору файлу |
| `pick_html_file_open()` | Діалог вибору HTML |
| `copy_to_clipboard(text)` | Копіювання в буфер (JS fallback) |

**Deep Research:**
| Метод | Призначення |
|-------|-------------|
| `deep_research_download(user_declarant_id)` | Завантаження всіх декларацій суб'єкта |
| `deep_research_download_one(declaration_id, target)` | Окрема декларація |
| `nazk_download_by_year(...)` | Завантаження по роках |
| `deep_research_list_folders()` | Список підкаталогів `deep_research/` |
| `deep_research_apply_folder(folder_name)` | Встановити як input_dir |

**Debug:**
| Метод | Призначення |
|-------|-------------|
| `debug_run_dossier_html_summary(args)` | Запуск dossier_html_summary.py |
| `debug_compare_models_html(args)` | Запуск порівняння двох моделей |
| `debug_wipe_usage_traces(args)` | Видалення артефактів/результатів |
| `get_system_metrics()` | CPU/RAM/GPU через psutil + nvidia-smi |
| `shutdown()` | Закриття вікна |

### 5.3 run_pipeline → subprocess

```python
main_cmd = [sys.executable, "main.py",
  "--input-dir", ..., "--model", ..., "--host", ...,
  "--timeout", ..., "--retries", ..., "--max-chars", ...,
  "--num-predict", ..., "--output", ...,
  ...всі інші прапорці...
]
subprocess.Popen(main_cmd, stdout=PIPE, stderr=STDOUT, text=True)
```

Stdout читається рядок за рядком у окремому потоці → `_emit_log()` → `window.evaluate_js("window._onLogLine(...)")` → React лог.

### 5.4 .run_control.json

Файл для управління поточним пайплайном без IPC:
```json
{ "command": "pause" | "resume" | "cancel" }
```

`main.py` перевіряє файл між деклараціями.

### 5.5 settings.json

Зберігає стан усіх налаштувань між сесіями. DEFAULTS (webview_app.py) містить значення за замовчуванням для ~40 ключів.

---

## 6. Допоміжні модулі

### 6.1 report.py

Генерація звітів з JSONL:
- `read_jsonl(path)` → список рядків
- `dedupe_by_latest(rows)` → дедублікація за (declaration_id, model), остання запис виграє
- `make_summary_csv(rows, path)` → CSV з основними полями
- `make_findings_csv(rows, path)` → CSV з розгорнутими знахідками
- `make_table_html(rows, path)` → інтерактивна HTML-таблиця (сортування, фільтр, кольорові ризики)

HTML-таблиця містить: ПІБ, посада, рік, модель, ризик-скор (кольоровий), рівень ризику, знахідки (розкриваються), red flags, дата створення.

### 6.2 dossier_html_summary.py

Генерує текстовий підсумок-досьє, дописуючи його в HTML-звіт:
- Зчитує HTML → обрізає до MAX_HTML_CHARS_DEFAULT (250k символів) для great-than-context моделей
- Запускає `call_ollama_text()` з dossier-промптом
- Вставляє результат у `<section id="declarator-dossier-summary">` → перезаписує HTML

Підтримує також режим порівняння моделей (`COMPARE_SECTION_ID`).

### 6.3 deep_research_bridge.py

Завантаження декларацій НАЗК через `nazk_parser`:
- `deep_research_download(user_declarant_id)` → папка `deep_research/{ПІБ}_{id}/`
- `nazk_download_by_year(year, ...)` → завантаження по конкретному року
- `list_deep_research_folders()` → список існуючих папок для UI
- Валідація шляхів (path traversal захист)

### 6.4 openrouter_client.py

OpenAI-compatible клієнт тільки на stdlib:
- `call_openrouter(model, system, user, host, api_key, ...)` → dict з аналізом
- `stream_openrouter_with_reasoning(...)` → SSE-потік з think-блоками
- `fetch_openrouter_models()` / `fetch_openrouter_models_enriched()`
- `fetch_openrouter_credits()`
- `test_openrouter_connection()`
- Заголовки: `HTTP-Referer: github.com/declarator-lm`, `X-Title: DeclaratorLM`

### 6.5 nazk_parser/

Окремий модуль (своя `main.py`, своя структура) для взаємодії з НАЗК API:
- Завантаження декларацій за user_declarant_id
- Зберігає як `decl_*.json` у `deep_research/`
- Не є частиною основного пайплайну — підключається через `deep_research_bridge.py`

### 6.6 tools/

| Скрипт | Призначення |
|--------|-------------|
| `analyze_compactplus.py` | Аналіз корпусу compact-пар (noise, дублікати, захищені поля) |
| `generate_compactplus_report.py` | Генерує `compactplus_findings.md` з аналізу |
| `validate_compact_v2.py` | Валідація compact v2: savings, coverage, банки, власники |
| `regenerate_compact_corpus.py` | Перегенерація всіх compact-снімків з raw |

---

## 7. Фронтенд: declarator-lm/

**Стек:** React 18 + Vite 5 + Geist шрифт. Single-file компонент `App.jsx` (~6100 рядків). Без роутера, без state management lib.

### 7.1 Структура

```
declarator-lm/
├── src/
│   ├── App.jsx       # Весь UI (~6100 рядків)
│   └── index.css     # Стилі (~3900 рядків)
├── dist/             # Зібраний SPA (index.html + assets/)
├── package.json      # React 18, Vite 5, @fontsource/geist
└── vite.config.js
```

### 7.2 Базові компоненти

| Компонент | Призначення |
|-----------|-------------|
| `Toggle` | Перемикач on/off з tooltip, compact-варіант |
| `FilePathInput` | Лейбл + текстове поле + кнопка вибору папки (іконка) |
| `TooltipWrap` | Обгортка з tooltip на hover |
| `LabelWithTooltip` | Лейбл з іконкою підказки |
| `LogLine` | Рядок логу з класифікацією (ok/error/info/deep/think) |
| `ModelCombobox` | Комбобокс вибору моделі з пошуком |
| `Toggle` + `compact` | Мінімальна версія перемикача для audit-панелі |

### 7.3 Стан (useState)

**Основні налаштування (~40 змінних):**
- `inputDir`, `processedDir`, `moveProcessed`
- `model`, `host`, `timeout`, `retries`, `retryDelay`
- `maxChars`, `numPredict`, `maxFiles`
- `outputJsonl`, `errorsJsonl`, `summaryCsv`, `findingsCsv`, `tableHtml`
- `makeReport`, `noDedupe`, `sortOrder`, `selectedFiles`, `fileQueueMode`
- `showSystemMetrics`, `playCompletionSound`

**Cloud/OpenRouter:**
- `cloudMode`, `cloudProvider` (`ollama|openrouter`)
- `cloudHost`, `cloudModel`, `cloudApiKey`
- `openrouterHost`, `openrouterModel`, `openrouterApiKey`
- `openrouterModels[]`, `openrouterModelPricing`, `openrouterPricingPerToken`
- `pipelineMaxConcurrent` (1–8)

**UI стан:**
- `isRunning`, `ready`, `progress` ({cur, total})
- `logLines[]` (останні 2000), `taskText`
- `debugUiMode`, `logoUnlockRippling`, `debugBadgeReveal`

**Debug/Audit:**
- `auditModeEnabled`, `auditModeDir`
- `auditCaptureRawDeclaration/CompactDeclaration/RequestPayload/ResponseRaw/ResponseParsed/NormalizedAnalysis/AttemptMeta`
- `compactLegacyPayload`

**Модальні вікна:**
- `showWelcomeModal`, `welcomeDismissed`
- `promptEditorOpen`, `promptEditorTab`, `promptDraft`, `sessionPromptOverrides`
- `showCloudComparisonModal`
- `wipeModalOpen`, `wipeBusy`

**Deep Research:**
- `deepResearchMode`, `deepResearchUserId`, `deepResearchFolders[]`
- `deepResearchBusy`, `deepResearchDownloadBusy`

**File picker:**
- `filesToProcess[]`, `filePickerOpen`, `fileFolderSnapshot`
- `filePickerSearch`, `filePickerSort`

### 7.4 Основні функції

| Функція | Призначення |
|---------|-------------|
| `applySettings(s)` | Застосовує об'єкт налаштувань до всіх state-змінних |
| `buildPipelineArgs()` | Збирає args-об'єкт для run_pipeline |
| `runPipeline()` | Виклик api().run_pipeline(args), підписка на логи через `_onLogLine` |
| `handleControlPipeline(cmd)` | pause/resume/cancel через api().control_pipeline |
| `loadOpenrouterModels(host, key)` | Завантаження + кешування списку моделей OR |
| `pickFolder(setter)` | Діалог → setter(path) |
| `openDeclarationsFolder()` | Відкриває папку в Explorer |
| `openPromptEditor()` | Завантажує вбудовані промпти + відкриває модалку |
| `runDebugDossierHtmlSummary()` | Запит підсумку досьє |
| `runDebugCompareModels()` | Compare-режим двох моделей |
| `runDeepResearchDownload()` | Завантаження через НАЗК API |

### 7.5 Секції UI

**Sidebar (налаштування):**
- Шлях до папки декларацій + кнопка Explorer
- File Queue (ручний вибір файлів / порядок)
- Модель (вибір Ollama або OpenRouter)
- Cloud/OpenRouter секція (host, model, api-key, кредити, тест з'єднання)
- Параметри запиту (timeout, retries, max-chars, num-predict, max-files)
- Шляхи виходу (JSONL, CSV, HTML)
- Переміщення оброблених
- Звіти (make-report, no-dedupe, sort)
- Системні метрики
- Звук завершення
- Редагувати промпт (модалка system+user+dossier)

**Основна область:**
- Заголовок + статус/прогрес
- Кнопки: Запустити / Пауза / Скасувати / Відкрити звіт
- Лог виконання (ScrollTo bottom, THINK-блоки collapsible)
- Прогрес-бар

**DEBUG sidebar (після unlock):**
- Compact v2 (legacy payload toggle)
- Режим аудиту (шлях + детальні toggle-и артефактів)
- Підсумок досьє (debug dossier summary)
- Порівняння моделей (debug compare)
- Перегенерувати звіт
- Видалити сліди використання (wipe modal)
- Редагування промптів сесії

**Deep Research вкладка:**
- Поле НАЗК user_declarant_id
- Кнопки: Завантажити всі / по роках
- Список папок `deep_research/`
- Застосувати папку як input_dir

### 7.6 Потік даних React ↔ Python

```
React                         pywebview API
  │                               │
  ├─ load_settings() ────────────► load_settings()
  │ ◄── settings dict ───────────┤
  │ applySettings(s)             │
  │                               │
  ├─ run_pipeline(args) ─────────► _run_pipeline_impl(args)
  │                               │  → subprocess main.py
  │                               │  → stdout line by line
  │ ◄── window._onLogLine(line) ──┤  → _emit_log(line)
  │ → logLines.push(line)        │
  │                               │
  ├─ run_extra_report(args) ─────► run_extra_report(args)
  │ ◄── { ok, table_html } ──────┤  → report.py subprocess
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
  "created_at": "ISO-8601"
}
```

### 8.3 Аудит-артефакти (`audit/{decl_id}/`)

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

- Завантаження всіх декларацій особи за НАЗК `user_declarant_id` → `deep_research/{ПІБ}_{id}/`
- Хронологічна обробка (найстаріші → найновіші)
- HTML-звіт з динамікою по роках
- Dossier Summary: LLM дописує підсумок

### 9.3 Dossier Summary (DEBUG)

- Без повного пайплайну
- Бере існуючий `report_table.html`
- LLM (`dossier_html_summary.py`) генерує 5–10 речень підсумку
- Вставляє в HTML

### 9.4 Compare Models (DEBUG)

- Обробляє ту саму декларацію двома різними моделями
- Виводить порівняльний HTML з обома результатами поряд

### 9.5 Audit Mode (DEBUG)

- Кожна декларація → окремий кейс-каталог у `audit/`
- Зберігаються вибрані артефакти (налаштовується через toggle-и)

### 9.6 CLI режим

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
DeclaratorLM v0.85 clean2/
│
├── main.py                       # 2100 рядків: compact v2, LLM, пайплайн, CLI
├── webview_app.py                # 2300 рядків: PyWebView API, subprocess міст
├── openrouter_client.py          # ~850 рядків: OpenRouter API клієнт
├── deep_research_bridge.py       # ~500 рядків: НАЗК API, завантаження декларацій
├── report.py                     # ~1500 рядків: CSV, HTML-звіти
├── dossier_html_summary.py       # ~340 рядків: LLM-підсумок досьє
├── launcher_gui.py               # Мінімальний launcher GUI (для EXE)
│
├── requirements.txt              # pywebview>=4, psutil, pythonnet
├── DeclaratorLM.spec             # PyInstaller onefile spec
├── settings.json                 # Збережені налаштування (auto-generated)
├── .run_control.json             # Файл управління pipeline (pause/resume/cancel)
│
├── declarator-lm/                # React SPA
│   ├── src/
│   │   ├── App.jsx               # 6100 рядків: весь UI
│   │   └── index.css             # 3900 рядків: стилі
│   ├── dist/                     # Зібраний SPA (include у PyInstaller)
│   └── package.json              # React 18, Vite 5, @fontsource/geist
│
├── nazk_parser/                  # Окремий модуль НАЗК
│   ├── main.py                   # CLI завантаження декларацій
│   └── dataset_declarations*/    # Локальні кеші
│
├── dataset_declarations/         # Вхідна папка JSON (за замовчуванням)
│   └── saved/                    # Збережені файли
├── dataset_declarations_done/    # Оброблені (якщо --move-processed)
│
├── deep_research/                # Завантажені набори для Deep Research
│   └── {ПІБ}_{user_id}/         # Папка особи
│       └── decl_*.json           # Всі декларації особи
│
├── compact/                      # Аудит-знімки (debug режим)
│   └── decl_{uuid}/
│       ├── raw_declaration.json
│       ├── compact_declaration.json
│       ├── request_payload.attempt1.json
│       ├── response_raw.attempt1.json
│       ├── response_parsed.attempt1.json
│       ├── normalized_analysis.json
│       └── attempt_meta.json
│
├── audit/                        # Нова папка аудиту (--audit-mode-dir)
│   └── {decl_stem}/              # Артефакти по декларації
│
├── tools/
│   ├── analyze_compactplus.py    # Аналіз корпусу compact пар
│   ├── generate_compactplus_report.py  # Генерує compactplus_findings.md
│   ├── validate_compact_v2.py    # Валідація compact v2
│   └── regenerate_compact_corpus.py   # Перегенерація compact знімків
│
├── assets/                       # Іконки (.ico), звуки (.wav/.mp3)
├── build/                        # PyInstaller build-артефакти
├── dist/                         # EXE (PyInstaller output)
├── venv/                         # Python virtual environment
│
├── README.md                     # Короткий огляд і дорожня карта
├── STRUCTURE.md                  # Цей файл
├── raw-compact.md                # Документація кроків НАЗК і compact v2
├── compactplus_findings.md       # Звіт аналізу compact v1 vs raw
└── compact_v2_test_report.md     # Тест-звіт compact v2 по корпусу
```

---

## 11. Збірка та розгортання

### 11.1 Фронтенд

```bash
cd declarator-lm
npm run build    # → dist/index.html + dist/assets/
```

dist/ копіюється в PyInstaller пакунок через `datas` в `DeclaratorLM.spec`.

### 11.2 EXE (PyInstaller)

```bash
pyinstaller DeclaratorLM.spec
# → dist/DeclaratorLM.exe (onefile, console=False)
```

`DeclaratorLM.spec` включає:
- `main.py` як прихований import
- `declarator-lm/dist/` → `declarator-lm/dist`
- `nazk_parser/` → `nazk_parser`
- `assets/` → `assets`

При запуску EXE: `_dispatch_frozen_subprocess_cli()` розпізнає CLI-аргументи (job=main/report/dossier) і перенаправляє виконання.

### 11.3 Python залежності

```
pywebview>=4.0,<6   — GUI через Edge Chromium (Windows)
psutil>=5.9,<8      — системні метрики (CPU, RAM)
pythonnet>=3.0.1,<4 — .NET інтеграція для edgechromium backend
```

Решта — стандартна бібліотека (urllib, json, threading, pathlib, argparse, csv, re, time, uuid).
