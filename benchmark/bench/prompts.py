"""Discover and validate prompt versions (webview DEBUG override JSON format)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .config import PROMPTS_DIR, PromptSpec

# Keys match webview_app._write_session_prompt_overrides / main.pipeline_prompts_for_process
_SYSTEM_KEY = "pipeline_system_prompt"
_USER_KEY = "pipeline_user_prompt_template"
_NAME_KEY = "pipeline_prompt_name"

_PAYLOAD_PLACEHOLDER = "{declaration_payload}"
# After removing the allowed placeholder, no other {…} must remain in the user template.
_OTHER_BRACE_RE = re.compile(r"\{[^{}]*\}")


class PromptValidationError(ValueError):
    pass


def _name_from_file(path: Path, data: dict) -> str:
    raw = str(data.get(_NAME_KEY) or "").strip()
    if raw:
        return raw
    return path.stem


def validate_user_template(user_tmpl: str) -> None:
    if _PAYLOAD_PLACEHOLDER not in user_tmpl:
        raise PromptValidationError(
            f"User-шаблон повинен містити {_PAYLOAD_PLACEHOLDER}"
        )
    stripped = user_tmpl.replace(_PAYLOAD_PLACEHOLDER, "")
    leftovers = _OTHER_BRACE_RE.findall(stripped)
    if leftovers:
        raise PromptValidationError(
            "User-шаблон містить зайві фігурні дужки окрім "
            f"{_PAYLOAD_PLACEHOLDER}: {leftovers[:5]}"
        )
    # Smoke .format to catch any other issues.
    try:
        user_tmpl.format(declaration_payload="{}")
    except KeyError as exc:
        raise PromptValidationError(
            f"Помилка .format() у user-шаблоні (зайвий плейсхолдер?): {exc}"
        ) from exc


def load_prompt_file(path: Path) -> PromptSpec:
    path = Path(path)
    if not path.is_file():
        raise PromptValidationError(f"Файл промпту не знайдено: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PromptValidationError(f"Некоректний JSON у {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise PromptValidationError(f"{path.name}: корінь повинен бути JSON-об'єктом")

    system = data.get(_SYSTEM_KEY)
    user = data.get(_USER_KEY)
    if not isinstance(system, str) or not system.strip():
        raise PromptValidationError(f"{path.name}: відсутній ключ {_SYSTEM_KEY}")
    if not isinstance(user, str) or not user.strip():
        raise PromptValidationError(f"{path.name}: відсутній ключ {_USER_KEY}")

    validate_user_template(user)
    name = _name_from_file(path, data)
    return PromptSpec(
        name=name,
        path=path.resolve(),
        system_prompt=system.strip(),
        user_prompt_template=user.strip(),
    )


def discover_prompts(prompts_dir: Optional[Path] = None) -> Tuple[List[PromptSpec], List[str]]:
    """Return (valid prompts, human-readable error strings for invalid files)."""
    root = Path(prompts_dir or PROMPTS_DIR)
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
        return [], []

    specs: List[PromptSpec] = []
    errors: List[str] = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.name.lower()):
        try:
            specs.append(load_prompt_file(path))
        except PromptValidationError as exc:
            errors.append(str(exc))
    return specs, errors


def builtin_core_as_prompt() -> PromptSpec:
    """Load the project's built-in SYSTEM/USER prompts as a PromptSpec named 'core'."""
    import sys

    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from main import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

    validate_user_template(USER_PROMPT_TEMPLATE)
    return PromptSpec(
        name="core",
        path=project_root / "main.py",
        system_prompt=SYSTEM_PROMPT.strip(),
        user_prompt_template=USER_PROMPT_TEMPLATE.strip(),
    )
