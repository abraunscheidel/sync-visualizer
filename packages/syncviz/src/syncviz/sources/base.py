"""Base class for format-specific data access.

Sources know how to read a format; they do not define what the data means.
They hand generic resources (TimeSeries, SpikeTrain, ...) to the rest of the
application (design doc §6, principle 1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class MissingDataError(KeyError):
    """Something a view needs is not in this collection (a source it does not have, or a path in a
    file that is not there). Views show a calm "no data" message rather than failing."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


@dataclass(frozen=True)
class DataEntry:
    """One thing a source can provide, as offered to the user when choosing what to show.

    `kind` is a generic resource kind ("timeseries", "events", "intervals") or "video";
    `members` names the parts of a container (several series stored together), in the order the source
    thinks natural (for neurons, by depth).
    """

    path: str
    kind: str
    members: tuple[str, ...] = field(default_factory=tuple)
    labels: dict[str, str] = field(default_factory=dict)   # display name of a member, where it has a better one


class Source(ABC):
    @abstractmethod
    def describe(self) -> list[str]:
        """Names of the data objects this source can provide, without loading them."""

    def close(self) -> None:
        """Release files held open for lazy reading. Safe to call more than once."""

    def catalog(self) -> list[DataEntry]:
        """What this source offers, classified by kind, for the "add a view" dialog. Sources that
        cannot say return nothing and can still be used through the project file."""
        return []
