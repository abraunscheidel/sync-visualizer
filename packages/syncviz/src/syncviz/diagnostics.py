"""Synchronization diagnostics: evidence that the sources' clocks agree, or that they do not (design doc §18.2).

A check looks at two or more sources and reports, in the same shape every time: a status, a one-line summary, the numbers
behind it, and the arrays needed to draw it. Nothing here can *prove* that sync is right; it can show disagreement, and
say which evidence is consistent with agreement. Status wording reflects that: "pass" means consistent with the clocks
agreeing to within the project's tolerance.

Two kinds of evidence are built in:

* `paired_events`: the same physical moments seen by two sources (video blackouts and trial boundaries, say). They are
  paired up, and the error of each pair, its typical size, and whether it grows over the session are measured.
* `event_response`: an independent cross-check that does not depend on any sync signal. A response with a known delay
  (neurons firing 5 to 30 ms after a whisker touch) should peak at about that delay when aligned on the stimulus. If the
  clocks disagree, the peak moves or smears.

More kinds can be added as plugins in the entry-point group `syncviz.sync_checks`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

import numpy as np

from syncviz import plugins

DEFAULT_TOLERANCE_MS = 20.0


class Status(str, Enum):
    PASS = "pass"                      # consistent with the clocks agreeing within the tolerance
    WARN = "warn"                      # close to the tolerance, or something unusual
    FAIL = "fail"                      # the clocks disagree by more than the tolerance
    INCONCLUSIVE = "inconclusive"      # the data cannot say (for example no clear response to measure)
    NOT_APPLICABLE = "not applicable"  # this recording lacks what the check needs

    @property
    def rank(self) -> int:
        return {"pass": 0, "not applicable": 0, "inconclusive": 1, "warn": 2, "fail": 3}[self.value]


@dataclass
class CheckResult:
    name: str
    kind: str
    status: Status
    summary: str                                           # one line, for the list
    details: list[str] = field(default_factory=list)       # the numbers, one per line
    data: dict[str, Any] = field(default_factory=dict)     # arrays and numbers for drawing it

    def to_json(self) -> dict:
        def plain(v):
            if isinstance(v, np.ndarray):
                return v.tolist()
            if isinstance(v, (np.floating, np.integer)):
                return v.item()
            if isinstance(v, dict):
                return {k: plain(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [plain(x) for x in v]
            return v

        return {"name": self.name, "kind": self.kind, "status": self.status.value, "summary": self.summary,
                "details": list(self.details), "data": plain(self.data)}

    @classmethod
    def from_json(cls, body: dict) -> "CheckResult":
        data = {k: (np.asarray(v) if isinstance(v, list) else v) for k, v in body.get("data", {}).items()}
        return cls(body["name"], body["kind"], Status(body["status"]), body["summary"], list(body.get("details", [])), data)


def overall(results: Sequence[CheckResult]) -> Status | None:
    """The worst status among results that say something, or None if there are none."""
    judged = [r.status for r in results if r.status is not Status.NOT_APPLICABLE]
    return max(judged, key=lambda s: s.rank) if judged else None


def summarize(results: Sequence[CheckResult]) -> str:
    """A short line such as "2 pass, 1 warn" for always-visible status."""
    if not results:
        return "not checked yet"
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status.value] = counts.get(r.status.value, 0) + 1
    order = ["fail", "warn", "inconclusive", "pass", "not applicable"]
    return ", ".join(f"{counts[s]} {s}" for s in order if s in counts)


def _grade(value: float, tolerance: float) -> Status:
    """pass within the tolerance, warn within twice it, fail beyond."""
    value = abs(value)
    return Status.PASS if value <= tolerance else Status.WARN if value <= 2 * tolerance else Status.FAIL


def _worst(*statuses: Status) -> Status:
    return max(statuses, key=lambda s: s.rank)


# -- paired events ------------------------------------------------------------------------------------
def pair_events(test: np.ndarray, reference: np.ndarray, window: float) -> tuple[np.ndarray, np.ndarray]:
    """Pair each reference event with the nearest test event within `window` seconds, each test event used once.
    Returns the indices into `test` and into `reference` of the pairs."""
    test, reference = np.asarray(test, float), np.asarray(reference, float)
    if len(test) == 0 or len(reference) == 0:
        return np.empty(0, int), np.empty(0, int)
    pos = np.clip(np.searchsorted(test, reference), 1, len(test) - 1) if len(test) > 1 else np.zeros(len(reference), int)
    left, right = np.maximum(pos - 1, 0), pos
    nearest = np.where(np.abs(test[left] - reference) <= np.abs(test[right] - reference), left, right)
    gap = np.abs(test[nearest] - reference)
    best: dict[int, tuple[float, int]] = {}                 # one reference per test event: the closest wins
    for ref_index in np.flatnonzero(gap <= window):
        t = int(nearest[ref_index])
        if t not in best or gap[ref_index] < best[t][0]:
            best[t] = (float(gap[ref_index]), int(ref_index))
    pairs = sorted((ref_index, t) for t, (_g, ref_index) in best.items())
    return (np.array([t for _r, t in pairs], int), np.array([r for r, _t in pairs], int))


def check_paired_events(test: Sequence[float], reference: Sequence[float], *, name: str = "Paired events",
                        tolerance_ms: float = DEFAULT_TOLERANCE_MS, match_ms: float = 500.0,
                        test_label: str = "test", reference_label: str = "reference",
                        declared_rate: float | None = None) -> CheckResult:
    """Do two sources see the same moments at the same times? Error is test minus reference."""
    test, reference = np.sort(np.asarray(test, float)), np.sort(np.asarray(reference, float))
    kind = "paired_events"
    if len(test) == 0 or len(reference) == 0:
        who = test_label if len(test) == 0 else reference_label
        return CheckResult(name, kind, Status.INCONCLUSIVE, f"no events found in {who}")
    ti, ri = pair_events(test, reference, match_ms / 1000.0)
    n_pairs = len(ti)
    if n_pairs < 5:
        return CheckResult(name, kind, Status.FAIL, f"only {n_pairs} of {len(reference)} {reference_label} events have a "
                           f"{test_label} event within {match_ms:g} ms",
                           [f"{test_label}: {len(test)} events", f"{reference_label}: {len(reference)} events"])
    error = (test[ti] - reference[ri]) * 1000.0                         # ms
    when = reference[ri]
    offset = float(np.median(error))
    centred = error - offset
    mad = float(np.median(np.abs(centred)))
    keep = np.abs(centred) <= max(3 * 1.4826 * mad, 1.0)                # fit drift on typical pairs, not outliers
    slope, intercept = np.polyfit(when[keep], error[keep], 1) if keep.sum() > 2 else (0.0, offset)
    span = float(when.max() - when.min())
    drift = float(slope * span)                                         # ms gained across the whole recording
    spread = float(np.percentile(np.abs(centred), 95))
    matched = n_pairs / len(reference)

    verdicts = [_grade(offset, tolerance_ms), _grade(spread, tolerance_ms), _grade(drift, tolerance_ms)]
    if matched < 0.5:
        verdicts.append(Status.FAIL)
    elif matched < 0.8:
        verdicts.append(Status.WARN)
    status = _worst(*verdicts)

    details = [
        f"{n_pairs} of {len(reference)} {reference_label} events paired with a {test_label} event (within {match_ms:g} ms); "
        f"{len(test) - n_pairs} {test_label} events unpaired",
        f"typical error (median) {offset:+.1f} ms: {test_label} minus {reference_label}",
        f"spread (95% of errors within) ±{spread:.1f} ms of that",
        f"drift {drift:+.1f} ms over {span:.0f} s ({slope * 1e6 / 1000:+.0f} ppm)",
        f"tolerance ±{tolerance_ms:g} ms (warn up to ±{2 * tolerance_ms:g} ms)",
    ]
    if declared_rate:
        implied = declared_rate * (1 + slope / 1000.0)
        details.append(f"implied rate {implied:.3f} per second against the declared {declared_rate:g}")
    summary = (f"error {offset:+.1f} ms, spread ±{spread:.1f} ms, drift {drift:+.1f} ms over {span / 60:.0f} min "
               f"({n_pairs}/{len(reference)} paired)")
    return CheckResult(name, kind, status, summary, details, {
        "when": when, "error_ms": error, "offset_ms": offset, "spread_ms": spread, "drift_ms": drift, "slope": float(slope),
        "intercept_ms": float(intercept), "tolerance_ms": tolerance_ms, "n_pairs": n_pairs,
        "unpaired_test": len(test) - n_pairs, "unpaired_reference": len(reference) - n_pairs,
    })


# -- event-aligned response --------------------------------------------------------------------------
def isolated(times: np.ndarray, gap: float) -> np.ndarray:
    """Events with no other event in the `gap` seconds before them, so each stands alone."""
    times = np.sort(np.asarray(times, float))
    if len(times) == 0:
        return times
    return times[np.r_[True, np.diff(times) > gap]]


def check_event_response(stimulus: Sequence[float], responses: Sequence[Sequence[float]], *, name: str = "Event response",
                         expect_ms: tuple[float, float] = (5.0, 30.0), tolerance_ms: float = DEFAULT_TOLERANCE_MS,
                         min_ratio: float = 1.5, isolate_ms: float = 300.0, bin_ms: float = 5.0,
                         before_ms: float = 200.0, after_ms: float = 300.0,
                         stimulus_label: str = "stimulus", response_label: str = "response") -> CheckResult:
    """Does the response peak when it should after the stimulus? The mean rate of all response series is aligned on
    each stimulus; if the clocks disagree the peak is early, late or smeared."""
    kind = "event_response"
    stim = isolated(np.asarray(stimulus, float), isolate_ms / 1000.0)
    series = [np.sort(np.asarray(r, float)) for r in responses if len(r)]
    if len(stim) < 20 or not series:
        return CheckResult(name, kind, Status.INCONCLUSIVE,
                           f"too few {stimulus_label} events ({len(stim)}) or no {response_label} events to measure a response")
    lo_s, hi_s = -before_ms / 1000.0, after_ms / 1000.0
    edges = np.arange(-before_ms, after_ms + bin_ms, bin_ms) / 1000.0
    counts = np.zeros(len(edges) - 1)
    for spikes in series:
        for t0 in stim:
            a, b = np.searchsorted(spikes, [t0 + lo_s, t0 + hi_s])
            counts += np.histogram(spikes[a:b] - t0, bins=edges)[0]
    rate = counts / (len(stim) * (bin_ms / 1000.0) * len(series))          # events per second per response series
    centers_ms = (edges[:-1] + edges[1:]) / 2 * 1000.0
    baseline = float(rate[centers_ms < -50].mean())
    lo, hi = expect_ms
    window = (centers_ms >= lo) & (centers_ms <= hi)
    search = (centers_ms >= 0) & (centers_ms <= hi + 4 * tolerance_ms)
    peak_index = int(np.flatnonzero(search)[np.argmax(rate[search])])
    peak_ms, peak_rate = float(centers_ms[peak_index]), float(rate[peak_index])
    ratio = peak_rate / baseline if baseline > 0 else float("inf")
    before = float(rate[(centers_ms >= -50) & (centers_ms < 0)].mean())
    data = {"centers_ms": centers_ms, "rate": rate, "baseline": baseline, "peak_ms": peak_ms, "peak_rate": peak_rate,
            "expect_ms": [lo, hi], "n_stimuli": len(stim), "ratio": ratio, "tolerance_ms": tolerance_ms}
    details = [
        f"aligned on {len(stim)} isolated {stimulus_label} events (no other within {isolate_ms:g} ms before), "
        f"averaged over {len(series)} {response_label} series",
        f"baseline {baseline:.2f} per second; peak {peak_rate:.2f} per second ({ratio:.1f}x baseline) at {peak_ms:+.0f} ms",
        f"expected peak between {lo:g} and {hi:g} ms after the stimulus; tolerance ±{tolerance_ms:g} ms",
        f"the 50 ms before the stimulus: {before:.2f} per second ({before / baseline:.2f}x baseline)" if baseline > 0 else "",
    ]
    details = [d for d in details if d]
    if ratio < min_ratio:
        return CheckResult(name, kind, Status.INCONCLUSIVE,
                           f"no clear response to {stimulus_label} (peak only {ratio:.1f}x baseline), so timing cannot be judged",
                           details, data)
    if lo <= peak_ms <= hi:
        status = Status.PASS
    elif lo - tolerance_ms <= peak_ms <= hi + tolerance_ms:
        status = Status.WARN
    else:
        status = Status.FAIL
    if baseline > 0 and before / baseline > 1.3 and status is Status.PASS:
        status = Status.WARN
        details.append("the rate already rises before the stimulus, which is not what a response to it would do")
    summary = f"{ratio:.1f}x baseline, peak at {peak_ms:+.0f} ms (expected {lo:g} to {hi:g} ms) from {len(stim)} {stimulus_label} events"
    return CheckResult(name, kind, status, summary, details, data)


BUILTIN = {"paired_events": check_paired_events, "event_response": check_event_response}


def get(kind: str):
    """The check function called `kind`: built in, else from a plugin."""
    if kind in BUILTIN:
        return BUILTIN[kind]
    try:
        return plugins.load("sync_checks", kind)
    except KeyError:
        raise KeyError(f"no sync check of kind {kind!r} (available: {', '.join(sorted({*BUILTIN, *plugins.available('sync_checks')}))})") from None
