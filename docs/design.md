# Sync Visualizer — Design Document

## 1. Overview

Sync Visualizer is a general-purpose desktop application for exploring synchronized scientific data from multiple temporal sources.

The core problem is:

> Given multiple data sources with different formats, sampling rates, and clocks, provide a unified timeline through which a researcher can interactively explore the relationships between those sources.

The initial application will demonstrate this using a neuroscience dataset containing:

- high-speed whisker video
- extracellular neural recordings
- behavioral events
- trial structure
- synchronization pulses

The architecture should remain general enough to support other scientific datasets and modalities.

The mouse neuroscience application is therefore a configuration of the framework, not the framework itself.

---

## 2. Design Goals

### Primary goals

- Synchronize multiple temporal data sources.
- Allow interactive exploration of synchronized data.
- Keep data access lazy and efficient.
- Separate data formats from generic representations.
- Support derived data and computational processing.
- Allow users to select and organize subsets of multidimensional datasets.
- Make synchronization and data transformations inspectable.
- Support cross-view interaction.
- Keep project configuration separate from implementation.
- Make the architecture reusable across scientific domains.

### Secondary goals

- Support expensive computations without blocking the UI.
- Cache derived and frequently accessed data.
- Make scientific assumptions visible.
- Preserve provenance where practical.
- Allow new data formats and processors to be added without changing the core application.

---

## 3. Non-Goals

The first version is not intended to:

- provide a complete neuroscience analysis environment
- implement every possible synchronization algorithm
- implement its own spike-sorting system
- provide sophisticated pose estimation
- replace specialized scientific packages
- provide a polished end-user product
- support every possible scientific file format
- solve general-purpose workflow management
- build a complete reproducible research platform

The architecture should leave room for these capabilities without requiring them initially.

---

## 4. High-Level Architecture

The system is organized around several major layers:

```text
Project / Container
        │
        ├── Sources
        │
        ├── Synchronization Definitions
        │
        ├── Groupings / Dimensions
        │
        └── Configuration
                │
                ▼
            Resources
                │
        ┌───────┴────────┐
        │                │
 Transformations     Processors
        │                │
        └───────┬────────┘
                ▼
        Derived Resources
                │
                ▼
       Resource Requests /
        User Selections
                │
                ▼
            Data Views
                │
                ▼
        Visualizations
                │
                ▼
       Semantic Actions
                │
                ▼
      Application / Project
```

The central architectural principle is:

> Sources are format/domain-specific. Resources and transformations are generic. Visualizations consume generic resources. Processors provide configurable computation.

---

## 5. Container / Project

A project represents a scientific dataset or experiment as configured for exploration.

The project contains:

- source definitions
- resource definitions
- synchronization definitions
- grouping/dimension definitions
- processor configurations
- visualization configuration
- user annotations
- application state where appropriate

The project should be primarily configuration-driven.

It should not contain implementation details specific to a particular scientific dataset wherever those details can instead be expressed through generic configuration.

Example:

```yaml
sources:
  neural:
    type: nwb
    path: ...

  video:
    type: nwb
    path: ...

synchronization:
  neural_video:
    sources:
      - neural
      - video
    method:
      type: synchronization_pulses
      reference: neural.sync_pulses
      target: video.sync_pulses
```

The exact configuration syntax is intentionally not fixed yet.

---

## 6. Data Sources

A Source represents where data comes from and how the application accesses the underlying data.

Examples:

- NWB files
- video files
- CSV files
- HDF5 files
- databases
- remote scientific data repositories

Sources are responsible for format-specific access.

They should not define the generic meaning of the data they expose.

For example:

```text
NWB Source
    ↓
TimeSeries
```

rather than:

```text
NWBTimeSeries
```

The resulting resource should be usable regardless of whether its underlying data came from NWB, CSV, HDF5, or another format.

---

## 7. Generic Resources

A Resource represents a generic scientific data structure that can be consumed by the rest of the application.

Examples:

- `TimeSeries`
- `Video`
- `SpikeTrain`
- `EventSeries`
- `Pose`
- spatial data
- tabular data
- images

Resources should not contain source-specific implementation details.

For example, a `TimeSeries` might represent:

```text
timestamps
values
units
metadata
```

regardless of whether those values came from NWB or another source.

---

## 8. Resource Manager

The Resource Manager is responsible for managing access to resources.

Responsibilities include:

- lazy loading
- caching
- sharing
- deduplication
- lifetime management
- asynchronous/background loading
- memory management
- eviction
- resolving resource requests

The Resource Manager should allow the application to describe a potentially expensive request without forcing the UI to know how the data is physically retrieved.

---

## 9. Resource Requests

A resource request describes what data is needed without necessarily requiring the entire resource to be loaded.

For example:

```text
Neural recording
where mouse = A
and trial = 17
from shared time 10–15 seconds
```

The Resource Manager determines how to fulfill that request.

This distinction is important because the underlying dataset may be enormous.

A request can therefore result in:

- a direct slice
- a filtered view
- a cached subset
- a transformed resource
- a lazily evaluated representation

---

## 10. Groupings and Dimensions

Datasets often contain multiple independent ways of subdividing their data.

Examples:

- mouse
- session
- trial
- channel
- condition
- stimulus
- experimental group
- recording site

A Grouping/Dimension describes one such way of partitioning or categorizing data.

A grouping should describe the dimension itself rather than permanently defining every possible value.

For example:

```yaml
groupings:
  - mouse
  - session
  - trial
  - condition
```

