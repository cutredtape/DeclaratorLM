# DeclaratorLM

Інструмент для автоматизованого аналізу антикорупційних декларацій НАЗК за допомогою великих мовних моделей (LLM). Підтримує локальну Ollama, хмарну Ollama та OpenRouter (100+ моделей).

## Що робить

- Читає JSON-декларації НАЗК (raw формат API), стискає їх до ефективного промпту (compact v2, −74% від оригіналу) і надсилає до LLM
- LLM повертає структурований JSON-аналіз: ризик-скор (0–100), знахідки, red flags, огляд активів сім'ї
- Результати зберігаються у JSONL, автоматично генеруються CSV і HTML-звіти
- Deep Research: завантаження всіх декларацій суб'єкта за його НАЗК-ID і хронологічний аналіз
- Dossier Summary: мовна модель дописує підсумок-досьє в кінці HTML-звіту по особі
- GUI на PyWebView + React; є CLI-режим для батч-обробки

## Технологічний стек

| Шар | Технологія |
|-----|------------|
| GUI | PyWebView 5 (Edge Chromium на Windows) |
| Frontend | React 18 + Vite 5, Geist шрифт |
| Backend | Python 3.11+, стандартна бібліотека (urllib, json, threading) |
| LLM (локальний) | Ollama `/api/chat` |
| LLM (хмара) | OpenRouter `/chat/completions` (OpenAI-compatible) |
| Звіти | CSV + HTML (report.py), JSONL |
| Збірка | PyInstaller (onefile, no console) |
| Залежності | pywebview, psutil, pythonnet |

## Швидкий старт

```bash
# 1. Встановити залежності
python -m pip install -r requirements.txt

# 2. Запустити GUI
python webview_app.py

# 3. Або CLI — обробити всі JSON у папці
python main.py --input-dir dataset_declarations --model llama3.1

# 4. OpenRouter (хмара)
python main.py --input-dir dataset_declarations \
  --provider openrouter \
  --openrouter-model meta-llama/llama-3.3-70b-instruct \
  --openrouter-api-key sk-or-v1-...
```

## Структура проєкту

```
DeclaratorLM/
├── main.py                  # Ядро: compact v2, LLM-клієнт, пайплайн, CLI
├── webview_app.py           # PyWebView API-сервер, subprocess-міст до main.py
├── openrouter_client.py     # OpenRouter/OpenAI-compatible клієнт
├── deep_research_bridge.py  # Завантаження декларацій НАЗК за user_declarant_id
├── report.py                # Генерація CSV + HTML звітів
├── dossier_html_summary.py  # LLM-підсумок досьє по HTML-звіту
├── declarator-lm/           # React фронтенд (src/, dist/)
├── nazk_parser/             # Парсер НАЗК API (окремий модуль)
├── dataset_declarations/    # Вхідні JSON декларацій
├── deep_research/           # Завантажені набори декларацій по особах
├── compact/                 # Аудит-артефакти (compact, raw, payload кожної декларації)
├── tools/                   # Допоміжні скрипти аналізу compact
└── assets/                  # Іконки, звуки
```

Детальний опис архітектури: [STRUCTURE.md](STRUCTURE.md)

## Дорожня карта

### Реалізовано
- Compact v2: −74% токенів, structured інтерпретація 13/18 кроків, `financial_institutions[]`
- Три LLM-провайдери: локальна Ollama, Cloud Ollama, OpenRouter (паралельна обробка до 8 потоків)
- Deep Research: хронологічний аналіз всіх декларацій суб'єкта
- Dossier Summary: LLM-підсумок по сукупності декларацій
- Compare режим: порівняння результатів двох моделей
- Audit режим: збереження всіх артефактів обробки по кожній декларації
- Reasoning debug: стримінг think-блоків від моделей з extended thinking
- Відновлення (resume): пропуск вже оброблених файлів при перезапуску
- Повний контроль промптів із UI (system + user prompt, dossier prompt)

### Потенційний розвиток
- Structured інтерпретація кроків 5, 7, 8, 10, 16 (рідкісні в поточному корпусі)
- `financial_institutions` — розширення поля person_open_account до повного розв'язання через person_index
- Векторний пошук/порівняння декларацій між суб'єктами
- Інтеграція з реєстрами (ДЗК, ЄДР) для крос-перевірки
- Веб-версія / REST API
