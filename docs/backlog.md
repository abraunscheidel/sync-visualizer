# Backlog

What is being worked on, what is next, and what has been parked. Update it when work starts, finishes, or is added. Design
reasoning lives in `docs/design.md` (the section numbers below); this file is only the list. Order within a section is the order
planned unless said otherwise.

## In progress

- Nothing. The next item below is first.

## Next, in order

1. **Groups** (28.9). Named, saved filters over items ("layer 4 units"), kept per project; a group is one selectable item with many
   members; rule-based groups work across sessions, explicit lists belong to one recording. "Save as group" from a selection.
2. **Aggregation views** (28.9). A time-aligned profile around events or clips, per group, as the main output (rate of each neuron around
   contact); a per-item table as the secondary one.
3. **Data-health report.** Grow the sync diagnostics into a general report, each warning linking to the region it is about.
4. **The profile layer** (28.9). Separate reading a file format from interpreting an experiment. Must be done before any new source type is
   added (see `docs/checklists.md`). It is also where plugin authoring (below) lives.

## Plugin authoring (28.15)

The aim: someone with a new experiment can get their data in with little work, see quickly whether it worked, and test it.

- **Declare common custom layouts in the project file**, not in code ("this table is events, time column `onset_s`, split by
  `frequency_hz`"). The biggest saving.
- **Load a plugin from a file named in the project** (`plugins: [my_experiment.py]`), with no packaging or install step.
- **`syncviz inspect file.nwb`**: list what is in a file the way the app sees it.
- **`syncviz check project.yaml`**: load everything without a window and report what is wrong.
- **A test kit**: a conformance check any source can be run through, and a helper that writes a tiny fixture file.
- **A short guide** with a worked example (the tone-table example in 28.15).

## Later, ideas, and decisions to revisit

- **Named delays** (28.10): give a view delay a name, attach it to several views, change it in one place.
- **Source time mapping** (28.10): a real clock offset (and drift) on a source, applied everywhere; test it with a copy of a video that has
  a few black frames added at the start. Sync diagnostics could suggest the correction.
- **Delay a processor declares for itself** (28.10): the trailing smoothed rate lags by its smoothing time; the view could compensate.
- **Relative timing conditions**: "unit fired 5 to 50 ms after a contact", not just "in the same segment".
- **Event detectors from signals** (28.13): turn a continuous signal into events ("angle above 20 degrees for 100 ms") so conditions can
  use it.
- **Colour video** (28.13): the video view decodes to brightness only.
- **Units' labels and order are read from `depth` and `layer`** in the NWB reader (28.13): belongs to the profile layer.
- **Manual segments and marks** (28.14): cut a recording by hand, mark moments; stored with the per-recording state.
- **Drag-rectangle selection** (28.11), for large grids of tiles.
- **Hover and selection on the video overlays** (28.7), and **on processed series** such as the population rate (needs its own design:
  they have no source reference).
- **Windows whose size depends on the event** (28.9), for example the length of the contact.
- **Attribute filters as chips** with Clear all and Back, so every restriction is one list (28.9).
- **Test speed** (28.7 end): the suite takes about 2.5 to 3 minutes; try one window per module and splitting pure logic from window tests.
- **Hover figures per kind of item**, chosen once for all units, say, rather than per item (28.7).

## Done recently

- Chips: Update | Revert (28.11).
- The event tracker view; the video's corner badges removed (28.11, end of 28.15's neighbour notes).
- docs/backlog.md itself.
- Multi-selection: Ctrl and Shift click, commands on several events, the Details table (28.11).
- Clips are part of the event filter; chips switch on and off; no windows dropdown (28.12).
- Clicks on a filtered-out region snap to the closest included point (28.12 end).
- The dark-frame rule is a setting; a project with no segmentation is one whole-recording segment (28.13).
- Event conditions and the Events panel; clip windows with anchors; epochs and measures; inspection (hover, selection, Details, commands);
  dates; the loading screen; collections, workspaces, delays, diagnostics, overlays.