The actual values can be discovered from the loaded dataset:

```text
mouse
  A
  B

condition
  concave
  convex

trial
  1
  2
  ...
```

This allows the same project configuration to work with datasets containing different numbers of mice, sessions, trials, etc.

Groupings may be:

- explicitly configured
- inferred from metadata
- derived from dataset structure
- defined through events or intervals

A trial is therefore not a special core concept. It is one possible grouping.

### 10.1 Intervals and segments

The core vocabulary for this is generic:

- An **`IntervalSeries`** is a resource: ordered time intervals, each with named
  attribute columns (for a trial table: stimulus, outcome, choice, and so on). It
  is the interval counterpart of `EventSeries`, and detected contacts or stimulus
  periods are the same type.
- A **segmentation** is a configured use of an interval series for navigation:
  stepping through its intervals one at a time, optionally filtered by attribute
  values. The core calls these **segments**.
- The word shown to the user ("Trial", "Epoch", "Bout", "Stimulus period") is a
  `label` in the project configuration. Core code and core tests never use it.
- Attribute columns are the dimensions a user can filter by. Which ones are
  offered is configured, not hardcoded.

```yaml
segmentations:
  trials:
    label: Trial
    from: session:intervals/trials
    number_attribute: trial
    filters: [stimulus, outcome]
```

Navigation is performed through actions (`SelectSegment`, `StepSegment`), which
move the shared timeline's playhead and selection, so views stay in step without
knowing about segments.

The navigator also follows the playhead:

