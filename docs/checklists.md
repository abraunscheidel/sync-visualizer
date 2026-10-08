# Checklists

Things that are easy to forget when changing the app. Where possible a test enforces the item; those are marked.

## Adding or changing a control

- [ ] **Workspace:** decide whether the control's setting belongs in a saved workspace (docs/design.md §28.3).
  If yes, wrap it with `saved_in_workspace(...)` and add it to that bar's `state()` and `apply_state()` in
  `controls.py`, defaulting to how the bar started. If not, wrap it with `not_saved(widget, "why")`.
  *Enforced:* `test_every_input_control_says_whether_a_workspace_saves_it` fails for an unmarked control.
- [ ] **Tooltip:** a field or item the user can see by name should explain itself: `context.explain(name, description_from_the_data)`;
  the project's notes on how to read it go in its `glossary:`, not in the application.
- [ ] **Shortcut:** if it has a keyboard shortcut, add it to the table in `keys.py` (so it can become configurable).
- [ ] **Navigation rules:** if it moves the playhead, make sure it goes through the timeline's constraint, so the
  filter governs it (§10.1). Never set `timeline.time` directly.
- [ ] **Wording:** the core is generic. Names like "Trial" come only from the project's `label`; "frame" is always
  "frame".
- [ ] **Tests:** one that fails without the change (check by temporarily breaking it), and offscreen only.

## Adding a view type

- [ ] Register the entry point in the package's `pyproject.toml` (group `syncviz.views`).
- [ ] A view must draw the time it is given and nothing else (the scheduler passes `playhead - lag`, §28.5); never read
  the timeline's own time inside a view, and convert any time a click produces back with `+ self.lag`.
- [ ] Implement `candidates(catalog)` so it appears in **Add view** (§28.2), and `display_name`.
- [ ] Report `extent()` and, if it has real dropouts, `coverage()`, so the timeline strip is honest.
- [ ] If it has a natural grid of ticks, implement `time_base()` so it can define a frame.
- [ ] If it can wait on slow work, implement `stalled_for(now)` (§34.3) and show one calm message over itself.
- [ ] If it has user settings, decide whether they belong in the workspace (as above).

## Anything that holds state about the open recording

- [ ] State that belongs to one collection (playhead, notes, manual alignment) goes in the per-collection state, not the
  workspace (§28.4). State that is how the window looks goes in the workspace (§28.3).
- [ ] A view must survive its data being absent in a collection: raise `MissingDataError` and the panel shows "No data".

## Adding a processor

- [ ] Say in its documentation which direction in time it can leak information, and default to the choice that cannot
  suggest an effect before its cause (see the population rate, section 20.1).
- [ ] Implement `candidates(catalog)` so it appears in **Add view**; keep its parameters in the series spec.
- [ ] Test what it conserves (for example the total number of events) and that it cannot create what is not in the data.

## Adding a sync check

- [ ] Put what is generic in `syncviz.diagnostics` and what depends on a source in that source's plugin (events it provides,
  or `Source.diagnostics()`); the core must not learn about any dataset.
- [ ] Say what a pass means and does not mean (consistent with, not proof). If the result could be circular (a reference
  derived from the thing tested), say so in the check's `note`.
- [ ] A recording that lacks the data gives *not applicable*, a measurement that cannot judge gives *inconclusive*; only real
  disagreement is *fail*. Test each, and test that a deliberately broken clock fails.

## Adding a source type

- [ ] Entry point in group `syncviz.sources`; implement `describe()` and `catalog()` (so its data can be added from the UI).
- [ ] Nothing source-specific in the core; it hands out generic resources only.
- [ ] If it has checks about itself, return them from `diagnostics()` (see "Adding a sync check").
- [ ] Anything that can be large (continuous signals) comes back as a `LazyTimeSeries` over the file, never loaded whole (§34.5); implement `close()` if the source keeps a file open.

## Before pushing

- [ ] Run the whole suite (`.venv\Scripts\python -m pytest -q`).
- [ ] Update `docs/design.md` for anything that changes behaviour a user or plugin author relies on.
- [ ] Long jobs run as tracked background tasks.
