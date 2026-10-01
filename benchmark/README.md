# DeclaratorLM Benchmark

Автономний інструмент для прогону **того самого корпусу декларацій** через
**кілька моделей × версій промпту** з подальшим порівнянням сукупних метрик.

**Не** змінює жодних файлів основного застосунку. Використовує
`main.process_file`, `report.py` та `openrouter_client` як бібліотеку.

> 📌 У git лежать лише інструмент і готові графіки метрик ([`figures/`](figures/)).
> Декларації та виходи прогонів лишаються локально (див. [`.gitignore`](.gitignore)).

## Встановлення

```bash
# Бажано використовувати venv проєкту (Python 3.11)
venv\Scripts\python.exe -m pip install -r benchmark\requirements.txt
```

Покладіть файли декларацій НАЗК `decl_<id>.json` у `benchmark/corpus/` (саме так
їх називає режим «Парсинг» застосунку і `nazk_parser/`) або вкажіть іншу теку
через `--corpus-dir`.

Версії промптів (необов'язково) кладуться в `benchmark/prompts/` — той самий
формат JSON, що й у редакторі промптів DEBUG у застосунку. Див.
[prompts/README.md](prompts/README.md). Вбудований промпт із `main.py`
доступний завжди під назвою **core-2**.

## Запуск

```bash
# Інтерактивний TUI
venv\Scripts\python.exe benchmark\run_benchmark.py

# Безкоштовна перевірка (без викликів LLM): compact + формат промпту + синтетичні звіти + матриця
venv\Scripts\python.exe benchmark\run_benchmark.py --dry-run --non-interactive ^
  --model dry-local --prompt core-2 --max-files 3 --yes --label dry

# Реальний прогін (локальна Ollama)
venv\Scripts\python.exe benchmark\run_benchmark.py --model llama3.1 --prompt core-2 --prompt core-3 --max-files 3

# OpenRouter
venv\Scripts\python.exe benchmark\run_benchmark.py ^
  --provider openrouter --model openrouter:qwen/qwen3-30b-a3b-instruct-2507 ^
  --prompt core-3 --corpus-dir dataset_declarations --max-files 2
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

## Результати: 17 моделей

Графіки проведеного порівняння лежать у [`figures/`](figures/), кожен у двох
мовних копіях: `*_en.png` і `*_uk.png`. Корпус — 140 декларацій: 80 вручну
розмічених (A — патерн + важіль посади, B — непояснене багатство, C — сильне
невинне пояснення, neg — без ризику) і 60 випадкових для фону. Кожна модель
проходила корпус тим самим промптом тричі. Рядки на графіках позначені
псевдонімами (`A-01`, `neg-12`), не справжніми особами.

| Графік | Що показує |
|---|---|
| `fig_reliability_cost` | Повнота й хибні тривоги проти вартості прогону |
| `fig_pareto_recall_fpr` | Компактний Парето-фронт «повнота / хибні тривоги» |
| `fig_pareto_two` | Два фронти: виявлення і якість тексту знахідок |
| `fig_communication` | Профіль тексту: частка знахідок із числами проти дублів заголовків |
| `fig_calibration` | Калібрування важкості за класами A/B/C/neg |
| `fig_score_profiles` | Середній `risk_score` і частка high+ за шарами корпусу |
| `fig_tradeoff` | Арифметика проти важеля посади: що модель зважує сильніше |
| `fig_find_vs_score` | Чи збігається знайдена проблема з балом ризику |
| `fig_heatmap` | 80 розмічених кейсів × 17 моделей, `risk_score` |
| `fig_agreement` | Попарна узгодженість моделей і розкид між ними |
| `fig_recall_sd` | Повнота ± SD за трьома прогонами |
| `fig_replicates` | Доля кожної очікуваної знахідки за три прогони і приріст від об'єднання |
| `fig_timing` | Швидкість: хвилин на декларацію і годин на весь корпус |

Два висновки, які прямо вплинули на застосунок:

- **дорожча модель не є надійно кращою** для тріажу;
- **та сама модель на тих самих деклараціях не завжди узгоджується сама із собою**,
  а знахідки різних прогонів доповнюють одна одну. Звідси режим «Реплік» і
  зшивання прогонів через Jev — див. [JEV.md](../docs/JEV.md).

Патерн у декларації — не доказ корупції. Графіки порівнюють поведінку моделей,
а не виносять судження про людей.

## Безпека

- `benchmark/corpus/*` та `benchmark/runs/` ігноруються git.
- Кореневий `requirements.txt` не змінюється; `rich` живе лише тут.
- `--dry-run` ніколи не викликає модель.
