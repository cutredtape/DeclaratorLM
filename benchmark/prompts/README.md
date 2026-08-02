# Версії промптів для бенчмарку

Кладіть сюди JSON-файли в **тому самому форматі**, що й редактор промптів
DEBUG у webview (`.debug_session_prompt_overrides.json`):

```json
{
  "pipeline_system_prompt": "...",
  "pipeline_user_prompt_template": "...{declaration_payload}...",
  "pipeline_prompt_name": "core-3"
}
```

Правила:

- User-шаблон **повинен** містити `{declaration_payload}` і **не мати жодних інших**
  фігурних дужок `{…}` (те саме обмеження, що й у `main.py` — там викликається
  `.format(declaration_payload=…)`).
- `pipeline_prompt_name` стає слаґом теки в `runs/.../reports/` та значенням
  колонки `run_meta.prompt_name` у звітах.
- Промпт сесії можна експортувати з редактора DEBUG у застосунку та вставити
  сюди як файл.
- `example-core3.json` — кандидат із `docs/prompt-status.md` (ще не перевірений на моделі).

Вбудований промпт з `main.py` завжди доступний у TUI під назвою **core**,
навіть без файлу тут.