- The current segment (and the timeline's selection) tracks the playhead as it moves
  into other matching segments, whether by playback or by the user seeking.
- **The filter says which segments match; a switch decides whether movement is restricted
  to them.** Restricted (the default), *every* way of moving the playhead stays inside the
  matching segments: previous/next, playback, stepping by frame, clicking or dragging on the
  timeline, clicking in a plot.
  *Pointer gestures aimed at a disabled region are ignored.* Hidden segments keep their place
  on the strip (so the sense of when things happened is preserved) but are hatched, the
  cursor changes to a "not allowed" symbol over them, and a drag across one leaves the
  playhead where it was until the pointer reaches a match again. No tooltip is needed.
  *Movement with no pointer position* (previous/next, stepping, playback) instead goes to the
  nearest allowed time: the start of the next matching segment when going forward, the end of
  the previous one when going backward, and the end of the last match when nothing matching
  lies ahead (playback then pauses).
  Unrestricted, none of them is, and the filter only marks which segments match: the
  timeline highlights them, the count shows how many, and a current segment that does not
  match is labelled "not in filter". Without a filter nothing is restricted.
- This is enforced in the timeline, not in each navigation command: the navigator installs
  itself as the timeline's *constraint*, and every move goes through it, so a new way of
  navigating cannot bypass the filter. Turning the restriction on while sitting on a
  non-matching segment moves to the next match. A toolbar checkbox (or `skip_filtered: false`
  in the project) turns the restriction off.

---

## 11. Selections and Data Views

Groupings describe how data can be subdivided.

A Selection describes what the user currently wants to examine.

For example:

```text
mouse = A
condition = convex
trial = 17
```

A selection can then produce a Data View or specialized Resource Request.

Conceptually:

```text
Underlying Resources
        │
        ▼
Available Dimensions
        │
        ▼
User Selection
        │
        ▼
Data View / Resource Request
        │
        ▼
Visualization
```

The underlying resource does not necessarily need to be physically split.

For example, if two mice are interleaved in one neural recording:

| time  | mouse | channel | voltage |
| ----- | ----- | ------- | ------- |
| 0.001 | A     | 1       | ...     |
| 0.001 | B     | 1       | ...     |
| 0.002 | A     | 1       | ...     |
| 0.002 | B     | 1       | ...     |

the application can request:

```text
mouse = A
```

and obtain a logical stream from the same underlying resource.

---

## 12. User-Controlled Data Organization

Selections should eventually control not only which data are displayed, but how the data are organized in the visualization.

For example:

```text
Mouse: [A]
```

could show one stream.

A future interface could instead support:

```text
Mouse: [Split]
```

resulting in:

```text
Mouse A
──────────────

Mouse B
──────────────
```

or:

```text
Mouse: [Combined]
```

resulting in multiple traces within one visualization.

Similarly, trials could eventually be:

- selected individually
- split into separate views
- combined
- filtered
- aligned around an event

This is a future visualization capability rather than a requirement for the first implementation.

---

## 13. Processors

A Processor is a configurable computational component that consumes resources and produces resources.

Example:

```text
Video Resource
      │
      ▼
Pose Estimator
      │
      ▼
Pose Resource
```

Other examples:

```text
Raw Neural Signal
      │
      ▼
Spike Detector
      │
      ▼
Spike Train
```

or:

```text
Video
  ↓
Object Detector
  ↓
Object Tracks
```

Processors are distinguished from simple transformations primarily by their nature:

- potentially expensive
- configurable
- model-based
- external-tool-based
- algorithmically complex
- potentially stateful or asynchronous

For example, SLEAP may be an implementation detail behind a generic `PoseEstimatorProcessor`.

---

## 14. Transformations and Derived Resources

A Transformation performs a generic operation on one or more resources.

Examples:

- aggregation
- downsampling
- filtering
- resampling
- normalization
- averaging
- windowing

A transformation produces a derived resource.

For example:

```text
Spike Train
    ↓
Firing Rate Transformation
    ↓
TimeSeries
```

The distinction between Processors and Transformations should remain practical rather than overly rigid. They can share execution infrastructure.

The important architectural distinction is:

> A transformation is primarily a generic data operation; a processor is a configurable computational component.

---

## 15. Resource Graph

Resources form a computational/data dependency graph:

```text
Source
  │
  ▼
Generic Resources
  │
  ├───────────────┐
  │               │
  ▼               ▼
Transformations  Processors
  │               │
  ▼               ▼
Derived Resources
  │
  ▼
Visualizations
```

This graph allows the application to build increasingly sophisticated analyses without coupling visualizations directly to raw source formats.

---

## 16. Events

An Event represents something occurring at a particular time or interval.

Examples:

- trial start
- trial end
- lick
- reward
- stimulus onset
- synchronization pulse
- detected contact

Events may come from the source dataset or be generated by the user/application.

Source events should remain immutable.

User-created annotations should be stored separately from source data.

For example:

```text
Source Event:
    lick at 12.43 s

User Annotation:
    "Interesting neural response"
    12.40–12.80 s
```

Events can also be used to define groupings or intervals.

For example:

```text
trial-start ───────────── trial-end
          ← Trial 17 →
```

---

## 17. Synchronization

Synchronization is responsible for relating independent temporal sources to a shared timeline.

The Synchronization Engine should not itself decide how synchronization is performed.

Instead, the project configuration declares:

- which sources are related
- which synchronization method should be used
- which synchronization data should be used

The synchronization method produces a `TimeMapping`.

Conceptually:

```text
Project
   │
   ▼
Synchronization Definition
   │
   ▼
Synchronization Method
   │
   ▼
Time Mapping
   │
   ▼
Shared Timeline
```

---

## 18. Synchronization Methods

A Synchronization Method is analogous to a Processor, except its output is temporal rather than scientific data:

```text
Temporal Data
      │
      ▼
Synchronization Method
      │
      ▼
Time Mapping
```

The first implementation will support synchronization pulses.

Example:

```yaml
synchronization:
  neural_video:
    sources:
      - neural
      - video

    method:
      type: synchronization_pulses
      reference: neural.sync_pulses
      target: video.sync_pulses
```

The exact configuration syntax is not fixed.

The important abstraction is that the project declares:

> These temporal sources are related using this method and these data.

### Initial method: synchronization pulses

Corresponding pulses are identified in the two sources.

The method estimates a mapping such as:

```text
t_neural = a + b * t_video
```

The mapping may initially be treated as linear.

### Future methods

The architecture should eventually support:

- shared clock
- known corresponding events
- event matching
- cross-correlation
- manual alignment points
- periodic reference signals
- piecewise mappings
- nonlinear mappings where scientifically appropriate

All of these ultimately produce a `TimeMapping`.

### 18.1 Sync signals declared on a source

Some sources carry a synchronization signal that is not stored as data. A video
may contain blackout frames or a flashing LED; the pulse times exist only in the
pixels. The project configuration therefore lets the user **declare** a sync
signal on a source, and the system obtains the pulse times by one of several
paths. Users should only pay the cost of detection when nothing cheaper exists.

Paths, from cheapest to most expensive:

1. **Known times.** The pulse times already exist in the dataset or in a file the
   user points to (an NWB table, a CSV). No decoding is needed.
2. **Predicted windows.** If the other side's pulse times are known, the expected
   times in this source can be predicted approximately, and only short windows
   around them are decoded and refined.
3. **Detection over the whole source.** A detector plugin scans the source
   (for example `dark_frames`, or an LED within a declared region of the frame).

Sketch (syntax not fixed):

```yaml
sources:
  video:
    type: video
    path: ...
    sync_signal:
      kind: dark_frames        # a detector plugin; others: led_region, audio_beep, ...
      threshold: auto          # or an explicit cutoff
      # alternatives that skip detection:
      # pulse_times: pulses.csv
```

Design consequences:

- Detectors are plugins, registered like sources and sync methods. The core does
  not know what a "blackout" is.
- A detector is a Processor (§13). It takes a video and produces an event series
  in the video's native time. A synchronization method (§18) then consumes it.
- Detection results are cached against the source file, the detector and its
  parameters, so a given video is analyzed at most once per configuration.
  Detection runs in the background with progress shown.
- Detection must be inspectable (§32): show the brightness (or equivalent) trace,
  the threshold, and the detected pulses, and allow the threshold to be adjusted.
- The user interface edits this configuration. The configuration remains the
  single source of truth.
- Expected structure (for example "about one pulse per trial") is validation,
  not an assumption. Disagreements are reported, not silently corrected.

#### Worked example: DANDI 000231 (sub-219CR, session 2019-04-04)

Measured on the full video by decoding every frame and recording mean brightness.
Measured on the full video by decoding every frame and recording mean brightness.
Both sessions of this mouse were scanned and agree.

- The video frame count equals the span of the NWB tracking frame grid exactly
  (session 2019-04-04: 391,200 frames; session 2019-04-03: 419,400 frames; both at
  200 Hz). The video container's own timing is unusable (it reports 30 fps and a
  duration of 13,040 s), so frames must be addressed by index, not container time.
- Brightness is clearly bimodal. Dark runs are all 27 or 28 frames long (about
  135 ms): 230 runs in session 2019-04-04 and 252 in session 2019-04-03.
