# DeclaratorLM — Frontend

React SPA, що виконується всередині PyWebView-вікна. Спілкується з Python-бекендом через `window.pywebview.api.*`.

## Стек

| | |
|---|---|
| Framework | React 18 |
| Bundler | Vite 5 |
| Шрифт | Geist + Geist Mono (@fontsource) |
| Стилі | CSS-модуль `index.css` (CSS vars, темна/світла тема через системні prefers-color-scheme) |
| Залежності runtime | лише React 18 + React DOM |

## Структура

```
declarator-lm/
├── src/
│   ├── App.jsx               # Основний UI, ~8 600 рядків (один компонент + хелпери)
│   ├── DossierPanel.jsx      # Живий вигляд досьє під час Deep Research
│   ├── DossierCharts.jsx     # Графіки досьє (ризик, фінанси, майно)
│   ├── UsageDashboard.jsx    # Дашборд «Зведення за весь час»
│   ├── VisualLogPanel.jsx    # Картковий живий лог обробки
│   ├── RiskGauge.jsx         # Кругова шкала risk score
│   ├── dossierChartConfig.js # Спільна конфігурація графіків досьє
│   ├── i18n/                 # Англійська версія інтерфейсу (словники + DOM-перекладач)
│   ├── fonts/                # e-Ukraine-Bold.woff2
│   ├── main.jsx / main.en.jsx # Точки входу (укр./англ.)
│   └── index.css             # Стилі, ~6 800 рядків
├── index.html / index.en.html
├── dist/                     # Зібраний SPA (включається в PyInstaller EXE)
├── package.json
└── vite.config.js
```

Детальний опис файлів, стану й функцій — у [STRUCTURE.md §7](../docs/STRUCTURE.md#7-фронтенд-declarator-lm).

## Розробка

```bash
npm install
npm run dev      # dev-сервер з HMR (але без pywebview API — використовувати EXE/webview_app.py)
npm run build    # → dist/  (обов'язково перед збіркою EXE або після будь-яких змін)
```

## Компоненти

| Компонент | Опис |
|-----------|------|
| `Toggle` | Перемикач on/off. Пропси: `label`, `tooltip`, `checked`, `onChange`, `disabled`, `compact` |
| `FilePathInput` | Поле шляху + кнопка вибору папки (іконка). Пропси: `label`, `tooltip`, `value`, `onChange`, `onBrowse`, `disabled` |
| `TooltipWrap` | Обгортка з підказкою при наведенні |
| `LabelWithTooltip` | `<label>` або `<span>` з іконкою підказки (?) |
| `LogLine` | Рядок логу (колір залежить від вмісту: ok/error/deep/think/info) |
| `RiskGauge` | Кругова шкала risk score для карток логу й досьє |

## Основні секції UI

### Sidebar
- Папка декларацій + кнопка Explorer
- File Queue (ручний вибір / порядок файлів)
- Модель (Ollama local/cloud або OpenRouter)
- Cloud / OpenRouter параметри (host, model, api-key, баланс, тест; для OpenRouter — «Паралель» і «Реплік»)
- Параметри запиту (timeout, retries, max-chars, num-predict)
- Вихідні файли (JSONL, CSV, HTML)
- Переміщення оброблених / звіти
- Метрики системи / звук завершення
- Jev (лише OpenRouter): «Jev-підказка LLM» (експериментально), «Jev-перевірка фактів»

### Основна область
- **Зведення за весь час** (дашборд плиток до запуску пайплайну): агрегація з `analysis_results.jsonl` + `usage_aggregate` у `settings.json`
- Статус, прогрес-бар
- Кнопки: Запустити / Пауза / Скасувати / Відкрити звіт
- Лог (авто-скрол, THINK-блоки collapsible)

### DEBUG sidebar (розблоковується жестом: Shift + 4 кліки на логотип)
- Компактизація: формат v2/v3, глибина (+ сирі кроки), minify для v3
- Режим аудиту: шлях + toggle-и артефактів
- Редактор промптів сесії: пайплайн, досьє, два набори питань Jev
- Підсумок досьє (окремий запит до моделі)
- Порівняння 2–4 моделей
- Перегенерація звіту, видалення слідів використання

### Deep Research вкладка
- Поле НАЗК user_declarant_id
- Завантаження всіх декларацій / по роках
- Список існуючих папок → застосувати як input_dir

## Взаємодія з Python

Весь обмін — асинхронні JS-виклики до `window.pywebview.api`:

```js
// Завантажити налаштування
const settings = await api().load_settings();

// Запустити пайплайн (підписка на логи через window._onLogLine)
await api().run_pipeline(args);

// Вибір папки
const path = await api().pick_folder();

// Список файлів декларацій
const { files } = await api().list_declaration_files(inputDir);
```

Логи з stdout `main.py` Python надсилає рядок за рядком через `evaluate_js("window._onLogLine(...)")` → React відображає у лог-панелі.

## Налаштування зберігаються в `../settings.json`

`save_settings(settings)` — при кожній зміні налаштувань. `load_settings()` — при старті. 58 ключів (`DEFAULTS` у `webview_app.py`).

## Примітки до розробки

- Весь UI — один файл `App.jsx` без роутера та state management бібліотек
- Модальні вікна рендеряться через `createPortal` у `document.body`
- Pywebview API недоступний у `npm run dev` — для тестування потрібен `python webview_app.py`
- Після будь-яких змін обов'язково `npm run build` перед запуском GUI або збіркою EXE
- CSS-змінні для кольорів у `:root` / `@media (prefers-color-scheme: dark)` — не використовувати хардкод кольорів
