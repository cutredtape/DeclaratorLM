# DeclaratorLM Benchmark

Автономна інфраструктура для прогону **того самого корпусу декларацій** через
**кілька моделей x версій промпту**, з подальшим порівнянням сукупних метрик.

**Не** змінює жодних наявних файлів проєкту. Використовує `main.process_file`,
`report.py` та `openrouter_client` як бібліотеку.

## Встановлення

```bash
# Бажано використовувати venv проєкту (Python 3.11)
venv\Scripts\python.exe -m pip install -r benchmark\requirements.txt
```

Покладіть файли декларацій НАЗК `*.json` у:

```
benchmark/corpus/
```

Версії промптів (необов'язково) кладуться в `benchmark/prompts/` — той самий
формат JSON, що й у редакторі промптів DEBUG у webview. Див. [prompts/README.md](prompts/README.md).
Вбудований `core` (з `main.py`) доступний завжди.

## Запуск

```bash
# Інтерактивний TUI
venv\Scripts\python.exe benchmark\run_benchmark.py

# Безкоштовна перевірка (без викликів LLM): compact + формат промпту + синтетичні звіти + матриця
venv\Scripts\python.exe benchmark\run_benchmark.py --dry-run --non-interactive ^
  --model dry-local --prompt core --max-files 3 --yes --label dry

# Приклад реального прогону (локальна Ollama)
venv\Scripts\python.exe benchmark\run_benchmark.py --model llama3.1 --prompt core --prompt core-3 --max-files 3

# OpenRouter
venv\Scripts\python.exe benchmark\run_benchmark.py ^
  --provider openrouter --model openrouter:meta-llama/llama-3.3-70b-instruct ^
  --prompt core-3 --max-files 2
```

Ключі API: `--api-key`, або змінні середовища `DECLARATOR_OPENROUTER_API_KEY` /
`OPENROUTER_API_KEY`, або файл проєкту `.declarator_secrets.json` (`openrouter_api_key`).
Ключі **ніколи** не записуються в `run_manifest.json`.

## Хід виконання

1. Скан `benchmark/corpus/` (кількість, розміри, биті JSON, SHA-256).
2. Вибір моделей + версій промпту + перемикачів артефактів аудиту.
3. **Перевірка перед запуском** (окрім `--dry-run`): хост доступний → модель у списку → мікро-smoke-виклик.
4. **Оцінка вартості** з локального `compact_declaration()` + цін OpenRouter; підтвердження.
5. Прогін матриці; кожна клітинка отримує власні:
   - `runs/<ts>_<label>/reports/<model>__<prompt>/` (JSONL + CSV + HTML)
   - `runs/<ts>_<label>/artifacts/<model>__<prompt>/` (артефакти у стилі аудиту)
6. Запис `matrix/matrix.{csv,json,html}` із метриками по всіх клітинках.

Відновлення: `--resume <назва_або_шлях_теки_прогону>`.

## Безпека

- `benchmark/corpus/*` та `benchmark/runs/` локально ігноруються git.
- Кореневий `requirements.txt` не змінюється; `rich` живе лише тут.
- `--dry-run` ніколи не викликає модель.

## Плани на майбутнє

- **`PrivacyFirstREADME.md`** — окремий документ (ще не написано): розібрати
  політики окремих провайдерів на OpenRouter щодо збереження/тренування на
  вхідних даних (data retention, параметр `provider.data_collection: deny`,
  zero-retention провайдери, безкоштовні `:free`-моделі як окремий ризик — вони
  часто вимагають логування як умову безкоштовності) і дати конкретні
  рекомендації з налаштування: які провайдери/моделі обирати для бенчмарку на
  реальному корпусі декларацій, а яких уникати.
