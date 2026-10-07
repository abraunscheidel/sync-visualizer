"""Base class for format-specific data access.

Sources know how to read a format; they do not define what the data means.
They hand generic resources (TimeSeries, SpikeTrain, ...) to the rest of the
application (design doc §6, principle 1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Source(ABC):
    @abstractmethod
    def describe(self) -> list[str]:
        """Names of the data objects this source can provide, without loading them."""