- Every dark frame lies inside a gap in the NWB whisker tracking (all but one
  frame of 6,823 in 2019-04-03), consistent with tracking being unable to run on
  black frames. Not every tracking gap is dark: a few percent of missing frames
  are short gaps (around 5 frames) of another cause.
- Almost every dark run begins within 2 frames of a trial start (98% exactly on
  it), and every trial has one. The few runs that are not at a trial start sit
  exactly at a trial **stop** where the next trial does not follow immediately:
  the end of the final trial in both sessions, and one stop followed by a 7 s gap
  at 1614.0 s in session 2019-04-04. So the blackout marks trial boundaries.

This is consistent with the blackout being a trial-boundary marker, and with the
NWB trial times and the video sharing one clock. It is not independent proof of
alignment: if the dataset authors derived the trial times from these same
blackouts, agreement shows the correction was applied, not that it was correct.
Also, here the blackout coincides with trial boundaries rather than carrying
extra timing information; a dataset with a separate neural recording would
supply a second pulse train to match against.

---

## 19. Time Mapping

A `TimeMapping` describes how timestamps in one temporal coordinate system correspond to timestamps in another.

For example:

```text
video time → shared time
neural time → shared time
```

The initial implementation can use simple linear mappings.

The abstraction should not permanently assume that all synchronization is linear.

Future mappings could be:

- linear
- piecewise linear
- nonlinear
- bidirectional
- time-varying

---

## 20. Synchronization Engine

The Synchronization Engine manages synchronization definitions and resulting time mappings.

Responsibilities:

- resolve synchronization methods
- execute synchronization
- store/expose resulting mappings
- convert timestamps between sources
- provide shared-time coordinates
- support synchronized seeking

The engine should not contain every synchronization algorithm itself.

Instead:

```text
Synchronization Engine
        │
   ┌────┴─────┐
   │          │
 Methods   Time Mappings
   │
 ┌─┼──────────────┐
 │ │              │
Pulse Event   Correlation
```

---

## 21. Shared Timeline

The application exposes a shared timeline to visualizations and interaction systems.

Every time-dependent resource retains its native timestamps.

The application should never assume that timestamps from independent sources are directly comparable.

Instead:

```text
Native source time
        ↓
Time Mapping
        ↓
Shared time
```

All synchronized visualizations operate through shared time.

---

## 22. Visualization and Interaction Architecture

Visualizations consume generic resources or data views.

Examples:

- video view
- time-series view
- raster view
- timeline view
- spatial view

Visualizations may define supported interactions, but resources themselves should not own Qt/UI callbacks.

The visualization translates a user gesture into a semantic application action.

---

## 23. Semantic Interaction / Application Actions

Examples:

```text
Seek(time)
SelectTimeRange(start, end)
SelectResource(resource)
Inspect(resource)
Highlight(resource)
CreateEvent(...)
Annotate(...)
Filter(...)
RequestTransformation(...)
```

For example:

```text
TimeSeries click
        │
        ▼
    Seek(12.43s)
```

or:

```text
TimeSeries drag
        │
        ▼
SelectInterval(10s, 15s)
```

This keeps UI implementation separate from application semantics.

### 23.1 Stepping and keyboard shortcuts

Two different kinds of "step" exist, and neither is special to any one experiment:

- **Segment navigation** moves between segments (trials, epochs, ...). Left and Right
  arrow.
- **Time stepping** moves the playhead by one *tick* of a time base. Shift+Left and
  Shift+Right, or the Step buttons. The less common action of a pair takes Shift.

**What a tick is is chosen by the user, not assumed.** Any view with a natural grid of
times can offer it: a video its frames, a signal its samples. The interface always calls
this unit a **frame**, and a "defined by" selector next to it lists every view that offers
a grid, plus a fixed interval. The first one is only the starting choice; a project can name another (`step: {view: ...}` or
`step: {interval_ms: ...}`). A step goes to the next tick of the chosen grid, not a fixed
distance, so from between frames it snaps to the next frame, and for irregular data it
follows the real sample times. The count box ("10 frames") repeats the step that many
times. Stepping pauses playback.

The choice matters: starting just before a tracking dropout, stepping by the video
advances frame by frame, while stepping by the tracked whisker signal jumps across the
dropout to its next sample.

**Shortcuts are defined in one table** (`keys.py`) so that configurable shortcuts, in a
project file or a settings dialog, can be added later by passing a different table.
Shortcuts are shown in the tooltips of the buttons they trigger. Spin boxes in the
toolbar give up keyboard focus when editing finishes, because a focused text field
would otherwise swallow the arrow keys.

---

## 24. Cross-View Interaction

Views should communicate through shared application actions rather than directly controlling each other.

For example:

```text
Video click ───────────┐
TimeSeries click ──────┼──→ Seek(12.43s)
Event click ───────────┘
```

Similarly:

```text
TimeSeries drag ───────┐
Video selection ───────┼──→ SelectInterval(10–15s)
Timeline selection ────┘
```

This allows new visualizations to participate in the interaction system without knowing about each other.

---

## 25. Visualization Configuration

The project should define which visualizations are available and how they are initially arranged.

However, visualizations should consume generic resources rather than directly accessing source-specific data.

Example:

```text
VideoView
    ← Video Data View

RasterView
    ← SpikeTrain Data View

TimelineView
    ← Events
```

---

## 26. Mouse Neuroscience Application

The first demonstration application uses a public mouse object-recognition neuroscience dataset.

The experiment combines:

- whisker video
- extracellular neural recordings
- behavioral events
- trial structure
- synchronization pulses

