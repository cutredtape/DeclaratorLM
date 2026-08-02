"""Scan and validate the benchmark corpus folder."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CorpusFile:
    path: Path
    name: str
    size_bytes: int
    sha256: str
    ok: bool
    error: str = ""
    declaration_id: str = ""
    declaration_year: Any = None


@dataclass
class CorpusScan:
    corpus_dir: Path
    files: List[CorpusFile] = field(default_factory=list)
    total_bytes: int = 0
    ok_count: int = 0
    bad_count: int = 0
    empty: bool = True

    @property
    def ok_files(self) -> List[CorpusFile]:
        return [f for f in self.files if f.ok]

    @property
    def bad_files(self) -> List[CorpusFile]:
        return [f for f in self.files if not f.ok]

    def paths(self, *, max_files: int = 0) -> List[Path]:
        paths = [f.path for f in self.ok_files]
        paths.sort(key=lambda p: p.name.lower())
        if max_files and max_files > 0:
            return paths[:max_files]
        return paths

    def to_manifest(self) -> Dict[str, Any]:
        return {
            "corpus_dir": str(self.corpus_dir),
            "file_count": len(self.files),
            "ok_count": self.ok_count,
            "bad_count": self.bad_count,
            "total_bytes": self.total_bytes,
            "files": [
                {
                    "name": f.name,
                    "size_bytes": f.size_bytes,
                    "sha256": f.sha256,
                    "ok": f.ok,
                    "error": f.error,
                    "declaration_id": f.declaration_id,
                    "declaration_year": f.declaration_year,
                }
                for f in self.files
            ],
        }


def _sha256_file(path: Path, *, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def scan_corpus(corpus_dir: Path) -> CorpusScan:
    """Scan *.json in corpus_dir (non-recursive). Report counts, sizes, broken JSON."""
    root = Path(corpus_dir)
    result = CorpusScan(corpus_dir=root)
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
        result.empty = True
        return result
    if not root.is_dir():
        raise NotADirectoryError(f"Corpus path is not a directory: {root}")

    json_files = sorted(root.glob("*.json"), key=lambda p: p.name.lower())
    result.empty = len(json_files) == 0

    for path in json_files:
        try:
            size = path.stat().st_size
        except OSError as exc:
            result.files.append(
                CorpusFile(
                    path=path,
                    name=path.name,
                    size_bytes=0,
                    sha256="",
                    ok=False,
                    error=f"stat failed: {exc}",
                )
            )
            result.bad_count += 1
            continue

        try:
            digest = _sha256_file(path)
        except OSError as exc:
            result.files.append(
                CorpusFile(
                    path=path,
                    name=path.name,
                    size_bytes=size,
                    sha256="",
                    ok=False,
                    error=f"hash failed: {exc}",
                )
            )
            result.bad_count += 1
            result.total_bytes += size
            continue

        decl_id = ""
        decl_year: Any = None
        ok = True
        err = ""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                ok = False
                err = "root is not a JSON object"
            else:
                decl_id = str(raw.get("id") or "").strip()
                decl_year = raw.get("declaration_year")
                if "data" not in raw and "step_1" not in raw:
                    # Soft warning only — still usable if compact can handle it.
                    pass
        except json.JSONDecodeError as exc:
            ok = False
            err = f"invalid JSON: {exc}"
        except OSError as exc:
            ok = False
            err = f"read failed: {exc}"

        result.files.append(
            CorpusFile(
                path=path,
                name=path.name,
                size_bytes=size,
                sha256=digest,
                ok=ok,
                error=err,
                declaration_id=decl_id,
                declaration_year=decl_year,
            )
        )
        result.total_bytes += size
        if ok:
            result.ok_count += 1
        else:
            result.bad_count += 1

    return result


def format_bytes(n: int) -> str:
    val = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(val)} {unit}"
            return f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{n} B"
