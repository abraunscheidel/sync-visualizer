"""Running a project's synchronization checks for one collection.

The generic checks (`syncviz.diagnostics`) know nothing about sources. This module resolves what a check's specification
names ("video:sync_signal", "session:units", ...) into event times, runs the check, and keeps its result on disk so
that an expensive first run (scanning a long video) is not repeated. Checks that only make sense for one kind of source
come from that source (`Source.diagnostics`), not from here.

A project describes its checks in a `sync` section:

    sync:
      tolerance_ms: 20
      checks:
        - name: Video blackouts vs trial starts
          type: paired_events
          test: video:sync_signal                              # the events whose clock is being examined
          reference: {from: "session:intervals/trials", edge: start}
          note: why exact agreement does (or does not) mean something
        - name: Neural response to whisker contact
          type: event_response
          stimulus: {from: "session:processing/behavior/contacts_by_whisker_C1", edge: start}
          response: "session:units"
          expect_ms: [5, 30]
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from syncviz import diagnostics
from syncviz.diagnostics import CheckResult, DEFAULT_TOLERANCE_MS, Status
from syncviz.sources import MissingDataError

PAIRED_KEYS = ("match_ms",)
RESPONSE_KEYS = ("isolate_ms", "min_ratio", "bin_ms", "before_ms", "after_ms")


def _times(streams) -> np.ndarray:
    return np.sort(np.concatenate([np.asarray(s.times, float) for s in streams])) if streams else np.empty(0)


def _label(spec) -> str:
    return spec if isinstance(spec, str) else str(spec.get("from", "?"))


def _run_one(resources, item: dict, tolerance_ms: float) -> CheckResult:
    kind = item["type"]
    name = item.get("name") or kind
    tolerance = float(item.get("tolerance_ms", tolerance_ms))
    function = diagnostics.get(kind)
    try:
        if kind == "paired_events":
            test = resources.event_streams(item["test"])
            reference = resources.event_streams(item["reference"])
            rate = next((s.metadata.get("fps") for s in test if s.metadata.get("fps")), None)
            result = function(_times(test), _times(reference), name=name, tolerance_ms=tolerance,
                              test_label=_label(item["test"]), reference_label=_label(item["reference"]),
                              declared_rate=rate, **{k: item[k] for k in PAIRED_KEYS if k in item})
        elif kind == "event_response":
            stimulus = resources.event_streams(item["stimulus"])
            responses = resources.event_streams(item["response"])
            extra = {k: item[k] for k in RESPONSE_KEYS if k in item}
            if "expect_ms" in item:
                extra["expect_ms"] = tuple(item["expect_ms"])
            result = function(_times(stimulus), [np.asarray(r.times) for r in responses], name=name, tolerance_ms=tolerance,
                              stimulus_label=_label(item["stimulus"]), response_label=_label(item["response"]), **extra)
        else:                                        # a plugin's own kind: it reads its own specification
            result = function(resources, item, tolerance)
    except MissingDataError as exc:
        return CheckResult(name, kind, Status.NOT_APPLICABLE, f"this recording lacks something the check needs ({exc})")
    except Exception as exc:                         # a broken check must not stop the others
        return CheckResult(name, kind, Status.INCONCLUSIVE, f"could not run: {exc}")
    if item.get("note"):
        result.details.append(f"Note: {item['note']}")
    return result


def run_checks(project, index: int) -> list[CheckResult]:
    """Every check for collection `index`: the checks each of its sources offers about itself, then the project's.
    Uses its own resources, so it can run on another thread while the application is in use."""
    resources = project.open_collection(index)
    try:
        spec = project.config.get("sync") or {}
        tolerance = float(spec.get("tolerance_ms", DEFAULT_TOLERANCE_MS))
        results: list[CheckResult] = []
        for source_name, source in resources.sources.items():
            for result in source.diagnostics():
                result.name = f"{source_name}: {result.name}"
                results.append(result)
        for item in spec.get("checks", []):
            results.append(_run_one(resources, item, tolerance))
        return results
    finally:
        resources.close()


# -- keeping results ---------------------------------------------------------------------------------
def _cache_file(project, index: int) -> Path | None:
    if project.cache is None:
        return None
    collection = project.collections[index]
    parts = [json.dumps(project.config.get("sync") or {}, sort_keys=True, default=str), collection.key]
    for name, template in sorted((project.config.get("sources") or {}).items()):
        try:
            source = project.build_sources(collection).get(name)
        except Exception:
            source = None
        path = getattr(source, "path", None)
        if path is not None and Path(path).exists():
            stat = Path(path).stat()
            parts.append(f"{path}:{stat.st_size}:{stat.st_mtime_ns}")
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]
    return Path(project.cache.root) / "diagnostics" / f"{digest}.json"


def load_cached(project, index: int) -> list[CheckResult] | None:
    """The saved results for this collection if the files and checks are unchanged, else None."""
    path = _cache_file(project, index)
    if path is None or not path.exists():
        return None
    try:
        return [CheckResult.from_json(body) for body in json.loads(path.read_text(encoding="utf-8"))]
    except (OSError, ValueError, KeyError):
        return None


def store(project, index: int, results: list[CheckResult]) -> None:
    path = _cache_file(project, index)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([r.to_json() for r in results]), encoding="utf-8")


def has_checks(project) -> bool:
    return bool((project.config.get("sync") or {}).get("checks"))
