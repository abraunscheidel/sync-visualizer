"""Always-present project information: sources, where each view's data exists, and notes."""

from __future__ import annotations

from html import escape

from PySide6.QtWidgets import QTextBrowser

from syncviz_app.context import AppContext
from syncviz_app.project import Project


class InfoPanel(QTextBrowser):
    def __init__(self, project: Project, context: AppContext) -> None:
        super().__init__()
        self.project, self.context = project, context
        self.setMinimumWidth(220)
        self.setOpenLinks(False)
        self.rebuild()

    def rebuild(self) -> None:
        p, c = self.project, self.context
        rows = [f"<h3>{escape(p.name)}</h3>", "<b>Sources</b><ul>"]
        for name, spec in (p.config.get("sources") or {}).items():
            rows.append(f"<li>{escape(name)} <i>({escape(str(spec.get('type')))})</i></li>")
        rows.append("</ul><b>Data extent</b> (shared time)<ul>")
        for name, (lo, hi) in c.extents.items():
            swatch = f"<span style='color:{c.colors.get(name, '#888888')}'>&#9632;</span> "
            gaps = len(c.coverage.get(name, [])) - 1
            note = f"<br>{gaps} gap{'s' if gaps != 1 else ''} in the data" if gaps > 0 else ""
            rows.append(f"<li>{swatch}{escape(name)}<br>{lo:.2f} to {hi:.2f} s{note}</li>")
        rows.append("</ul>")
        if c.notes:
            rows.append("<b>Notes</b><ul>" + "".join(f"<li>{escape(n)}</li>" for n in c.notes) + "</ul>")
        self.setHtml("".join(rows))
