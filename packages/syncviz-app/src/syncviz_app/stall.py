"""Waiting for slow views instead of playing past them.

Playback never waits for the picture while frames keep arriving, however late. But when a view
makes no progress at all for a while (a long seek into a distant part of a large file, a slow
disk, a network source later on), the clock would run ahead and the view would show
nothing useful. The guard then holds the playhead, with a visible "Buffering" state, and lets
go once every view has caught up.

Only playback is ever held. Scrubbing and stepping are paused interactions where the user is
already waiting on the view, which shows its own loading cue.
"""

from __future__ import annotations

from typing import Sequence

HOLD_AFTER_S = 0.4          # no progress for this long, while playing, counts as a real stall


class StallGuard:
    def __init__(self, timeline, views: Sequence, hold_after: float = HOLD_AFTER_S) -> None:
        self.timeline = timeline
        self.views = views if isinstance(views, list) else list(views)     # shared: views come and go
        self.hold_after = hold_after

    def check(self, now: float) -> None:
        tl = self.timeline
        waiting = [v for v in self.views if v.isVisible() and v.stalled_for(now) > 0.0]
        if not tl.playing:
            tl.hold(None)
        elif tl.holding is None:
            slow = [v.title for v in waiting if v.stalled_for(now) >= self.hold_after]
            if slow:
                tl.hold(", ".join(slow))
        elif not waiting:                  # everything has caught up: carry on
            tl.hold(None)