The scientific conceptual chain is:

```text
Object
   ↓
Whisker movements / contact
   ↓
Sensory signals
   ↓
Neural activity
   ↓
Decision
   ↓
Lick
```

The application is not intended to claim that the mouse consciously constructs a human-like mental model. The measurable questions concern relationships between physical interaction, neural activity, and behavior.

---

## 27. Initial Mouse Data Architecture

The first implementation should focus on one representative session.

Conceptually:

```text
NWB Dataset
     │
     ├── Video Resource
     │
     ├── Neural Resource
     │
     ├── Behavioral Events
     │
     ├── Trial Grouping
     │
     └── Synchronization Pulses
```

The application should not initially attempt to load the entire dataset.

---

## 28. Initial UI

The first UI should intentionally be minimal.

Conceptually:

```text
┌──────────────────────────────────────────────┐
│ Dataset / Session                            │
│ Mouse: [A ▼]       Trial: [17 ▼]             │
├──────────────────────┬───────────────────────┤
│                      │                       │
│       VIDEO          │       RASTER          │
│                      │                       │
│                      │                       │
├──────────────────────┴───────────────────────┤
│                  TIMELINE                     │
│       |-------------●----------------|        │
└──────────────────────────────────────────────┘
```

The initial goal is functionality rather than visual polish.

### 28.1 Structure of the window

The sketch above is the mouse project's layout, not the framework's. The window has
two kinds of parts:

- **Always present:** playback controls, segment navigation with its filters, the
  project information panel, and the timeline strip.
- **Views:** every other panel. Which views exist, and how many, comes from the
  project configuration and the installed view plugins. Video is one view type like
  any other, provided by the video package, not the shell.

**Filters.** Each filter shows how many segments each option would leave given the
other filters' choices, and options that would leave none are disabled, so an empty
result cannot be reached. A label shows "N of M match". Changing a filter applies
immediately; if it hides the current segment the navigator moves to the next match after
the playhead, and leaves the playhead alone when the current segment still matches. A
checkbox, always available, decides whether movement is restricted to the matches (see
section 10.1); the timeline strip highlights matching segments, and while movement is
restricted hatches the rest as disabled (they stay in place, so time on the strip stays
proportional to time in the session).

**Controls.** The top row holds playback and two clearly separate ways of moving, each with
its own caption: **Segment** (previous and next, such as trials) and **Frame** (step by a
chosen number of frames, with a selector for what defines a frame). The second row holds
the filters. Section headings are generic; the names of the items (such as "Trial 46",
"118 of 228 trials match") come from the project configuration (`label`, and `label_plural`
where adding an "s" is wrong).

**Timeline strip.** The grey bar is the shared timeline: its bands are segments, the
amber band the current one, the blue band the selection. Beneath it, "Data coverage"
has one line per view, drawn only where that view has data, so a gap in a source is
a break in its line. Each view has a fixed colour, shown as a stripe on its panel title
and on its line; hovering a line names the view, its extent, how many gaps it has and
whether it has data at the pointer. Gaps narrower than a pixel are closed up when
drawing; they are still counted in the tooltip and the project panel. The timeline
spans the union of all views' extents, and no source defines its start.

---

## 29. Initial Neural Visualization

The first neural visualization should use a spike raster where available.

A raster preserves individual spike timing:

```text
Neuron 1   |  |   |     ||   |
Neuron 2   |    ||      |      |
Neuron 3   ||     |  |      ||
           ─────────────────────
                    time →
```

A firing-rate heatmap or probe-depth visualization can be added later when a scientific question benefits from it.

---

## 30. Initial Video Visualization

The initial video view should:

- display the whisker video
- respond to shared-time seeking
- display the current synchronized time
- support play/pause
- support scrubbing

Later it can support:

- whisker tracking overlays
- object overlays
- contact markers
- pose visualization

---

## 31. Trial / Group Navigation

The initial UI should provide navigation through the discovered grouping structure.

For example:

```text
Mouse: [A]
Trial: [17]

        ← Previous    Next →
```

The application should not hardcode "trial" into the architecture.

Trial navigation is an application of the general grouping/selection system.

Future interfaces can allow dimensions to be:

- filtered
- selected
- split into views
- combined
- aligned
- compared

---

## 32. Synchronization Diagnostics

Synchronization should be inspectable.

The application should eventually provide a way to inspect corresponding synchronization events and the resulting mapping.

For example:

```text
Neural pulse:  12,345.678 s
Video pulse:       61.234 s
                     │
                     ▼
               Time Mapping
                     │
                     ▼
Shared time:     12,345.678 s
```

This is particularly important because synchronization errors can create false scientific relationships.

---

## 33. Clip / Interval Retrieval

The core system should support requesting small temporal intervals from larger resources.

For example:

```text
shared time: 10.0–15.0 s
```

could request:

```text
Video:
    corresponding video frames

Neural:
    corresponding neural samples/spikes

Events:
    events in the interval
```

This should be handled through resource requests rather than requiring visualizations to understand source-specific indexing.

---

## 34. Performance

The application should be designed around the assumption that scientific datasets can be much larger than memory.

Important principles:

- lazy loading
- interval-based requests
- caching
- asynchronous computation
- background processing
- downsampling where appropriate
- avoiding repeated scans of large recordings
- keeping the UI thread responsive

For example, a neural recording sampled at 30 kHz across 64 channels represents approximately 1.92 million voltage samples per second.

Interactive controls should therefore not repeatedly process the entire recording.

