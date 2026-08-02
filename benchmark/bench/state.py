"""Persist and resume benchmark run progress."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CellProgress:
    model_id: str
    prompt_name: str
    status: str = "pending"  # pending | running | done | failed | skipped | circuit_open
    ok_count: int = 0
    err_count: int = 0
    consecutive_failures: int = 0
    last_error: str = ""
    started_at_utc: str = ""
    finished_at_utc: str = ""
    processed_files: List[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.model_id}||{self.prompt_name}"


@dataclass
class BenchState:
    run_dir: str
    run_id: str
    status: str = "created"  # created | running | paused | done | aborted
    cells: Dict[str, CellProgress] = field(default_factory=dict)
    updated_at_utc: str = field(default_factory=_now)

    def ensure_cell(self, model_id: str, prompt_name: str) -> CellProgress:
        key = f"{model_id}||{prompt_name}"
        if key not in self.cells:
            self.cells[key] = CellProgress(model_id=model_id, prompt_name=prompt_name)
        return self.cells[key]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_dir": self.run_dir,
            "run_id": self.run_id,
            "status": self.status,
            "updated_at_utc": self.updated_at_utc,
            "cells": {
                k: asdict(v) for k, v in self.cells.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchState":
        cells: Dict[str, CellProgress] = {}
        raw_cells = data.get("cells") or {}
        if isinstance(raw_cells, dict):
            for key, val in raw_cells.items():
                if not isinstance(val, dict):
                    continue
                cells[str(key)] = CellProgress(
                    model_id=str(val.get("model_id") or ""),
                    prompt_name=str(val.get("prompt_name") or ""),
                    status=str(val.get("status") or "pending"),
                    ok_count=int(val.get("ok_count") or 0),
                    err_count=int(val.get("err_count") or 0),
                    consecutive_failures=int(val.get("consecutive_failures") or 0),
                    last_error=str(val.get("last_error") or ""),
                    started_at_utc=str(val.get("started_at_utc") or ""),
                    finished_at_utc=str(val.get("finished_at_utc") or ""),
                    processed_files=list(val.get("processed_files") or []),
                )
        return cls(
            run_dir=str(data.get("run_dir") or ""),
            run_id=str(data.get("run_id") or ""),
            status=str(data.get("status") or "created"),
            cells=cells,
            updated_at_utc=str(data.get("updated_at_utc") or _now()),
        )


def state_path(run_dir: Path) -> Path:
    return Path(run_dir) / "bench_state.json"


def save_state(state: BenchState, run_dir: Path) -> None:
    state.updated_at_utc = _now()
    path = state_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def load_state(run_dir: Path) -> Optional[BenchState]:
    path = state_path(run_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return BenchState.from_dict(data)


def write_manifest(run_dir: Path, manifest: Dict[str, Any]) -> Path:
    path = Path(run_dir) / "run_manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
