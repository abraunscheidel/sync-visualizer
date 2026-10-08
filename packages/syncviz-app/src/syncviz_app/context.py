"""Everything a view or control needs to take part in the application."""

from __future__ import annotations

from dataclasses import dataclass, field

from syncviz.cache import DiskCache
from syncviz.catalog import Collection
from syncviz.core import ActionBus, SegmentNavigator, Stepper, Timeline
from syncviz_app.project import ResourceStore


def explain(glossary: dict[str, str], term: str, described: str = "") -> str:
    """Text for a tooltip: what the source says the thing is (`described`), then the project's note on how to read it.
    Either may be missing; the result may be empty."""
    parts = [text.strip() for text in (described, glossary.get(term, "")) if text and text.strip()]
    return "\n\n".join(parts)


@dataclass
class AppContext:
    bus: ActionBus
    timeline: Timeline
    resources: ResourceStore
    navigator: SegmentNavigator | None = None
    stepper: Stepper | None = None                       # what one "step" of the playhead means
    cache: DiskCache | None = None                       # where expensive derived results are kept
    # Extent of each view's data in shared time, by view title. All sources are equal:
    # the timeline spans the union of these, and no source defines time zero.
    extents: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Runs of shared time in which each view has data (gaps are the spaces between runs), and the
    # colour each view is shown in wherever it is represented outside its own panel.
    coverage: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    colors: dict[str, str] = field(default_factory=dict)
    collection: Collection | None = None                 # the recording that is open
    collection_label: str = "Collection"                # what the project calls one ("Session")
    glossary: dict[str, str] = field(default_factory=dict)   # the project's notes on how to read a field, by its name
    notes: list[str] = field(default_factory=list)       # plain factual remarks about the data

    def explain(self, term: str, described: str = "") -> str:
        """Tooltip text for a field: what the source says it is, then the project's note on how to read it."""
        return explain(self.glossary, term, described)