### 34.1 Video access

Videos are multi-GB and are never loaded whole. Decoded frames for the whole
session would be orders of magnitude larger than memory (about 137 GB for
391,200 grayscale frames at 640x550).

- **Frames are identified by index, not by container time.** Some scientific
  videos carry meaningless timestamps (DANDI 000231 stores 200 fps video with
  30 fps-style timestamps and a container duration of 13,040 s). The frame rate
  comes from configuration or dataset metadata.
- **Frame index.** Built once from packet headers without decoding, then cached.
  It records each frame's presentation order and which frames are keyframes.
- **Random access.** To reach frame N, seek to the latest keyframe at or before N
  and decode forward. Only that group of pictures is read from disk.
- **Bounded memory.** Callers receive only the frames they ask for. A
  byte-bounded cache (default 400 MB, least recently used out first) keeps every frame
  decoded on the way to the one requested, so stepping back over frames just played
  costs nothing. The frame asked for is always returned, whatever the budget.
  Background prefetch is not built.
- **Latest request wins, but never discard a finished frame.** A view asks for the
  frame under the playhead; the decoder always works on the most recent request and
  skips older ones. A frame that finishes after the playhead has moved on must still
  be shown. Dropping such "stale" frames froze the picture whenever decoding took
  longer than the interval between redraws, which is true of any real video. A test
  with deliberately slow decoding guards against this.
- **Short forward jumps continue the running decode** and skip the frames in
  between, instead of re-seeking, when that is cheaper (during playback the playhead
  moves several frames per redraw).
- **Interface.** A `Video` resource exposes frame count, rate and frame reads.
  Views never see the container, the codec, or where the bytes live.

Measured on DANDI 000231 (sub-219CR, 2019-04-04, 2.7 GB MKV, h264 with B-frames),
while another full-video decode was running on the same machine:

| Measurement | Result |
| --- | --- |
| Frame index build | 5.6 s, 391,200 frames (matches the full decode exactly) |
| Keyframe spacing | mean 179 frames, median 187, max 250 |
| Random access to one frame | median 68 ms, p95 124 ms, max 128 ms |
| Sequential decode, converting each frame to gray | about 172-212 frames/s |
| Sequential decode, reading the luma plane directly | about 1,450-1,580 frames/s |
| Raw decode only (8 cores) | about 1,600-2,000 frames/s |
| Conversion to RGB (what a display needs) | about 380 frames/s |
| Step backward one frame, no cache | median 85 ms, p95 130 ms |
| Step backward one frame, with cache | 0 ms (cache hit) |
| Jump to a random far frame | median 38-49 ms, p95 76-101 ms |
| Video frames shown in the window during 1x playback | about 48 per second (display refresh limits this to 60 at most) |
| Content check | frame N read by seek matches frame N from the full decode, on 48 frames including blackout boundaries |

Raw decoding is not the bottleneck. The per-frame format conversion was: it ran
about 9x slower than decoding because it is a single-threaded step on every
frame. For 8-bit YUV video the first plane already is the grayscale image, so the
reader and the brightness scan use it directly. A full-session brightness scan
dropped from about 23 minutes to about 4, with identical results (230 blackouts
starting on the same frames). All timings were measured while another decode was
running, so an idle machine should do better.

**Pixel values.** The luma plane keeps the encoded values. For this video black is
16.0 and normal frames are about 129 (video range, black near 16 and white near
235), not 0-255. Formats whose first plane is not 8-bit brightness (RGB or planar
RGB, 10/12/16-bit YUV) fall back to a conversion that returns full range. The two
paths are therefore not numerically comparable, and `has_native_luma` reports
which one applies. Planned: rescale native luma to full range with a lookup table
so all frames mean the same thing across videos; and request real color channels
explicitly where they matter (a colored sync LED, display).

**Proxy video (optional, off by default).** Not needed for this recording. If added:
- Two kinds solve different problems. A same-resolution all-keyframe proxy fixes
  slow seeking without losing image quality, at a large disk cost. A
  lower-resolution proxy fixes slow decoding and playback, at a cost in quality.
- A proxy is for navigation only: scrubbing and playing use it, and a resting
  playhead shows the original frame at full resolution. Whisker-scale detail is
  lost by downscaling, so quality-critical videos should not default to one.
- Analyses (detection, tracking, pose estimation) never read a proxy.
- Whether a proxy is worthwhile is decided by measurement: time a short decode on
  import and compare it with the video's frame rate.

**Remote video (future).** Not needed yet, but the design should not rule it out:

- Local files are one implementation of a byte-access interface. A remote
  implementation would use HTTP range requests with an on-disk block cache.
- The frame index is the difficulty. In MKV, packet headers are interleaved with
  the data, so building the index over a network can mean reading the whole file.
  MP4 stores a complete frame table in one small block and does not have this
  problem.
- Options when remote support is added: a one-time MP4 proxy with the table at
  the start, or a precomputed index published beside the video.
- To keep this open, the frame index and the frame reader must not assume that a
  local file path exists beyond the point where they are opened.

### 34.2 Keeping the interface responsive during playback

Redrawing every view on every playhead change used the main thread almost
completely during playback (about 15 ms of each 16.7 ms frame in measurement:
scrolling plots cost 5-7 ms each to scroll and repaint), so clicks, such as on the
filters, waited behind drawing and felt laggy. The remedies, in order of effect:

