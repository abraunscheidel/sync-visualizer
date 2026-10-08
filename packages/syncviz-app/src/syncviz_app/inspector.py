"""Works out the details of a target for the application (design doc section 28.7)."""

from __future__ import annotations

from syncviz.inspection import (
    Details, Field, Scope, Target, WHOLE, event_fields, interval_fields, timeseries_fields,
)
from syncviz.sources import MissingDataError
from syncviz_app.context import AppContext


class Inspector:
    """Turns a `Target` into `Details`: the file's description and the project's note, then statistics over the
    current segment (or the whole recording when there are no segments)."""

    def __init__(self, context: AppContext) -> None:
        self.context = context
        self._catalogs: dict[str, list] = {}
        self.hover_keys: set[str] | None = None            # which figures a hover shows; None = each statistic's default

    def scope(self) -> Scope:
        nav = self.context.navigator
        if nav is None:
            return WHOLE
        start, stop = nav.bounds
        return Scope(f"this {nav.label.lower()}", start, stop)

    def _described(self, target: Target) -> str:
        if target.source not in self._catalogs:
            try:
                self._catalogs[target.source] = self.context.resources.source(target.source).catalog()
            except Exception:
                self._catalogs[target.source] = []
        for entry in self._catalogs[target.source]:
            if entry.path == target.path:
                if target.member and entry.member_descriptions.get(target.member):
                    return entry.member_descriptions[target.member]
                return entry.description
        return ""

    def details(self, target: Target) -> Details:
        scope = self.scope()
        title = target.label or target.member or target.path
        details = Details(title, self.context.explain(title, self._described(target)), scope=scope)
        try:
            resources = self.context.resources
            if target.kind == "events":
                details.fields = event_fields(resources.events(target.ref, target.member), scope, self.context.dates)
            elif target.kind == "intervals":
                details.fields = interval_fields(resources.intervals(target.ref), scope)
            elif target.kind == "timeseries":
                details.fields = timeseries_fields(resources.timeseries(target.ref, target.member), scope)
            details.fields += self._from_source(target)
        except MissingDataError:
            details.fields = [Field("Data", "not available in this recording", brief=True)]
        if target.time is not None:
            details.fields.insert(0, Field("At", f"{target.time:.4f} s", brief=True))
        return details

    def _from_source(self, target: Target) -> list[Field]:
        try:
            return list(self.context.resources.source(target.source).details(target))
        except MissingDataError:
            return []

    def shown_on_hover(self, field: Field) -> bool:
        return field.brief if self.hover_keys is None else field.key in self.hover_keys

    def full_text(self, target: Target) -> str:
        """Everything known about the target as plain text, for copying."""
        details = self.details(target)
        lines = [details.title, f"Statistics over: {details.scope.label}"]
        if details.description:
            lines += ["", details.description]
        lines.append("")
        lines += [f"{f.name}: {f.value}" for f in details.fields]
        return "\n".join(lines)

    def hover_text(self, target: Target) -> str:
        """The tooltip: title, description, and the brief statistics."""
        details = self.details(target)
        lines = [details.title]
        if details.description:
            lines += ["", details.description]
        brief = [f for f in details.fields if self.shown_on_hover(f)]
        if brief:
            lines.append("")
            lines += [f"{f.name}: {f.value}" for f in brief]
        return "\n".join(lines)
