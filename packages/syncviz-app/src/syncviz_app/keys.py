"""Keyboard shortcuts, all in one place.

Defaults live here so that letting a project or a settings dialog override them later is a
matter of passing a different table; nothing else needs to change. The less common action of
a pair takes Shift.
"""

DEFAULT_KEYS: dict[str, str] = {
    "play_pause": "Space",
    "previous_segment": "Left",
    "next_segment": "Right",
    "step_back": "Shift+Left",
    "step_forward": "Shift+Right",
}