- **Per-view redraw rates.** A scrolling plot looks the same at 30 redraws per
  second as at 60; the video gets the full display rate. A project may override
  `refresh_hz` per view.
- **An adaptive governor.** The scheduler measures how late its own timer fires.
  When the interface is falling behind it lowers every view's rate, and raises
  them again when there is headroom. Cost depends on pixel count (display scaling,
  large monitors), so a fixed limit tuned on one machine would be wrong on another.
- **Throttled secondary updates.** The time label and the timeline strip update at
  a lower rate while playing; user input (dragging the strip, seeking) is never
  throttled.
- A view that has not drawn the latest playhead position is always brought up to
  date, so the final state after a seek or when playback stops is never skipped.

Measured offscreen on one machine (1500x900), wait before a zero-delay event ran
during playback: median 12.6 ms before, 0.1 ms after; 95th percentile 15.8 ms before,
14.2 ms after (an event arriving during a paint still waits for it). Shortening
Python's thread switch interval made things much worse and should not be used.

---

## 35. Technology

Initial technology:

- Python
- Qt-based desktop UI
- scientific Python ecosystem
- NumPy
- SciPy
- pandas where appropriate
- matplotlib and/or another suitable visualization layer
- PyNWB for NWB access
- DANDI tooling for dataset access
- Git
- Linux-compatible development environment

Specialized scientific functionality should preferably use established libraries rather than being reimplemented unnecessarily.

---

## 36. Dependency / Implementation Philosophy

The project should distinguish:

> Does this code work technically?

from:

> Is this computation scientifically appropriate?

Established scientific libraries can handle implementation details such as:

- file parsing
- signal processing
- statistical calculations
- data access
- pose estimation
- spike processing

But the project should still understand:

- what the algorithm means
- what assumptions it makes
- what its inputs represent
- what its outputs mean
- how to validate the result

Visual inspection and sanity checks should be treated as legitimate validation tools.

---

## 37. Testing

Testing should cover:

### Core

- time mappings
- synchronization
- resource requests
- selections
- grouping
- transformations
- event handling

### Data sources

- loading
- timestamp handling
- metadata
- partial access

### Visualization

- seeking
- interaction actions
- synchronization between views

### Integration

A representative real dataset should provide an end-to-end test:

```text
Source
 → Resource
 → Selection
 → Synchronization
 → Data View
 → Visualization
 → User Interaction
```

---

## 38. Development Strategy

Development should proceed through vertical slices rather than building every abstraction independently.

The first vertical slice should be:

```text
Real NWB data
     ↓
Resource
     ↓
Pulse synchronization
     ↓
Shared timeline
     ↓
Video + neural raster
     ↓
Interactive seeking
```

Once this works, group selection and other capabilities can be expanded using the real requirements discovered during exploration.

The architecture should evolve based on actual scientific use rather than trying to predict every future requirement.

---

## 39. First-Pass Scope

The first pass should focus on a single real session and provide:

1. Load one representative session.
2. Discover/expose useful dataset dimensions.
3. Allow basic user selection of those dimensions.
4. Synchronize temporal sources using pulses.
5. Provide a shared timeline.
6. Display synchronized whisker video.
7. Display neural spike raster.
8. Navigate trials/groups.
9. Provide basic synchronization diagnostics.

This is intentionally narrow.

The first milestone is:

> Given one real mouse session, launch the application, load the configured data, select a trial, and watch synchronized whisker video and neural activity while moving through time.

If that works reliably, the first version is successful.

---

## 40. Features to Defer

The following should not be required for the first implementation.

### Pose estimation

Eventually:

```text
Video
  ↓
Pose Estimator
  ↓
Whisker Pose
  ↓
Contact Detection
  ↓
Contact Events
```

SLEAP or another pose-estimation system can be integrated through a Processor.

### Spike detection and sorting

Eventually:

```text
Raw Neural Signal
  ↓
Spike Detection
  ↓
Spike Sorting
  ↓
Spike Train
```

The initial application should use existing neural representations where possible rather than rebuilding spike detection/sorting.

### Advanced neural visualization

Future possibilities:

- firing-rate heatmaps
- probe-depth activity maps
- population activity
- spatial neural representations

### Trial comparison

Eventually:

```text
Trial 12 ─────────────
Trial 13 ─────────────
Trial 14 ─────────────
              ↑
        aligned event
```

This could become an important scientific analysis feature.

### Advanced synchronization

Future methods:

- shared clocks
- event matching
- correlation
- manual anchors
- periodic reference signals
- nonlinear/piecewise mappings

### Advanced annotations

Future support:

- behavioral annotations
- suspected contacts
- interesting neural responses
- experimental errors
- research notes

### Provenance

Eventually, derived results should be able to retain their computational history:

```text
Firing Rate
    ↑
Spike Train
    ↑
Spike Detector
    ↑
Neural Recording
    ↑
session.nwb
```

This could eventually support reproducibility and research auditing.

---

## 41. Before Implementation

The architecture is now sufficiently defined that additional design work should be minimized until implementation reveals concrete problems.

### Shared time rule

Every time-dependent resource retains its own native time coordinate.

The application should never assume timestamps from independent sources are directly comparable.

Mappings convert native time to shared time.

### Resource / Request boundary

A resource request should be cheap to describe even when fulfilling it is expensive.

For example:

```text
Neural recording
where mouse=A
and trial=17
from shared time 10–15 seconds
```

The Resource Manager determines how to fulfill the request.

### Minimal UI

The first UI should be functional rather than polished.

