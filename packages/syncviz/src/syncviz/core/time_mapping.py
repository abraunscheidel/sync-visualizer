"""Mappings between a source's native time coordinate and shared time.

Every time-dependent resource keeps its native timestamps; a TimeMapping is the
only sanctioned way to compare them across sources (design doc §19, §21).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import ArrayLike


@runtime_checkable
class TimeMapping(Protocol):
    """Converts between one source's native time and shared time.

    Deliberately not assumed to be linear; LinearTimeMapping is just the first
    implementation.
    """

    def to_shared(self, native: ArrayLike) -> np.ndarray: ...

    def to_native(self, shared: ArrayLike) -> np.ndarray: ...


@dataclass(frozen=True)
class LinearTimeMapping:
    """shared = offset + scale * native"""

    offset: float = 0.0
    scale: float = 1.0

    def __post_init__(self) -> None:
        if self.scale == 0:
            raise ValueError("scale must be non-zero for the mapping to be invertible")

    @classmethod
    def identity(cls) -> LinearTimeMapping:
        return cls()

    @classmethod
    def fit(cls, native: ArrayLike, shared: ArrayLike) -> LinearTimeMapping:
        """Least-squares fit from corresponding timestamps, e.g. matched sync pulses."""
        native = np.asarray(native, dtype=float)
        shared = np.asarray(shared, dtype=float)
        if native.shape != shared.shape or native.ndim != 1:
            raise ValueError("native and shared must be 1-D arrays of equal length")
        if native.size < 2:
            raise ValueError("need at least two corresponding timestamps to fit")
        scale, offset = np.polyfit(native, shared, deg=1)
        return cls(offset=float(offset), scale=float(scale))

    def to_shared(self, native: ArrayLike) -> np.ndarray:
        return self.offset + self.scale * np.asarray(native, dtype=float)

    def to_native(self, shared: ArrayLike) -> np.ndarray:
        return (np.asarray(shared, dtype=float) - self.offset) / self.scale
