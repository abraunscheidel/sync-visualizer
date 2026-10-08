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
            rows.append(f"<li>{escape(name)}<br>{lo:.2f} to {hi:.2f} s</li>")
        rows.append("</ul>")
        if c.notes:
            rows.append("<b>Notes</b><ul>" + "".join(f"<li>{escape(n)}</li>" for n in c.notes) + "</ul>")
        self.setHtml("".join(rows))
