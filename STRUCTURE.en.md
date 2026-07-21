# DeclaratorLM — detailed project architecture

*Українська версія: [STRUCTURE.md](STRUCTURE.md)*

## Table of contents

1. [Overall architecture](#1-overall-architecture)
2. [Backend: main.py](#2-backend-mainpy)
3. [Compact v2: the declaration-compression algorithm](#3-compact-v2-the-declaration-compression-algorithm)
4. [LLM providers](#4-llm-providers)
5. [Webview API: webview_app.py](#5-webview-api-webview_apppy)
6. [Supporting modules](#6-supporting-modules)
7. [Frontend: declarator-lm/](#7-frontend-declarator-lm)
8. [Data formats](#8-data-formats)
9. [Modes of operation](#9-modes-of-operation)
10. [File structure](#10-file-structure)
11. [Build and deployment](#11-build-and-deployment)

---

## 1. Overall architecture

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

**How it works:**
1. The user interacts with the React UI inside a PyWebView window (Ukrainian via `webview_app.py`, English via `webview_app_en.py` — the same code with a different language flag).
2. React calls Python methods through `window.pywebview.api.*`.
3. `webview_app.py` builds a command and launches `main.py` as a subprocess with `--control-file` for pause/resume/cancel.
4. `main.py` reads the declaration JSON files, builds compact v2, calls the LLM, normalizes the response, and writes JSONL.
5. When it's done, `webview_app.py` runs `report.py` to build the CSV/HTML, and — for Deep Research — additionally injects charts (`dossier_charts_html.py`) and an LLM summary (`dossier_html_summary.py`) into that same HTML file.
6. React displays the results via `run_extra_report` / `open_report_table`, and the "idle" state either through the usage dashboard (`get_usage_dashboard_stats`) or the live dossier view (`get_dossier_chart_data`) during Deep Research.

---

## 2. Backend: main.py

**Size:** 3,075 lines. The single entry point for both the GUI (via subprocess) and direct CLI use.

### 2.1 Prompts

```python
SYSTEM_PROMPT   # Analyst role, JSON response format, 9 rules
USER_PROMPT_TEMPLATE  # Template with {declaration_payload}
```

`SYSTEM_PROMPT` (lines 61–~100): casts the model as a NAZK-declaration anticorruption analyst; 9 numbered rules — no fabricated facts, explicitly flag uncertainty, score risk 0–100, output JSON only (no prose outside it), be maximally concrete (names/assets/sums/dates), forbid vague judgments not tied to facts, never invent missing names/positions/sources, factor in `step_0` context (declaration type/period/service status), and treat structured sections as covering the main steps while rare uncovered ones live in `raw_extras`. It then embeds the exact expected JSON response schema inline.

`USER_PROMPT_TEMPLATE` (lines ~100–128): instructs the model to compare income/cash/property/vehicles/major changes, watch for suspicious patterns (unsourced purchases, undervalued or missing valuations, many transactions in a short period, assets held by family members), still return valid low-score JSON when nothing is suspicious, always include concrete names/positions/owners/sums/dates, explain in `clear_facts` when something is *not* suspicious, and explicitly factor in `step_0_interpreted`, `financial_institutions`, and `raw_extras`. It ends with a single `{declaration_payload}` placeholder.

Prompts can be overridden for a session via `--prompt-overrides` (a JSON file with keys `pipeline_system_prompt`, `pipeline_user_prompt_template`, `dossier_system_prompt`, `dossier_user_prompt_template`) — loaded once at startup (`load_prompt_overrides_file`) and applied per file (`pipeline_prompts_for_process`). The file is generated by `webview_app.py` (`.debug_session_prompt_overrides.json`) from the DEBUG panel's prompt editor; `main.py` itself only reads the `pipeline_*` keys — `dossier_*` keys belong to the separate dossier-summary feature.

### 2.2 Utilities

| Function | Purpose |
|---------|-------------|
| `safe_float(v)` | Parses numbers from strings (spaces, commas → periods), returns `float\|None` |
| `as_list(v)` | Guarantees a list (dict or non-list → `[]`) |
| `as_str_list(v)` | A list of strings |
| `normalize_risk_level(v, score)` | Validates the risk level or derives it from the numeric score |
| `normalize_confidence(v)` | Normalizes 0–100 → 0–1 (supports older response shapes) |

### 2.3 Pipeline (process_file)

```
JSON file
   │
   ▼
compact_declaration(raw, legacy_payload=False)
   │   → compact v2 JSON
   │
   ▼
user_prompt = USER_PROMPT_TEMPLATE.format(declaration_payload=compact_str)
   │
   ▼
call_ollama() or openrouter_client.call_openrouter()  [retries, timeout]
   │   → raw text response from the model
   │
   ▼
extract_json_from_model_output(text)
   │   → strips ```json fences, finds the first "{", uses
   │     json.JSONDecoder().raw_decode (not rfind('}') — robust to
   │     trailing junk/truncation); one repair retry on failure
   │     (_repair_common_json_issues: trailing commas)
   │
   ▼
normalize_analysis_payload(analysis_raw, ...)
   │   → a normalized dict with guaranteed types
   │
   ▼
append_jsonl(output_path, result)
   │
   ▼
[if audit mode] → save artifacts to ./{audit_mode_dir}/{decl_stem}/
```

**Retry logic:**
- `--retries N` (default 2) → at most N+1 attempts; any exception waits `retry_delay*(attempt+1)`.
- A dedicated `IncompleteAnalysisError` is retried separately: if `risk_score >= 30` but `findings` is empty, that's a sign of a "salvaged" partial response rather than a legitimate result.
- On `PayloadLimitExceededError` (payload exceeds `--max-chars`), `--on-limit` decides the behavior:
  - `auto-raise-32000` (default): auto-raises the limit to ≥32000 and retries once
  - `ask`: waits for a decision via `--control-file` (up to 180s, then defaults to raising the limit)
  - `skip`: skips the declaration
  - `fail-run`: aborts the whole run

**Concurrency (OpenRouter only):**
- `--max-concurrent-declarations N` (1–8), only allowed when `--provider openrouter` **and** `--on-limit` is `skip` or `fail-run` (to avoid a race on the shared `args.max_chars` under `ask`/`auto-raise-32000`).
- `ThreadPoolExecutor` + a manual `wait(FIRST_COMPLETED)` loop.
- Ollama is always sequential ("model bottleneck" — one model held in memory at a time).

**Progress/telemetry for the UI:** a separate structured log channel, `VISUAL_LOG|{json}` (states `PROCESSING`/`OK`/`ERR`/`LIMIT_EXCEEDED` per file), plus `PIPELINE_TOTAL|N`, `PIPELINE_ERR_REVIEW|{...}`, `VISUAL_RUN_TOTALS|{...}` — this is exactly what `VisualLogPanel.jsx` consumes for the card-based live log. At the end of a run, if `--control-file` is set, there's an interactive error-review phase (`_run_error_review_phase`): `retry` / `raise_limits` / `ignore` / `stop` for files that failed to process.

**Reasoning debug (`--reasoning-debug`):** streams Ollama's `/api/chat` with `think:true`, buffers reasoning deltas, and emits `THINK_EVENT|<text>` lines to stdout with debounced flushing (flush at ≥80 chars, on punctuation, or after a 0.7s timeout). Falls back to a non-streaming call if streaming fails. On OpenRouter it's ignored with a warning (the model just gets a normal request).

**OpenRouter pricing/usage:** before running, `main()` fetches live model prices and context limits (`fetch_openrouter_models_enriched`), used both to cap payload size for a given model and to compute per-result token/cost usage (`openrouter_usage` in the output), plus a run-totals cost footer at the end.

### 2.4 Resume

`load_processed_filenames()` reads the JSONL and returns the files already processed for the current model. The comparison key is `(model_id, launch_mode)`: switching model or provider means every file is reprocessed; older rows with a plain `model` string (no mode suffix) are treated as `local` for backward compatibility.

### 2.5 File sort order

| `--sort-order` | Logic |
|----------------|--------|
| `alpha` (default) | by name A→Z |
| `alpha-desc` | by name Z→A |
| `mtime` | newest first |
| `mtime-asc` | oldest first |
| `size` | largest first |
| `size-asc` | smallest first |

`--selected-files` (a CSV list of names) fully overrides the ordering and ignores `--max-files`. If `--input-dir` resolves to somewhere inside the project's `deep_research/` folder, files are instead sorted chronologically by `declaration_year`+`date` (oldest first) — this is how Deep Research mode processes a person's history.

### 2.6 normalize_analysis_payload

Normalizes the raw LLM response into a stable shape:
- `subject_profile`: declaration_id, user_declarant_id, full name, position, workplace, declaration year and type
- `risk_score`: int 0–100
- `risk_level`: `low|medium|high|critical`
- `findings[]`: a normalized array (title, type, severity, confidence 0–1, evidence, involved_persons, related_assets_or_income, rationale)
- `family_assets_overview[]`: person, asset_count, asset_examples
- `red_flags[]`, `needs_verification[]`, `clear_facts[]`
- `final_assessment`: a string
- `run_meta`: model, launch_mode, source_file, declaration_id, chars_sent, attempt_count, etc.

### 2.7 Full CLI argument reference (build_parser)

| Flag | Default | Purpose |
|---|---|---|
| `--input-dir` | `dataset_declarations` | Folder with declaration JSON files |
| `--output` | `analysis_results.jsonl` | Output JSONL file for successful analyses |
| `--errors-output` | `analysis_errors.jsonl` | Output JSONL file for processing errors |
| `--model` | `llama3.1` | Ollama model name |
| `--host` | `http://127.0.0.1:11434` | Ollama host URL |
| `--timeout` | `600` | Seconds to wait for a response per declaration |
| `--num-predict` | `16000` | Ollama `num_predict`; a negative value means no artificial cap |
| `--max-files` | `0` | Maximum files to process per run (0 = all) |
| `--selected-files` | `""` | CSV list of specific files; preserves order, ignores `--max-files` |
| `--sort-order` | `alpha` | `alpha \| alpha-desc \| mtime \| mtime-asc \| size \| size-asc` |
| `--max-chars` | `64000` | Max characters of compact payload sent to the model |
| `--retries` | `2` | Retries per file on transient failures |
| `--retry-delay` | `5` | Base delay (s) between retries |
| `--debug-payload-dir` | `""` | Optional: save the exact payload sent to the model, for diagnostics |
| `--control-file` | `""` | JSON control file (pause/resume/stop, error review, `on-limit ask`) |
| `--processed-dir` | `""` | If set, a successfully analyzed JSON is moved here from `--input-dir` (setting the path itself is what triggers the move — there is no separate `--move-processed` flag) |
| `--save-compact-declarations` / `--no-save-compact-declarations` | `False` | Save the compact JSON in `--compact-declarations-dir` before querying the model |
| `--compact-legacy-payload` / `--no-compact-legacy-payload` | `False` | Add `all_nonempty_steps_payload` (a full raw copy of the steps) alongside compact v2 |
| `--compact-declarations-dir` | `оброблені декларації/compact` | Directory for saved compact declarations (relative to the project root) |
| `--audit-mode` | off | Enables debug-only audit-capture artifacts (isolated from normal output) |
| `--audit-mode-dir` | `audit` | Root directory for audit artifacts |
| `--audit-capture-raw-declaration` and 6 sibling flags | all `False` | Fine-grained control over which artifacts get saved: `-compact-declaration`, `-request-payload`, `-response-raw`, `-response-parsed`, `-normalized-analysis`, `-attempt-meta` |
| `--on-limit` | `auto-raise-32000` | `auto-raise-32000 \| ask \| skip \| fail-run` — behavior when `--max-chars` is exceeded |
| `--reasoning-debug` | off | Stream the model's reasoning tokens as `THINK_EVENT` lines on stdout |
| `--api-key` | `""` | Bearer token for a cloud Ollama endpoint |
| `--cloud-mode` | off | Cloud-mode flag (logging/UX only) |
| `--provider` | `ollama` | `ollama \| openrouter` |
| `--openrouter-host` | `https://openrouter.ai/api/v1` | OpenRouter base URL |
| `--openrouter-model` | `""` | OpenRouter model id |
| `--openrouter-api-key` | `""` | OpenRouter API key (`sk-or-v1-...`) |
| `--prompt-overrides` | `""` | JSON file with `pipeline_system_prompt` / `pipeline_user_prompt_template` / `dossier_*` |
| `--max-concurrent-declarations` | `1` | Concurrency (`--provider openrouter` only, max 8; ignored for Ollama and under `--on-limit ask`/`auto-raise-32000`) |

---

## 3. Compact v2: the declaration-compression algorithm

### 3.1 Input data

A raw NAZK declaration JSON (~11k characters on average):
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
    "step_2": { "data": [{ "id": "2", "subjectRelation": "spouse", ... }] },
    "step_3": { "data": [{ "objectType": "Apartment", "rights": [...], ... }] },
    ...
    "step_17": { "data": [{ "establishment_ua_company_name": "...", ... }] }
  }
}
```

### 3.2 Step 1: person_index

```python
person_index = {"1": "Declarant"}
# + for each family member from step_2:
# person_index["2"] = "spouse: Maria Ivanenko"
```

Used to resolve asset owners.

### 3.3 Step 2: structured mapping (13/18 steps)

`COMPACT_COVERED_STEP_NUMBERS = {0, 1, 2, 3, 4, 6, 9, 11, 12, 13, 14, 15, 17}`.

| Step | compact v2 section | Fields |
|------|--------------------|------|
| 0 | `step_0_interpreted` | declaration_type_code/label (fallback → raw.type), period, public_service_context |
| 1 | `meta.declarant` | lastname, firstname, middlename, work_place, work_post |
| 2 | `family_members[]` | id, subjectRelation, full name |
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

**5 uninterpreted steps:** step_5, 7, 8, 10, 16 → into `raw_extras` (if non-empty).

> `step_17` (banks) originally looked like a "critical gap" with no structured equivalent (see the historical breakdown in [raw-compact.md](raw-compact.md)) — that has since been fixed: `compact_financial_institutions()` builds `financial_institutions[]` as a full structured section, and `USER_PROMPT_TEMPLATE` explicitly references it.

### 3.4 Step 3: _resolve_right_holders

Turns a `rights[]` array into a list of owner strings:

```
rightBelongs ∈ person_index   →  "spouse: Maria Ivanenko"
rightBelongs outside index    →  "Person id=1477..."
citizen present               →  the citizen string
ua_lastname/firstname present →  "Ivanenko Maria Petrivna"
no rights, item.person exists →  fallback via person_index
```

### 3.5 Step 4: quick_totals

Aggregates via `safe_float`:
- `income_total_uah_estimated` — sum of incomes
- `cash_assets_total_estimated` — sum of cash assets
- `vehicle_declared_cost_total_estimated` — sum of vehicles
- `realty_declared_cost_total_estimated` — sum of real estate
- `liabilities_total_estimated` — sum of liabilities

### 3.6 Step 5: noise stripping (raw_extras)

`strip_compact_noise()` — recursively cleans up the uncovered steps:

**Dropped keys:** `*_extendedstatus`, `*Path` (administrative-division codes), `iteration`, `*_id`, `hash*`, `object_identificationNumber`

**Dropped placeholders:** `[Confidential information]`, `[Not applicable]`, `""`

**Protected (never dropped):** `id`, `rightBelongs`, `ownershipType`, `otherOwnership`, `owningDate`, `currency`, `sources`, `person_who_care`, `workPlace`, `workPost`, `establishment_ua_company_name`, `establishment_ua_company_code`, `establishment_type`, `person_open_account`, `persons_has_accounts`, `citizen`, anything starting with `size*`/`cost*`, anything ending in `Date`

### 3.7 compact v2 output

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
  "raw_extras": { "step_5": {...}, ... }  // only if there are non-empty uncovered steps
}
```

**Legacy mode (`--compact-legacy-payload`):** additionally includes `all_nonempty_steps_payload` — a full raw copy (for audit/debugging).

A step-by-step breakdown, a stability rating per step, and known limitations are documented in [raw-compact.md](raw-compact.md) (Ukrainian).

---

## 4. LLM providers

### 4.1 Ollama (local and cloud)

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

- Local: `http://127.0.0.1:11434`
- Cloud Ollama: any host + a bearer token (`--api-key`)
- Reasoning debug: `_http_post_chat_stream_with_reasoning()` — streaming with THINK_EVENT output

`call_ollama_text()` — the same, without `format=json` (used for the dossier summary).

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

- `call_openrouter()` → the full parsed JSON response
- `call_openrouter_text()` → the same without `response_format=json_object`, used by `dossier_html_summary.py` for the dossier summary via OpenRouter
- `stream_openrouter_with_reasoning()` → SSE streaming with think-blocks
- `fetch_openrouter_models()` → GET `/models` → a list of model ids
- `fetch_openrouter_models_enriched()` → + context length, price, provider
- `fetch_openrouter_credits()` → GET `/credits` → remaining balance
- `test_openrouter_connection()` → a minimal test request

Headers: `HTTP-Referer`, `X-Title`, `Authorization: Bearer`, `User-Agent`.

---

## 5. Webview API: webview_app.py

**2,884 lines.** Launches a PyWebView window (1180×820, resizable) with the embedded React SPA. The `Api` class (line 731) — every public (non-underscore) method on it is automatically exposed to JS as `window.pywebview.api.*`.

### 5.1 Launch

```python
webview.create_window(title, url="dist/index.html" | "dist/index.en.html", js_api=Api(), ...)
webview.start(gui="edgechromium", ...)
```

On the first `window.loaded`, `_createApi(api)` is sent to JS so React knows pywebview is ready.

### 5.2 API methods (JS → Python)

**Settings / lifecycle:**
| Method | Purpose |
|-------|-------------|
| `load_settings()` | Reads `settings.json` + secrets, merges over `DEFAULTS`, migrates stale deep_research paths |
| `save_settings(settings)` | Persists `settings.json`; secrets (`openrouter_api_key`, `cloud_api_key`) go to `.declarator_secrets.json`; deep_research paths go into separate `deep_*` keys |
| `dismiss_welcome_modal()` | Marks the first-run welcome modal as seen |
| `unlock_debug_ui_mode()` | Turns on Debug UI for the running session (a gesture on the logo, no restart needed) |
| `copy_to_clipboard(text)` | Copies text via raw Win32 `user32`/`kernel32` calls (works around pywebview's unreliable JS clipboard) |
| `shutdown()` | Removes the session prompt-override file and stops the pipeline subprocess on window close |

**Validation / connection tests:**
| Method | Purpose |
|-------|-------------|
| `validate(args)` | Validates the form (concurrency 1–8, input_dir existence, cloud credentials); pings Ollama's `/api/tags` for local mode |
| `fetch_models(host, api_key)` | GET Ollama `/api/tags` → list of models |
| `fetch_openrouter_models(host, api_key)` | GET OpenRouter `/models` → list of ids |
| `fetch_openrouter_models_enriched(...)` | + price ($/1M tokens), context length, provider |
| `fetch_openrouter_credits(...)` | Remaining OpenRouter balance |
| `test_openrouter_connection(...)` | Debug: a connectivity/auth check against OpenRouter |
| `test_ollama_connection(...)` | Debug: a connectivity check against Ollama |

**Filesystem:**
| Method | Purpose |
|-------|-------------|
| `pick_folder()` / `pick_file()` / `pick_html_file_open()` | Native folder/save/open dialogs |
| `declaration_folders_snapshot(input_dir, processed_dir)` | Cheap `*.json` count+fingerprint of both folders (no full parsing) |
| `list_declaration_files(input_dir)` | Lists `*.json` with name/year/position/workplace/mtime/size per declaration |
| `open_file_path` / `open_report_table` / `open_extra_report` / `open_declarations_folder` | Opens files/folders via the OS default handler |

**Pipeline control:**
| Method | Purpose |
|-------|-------------|
| `run_pipeline(args)` | The main entry point; rejects overlapping runs; launches `main.py` as a subprocess with `--control-file .run_control.json` |
| `control_pipeline(command)` | Writes `{"command": "pause"\|"resume"\|"stop"}` to `.run_control.json` |
| `pipeline_error_action(payload)` | Writes `{"command":"error_action","action":"retry"\|"raise_limits"\|"ignore",...}` for the interactive end-of-run error review |
| `run_extra_report(args)` | Reruns `report.py` from the existing JSONL; for Deep Research it also re-injects the dossier charts |

**Reports / dossier / usage:**
| Method | Purpose |
|-------|-------------|
| `get_usage_dashboard_stats(args)` | Aggregated stats for the idle-state usage dashboard (`usage_dashboard.aggregate_dashboard`) |
| `get_dossier_chart_data(args)` | Time-series data for the live dossier charts during Deep Research (`dossier_charts.build_dossier_chart_series`; only valid when `input_dir` is under `deep_research/`) |

**Deep Research / NAZK download:**
| Method | Purpose |
|-------|-------------|
| `deep_research_download(user_declarant_id)` | Downloads every declaration for a subject → `deep_research/{lastname}_{id}/` |
| `deep_research_download_one(declaration_id, target)` | A single declaration by id |
| `nazk_download_by_year(...)` | Bulk download for a year (with filters) via NAZK's open search |
| `deep_research_list_folders()` | Lists `deep_research/` subfolders |
| `deep_research_apply_folder(folder_name)` | Points `input_dir` at an existing folder without a new download |

**Debug:**
| Method | Purpose |
|-------|-------------|
| `get_builtin_prompts()` | Returns the built-in pipeline/dossier prompts for the prompt editor (doesn't touch project files) |
| `debug_run_dossier_html_summary(args)` | Runs the LLM dossier summary without the full pipeline |
| `debug_compare_models_html(args)` | Runs one declaration through **2–4** selected models → `compare/<timestamp>_<file>/` |
| `debug_wipe_usage_traces(args)` | Deletes usage traces (blocked while a run is active) |
| `get_system_metrics()` | CPU/RAM (app + Ollama process via psutil), CPU temp, NVIDIA GPU (via `nvidia-smi`), cached for 1.5s |

### 5.3 run_pipeline → subprocess

```python
main_cmd = [sys.executable, "main.py",
  "--input-dir", ..., "--model", ..., "--host", ...,
  "--timeout", ..., "--retries", ..., "--max-chars", ...,
  "--num-predict", ..., "--output", ...,
  ...every other flag from section 2.7...
]
subprocess.Popen(main_cmd, stdout=PIPE, stderr=STDOUT, text=True)
```

Stdout is read line by line on a separate thread → `_emit_log()` → `window.evaluate_js("window._onLogLine(...)")` → the React log/card feed.

### 5.4 .run_control.json

A file for controlling the running pipeline without IPC:
```json
{ "command": "pause" | "resume" | "stop" | "error_action", ... }
```

`main.py` checks this file between declarations (`read_control_command`), blocks while paused (`wait_if_paused`, polling every 0.5s), and the same poll-loop pattern implements waiting for a token-limit decision (`wait_for_limit_decision`) and error review (`wait_for_error_action`), acknowledged via `write_control_ack`.

### 5.5 settings.json

Persists all settings between sessions. `DEFAULTS` (in `webview_app.py`, ~48 keys), grouped:

- **Pipeline:** `input_dir`, `processed_dir`, `move_processed`, `save_compact_declarations`, `max_files`, `model`, `host`, `timeout`, `retries`, `retry_delay`, `max_chars`, `num_predict`, `make_report`, `no_dedupe`, `compact_legacy_payload`, `pipeline_max_concurrent`, `sort_order`, `selected_files`, `file_queue_mode`
- **Output paths:** `output_jsonl`, `errors_jsonl`, `summary_csv`, `findings_csv`, `table_html`
- **Audit:** `audit_mode_enabled`, `audit_mode_dir`, seven `audit_capture_*` flags (all `True` by default)
- **Cloud / OpenRouter:** `cloud_mode`, `cloud_provider`, `cloud_host`, `cloud_model`, `cloud_api_key`, `openrouter_host`, `openrouter_model`, `openrouter_api_key`, `compare_enabled`, `compare_count`, `compare_models`
- **UI:** `show_system_metrics`, `play_completion_sound`, `think_event_debug`, `welcome_modal_seen`, `show_header_taglines`
- **Deep Research:** a separate `DEEP_PATH_KEYS` set (`deep_input_dir`, `deep_output_jsonl`, `deep_errors_jsonl`, `deep_summary_csv`, `deep_findings_csv`, `deep_table_html`), only populated in `settings.json` once the user is working inside a `deep_research/` folder

Secrets (`openrouter_api_key`, `cloud_api_key`) are never written to `settings.json` — they live in a separate `.declarator_secrets.json`.

The UI language is **not** a `settings.json` setting; it's resolved once at process launch via `--lang`/`DECLARATOR_UI_LANG`/`DECLARATOR_LANG` (`_ui_lang()`), which picks `dist/index.html` or `dist/index.en.html` (`_frontend_index_path()`). There is no `set_language`-style method on the `Api` class — there is no in-window language switcher.

---

## 6. Supporting modules

### 6.1 report.py (1,701 lines)

Generates reports from the JSONL. Only imports `report_i18n` — it has no direct dependency on `dossier_charts_html.py`/`dossier_html_summary.py` (the "table → charts → summary" HTML composition is done by `webview_app.py`, not by `report.py` itself).

- `read_jsonl(path)` → a list of rows
- `dedupe_by_latest(rows)` → dedupes by (declaration_id, model), the latest row wins
- `build_summary_rows()` / `build_findings_rows()` + a generic `write_csv()` → the summary CSV and findings CSV
- `write_filterable_html()` → the interactive HTML report (successor to the old `make_table_html`): a master/detail table with per-declaration expansion, finding cards with severity badges and evidence, a family/assets block, filters and sorting, column show/hide, row bookmarking (localStorage), a link back to the original filing via `nazk_public_declaration_url()` (`https://public.nazk.gov.ua/documents/{uuid}`), an errors-run summary block, and dossier-mode chronological sorting (`sort_rows_dossier_chronological`, active with `--dossier-chronological` or when the input path is under `deep_research/`)
- `write_extras_html()` / `--extras-only` — **marked deprecated**, now just calls `write_filterable_html` with a deprecation warning

### 6.2 report_i18n.py (92 lines)

**Not** a UI-language switcher — this is a lookup table from English enum codes to Ukrainian labels for values in the LLM's analysis JSON (`FINDING_TYPE_UK`, `RISK_LEVEL_UK`/`SEVERITY_UK`, `PROFILE_FIELD_UK`), plus sort helpers (`severity_sort_rank`, `RISK_LEVEL_FILTER_ORDER`). Used by `report.py` and `usage_dashboard.py` to render `finding.type`/`risk_level`/profile-field keys in Ukrainian in the HTML/dashboard. It adds no English output — it's purely report-label localization.

### 6.3 dossier_charts.py (287 lines) and dossier_charts_html.py (412 lines)

A clean data/render split:

- **`dossier_charts.py`** — pure aggregation, no HTML. `build_dossier_chart_series()` walks a `deep_research/{person}_{id}/decl_*.json` folder chronologically and computes, per year: risk score/level, findings count and red-flags count, finances (income/assets/liabilities), and counts of real estate/vehicles/land plots. Only "annual" and "before dismissal" declaration types are included (declarations of changes are excluded). Returns a JSON-able payload (`person`, `years`, `records`, `processed_count`, `avg_duration_sec`).
- **`dossier_charts_html.py`** — renders that same data as inline SVG + vanilla-JS charts embedded directly into `report_table.html` (no chart library). Three charts: **"Risk indicators"** (risk score + findings + red flags), **"Finances (UAH)"** (income/assets/liabilities), **"Property (count)"** (real estate/cars/land) — with hover tooltips and a legend toggle. `append_dossier_charts_to_html()` inserts/replaces the `<section id="declarator-dossier-charts">` block atomically (via `.tmp` + `os.replace`).

The chart configuration (titles, colors, series) is mirrored on the frontend in `declarator-lm/src/dossierChartConfig.js` — the same set of charts is rendered both by the live React component (`DossierCharts.jsx`, during processing) and by the static HTML report (`dossier_charts_html.py`, after the run finishes); both consume the same `build_dossier_chart_series()` function.

### 6.4 dossier_html_summary.py (336 lines)

Generates a text dossier summary and appends it to the HTML report:
- Reads `report_table.html` (after the charts have already been injected) → `prepare_html_for_prompt()`: strips `<script>` tags, truncates to 250,000 characters
- Builds the system/user prompts (with optional session overrides)
- Calls the LLM — `main.call_ollama_text()`, or, if `provider="openrouter"`, `openrouter_client.call_openrouter_text()`
- Inserts the result into `<section id="declarator-dossier-summary">` before `</body>`, atomically rewriting the HTML

Also supports **multi-model comparison at the dossier level**: `build_dossier_models_comparison_report()` runs the same dossier prompt through 2–4 selected models and renders a separate HTML with the answers side by side (`<section id="declarator-dossier-model-compare">`) — distinct from the single-declaration `debug_compare_models_html` in `webview_app.py`.

### 6.5 usage_dashboard.py (387 lines)

Computes the aggregated payload for the usage dashboard (shown when the app is idle, rendered by `UsageDashboard.jsx`). Two data sources:
- **`analysis_results.jsonl`** (via `report.read_jsonl`/`dedupe_by_latest`) → `aggregate_dashboard()`: risk-level distribution, average/median risk score, total red flags, top finding types, per-model/per-year counts, the single highest-risk declaration, total analysis time, average time per declaration, and an estimate of "time saved" versus manual review (constant `MANUAL_REVIEW_MINUTES = 10` — an effort estimate, not a dollar-cost figure).
- **`settings.json` → `usage_aggregate`** — persistent session history (not per-declaration): cumulative wall time and the last 50 sessions (date, duration, count processed, critical count, model); appended to by `append_usage_session()` after every pipeline run.

Returns a plain dict (not HTML) — the actual rendering is done by `UsageDashboard.jsx` on the frontend.

### 6.6 webview_app_en.py (13 lines)

```python
"""Launch DeclaratorLM with the English UI (index.en.html)."""
import os, sys
os.environ["DECLARATOR_UI_LANG"] = "en"
import webview_app
if __name__ == "__main__":
    sys.exit(webview_app.main() or 0)
```

A thin wrapper, not a separate app: it sets the environment variable **before** importing `webview_app`, then calls the same `webview_app.main()`. The batch-file equivalent is `run_en.bat` (`set DECLARATOR_UI_LANG=en && python webview_app.py`).

### 6.7 deep_research_bridge.py (643 lines)

The bridge between `webview_app.py` and the standalone `nazk_parser/` module. Wrapped in `# --- DEEP_RESEARCH_BEGIN/END` markers — by design, the whole Deep Research feature can be disabled by deleting this file and its call sites in `webview_app.py`. It dynamically adds `nazk_parser/` to `sys.path` on each call rather than importing it as a package.

- `run_deep_research_download(user_declarant_id)` — validates the id → `peek_first_lastname()` (confirms the API responds and gets a last name) → `download_all_for_user_declarant()` into `deep_research/{slug}_{id}/`; emits progress as `DEEP_DOWNLOAD_PROGRESS|{json}`.
- `run_deep_research_download_one(declaration_id, target_input_dir)` — a single declaration by id into an arbitrary (validated) directory.
- `run_nazk_download_by_year(...)` — validates the year (2015…current), the search-query length (3–255 chars), declaration type (1–4), and document type (1–3); caps the run at 500 files; emits `NAZK_DOWNLOAD_PROGRESS|{json}`.
- `apply_deep_research_folder(folder_name)` / `list_deep_research_folders()` — "no download" mode: reuse an already-downloaded `deep_research/<...>` folder as `input_dir`, or list the existing folders with their declaration counts.
- `_format_nazk_diag(...)` — a shared human-readable error format (HTTP status, message, URL) used by all three download flows.
- Path-traversal protection — two independent guards: `_safe_deep_research_subdir()` (for listing/applying a folder: rejects `..` and path separators) and `_output_dir_must_be_under_project()` (for downloads: the target directory must resolve to somewhere under the project root).

### 6.8 openrouter_client.py (986 lines)

An OpenAI-compatible client using only the standard library:
- `call_openrouter(model, system, user, host, api_key, ...)` → a dict with the analysis
- `call_openrouter_text(...)` → the same without `response_format=json_object`, used for the dossier summary
- `stream_openrouter_with_reasoning(...)` → SSE streaming with think-blocks
- `fetch_openrouter_models()` / `fetch_openrouter_models_enriched()`
- `fetch_openrouter_credits()`
- `test_openrouter_connection()`
- Headers: `HTTP-Referer: github.com/declarator-lm`, `X-Title: DeclaratorLM`

### 6.9 nazk_parser/ — the open NAZK API client

A standalone module (its own `main.py`, its own structure) that talks directly to the open API of the [National Agency on Corruption Prevention](https://public.nazk.gov.ua/public_api) and uses **no** authentication key (it's a public API, protected only by browser-like headers against WAF blocking).

- **Base URL:** `https://public-api.nazk.gov.ua/v2`
  - `GET /documents/list?page=...&user_declarant_id=...&declaration_type=...&declaration_year=...` — a paginated list
  - `GET /documents/{document_id}` — the full declaration by id
  - The human-facing declaration card (not the API): `https://public.nazk.gov.ua/documents/{uuid}`
- `nazk_client.py` (259 lines): a `urllib` wrapper with retries (up to 8 attempts) on 429/500/502/503/504, honoring `Retry-After` for 429 (clamped 8–120s); `fetch_list_page()`, `fetch_document()`.
- `nazk_download.py` (308 lines): `download_professional_dataset()` (paging up to a file-count limit), `peek_first_lastname()` (get the first last name for a `user_declarant_id`, to name a folder before a full download), `download_all_for_user_declarant()` (every declaration for a subject, with an `on_progress` callback), `download_with_filters()` (a filtered selection with local criteria matching), `scan_local_folder()` (no network — search already-downloaded files).
- `filters.py` (107 lines): `FilterCriteria` (year/year range/substring match on workplace/last name/first name), `matches_filters()`, `row_preview()` for a UI preview.
- `nazk_parser/main.py` (82 lines) — a standalone CLI (`python main.py` from the `nazk_parser/` folder): `--save-dir`, `--limit`, `--delay`, `--query`, `--user-declarant-id`, `--declaration-year`, `--declaration-type`, `--document-type`. Not part of the main pipeline — wired in through `deep_research_bridge.py`.

### 6.10 launcher_gui.py (1,029 lines)

**Not the packaged EXE's entry point** (this corrects a claim in an earlier version of this document — `DeclaratorLM.spec` builds `webview_app.py`; `launcher_gui.py` isn't referenced in the spec and isn't imported anywhere else in the project). It's a standalone **Tkinter launcher**, entirely independent of pywebview/React: its own `Tk`/`ttk` window with the same settings fields as `webview_app.py`'s `DEFAULTS`, reading/writing the same `settings.json`, launching `main.py` via `subprocess.Popen` and streaming stdout into a text widget, driving the same `.run_control.json` (pause/stop), and — after a run — also invoking `dossier_html_summary`/`dossier_charts_html`. Useful as a lightweight GUI alternative without an npm/Vite/pywebview dependency — for example, on environments without .NET/EdgeChromium available.

### 6.11 tools/

| Script | Purpose |
|--------|-------------|
| `analyze_compactplus.py` | Analyzes the corpus of compact-vs-raw pairs (noise, duplicates, protected fields) |
| `generate_compactplus_report.py` | Generates a findings report from that analysis |
| `validate_compact_v2.py` | Validates compact v2: character savings, step coverage, banks, owner resolution |
| `regenerate_compact_corpus.py` | Regenerates every compact snapshot from the raw corpus |
| `compare_test_corpus_reports.py` | A one-off script comparing two analysis runs of the same test dossier (e.g. before/after a compact-format change) by risk score, finding counts, and thematic coverage — a regression check when the prompt or compact logic changes |
| `verify_test_corpus_compact.py` | A linter for `compact_declaration()` run against the same test corpus: looks for unresolved `"Person id=..."` placeholders, unknown declaration-type codes, corporate-rights entries missing a name/owners, unresolved `person_who_care`, malformed owner strings — exits with code 1 if any issues are found |
| `_ua_ui_strings*.txt`, `_en_ui_strings*.txt`, `*_clean_added.txt`, `_ua_ui_added.txt` | Working artifacts from extracting UI strings while adding the English interface (snapshots of UK/EN string lists at various stages of translation) — not code, not loaded by the app at runtime; safe to remove before release if no longer needed to double-check the translation |

---

## 7. Frontend: declarator-lm/

**Stack:** React 18 + Vite 5 + the Geist font. `App.jsx` is 7,247 lines, one main component with no router and no state-management library (just `useState`/`useEffect`).

### 7.1 Structure

```
declarator-lm/
├── src/
│   ├── App.jsx               # Main UI, 7,247 lines
│   ├── DossierPanel.jsx      # Live "dossier" view during Deep Research (415 lines)
│   ├── DossierCharts.jsx     # Three animated SVG dossier charts (320 lines)
│   ├── UsageDashboard.jsx    # "All-time summary" dashboard (535 lines)
│   ├── VisualLogPanel.jsx    # Card-based live processing log (859 lines)
│   ├── dossierChartConfig.js # Shared dossier chart config (126 lines)
│   ├── index.css             # Styles (~3,900 lines)
│   ├── main.jsx / main.en.jsx # Two Vite entry points (Ukrainian/English)
│   └── i18n/
│       ├── index.jsx         # I18nProvider/useI18n/useT React context
│       ├── enCatalog.js      # Exact-match Ukrainian→English dictionary (558 lines)
│       └── domTranslate.js   # MutationObserver-based DOM translator (58 lines)
├── index.html / index.en.html # Two HTML entry points (lang="uk" / lang="en")
├── dist/                     # Built SPA (bundled into the PyInstaller EXE)
├── package.json              # declarator-lm@0.3.0, React 18, Vite 5, @fontsource/geist(-mono)
└── vite.config.js            # rollupOptions.input = { main: index.html, en: index.en.html }
```

### 7.2 Base components

| Component | Purpose |
|-----------|-------------|
| `Toggle` | An on/off switch with a tooltip, compact variant |
| `FilePathInput` | Label + text field + a folder-picker button |
| `TooltipWrap` | A hover-tooltip wrapper |
| `LabelWithTooltip` | A label with a hint icon |
| `ModelCombobox` | A searchable model-selection combobox |
| `DossierPanel` | `NowCard` (the person currently being processed, risk gauge, processing status), `DossierProgressStrip` — the top progress bar for dossier mode; embeds `DossierCharts` at the bottom |
| `DossierCharts` | Three per-year charts (risk/finances/property) with tooltips and a toggleable legend; the one component that genuinely uses `useI18n` |
| `UsageDashboard` | Summary tiles (analysis time, time saved, red flags, average risk, highest-risk declaration, last session), auto-flipping every 10s |
| `VisualLogPanel` | Processing cards (`OkCard`/`ErrorCard`/`LimitCard`/`ProcessingCard`) with a risk gauge, finding tags, cost/duration badges, FLIP animation, a cards/text toggle, and inline error-review actions (retry/ignore/raise limits) |

### 7.3 State (useState) — main groups

**Pipeline (~40 variables):** `inputDir`, `processedDir`, `moveProcessed`, `model`, `host`, `timeout`, `retries`, `retryDelay`, `maxChars`, `numPredict`, `maxFiles`, `outputJsonl`, `errorsJsonl`, `summaryCsv`, `findingsCsv`, `tableHtml`, `makeReport`, `noDedupe`, `sortOrder`, `selectedFiles`, `fileQueueMode`, `showSystemMetrics`, `playCompletionSound`.

**Cloud/OpenRouter:** `cloudMode`, `cloudProvider`, `cloudHost`, `cloudModel`, `cloudApiKey`, `openrouterHost`, `openrouterModel`, `openrouterApiKey`, `openrouterModels[]`, `openrouterModelPricing`, `pipelineMaxConcurrent`.

**UI/execution:** `isRunning`, `ready`, `progress`, `logLines[]` (last 2,000), `logViewMode` (cards/text, persisted to localStorage), `visualEntries`, `visualRunTotals`, `pendingThink`, `debugUiMode`.

**Dossier / dashboard (new):** `usageStats`/`usageStatsLoading`/`usageStatsError` — the `UsageDashboard` data; `dossierChartData`/`dossierChartLoading`/`dossierChartError`/`dossierMainView` — the `DossierCharts` data and the "Dossier/Log" sub-tab in Deep Research; `showDossierLive`/`showUsageDashboard` — which of the three idle states to show (live dossier, usage dashboard, or the default empty log).

**Error review (new):** `errorActionBusy`, `errorActionTargetFile` + `handlePipelineErrorAction`/`handleErrorRaiseLimits` — the inline retry/ignore/raise-limits buttons right in the error card, sent via `api().pipeline_error_action(...)`.

**Debug/Audit:** `auditModeEnabled`, `auditModeDir`, seven `auditCapture*` flags, `compactLegacyPayload`.

**Modals:** `showWelcomeModal`, `promptEditorOpen`/`promptEditorTab`/`promptDraft`/`sessionPromptOverrides`, `showCloudComparisonModal`, `wipeModalOpen`.

**Deep Research:** `deepResearchMode`, `deepResearchUserId`, `deepResearchFolders[]`, `deepResearchBusy`, `deepResearchDownloadBusy`.

**File picker:** `filesToProcess[]`, `filePickerOpen`, `fileFolderSnapshot`, `filePickerSearch`, `filePickerSort`.

### 7.4 Main functions

| Function | Purpose |
|---------|-------------|
| `applySettings(s)` | Applies a settings object to every state variable |
| `buildPipelineArgs()` | Assembles the args object for `run_pipeline` |
| `runPipeline()` | Calls `api().run_pipeline(args)`, subscribes to logs via `_onLogLine` |
| `handleControlPipeline(cmd)` | pause/resume/stop via `api().control_pipeline` |
| `handlePipelineErrorAction` / `handleErrorRaiseLimits` | Inline error-review actions from a card |
| `refreshUsageStats()` | `api().get_usage_dashboard_stats(...)` → the `UsageDashboard` state |
| `refreshDossierCharts()` (debounced) | `api().get_dossier_chart_data(...)` → the `DossierCharts` state |
| `loadOpenrouterModels(host, key)` | Loads + caches the OpenRouter model list |
| `pickFolder(setter)` | Opens a dialog → setter(path) |
| `openPromptEditor()` | Loads the built-in prompts + opens the modal |
| `runDebugDossierHtmlSummary()` / `runDebugCompareModels()` | Debug summary/comparison requests |
| `runDeepResearchDownload()` | Downloads via the NAZK API |

### 7.5 UI sections

**Sidebar (settings):** declaration path, File Queue, model (Ollama/OpenRouter), the Cloud section (host/model/key/credits/test), request parameters, output paths, moving processed files, reports, system metrics, sound, prompt editor.

**Main area — three idle states (new):**
- the default empty log (nothing running, no Deep Research)
- **Usage dashboard** (`UsageDashboard`) — shown by default when nothing is running and the log is empty
- **Live "Dossier" view** (`DossierPanel` + `DossierCharts`) — shown when Deep Research is active on an input folder under `deep_research/...`

While a run is active: a progress bar, Run/Pause/Cancel/Open report buttons, and the log as either cards (`VisualLogPanel`) or plain text, toggled by a "Cards/Text" button.

**DEBUG sidebar (after unlocking):** compact v2 (legacy payload toggle), audit mode, dossier summary, model comparison, regenerate report, wipe usage traces, session prompt editing.

**Deep Research tab:** the NAZK `user_declarant_id` field, "download all" / "download by year" buttons, the list of `deep_research/` folders, applying a folder as `input_dir`.

### 7.6 Multi-language support (in detail)

Language is a property of the process, not of React state: it's chosen by a flag/environment variable when the Python server launches (see §6.6, §5.5), which then serves one of two static HTML entry points built by Vite (`vite.config.js`: `rollupOptions.input = { main: "index.html", en: "index.en.html" }`).

- Both `main.jsx` and `main.en.jsx` wrap `<App/>` in `<I18nProvider locale="uk"|"en">`, but only `main.en.jsx` additionally calls `installDomTranslator(document.body)`.
- `App.jsx` **does not use** `useI18n`/`useT` at all — its text is hardcoded Ukrainian throughout.
- The actual translation is done by `domTranslate.js`: an initial recursive DOM walk plus a `MutationObserver` (childList/subtree/characterData/attributes) that swaps in any text node or attribute (`title`/`aria-label`/`placeholder`/`alt`) that **exactly** matches a key in `enCatalog.js` — including nodes added later (log cards, modals).
- The exception is `DossierCharts.jsx`, the one component genuinely wired into `useI18n`/`t()`, which also branches on `locale` directly for money/unit formatting ("million/thousand" vs. "M"/"k", "UAH" vs. the Ukrainian currency abbreviation).

### 7.7 React ↔ Python data flow

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
  ├─ run_extra_report(args) ─────► report.py subprocess (+ dossier charts)
  │                               │
  └─ save_settings(settings) ────► save_settings(settings)
```

---

## 8. Data formats

### 8.1 Input JSON (raw NAZK)

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
    "step_2": { "data": [ { "id": "2", "subjectRelation": "spouse", ... } ] },
    "step_3": { "data": [ { "objectType": "Apartment", "totalArea": "52", "rights": [ { "rightBelongs": "1", "ownershipType": "Joint ownership" } ] } ] },
    "step_4" – "step_17": { "data": [...] | {} | isNotApplicable: 1 }
  }
}
```

**NAZK declaration steps:**
- `step_0` — general declaration information
- `step_1` — the declarant's personal data (~70 fields, mostly placeholders)
- `step_2` — family members
- `step_3` — real estate
- `step_4` — unfinished construction
- `step_5` — valuable movable property
- `step_6` — vehicles
- `step_7` — securities
- `step_8` — corporate capital participation
- `step_9` — corporate rights (beneficial owner)
- `step_10` — intangible assets
- `step_11` — income
- `step_12` — cash assets
- `step_13` — financial liabilities
- `step_14` — significant changes in property status
- `step_15` — transaction expenses
- `step_16` — an additional form block
- `step_17` — financial institutions / bank accounts

### 8.2 Output JSONL (one row)

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

### 8.3 Audit artifacts (`{audit_mode_dir}/{decl_stem}/`)

| File | Condition | Contents |
|------|-------|-------|
| `raw_declaration.json` | `--audit-capture-raw-declaration` | The raw original |
| `compact_declaration.json` | `--audit-capture-compact-declaration` | Compact v2 |
| `request_payload.attempt{N}.json` | `--audit-capture-request-payload` | What was sent to the LLM |
| `response_raw.attempt{N}.json` | `--audit-capture-response-raw` | The raw response |
| `response_parsed.attempt{N}.json` | `--audit-capture-response-parsed` | The parsed JSON |
| `normalized_analysis.json` | `--audit-capture-normalized-analysis` | The normalized result |
| `attempt_meta.json` | `--audit-capture-attempt-meta` | Timings, attempt statuses |

---

## 9. Modes of operation

### 9.1 Regular pipeline

1. Pick a folder of declaration JSON files
2. Pick a model (Ollama / OpenRouter)
3. Click "Run"
4. Results → JSONL → CSV + HTML

### 9.2 Deep Research

- Download every declaration for a person by their NAZK `user_declarant_id` → `deep_research/{name}_{id}/`, or reuse an already-downloaded folder without hitting the API again
- Chronological processing (oldest → newest)
- A live "Dossier" view while processing (charts update as results arrive)
- An HTML report with year-by-year trend charts plus an LLM dossier summary at the end

### 9.3 Dossier Summary (DEBUG)

- Without running the full pipeline
- Takes an existing `report_table.html`
- The LLM (`dossier_html_summary.py`) generates a text summary and inserts it into the HTML
- Or — a multi-model (2–4) comparison at the whole-dossier level, as a separate HTML file

### 9.4 Compare Models (DEBUG)

- Processes the same declaration through 2–4 different models (`webview_app.py: debug_compare_models_html`)
- Outputs a side-by-side comparison HTML into `compare/<timestamp>_<file>/`

### 9.5 Audit Mode (DEBUG)

- Every declaration gets its own case folder under `{audit_mode_dir}/`
- Selected artifacts are saved (configurable via toggles)

### 9.6 Usage Dashboard (idle state)

- Shown by default when nothing is running and the log is empty
- Aggregated stats across the whole `analysis_results.jsonl` history plus persistent sessions from `settings.json`

### 9.7 CLI mode

```bash
python main.py \
  --input-dir dataset_declarations \
  --model llama3.1 \
  --host http://127.0.0.1:11434 \
  --max-files 5 \
  --output results.jsonl
```

---

## 10. File structure

```
DeclaratorLM/
│
├── main.py                       # 3,075 lines: compact v2, LLM, pipeline, CLI
├── webview_app.py                # 2,884 lines: PyWebView API (UA), subprocess bridge
├── webview_app_en.py             # 13 lines: the same server in English
├── openrouter_client.py          # 986 lines: the OpenRouter API client
├── deep_research_bridge.py       # 643 lines: NAZK API, declaration downloads
├── report.py                     # 1,701 lines: CSV, the interactive HTML report
├── report_i18n.py                # 92 lines: Ukrainian labels for analysis values
├── dossier_charts.py             # 287 lines: time-series data for dossier charts
├── dossier_charts_html.py        # 412 lines: embeds charts into the HTML report
├── dossier_html_summary.py       # 336 lines: LLM dossier summary + model comparison
├── usage_dashboard.py            # 387 lines: aggregated usage statistics
├── launcher_gui.py               # 1,029 lines: standalone Tkinter launcher (not the EXE entry point)
│
├── requirements.txt              # pywebview>=4,<6; psutil>=5.9,<8; pythonnet>=3.0.1,<4
├── DeclaratorLM.spec             # PyInstaller onefile spec (entry point: webview_app.py)
├── settings.json                 # Saved settings (auto-generated, gitignored)
├── .run_control.json             # Pipeline control file (gitignored)
├── .declarator_secrets.json      # OpenRouter/Cloud API keys, kept apart from settings.json (gitignored)
│
├── declarator-lm/                # The React SPA
│   ├── src/
│   │   ├── App.jsx               # 7,247 lines: the main UI
│   │   ├── DossierPanel.jsx      # 415 lines: the live dossier view
│   │   ├── DossierCharts.jsx     # 320 lines: dossier charts
│   │   ├── UsageDashboard.jsx    # 535 lines: the usage dashboard
│   │   ├── VisualLogPanel.jsx    # 859 lines: the card-based processing log
│   │   ├── dossierChartConfig.js # 126 lines: chart configuration
│   │   ├── i18n/                 # index.jsx, enCatalog.js, domTranslate.js
│   │   └── index.css             # ~3,900 lines: styles
│   ├── index.html / index.en.html # Two Vite entry points
│   ├── dist/                     # The built SPA (bundled into the PyInstaller EXE)
│   └── package.json              # declarator-lm@0.3.0
│
├── nazk_parser/                  # The standalone NAZK module (base URL: public-api.nazk.gov.ua/v2)
│   ├── main.py                   # CLI for downloading declarations
│   ├── nazk_client.py            # An HTTP client with retries
│   ├── nazk_download.py          # Paging/saving orchestration
│   └── filters.py                # Local filtering of downloaded declarations
│
├── dataset_declarations/         # The default input folder (gitignored)
├── dataset_declarations_done/    # Processed files, if --processed-dir is set (gitignored)
├── deep_research/                # Downloaded Deep Research corpora (gitignored)
│   └── {name}_{user_id}/         # One person's folder, decl_*.json
├── оброблені декларації/compact/ # Saved compact declarations, if --save-compact-declarations (gitignored)
├── audit/                        # Audit artifacts, --audit-mode-dir (gitignored)
├── compare/                      # Model-comparison outputs, --debug-compare-models-html (gitignored)
│
├── tools/                        # Compact-corpus analysis/validation (see §6.11)
├── docs/screenshots/             # Screenshots used in the README
├── assets/                       # Icons (.ico), sounds (.wav/.mp3)
├── build/, dist/, venv/          # Build/EXE artifacts, virtual environment (gitignored)
│
├── README.md / README.en.md      # Project overview and roadmap (Ukrainian/English)
├── STRUCTURE.md / STRUCTURE.en.md # This file (Ukrainian/English)
└── raw-compact.md                # Step-by-step breakdown of NAZK steps → compact v2 mapping (Ukrainian)
```

> Two files this document used to reference, `compactplus_findings.md` and `compact_v2_test_report.md`, are not present in the current working tree (they may only ever have existed locally during development, and they're not in `.gitignore` either). If they're missing for you too, treat any reference to them as historical.

---

## 11. Build and deployment

### 11.1 Frontend

```bash
cd declarator-lm
npm install
npm run build    # → dist/index.html + dist/index.en.html + dist/assets/
```

`vite.config.js` defines two entry points (`rollupOptions.input`), so a single build produces both language versions at once. `dist/` is copied into the PyInstaller bundle via `datas` in `DeclaratorLM.spec`. There's also `BUILD_FRONTEND.bat` — the same thing as a double-clickable script (checks for `package.json` and reports an exit code).

### 11.2 EXE (PyInstaller)

```bash
pyinstaller DeclaratorLM.spec
# → dist/DeclaratorLM.exe (onefile, console=False)
```

`DeclaratorLM.spec`:
- **Entry point:** `webview_app.py` (**not** `launcher_gui.py` — see the correction in §6.10).
- **Datas:** `declarator-lm/dist` → `declarator-lm/dist`; `nazk_parser/` → `nazk_parser`; plus copies of `main.py`, `report.py`, `openrouter_client.py`, `dossier_html_summary.py`, `deep_research_bridge.py` at the bundle root.
- **Hidden imports:** `clr`, `main`, `openrouter_client`, `deep_research_bridge`, `dossier_html_summary`, `report`, `collect_submodules("webview")`.
- **collect_all:** `webview`, `pythonnet`, `clr_loader`, `bottle`, `proxy_tools`, `psutil`, `cffi` (without this, `import webview` crashes, per the author's own comment).
- **Icon:** `assets/app.ico`. Onefile, `console=False`, `upx=False`.

### 11.3 Helper batch scripts

| Script | Purpose |
|--------|-------------|
| `BUILD_FRONTEND.bat` | Builds the frontend (`npm run build`) |
| `run_en.bat` | Launches the app with the English UI (`DECLARATOR_UI_LANG=en`) |
| `reasoning.bat` | Launches with reasoning/THINK streaming enabled (`DECLARATOR_REASONING_DEBUG=1`) |

### 11.4 Python dependencies

```
pywebview>=4.0,<6   — the GUI, via Edge Chromium (Windows)
psutil>=5.9,<8      — system metrics (CPU, RAM)
pythonnet>=3.0.1,<4 — .NET interop for the edgechromium backend (import clr)
```

Everything else is standard library (urllib, json, threading, pathlib, argparse, csv, re, time, uuid). `nazk_parser/` has no external dependencies at all.
