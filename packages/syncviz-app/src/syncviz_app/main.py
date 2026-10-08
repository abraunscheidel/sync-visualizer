"""Command line entry point: `syncviz path/to/project.yaml`."""

from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtWidgets import QApplication

from syncviz.core import Seek, StepSegment
from syncviz_app.app import build_window


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="syncviz")
    parser.add_argument("project", help="path to a project YAML file")
    parser.add_argument("--workspace", metavar="NAME", help="open this saved workspace (overrides the project file's `workspace:`)")
    parser.add_argument("--collection", metavar="KEY", help="open this collection (session) first")
    parser.add_argument("--debug", action="store_true",
                        help="add the Debug menu (slow-decoding simulation, live status); also set by SYNCVIZ_DEBUG=1")
    parser.add_argument("--screenshot", metavar="PNG", help="render one frame to a file and exit (for checking)")
    parser.add_argument("--segment-step", type=int, default=0, help="with --screenshot: step this many segments first")
    parser.add_argument("--time", type=float, help="with --screenshot: seek to this shared time first")
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = build_window(args.project, debug=args.debug or os.environ.get("SYNCVIZ_DEBUG") == "1",
                          use_workspace=not args.screenshot, workspace_name=args.workspace,
                          collection=args.collection)
    window.show()

    if args.screenshot:
        bus = window.context.bus
        for _ in range(abs(args.segment_step)):
            bus.publish(StepSegment(1 if args.segment_step > 0 else -1))
        if args.time is not None:
            bus.publish(Seek(args.time))
        # Give background work (video decoding) a moment, then render.
        from PySide6.QtCore import QTimer
        def finish():
            window.refresh_now()
            window.grab().save(args.screenshot)
            app.quit()
        QTimer.singleShot(2500, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
