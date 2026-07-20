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
│   ├── App.jsx       # Весь UI ~6100 рядків (один компонент + хелпери)
│   └── index.css     # Стилі ~3900 рядків
├── dist/             # Зібраний SPA (включається в PyInstaller EXE)
├── package.json
└── vite.config.js
```

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
| `ModelCombobox` | Combobox вибору моделі з живим пошуком |

## Основні секції UI

### Sidebar
- Папка декларацій + кнопка Explorer
- File Queue (ручний вибір / порядок файлів)
- Модель (Ollama local/cloud або OpenRouter)
- Cloud / OpenRouter параметри (host, model, api-key, кредити, тест)
- Параметри запиту (timeout, retries, max-chars, num-predict)
- Вихідні файли (JSONL, CSV, HTML)
- Переміщення оброблених / звіти
- Метрики системи / звук завершення

### Основна область
- **Зведення за весь час** (дашборд плиток до запуску пайплайну): агрегація з `analysis_results.jsonl` + `usage_aggregate` у `settings.json`
- Статус, прогрес-бар
- Кнопки: Запустити / Пауза / Скасувати / Відкрити звіт
- Лог (авто-скрол, THINK-блоки collapsible)

### DEBUG sidebar (розблоковується жестом)
- Legacy payload toggle (compact v2 vs v1)
- Режим аудиту: шлях + toggle-и артефактів
- Підсумок досьє (окремий запит до моделі)
- Порівняння двох моделей
- Видалення слідів використання

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

Логи з stdout `main.py` надходять рядок за рядком через `window.evaluate_js("window._onLogLine(...)")` → React відображає у лог-панелі.

## Налаштування зберігаються в `../settings.json`

`save_settings(settings)` — при кожній зміні налаштувань. `load_settings()` — при старті. Близько 40 ключів.

## Примітки до розробки

- Весь UI — один файл `App.jsx` без роутера та state management бібліотек
- Модальні вікна рендеряться через `createPortal` у `document.body`
- Pywebview API недоступний у `npm run dev` — для тестування потрібен `python webview_app.py`
- Після будь-яких змін обов'язково `npm run build` перед запуском GUI або збіркою EXE
- CSS-змінні для кольорів у `:root` / `@media (prefers-color-scheme: dark)` — не використовувати хардкод кольорів
