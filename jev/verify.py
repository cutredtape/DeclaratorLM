"""Перевірка знахідок LLM через Jev: чи збігаються їхні факти з декларацією (docs/JEV.md §3.7).

Один виклик Jev на декларацію: стан = очищений компакт декларації + знахідки;
на кожну знахідку два noul-питання:
  * grounded    — згадані суми, площі, дати, майно й особи справді є в
                  декларації й відповідають написаному;
  * substantive — це вагома ознака ризику, а не звичайна ситуація чи технічна
                  неповнота даних.

Як це поводиться: grounded надійно відрізняє справжні знахідки від тих самих
із навмисно зіпсованими числами, а найнижчі оцінки серед справжніх знахідок
вказують на фактичні помилки LLM (переплутані об'єкти й власники, хибні
суми). Чи правильна сама знахідка, grounded НЕ каже — хибні тривоги LLM
здебільшого правдиві дрібниці, а не вигадані факти. substantive як
доповнення до серйозності (спершу серйозність, потім substantive) покращує
порядок знахідок.

Тому в пайплайні: grounded < GROUNDED_WARN → попередження у звіті (знахідка
лишається — часто вона правильна по суті, але з хибними цифрами);
substantive — лише порядок знахідок однакової серйозності.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import client as jev_client

GROUNDED_WARN = 0.5

# Для перевірки фактів рік і тип декларації потрібні (знахідки на них
# посилаються) — тому не coreframe-strip, а лише службовий шум.
STATE_STRIP = ["steps_context", "meta.id", "step_0_interpreted.public_service_context"]

GROUNDED_INSTR = (
    "Знахідка {k} у полі `findings` спирається на факти, які справді є в полі "
    "`декларація`: згадані в ній суми, площі, дати, об'єкти майна й особи там "
    "присутні й відповідають написаному."
)
SUBSTANTIVE_INSTR = (
    "Знахідка {k} у полі `findings` описує вагому ознаку корупційного ризику, яку "
    "варто перевіряти, а не звичайну для такої декларації ситуацію чи технічну "
    "неповноту даних."
)

_SEV_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}


def declaration_state(compact: Dict[str, Any]) -> Dict[str, Any]:
    return jev_client.clean_state(compact, strip=STATE_STRIP, drop_empty=True)


def ask(
    decl_state: Dict[str, Any],
    findings: List[Dict[str, Any]],
    api_key: str,
    *,
    with_substantive: bool = True,
    model: str = jev_client.DEFAULT_JEV_MODEL,
    timeout_sec: int = 60,
    retries: int = 2,
    retry_delay: float = 3.0,
) -> List[Dict[str, float]]:
    """Ймовірності grounded (і substantive) для кожної знахідки, у тому ж порядку."""
    if not findings:
        return []
    state = {
        "декларація": decl_state,
        "findings": {
            f"f{i}": {
                "title": f.get("title", ""),
                "type": f.get("type", ""),
                "rationale": f.get("rationale", ""),
                "evidence": f.get("evidence") or [],
            }
            for i, f in enumerate(findings)
        },
    }
    questions: Dict[str, Dict[str, Any]] = {}
    for i in range(len(findings)):
        questions[f"g_f{i}"] = {"type": "noul", "instructions": GROUNDED_INSTR.format(k=f"f{i}")}
        if with_substantive:
            questions[f"s_f{i}"] = {"type": "noul", "instructions": SUBSTANTIVE_INSTR.format(k=f"f{i}")}
    raw = jev_client.call_jev(
        state, questions, model=model, api_key=api_key,
        timeout_sec=timeout_sec, retries=retries, retry_delay=retry_delay,
    )
    out: List[Dict[str, float]] = []
    for i in range(len(findings)):
        row = {"grounded": jev_client._noul_probability(jev_client._answer_block(raw, f"g_f{i}"))}
        if with_substantive:
            row["substantive"] = jev_client._noul_probability(jev_client._answer_block(raw, f"s_f{i}"))
        out.append(row)
    return out


def annotate_result(
    result: Dict[str, Any], compact: Dict[str, Any], api_key: str, **kwargs: Any
) -> Optional[Dict[str, Any]]:
    """Дописує в кожну знахідку `_jev_grounded`/`_jev_substantive` і впорядковує
    знахідки однакової серйозності за substantive. Повертає блок для run_meta
    або None, якщо знахідок немає. Винятки Jev — нагору: вирішує викликач."""
    analysis = result.get("analysis") or {}
    findings = [f for f in (analysis.get("findings") or []) if isinstance(f, dict)]
    if not findings:
        return None
    scores = ask(declaration_state(compact), findings, api_key, **kwargs)
    for f, s in zip(findings, scores):
        f["_jev_grounded"] = round(s["grounded"], 3)
        f["_jev_substantive"] = round(s["substantive"], 3)
    # Стабільне сортування: спершу серйозність (як і раніше), усередині рівня —
    # substantive; інший порядок LLM нічого не означав.
    findings.sort(
        key=lambda f: (_SEV_RANK.get(str(f.get("severity", "")).lower(), 0), f.get("_jev_substantive", 0.0)),
        reverse=True,
    )
    analysis["findings"] = findings
    flagged = sum(1 for f in findings if f["_jev_grounded"] < GROUNDED_WARN)
    return {"n_findings": len(findings), "n_not_grounded": flagged, "warn_threshold": GROUNDED_WARN}
