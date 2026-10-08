# Checklists

Things that are easy to forget when changing the app. Where possible a test enforces the item; those are marked.

## Adding or changing a control

- [ ] **Workspace:** decide whether the control's setting belongs in a saved workspace (docs/design.md §28.3).
  If yes, wrap it with `saved_in_workspace(...)` and add it to that bar's `state()` and `apply_state()` in
  `controls.py`, defaulting to how the bar started. If not, wrap it with `not_saved(widget, "why")`.
  *Enforced:* `test_every_input_control_says_whether_a_workspace_saves_it` fails for an unmarked control.
- [ ] **Shortcut:** if it has a keyboard shortcut, add it to the table in `keys.py` (so it can become configurable).
- [ ] **Navigation rules:** if it moves the playhead, make sure it goes through the timeline's constraint, so the
  filter governs it (§10.1). Never set `timeline.time` directly.
- [ ] **Wording:** the core is generic. Names like "Trial" come only from the project's `label`; "frame" is always
  "frame".
- [ ] **Tests:** one that fails without the change (check by temporarily breaking it), and offscreen only.

## Adding a view type

- [ ] Register the entry point in the package's `pyproject.toml` (group `syncviz.views`).
- [ ] Implement `candidates(catalog)` so it appears in **Add view** (§28.2), and `display_name`.
- [ ] Report `extent()` and, if it has real dropouts, `coverage()`, so the timeline strip is honest.
- [ ] If it has a natural grid of ticks, implement `time_base()` so it can define a frame.
- [ ] If it can wait on slow work, implement `stalled_for(now)` (§34.3) and show one calm message over itself.
- [ ] If it has user settings, decide whether they belong in the workspace (as above).

## Adding a source type

- [ ] Entry point in group `syncviz.sources`; implement `describe()` and `catalog()` (so its data can be added from the UI).
- [ ] Nothing source-specific in the core; it hands out generic resources only.

## Before pushing

- [ ] Run the whole suite (`.venv\Scripts\python -m pytest -q`).
- [ ] Update `docs/design.md` for anything that changes behaviour a user or plugin author relies on.
- [ ] Long jobs run as tracked background tasks.
