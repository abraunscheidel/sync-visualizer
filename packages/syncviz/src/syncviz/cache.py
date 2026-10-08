"""On-disk cache for expensive derived arrays (design doc §8, §18.1).

Entries are keyed by the input file (path, size, modification time), the name
of the analysis, and its parameters, so editing or replacing a file or
changing a parameter never returns a stale result.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

import numpy as np


class DiskCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def key(self, source_file: str | Path, analysis: str, params: dict | None = None) -> str:
        p = Path(source_file)
        st = p.stat()
        ident = {
            "file": str(p.resolve()),
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "analysis": analysis,
            "params": params or {},
        }
        digest = hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:24]
        return f"{analysis}-{digest}"

    def get_or_compute(
        self,
        source_file: str | Path,
        analysis: str,
        compute: Callable[[], np.ndarray],
        params: dict | None = None,
    ) -> np.ndarray:
        path = self.root / f"{self.key(source_file, analysis, params)}.npy"
        if path.exists():
            return np.load(path)
        result = np.asarray(compute())
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.npy")
        np.save(tmp, result)
        tmp.replace(path)    # atomic, so an interrupted scan never leaves a half-written entry
        return result