The interesting engineering work is underneath:

- resource management
- synchronization
- selection
- data access
- cross-view interaction

### First concrete data path

Initially support one real path:

```text
DANDI / NWB
     ↓
Resources
     ↓
Selection
     ↓
Pulse synchronization
     ↓
Video + raster
     ↓
Qt UI
```

Do not initially support arbitrary formats merely because the architecture can accommodate them.

Build one real path end-to-end first, then generalize based on actual requirements.

### Stop designing when the architecture is sufficient

The project should not attempt to fully resolve, before implementation:

- arbitrary processor architecture
- nonlinear synchronization
- complex multidimensional grouping
- complete provenance
- 3D visualization
- every possible scientific data format

The existing abstractions should provide extension points for these capabilities.

The next step is therefore implementation, not further architectural expansion.

---

## 42. Proposed Project Structure

```text
sync-visualizer/
│
├── pyproject.toml
├── README.md
│
├── src/
│   └── syncviz/
│
│       ├── core/
│       │   ├── timeline.py
│       │   ├── time_mapping.py
│       │   ├── synchronization.py
│       │   ├── events.py
│       │   ├── project.py
│       │   ├── configuration.py
│       │   └── actions.py
│       │
│       ├── sources/
│       │   ├── base.py
│       │   ├── nwb.py
│       │   ├── video.py
│       │   └── ...
│       │
│       ├── resources/
│       │   ├── base.py
│       │   ├── timeseries.py
│       │   ├── spikes.py
│       │   ├── events.py
│       │   ├── pose.py
│       │   └── ...
│       │
│       ├── processors/
│       │   ├── base.py
│       │   ├── pose_estimation.py
│       │   ├── spike_detection.py
│       │   └── ...
│       │
│       ├── resource_manager/
│       │   ├── manager.py
│       │   ├── cache.py
│       │   ├── requests.py
│       │   └── execution.py
│       │
│       ├── transformations/
│       │   ├── base.py
│       │   ├── aggregation.py
│       │   ├── downsampling.py
│       │   └── ...
│       │
│       ├── visualization/
│       │   ├── base.py
│       │   ├── video_view.py
│       │   ├── timeseries_view.py
│       │   ├── raster_view.py
│       │   └── timeline_view.py
│       │
│       ├── app/
│       │   ├── main.py
│       │   ├── main_window.py
│       │   └── ...
│       │
│       └── annotations/
│           └── ...
│
├── projects/
│   └── mouse_example/
│       └── project.yaml
│
└── tests/
```

The exact structure can change as implementation reveals better boundaries.

---

## 43. Architectural Principles

The project should preserve these principles:

### 1. Sources are not resources

Sources know how to access data.

Resources describe generic scientific data.

### 2. Resources are not visualizations

A resource represents data.

A visualization decides how to display it.

### 3. Resources are not UI

Resources should not contain Qt callbacks or visualization logic.

### 4. Processors are configurable computation

Expensive/model-based/external computation belongs behind Processor interfaces.

### 5. Transformations are generic operations

Generic mathematical or structural operations should remain reusable.

### 6. Synchronization produces mappings

The Synchronization Engine manages synchronization, while Synchronization Methods implement specific ways of deriving time mappings.

### 7. Groupings describe available dimensions

They should not hardcode every possible value.

### 8. Selections describe what the user wants

The same underlying resource can support many different views.

### 9. The UI communicates through semantic actions

Views should not directly manipulate each other.

### 10. Shared time is an abstraction

Native timestamps remain associated with their source.

### 11. Lazy access is the default

Large scientific datasets should not need to be loaded entirely into memory.

### 12. Scientific correctness matters independently of technical correctness

A computation that runs successfully is not necessarily scientifically appropriate.

### 13. Configuration should describe experiments, not implement them

The mouse project should configure the general framework rather than create a parallel mouse-specific architecture.

### 14. Prefer real requirements over speculative architecture

Build a useful vertical slice, then generalize where actual requirements justify it.

---

## 44. Long-Term Possibilities

If the architecture proves useful, the system could eventually support:

- multiple simultaneous experimental sessions
- large-scale neural datasets
- multi-camera 3D tracking
- interactive pose analysis
- spike detection/sorting pipelines
- trial alignment and comparison
- population neural analysis
- spatial neural visualization
- user-defined processing pipelines
- automatic synchronization discovery
- provenance tracking
- reproducible analysis workflows
- remote datasets
- additional scientific domains

The framework could eventually become a general environment for exploring relationships between:

```text
Physical world
      ↓
Sensors / experiments
      ↓
Raw data
      ↓
Processed data
      ↓
Scientific measurements
      ↓
Interpretation
```

---

## 45. Definition of Success

The project succeeds initially if a researcher can:

1. Open a real scientific dataset.
2. Understand what data it contains.
3. Select the relevant subset.
4. Synchronize independent temporal sources.
5. View those sources together.
6. Move through the experiment interactively.
7. Notice relationships or anomalies that would be difficult to see from an isolated dataset.
8. Use those observations to motivate further computational analysis.

The deeper goal is not simply to make synchronized plots.

It is to build a system that supports the research loop:

```text
Research Question
       ↓
Experiment / Data
       ↓
Exploration
       ↓
Observation
       ↓
Hypothesis
       ↓
Analysis
       ↓
Interpretation
       ↓
Improved Question / Experiment
```

The first implementation should therefore optimize for scientific exploration and learning, while the architecture leaves room to grow into a broader research-software platform.
