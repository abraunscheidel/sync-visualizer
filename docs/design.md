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

### 34.3 Waiting for slow views

Playback never waits while a view keeps producing frames, however late. If a visible view makes no
progress for 0.4 s while playing (`View.stalled_for`), the `StallGuard` (`syncviz_app/stall.py`) sets
`Timeline.holding`: the clock stops advancing but `playing` stays on, so playback resumes by itself when
every view has caught up, and pressing pause during a hold is a real pause. The view itself shows
a single centred message over its picture ("Loading…", which becomes "Buffering…" during a hold); the toolbar says nothing. Nothing is held while paused, so
scrubbing and stepping are never interrupted; the view shows its normal loading cue after 180 ms.

### 34.4 Debug mode

`syncviz --debug` (or `SYNCVIZ_DEBUG=1`, or the "Sync Visualizer (debug).bat" launcher) adds a Debug menu:
simulate slow decoding (50 ms to 1.5 s per frame), stall the next frame for 3 s, and a live status line
(playing/holding, governor scale, how long each view has waited). Off by default. Views opt in by exposing
`simulated_delay_s` and `stall_once`, so the window stays source-agnostic.

### 28.2 Adding, removing and switching views

The left sidebar has a **Views** list above the project information. Each view has a checkbox that
shows or hides its panel (it stays loaded, so switching between five views is instant and nothing is
re-read) and a double-click brings it to the front. **Add view…** opens a dialog listing what the
project's sources can feed: each source offers a `catalog()` of `DataEntry` (path, kind, members) and each
view type offers `candidates(catalog)` (so the app knows no view type by name; a plugin view appears in the
dialog by implementing it). **Remove** discards a view. Both go through `MainWindow.add_view/remove_view`, which
update colours, extents, the timeline's range, the frame-definition choices and the coverage strip
(`view_factory.py`). Views added in the UI last for the session; they are not written back to the project
file yet.

### 28.3 Workspaces

The project file is the author's description of the data and is never rewritten. What the user arranges and
sets up while working is a **workspace**: the views added and the project views removed; Qt's saved geometry and
panel/toolbar/sidebar positions (including which panels are hidden); and the working settings, which are the
filters and whether movement skips what they hide, the playback speed, what defines a frame and how many each step
moves, and the playhead position (never whether it is playing). Each workspace is its own file, `<name>.json`, in the
project's own `workspaces` folder (next to the project file; `workspaces_dir:` in the project file moves it), so
projects never share files and one project can hold several presets (the folder is git-ignored). Which opens first
is the project file's `workspace: <name>`, overridden by `--workspace NAME`; otherwise "Default", and if that has
not been saved the project's own views and default settings are shown.

**Nothing is written unless the user saves.** *Save workspace* (Ctrl+S, also a button under the views list) writes
the workspace in use; closing never saves, and switching to another workspace drops unsaved changes to the one left.
The Workspace menu lists the saved ones (the one in use is ticked and named in the window title) with *Save
workspace as…*, *Delete workspace* and *Reset to the project's defaults* (which changes only what is on screen).
A workspace that is missing or unreadable is ignored, saved values that no longer exist (a filter option, a frame
definition) are skipped, and `--screenshot` mode uses none.

### 34.5 Reading large series lazily

Continuous recordings can be many gigabytes (the ephys session in DANDI 000231 is about 6.8 GB), so a series is
never assumed to fit in memory. A source returns either a `TimeSeries` (all samples in memory) or a
`LazyTimeSeries` (a handle to samples that stay in their file) and views use only what both offer: `window`,
`coverage`, `first_time`, `last_time`, `count_between`, `sample_values` and `time_base`.

* **Windows:** `window(lo, hi, max_points)` reads only those samples. A regular series needs no stored time axis;
  an explicit one (an array of timestamps) is searched by binary search (about log2 n single-value reads), never
  loaded. A window with more samples than a plot has pixels is reduced to the lowest and highest sample of each
  bucket, which looks identical to plotting everything; a window too big to read at all (over 20 million samples)
  is read thinned.
* **Axis range:** from about fifty small blocks spread through the series, not a strided read (which touches
  every stored chunk and so reads the whole file).
* **Gaps:** a regular series has none; an explicit time axis is scanned once in 4-million-sample chunks.
* **NWB:** a series of 5 million samples or more (`lazy_min_samples` in the source's configuration) stays in the
  file, read through a read-only HDF5 handle that is kept open and released when the window closes.
  `conversion` and `offset` are applied to stored numbers for both kinds, so values are in the series' unit.
* **Not yet:** multi-channel traces (2-D) are not offered by the Add view dialog; they need a channel choice.
  Thinned windows draw no gap breaks (their spacing is no longer the data's).

### 28.4 Collections

A project can hold many recordings. The core calls one a **collection** (a bundle of sources that share one
timeline); the project's `collections.label` is what the interface calls it ("Session"). The window always shows one
collection and opens another without restarting.

* **Finding them:** `collections.from` names a provider. `glob` makes one collection per file matching a pattern;
  `list` takes them written out. More providers can be added as plugins (`syncviz.collection_providers`).
* **One definition for all:** `sources` is a template. `{path}`, `{dir}`, `{stem}` and `{name}` (and, for a list,
  any field of the entry) are filled in per collection, and a `*` in a path is globbed. A source whose file is not
  there for a collection is left out, not an error. Views refer to sources by the names given in `sources`, so the same
  view specs serve every collection.
* **Attributes:** regular expressions over the path (`mouse: 'sub-([^_/]+)_'`), or stated in a list. They are
  filterable like segment attributes.
* **Switching:** the segments, sources, views, timeline range and filter options are replaced; the workspace (which
  views, where, what settings) carries over, as do views the user added or removed. A view whose data is missing keeps
  its panel and says "No data in this session". If the new collection cannot be opened (for example it has no segments)
  nothing changes. Playback stops.
* **UI:** a first toolbar row (shown only when there is more than one) has previous/next, a picker, and filters on
  the attributes that tell collections apart, with counts. A filter that excludes the open collection moves to the
  nearest match; `--collection KEY` or `collection:` in the project file chooses the first one.
* **What is remembered:** how the window looks and its settings are the workspace (per project). Facts about a
  recording (for now where the playhead was) are per collection: kept while the app runs, and written to
  `collection_state/<key>.json` beside the project when the workspace is saved.
* **Not yet:** moving through segments across collections as one pooled list, and remote locations.

### 16.1 Spike units and indicator lights

A sorted **unit** (a putative single neuron: spike sorting groups spikes by waveform) is an `EventSeries` of spike
times with the unit's table columns (depth, layer, an inhibitory guess, the channel it was on) as `metadata`. The NWB
source reads its `units` table as a container of event series named by unit id, and offers them in the catalog
shallowest first, labelled "Unit 7 · L4". A unit is not a channel: the file has 63 channels and 13 units, and channels
can hold several units or none. Spikes carry no amplitude here, so a spike is binary.

The **indicators** view shows rows as tiles that together fill the panel (as large as the panel allows, so flashes are easy to see), without a time axis: the playhead is the time. An event's lamp is fully lit
at the event and fades linearly over `decay` seconds of recording time (default 0.15 s); an interval's lamp is lit
while the playhead is inside it, then fades. Brightness depends only on the playhead, so pausing, scrubbing and
stepping are correct and a spike between two redraws still glows. One neutral colour (colour would imply a different
measurement); the label is the unit's name. `columns` fixes the column count; by default the grid is chosen to give the biggest, most even tiles for the
panel's shape, with the label inside each tile. Rows use the same specification as the event tracks, which remain the way to see spike timing
over seconds, and both views offer the same rows in the Add view dialog. Not built: a rate mode (spikes in a
trailing window), trial-aligned rasters, and a firing-rate heat map.

### 16.2 Parked idea: acting on an indicator light

Not built; recorded so it is not lost. These would be actions in the sense of 28.7. Clicking a light (an event row, such as a spike unit) could mean three things,
in increasing scope, and each is useful alone:

1. **Jump to an occurrence.** Click goes to that row's next event, Shift-click to the previous. Needs only the row's
   event times, which the view already has. Also gives "step through spikes".
2. **Clip.** Click selects a window around an occurrence (a configurable amount before and after, for example 200 ms)
   and loops or plays just that, using the timeline's existing selection range.
3. **Event-triggered filter.** The lit rows become a restriction: movement is limited to windows around every event of
   the chosen rows, as a segment filter limits movement to matching segments. An event window is just a segment, so
   hatching, skipping and previous/next could be reused.

Open questions for step 3:
* Several rows selected: the *union* of their windows is the natural default (any of these units); "all firing
  together" is a different, analytical question for later.
* It should *intersect* with the other filters (for example one unit's spikes, but only in concave trials). That points
  to a general stack of restrictions, each narrowing what is reachable: collection, then segment, then event.
* Scale: a busy unit has tens of thousands of spikes, so overlapping windows must be merged, and the timeline strip
  would show them as a density rather than as individual stripes.
* Safety: a stray click during playback must not silently change what plays, so active event filters need to be obvious
  and easy to clear.
* Event filters are working settings, so they belong in the workspace (see docs/checklists.md).

### 28.5 Display delay

A view can be delayed for exploring: `View.lag` (seconds) makes it draw the moment `lag` before the playhead. **Positive
means delayed** (the view runs behind the playhead); negative means it runs ahead. This matches the time-mapping maths
(`shared = offset + native`: a positive offset makes events appear later), so a delay that proves useful could become a
real sync correction with the same number. The interface always says it in words, so nobody has to remember the sign:
"This view runs 15 ms behind the playhead.", and a panel's title carries `[delayed 15 ms]` or `[ahead 15 ms]`.

It is a lens, not a correction: it changes only what that view draws. The data, the extents and coverage on the timeline
strip, the segments and the other views stay at true times. Sync correction (the claim that a source's clock is off) is a
different thing: it is a fact about a recording, belongs to the source and the collection, and reuses the time-mapping
machinery instead of this.

* **Where:** `RefreshScheduler` hands each view `playhead - lag`. Clicking in a plot adds the lag back, so it seeks the
  playhead, not the view's own time. Stepping by the view's grid goes through `Shifted`, which moves its ticks by the lag.
* **Set from:** the "Delay" field under the Views list (milliseconds, for the selected view), or `lag_ms:` in a view's
  specification as its starting value. It is saved in the workspace by view title, and "Reset to the project's
  defaults" returns each view to its `lag_ms`.
* **Caution:** aligning by eye can look convincing and still be wrong. A measured latency (for example the event-aligned
  firing rate) is the number to trust; the delay only helps to see it.

### 20.1 Processors and the population rate

A **processor** turns resources into a new resource: here event series in, a regularly sampled time series out
(`syncviz/processors.py`; more can be plugins in `syncviz.processors`). Nothing is written to the data file. A view's
specification says what to compute and from what, so the result is reproducible and is computed when the view is made:

    series:
      process: population_rate
      inputs: ["session:units"]        # text = every member of that event container; {from, member} = one member
      bin_ms: 10
      smooth_ms: 20
      smoothing: trailing

The same derived series is computed once and shared (`ResourceStore.derived`). A processor lists what it could offer from
the data a project has (`candidates(catalog)`), so the Add view dialog shows "Combined event rate of units" without
knowing the processor by name.

**Population rate** is how often events happen across a group of event series, over time: for spike units, the average
firing rate of a unit at each moment, in events per second per member. The total number of events is preserved.

**Smoothing must not suggest an effect before its cause.** A symmetric (centred) window spreads every spike into the past,
so a response appears to begin before the stimulus. On the real recording (mouse 229CR, 442 whisker contacts) the rate
was flat at about 6.5 Hz per unit until contact and jumped to about 15 Hz at +15 ms when unsmoothed, but a 50 ms centred
window started rising at -50 ms and flattened the peak to 9 Hz. The default is therefore **trailing** smoothing: a
moment's rate uses only earlier events, weighted by an exponential (time constant `smooth_ms`, default 20 ms), so the rate
can never rise before its cause. The price is a lag of about `smooth_ms` (the peak moves from +15 ms to about +30 ms),
which the view's display delay can offset. `smoothing: centered` remains available for a smoother, time-unbiased
picture; use it knowing it blurs latencies of a few tens of milliseconds.

### 18.2 Synchronization diagnostics

Evidence that the sources' clocks agree, or that they do not. It is a **core application component**, not a view: it is not
drawn at the playhead, is not part of a workspace's arrangement, has no extent on the timeline strip, and is about how
sources relate to each other. It is reached from **Tools > Sync diagnostics** and from a status line in the sidebar that is
always visible ("Sync: 3 pass", in the colour of the worst result), so a problem is not hidden in a window that is closed.

**Where the code lives.** The window, the status and the drawing are core. The generic checks (`syncviz.diagnostics`) know
nothing about any source. What only a source can say comes from that source's own code, in two ways:

* a source provides the events a check names: the video plugin returns its blackouts as `video:sync_signal` through the
  sync-detector plugin the project configures; the NWB plugin returns spike units as `session:units`;
* a source can run checks about itself (`Source.diagnostics()`): the video checks that its frames are evenly spaced,
  because frame number / rate is true only if none were dropped. A dropped frame makes later frames later than that says.

**Kinds of evidence** (a project's `sync:` section lists them; more kinds can be plugins in `syncviz.sync_checks`):

* `paired_events`: the same moments seen by two sources. Events are paired (nearest within a window, each used once) and the
  error of each pair is measured: its typical size (median), its spread (95% of errors within), and how much it grows
  across the recording (drift, fitted to typical pairs so a few glitches do not hide it). The implied rate is reported when
  one side has a declared rate.
* `event_response`: an independent cross-check that does not use any sync signal. Neurons should respond a known time after a
  stimulus; aligned on isolated stimuli, the response peak should fall in the expected window. A clock disagreement
  moves or smears it. If there is no clear response the result is *inconclusive*, never a sync failure.

**Verdicts** are against the project's tolerance (default 20 ms): *pass* within it, *warn* within twice it, *fail* beyond;
*inconclusive* when the data cannot say; *not applicable* when the recording lacks what the check needs (no neural data).
Wording is "consistent with", never "verified". A check can carry a `note`, shown with it, for what its result does and
does not mean.

**Running.** On demand, off the main thread, because scanning a long video takes minutes the first time (the 3.4 GB video
took about five minutes). Results are kept beside the other derived data, keyed by the project's checks and the
sources' files, so they are shown on opening without running and are discarded if a file changes. Clicking a pair in the
error plot moves the playhead there, to look at the moment in the other views.

**Real recordings (DANDI 000231).** Video blackouts match trial boundaries at exactly 0 ms on all three sessions. That is
perfect to the frame, which suggests the dataset's trial times were *defined from* the blackouts, so it shows the two
were built consistently and is not independent evidence (the project's note says so). The independent evidence is the
neural response to whisker contact: on the recording that has neural data, firing roughly doubles and peaks 15 ms after
contact.


### 34.6 Video overlays and view settings

The video view can draw **layers** over the picture (`syncviz_video/overlays.py`). A layer is told which moment of the video is
on screen, which is the frame's own time and not the playhead's (decoding can lag behind it), so an overlay always matches the
picture, and paints itself over the image.

**Corner badges** are the first layer: a small labelled badge for each event row in a corner of the picture, lit when the
event happens at that frame and fading over `decay` seconds (default 0.25 s, longer than the indicator lights' because an
event can be shorter than one screen refresh); an interval's badge stays for as long as it lasts. Only lit badges are
drawn, each in a fixed slot among the shown rows, so nothing shifts when another appears. Rows use the same specification as
the event tracks. A row whose data a recording lacks is left out with a note; the picture is still shown.

**What is shown is the project's choice**, in the video view's `overlay:` section (`corner`, `decay`, `rows`, and optionally
`hidden`); the application has no defaults of its own and a view with no `overlay:` has no badges. The viewer can change the
corner (top left, top right, bottom left, bottom right, or off) and switch events on or off.

**View settings** are the general way a view offers such choices: `View.settings()` lists `ViewSetting`s (a choice or a
toggle), the Views list shows them when the view is selected, `apply_setting` changes one and `reset_settings` returns to the
project's values. The window keeps the user's choices by view title in the workspace (`view_settings`), so they are saved
with it, switch with it, and reset to the project's values with it.

**Tracked lines and contact rings** are two more layers that mark where something is in the picture itself, under the badges.
A *line* follows a tracked thing from one point to another (a whisker from base to tip): four series of x and y positions are
looked up at the frame on screen, using the nearest sample within one and a half sample intervals, and a frame with no such
sample, or a missing value, shows no line rather than a stale one. A *ring* marks where an interval happened in the picture
(a contact, at the whisker tip) for as long as it lasts, then fades; it uses that interval's own position from the table, and
`color_of` gives it the colour of a line.

**Positions are in picture pixels.** The NWB file stores them with a unit conversion (this dataset's whisker positions are pixel
column and row numbers, converted at 0.05 mm per pixel and labelled millimetres). The source keeps the conversion with the
series (`metadata.conversion`), and the layer undoes it, or the project says `units_per_pixel`. On a real frame the tracked
whiskers lie along the visible whiskers and the rings sit where they meet the object. That is also a direct visual check that the
tracking and the video are on the same clock: if the lines lagged the whiskers, they would trail behind them as the whiskers move.

Everything is switchable per item in the Views list (`Draw Whisker C0`, `Draw Contact point C1`, ...) and saved with the workspace.

**Groups and a master switch.** Any overlay item (a badge row, a line, a ring) can name a `group:` in the project file; a group may
mix badges and drawings (all the "Contacts" together, say). The Views list shows each group as one switch above its members, with a
partial state when only some are on; clicking it turns every member on, or off if they were all on. Only the members' switches are
saved (the group's is worked out from them). A single "Show overlays" switch hides or shows every layer without forgetting the
individual choices underneath. Groups are a general property of view settings (`ViewSetting.group`), so any view can use them.

**Tracked points (pose).** Several named points tracked over time, with the links between them, are a core resource (`PointTracks`:
times, x and y of each point, the point names and the edges). The NWB source reads the ndx-pose layout (this dataset has eight
markers per whisker, tip to base) with positions left as stored (picture pixels), and a source says it has some by returning them
from `read_points`. The video overlay `skeletons:` draws them on the picture: **curve** (smooth through the points), **points** (a dot
at each, the first larger) or **both**, chosen in the Views list (`skeleton_style:` is the project's start). Points are placed from the
tracked sample nearest the frame on screen, a frame with no sample close enough shows nothing, and a point missing in a frame is
skipped, never drawn at the origin. A whisker read takes about 0.4 s and 30 MB.

### 28.6 What a field means: descriptions and the glossary

A name on screen should say what it is and how to read it. Two sources feed one tooltip (`AppContext.explain(term, described)`):

* **What it is, from the data.** Sources pass on the descriptions stored in the files: `IntervalSeries.descriptions` (one per
  attribute, for example a trial table column) and `DataEntry.description` / `member_descriptions` (what the Add view dialog shows).
  Placeholders such as "no description" are dropped, and an item with nothing to say gets no tooltip.
* **How to read it, from the project.** A `glossary:` section of the project file maps the names the interface shows (a filter's
  field, an overlay item, a group) to a note. A view item can also carry its own `description:`, which then stands in for the
  file's. The glossary is where interpretation lives (which flag means "ignore this trial", why a ring does not move), and the
  application has no such text of its own.

Shown today as tooltips on the segment filters, on the Add view dialog's entries, and on the overlay switches and groups in the Views
list. The longer, dataset-wide reference is in `docs/datasets/`.

### 28.7 Inspecting data: targets, details, presenters, actions

Decided in discussion; not yet built. One mechanism for showing extra information about what is on screen, instead of a
special case per view. It has four separate layers.

**Targets.** A view can say what is under a point and returns a generic reference: source, data path, member or item, and
optionally a time. A unit row, a whisker curve, a contact badge, an indicator tile and a trial all return one. The core
never learns what a "unit" is.

**Details.** What is known about a target: labelled fields in groups (name, value, unit), plus the description and glossary
text of 28.6. They come from (a) generic statistics by resource type (events: count, rate, inter-event interval; time
series: min, max, mean; intervals: count, duration), (b) source-specific extras (the NWB source adds the file's own columns,
such as unit quality), supplied like `diagnostics()`, and (c) project config (glossary, default fields). Each statistic has a
*scope*: the current segment, the whole session, or a window around the playhead. **The default scope is the current
segment**, because with filters active it is unclear what to include from other segments.

**Presenters.** Swappable ways to show the same details:

| Presenter | Trigger | Lifetime | For |
|---|---|---|---|
| Tooltip | hover | momentary | the description plus the user's chosen stats |
| Detail panel | the selection changes | until it changes again | every field, with small plots |
| Selection-bound view | the selection changes | persistent | e.g. a raster for the selected unit |
| Temporary view | "open as view" | until replaced or pinned | the same view, not yet in the views list |

* The detail panel is a **docked core panel**.
* There is **one selection** at a time (the contract does not prevent several later). It is shared state like the playhead.
* A view can have a subject setting: "follow selection" or fixed to one item. A selection-bound view is an ordinary view.
* A temporary view is a view that is not in the views list yet; "pin" adds it. There is no separate popup system.
* The hover figures are a user-chosen subset of the detail fields, picked from the same checklist the panel uses, saved in
  the workspace (see docs/checklists.md), with defaults from project config. This replaces the earlier parked idea of a
  separate hover-stats feature.

**Actions (now called commands, see 28.9).** Everything a user can do with a target is a named action registered for a kind of target: select, seek to this
time, open as view, show details, filter to windows around this event (16.2), copy value, and so on. Views, sources and
plugins can add actions. Actions live in their own registry and do not depend on any menu: the context menu is only one way to trigger them, alongside
click bindings, keyboard shortcuts, toolbar buttons and anything added later. View-specific actions (jump, clip, event
filters) are registered by the view or plugin that owns them. Right-click opens a menu of the actions that apply to the
target; the menu shows shortcuts. "Open as view" is a submenu listing every way the target can be visualized, built from
the view types that accept it.
Left click runs the primary action and double click a second one, both set in project config, so the app stays agnostic.
Select means marking one item (a unit, a row, a curve) as the shared current selection: highlighted wherever it appears,
shown in the detail panel, followed by selection-bound views; it never moves time or playback by itself. Decided: left click only selects, so a
user can select something and act on it without changing playback. Double click seeks to the target's time (when it has
one). Both are defaults that project config can change, and seeking is also available from the menu. Applicability is declared by the
action, never hardcoded in the core. The ideas in 16.2 become ordinary actions rather than a feature of their own.

**Rules.**
* Hover is cheap, read-only and changes no state. Expensive statistics are computed lazily, cached and kept off the GUI thread.
* Click changes state (the selection); it never moves the time axis unless the action says so.
* Views return targets only; they never format details. The core presents what the source supplies.
* Operational information (sync diagnostics) stays a core component and is not mixed into details.

**Status.** Steps 1 to 3 are built. Step 1: `syncviz/inspection.py` (Target, Scope, Field, Details, statistics by resource
type), `syncviz_app/inspector.py`, `View.target_at` and hover on the indicator lights, the tracks view and the time series
view. Step 2: `Selection` (one shared item), the docked Details panel (`details_panel.py`) with every field and a per-figure
"On hover" tick saved in the workspace (`settings.inspection.hover`), and the optional `Source.details(target)` hook. Step 3:
`target_actions.py`, the action registry. Built in: Select, Go to this time (the item's own moment, else the time under the
pointer, plus the view's delay), Copy details, Clear selection (Esc), Show details and Open as view (a submenu built from each
view type's `spec_for(target)`, which adds the view to the views list). Views add their own by overriding
`View.target_actions`; plugins can register more. Right-click on an item in a view opens the menu for it. A click and a double
click run the actions the project binds with `interaction: {click: select, double_click: seek}`; where a click lands on
nothing selectable it still seeks. `Target.at` is the time under the pointer and does not make two targets different items.
Step 4: a view that can show an item in place of what it shows (`show_target`: the tracks and plot views) has a saved
setting "Follow the selected item"; ticking it makes the view show whatever is selected, unticking keeps what it shows now, and
reset returns to what its spec gave. "Show in temporary view" (on the same menu as Open as view) opens one view of the
chosen type for the item; it follows the selection, the next peek replaces it, it is marked "(temporary)" in its title and in
the views list, it is not in the workspace (neither the view nor its settings), and Keep in the views list makes it an ordinary
view. A following view does not refresh its extent in the timeline (the data is the same recording).
Backlog: hover and selection on the video overlays; hover and selection for processed series such as the population rate
(needs its own design: they have no source reference); a selection-bound view that does more than show the item (a spike
raster or event-aligned response for the selected unit); the jump/clip/event-filter actions of 16.2.

### 28.8 Dates and times

One standard, in `syncviz/formatting.py`: ISO 8601 for display, `2023-04-15` for a date and `2023-04-15 10:15` (24-hour, plus
the zone if the data has one) for a date and time. `parse_datetime` reads the year-first spellings data comes in (`20230415`,
`2023_04_15`, `20230415T101530`, with an optional zone); day-first and month-first forms are ambiguous and are never guessed.
A project chooses another display with `display: {date: iso, datetime: iso}`, each a preset (`iso`, `us`, `eu`, `long`,
`short`) or a `strftime` pattern. Which collection attributes are dates is stated in `collections: {attribute_types: {day:
date}}`; the dropdowns then show them in the chosen form while filtering on the stored value, and `collections: {title:
"{mouse} · {date}"}` names sessions in the picker by their attributes. Dates in a file's metadata (the details panel) use the
same display. Anything that shows a date to a person should go through `DateFormat.show`.

**Order of building.** (1) target and details contract, with hover on the existing views; (2) selection and the detail panel;
(3) actions and the context menu; (4) selection-bound and temporary views.

### 28.9 Commands, filters, groups, sources: decisions

Decided in discussion. Items marked *built* are in the code; the rest is planned and listed in order at the end.

**Words.** Four different things, kept apart:

* A **bus message** (`Seek`, `SetPlaying`, `SelectSegment`; called "actions" in sections 23 and 24) is a plain data record
  saying "change shared state this way". This is how state changes.
* A **command** (*built*, `syncviz_app/commands.py`; it was called a target action in 28.7) is a named, discoverable
  operation on a target: select, go to this time, open as view, copy details. It adds a label, a rule for when it applies and
  an id, so a menu can list it, a click or key can be bound to it, a project can switch it on or off, and a plugin can add one.
  Running one usually publishes bus messages or opens a view. It exists because methods cannot be enumerated with their
  applicability, and because a compound command (several state changes) can later be one undo step. It has `run` and `applies`
  only; lifecycle hooks and undo are added when something needs them.
* A **processor** is data in, data out: it takes resources and parameters and returns a new resource (population rate,
  epochs, per-epoch measures, sync check verdicts). It changes nothing else, so it can be cached and run twice. A command may
  *ask for* a processor's result (open the rate of this unit), but never is one.
* A **view** draws.

The test: calling it twice with the same input gives the same data and changes nothing, so it is a processor. It changes what
the application shows or does, so it is a command.

**Filter or new view.** Filtering a view changes which items it shows (a view setting). Opening a view presents data in a
different form or different data (a command). *Built:* Open as view and Show in temporary view never offer the origin's own
kind of view for the same data; that is a filter. Which fields a view can be filtered by come from the items' own metadata
(the source supplies the facts, the core builds the control: a dropdown for categories, a range for numbers); a plugin is only
needed for a field that has to be computed. Commands can be switched on and off in the project (`interaction:`), each declaring
its default; a command like "isolate one item" is off by default because selection already gives one item extra attention.

**Filtering hierarchy**, outermost first. Each only narrows; reachable time is the intersection of 1 to 3.

1. **Collection:** which session is open (filter by mouse, date).
2. **Segment filter:** attribute equality on the active segmentation, including attributes derived from events. Global:
   it limits playback and the timeline.
3. **Window restriction:** event windows ("500 ms around every contact C0"). Global, because there is one playhead. These are
   not a separate mechanism but a **derived segmentation**: an epoch set made by a processor from events, whose segments carry
   the attributes of the segment they fall in (stimulus, outcome), so the filters of level 2 still apply and the navigator
   (previous/next, hatching) works unchanged. The active segmentation is chosen by the user.
4. **Item filter:** which rows, units or series a view shows. Local to a view. Promoting one to a global restriction is an
   explicit command, never implicit.
5. **Selection** is not a filter: highlight and subject.

Active restrictions show as removable chips with Clear all and Back to the previous set; the current set is a working setting
saved in the workspace.

**Groups** (planned). A group is a named predicate over items: a rule ("layer = 4") or an explicit list. A saved item filter and
a group are the same thing. A group is one selectable item with many members, so there is still one selection; it appears in
filter dropdowns like any option, and it aggregates (the population rate over its members, surface against deep on one plot).
Rule-based groups work across sessions; explicit lists belong to one collection, since unit ids differ between mice. Groups are
saved at *project* level, not inside a workspace, because they are the data's vocabulary and cut across tasks; a workspace may
say which groups are shown (default all).

**Sources: file format or experiment.** The format reader (file to generic resources: NWB, video) and the experiment's
interpretation (where trials and units are, derived facts, per-source diagnostics and details) are different things.
Today the NWB reader is already generic and the experiment lives in the project file, but `Source` carries both kinds of hook.
Planned: an optional **profile** beside `type:` on a source, holding the interpretation hooks (`details`, `diagnostics`, derived
facts). Declarative config wherever possible; a shared base profile for a format's common elements (an NWB profile) that
experiment profiles extend, using inheritance only to reuse code. Format readers stay first-party packages outside the
dependency-free kernel, since they need pynwb and h5py.

**Epochs and the next analysis steps** (planned). An epoch is a window: from an interval or from an event plus a window. Trials
are epochs. With per-epoch measures (event present, event count, a unit's spikes in the window) as derived attributes, these all
become the same machinery: filtering segments by event presence ("trials where whisker C0 touched"), event-centered
exploration, search by scientific property, comparison between conditions, aggregation (a time-aligned profile around
contacts, per group, as the main output; a per-unit mean table secondary), and a ranked list of unusual epochs (a sort on a
measure, with the score always shown, never a black box). Derived data should record where it came from (inputs and window) so
a point on a derived plot resolves back to times and targets. The sync diagnostics grow into a general data-health report.
An epoch "contains" an event when it overlaps the epoch's window; the window is configurable. Event-based filters are defined
in the project first; a command to make windows from a selected event comes second.

**Epochs: built.** `syncviz/epochs.py` (pure functions) and `syncviz_app/segmentation.py` (builds the project's segmentations
for a recording, cached). A segmentation can have `measures:` (an attribute worked out from the events or intervals that fall
in each segment, as a count or as presence with two labels, edge overlap/start/stop; a measure whose data is missing in a
recording is skipped with a note), so "trials where whisker C0 touched" is an ordinary filter. A segmentation can instead have
`derive:` (a window `before_ms`/`after_ms` around each event or interval edge, `within:` another segmentation; windows are clipped
to it, take its attributes, merge when they overlap, and say how many events each holds). Derived segmentations confine
movement to their windows by default (`confine:`), so the timeline is limited to the clips. A toolbar dropdown chooses which
segmentation to navigate (saved in the workspace under the filters); the playhead stays where it is if it falls in one of the
new segments, else moves to the nearest. A collection that cannot make the chosen segmentation falls back to the first.
YAML note: unquoted `yes`/`no` are read as true/false, so measure labels are checked and the error says to quote them.
Not yet: the removable chips and Back for restrictions; windows whose size depends on the event.

**Planned work, in order.** Do not lose track of these.

1. ~~Epochs~~ (built, see above), except the chips for restrictions.
2. Groups.
3. Aggregation views over groups and epochs.
4. The data-health report.
5. **The profile layer.** After 1 to 4 and *before any new source type is added*. The checklist says so.

**Later: test speed.** The full suite takes about 2.5 to 3 minutes because most tests build a whole window with real files. After the
work above, look for cheaper sharing: build the window once per module and reset its state between tests (selection, filters,
views added, lags), keep the generated data files at module scope, and split pure logic from window tests so more of it runs
without Qt. Tests that change window structure (switching collections, removing views) may still need their own window, so
sharing will not suit every test and each move must keep the tests independent of order.

### 28.10 Decisions: delay, event conditions, panels

**Views and panels.** A *view* presents recording data; there can be many, each showing something from the data. A *core panel*
holds or controls shared application state; there is one (the Details panel, the views list, the segment filters, the event
conditions). The event tracker that lights up when events happen presents data, so it is the indicator-lights view; the
conditions that restrict the data are state, so they are a docked core panel.

**Delay belongs to the view.** A view's delay is an analysis choice about how to look at the data (the neurons fire when the
file says they do), not a property of the source. A view opened from another (Open as view, Show in temporary view) starts with
the origin's delay and the user can change it. *Built.* Three different reasons for an offset exist and should stay apart:
1. a real clock offset in a source, which belongs on the source as a time mapping (below);
2. the lag of a processed view (the trailing smoothed rate lags by about its smoothing time), which a processor could declare
   so the view compensates without anyone typing a number;
3. an analysis choice, which is today's delay field.

**Later: named delays.** A delay given a name ("neural lag 20 ms") that can be attached to several views and changed in one place.

**Later: mapping and offsetting data (time mapping on a source).** For when two sources really disagree about time, not just how
the user wants to view them. A source gets an offset (and later a drift) that is applied wherever its data is used, so all views,
statistics, windows and the sync diagnostics see the corrected times; the diagnostics can suggest a correction when a check fails.
Easy way to build and test it without waiting for a mismatched data set: make a copy of one of the test videos with a few black
frames added at the start, so the video lags the recording by a known amount, then check that the sync diagnostics see the offset
and that entering the offset makes the video line up (blackouts back on the trial starts).

**Event conditions (built, first version).** `syncviz/conditions.py` (pure), `event_conditions.py` (the conditions in force), `events_panel.py` (the docked Events panel and its dialog). The project names the events in an `events:` section by scope; the panel starts empty; chips and the filters are saved in the workspace (`settings.events`); a condition that would leave no segment is refused with a message; conditions follow the chosen segmentation and the open recording (dropped with a note if nothing would be left); the command "Only segments with this event" is offered on any target the project names. The per-whisker dropdowns and the Behavior events view were removed from the whisker project. Still to do from the description below: the indicator view's group headings and search box, and "make windows around this event".

**Event conditions (design).** A *chip* is a small labelled token for one active condition, shown in a docked panel where it can be
changed or removed with a click. One chip is one question with an answer: a list of events of which any one counts (the OR) and
yes or no. Different chips combine with AND, and with the other filters. This covers "(C0 or C1 touched) and (licked)" without a
query builder; deeper nesting would use saved groups as building blocks. The panel starts empty and the user adds what they need;
the picker offers only the events the project names, grouped by scope, with search; the chips are saved in the workspace. A chip
may carry a window relative to the segment ("within the first 500 ms"); by default it means anywhere in the segment. Clicking an
event in an indicator-lights view offers two commands: only segments with this event (adds a chip), and make windows around this
event (asks for the size, with a project default, and adds a derived segmentation saved in the workspace). The indicator view
gains group headings and a search box so a long list stays usable. The usability of the chips should be tested with real use
before it is settled.

### 28.11 Decisions: multi-selection, the event tracker, clip windows

Decided in discussion (not built yet unless noted).

* **Selection becomes a set.** Click selects one item; Ctrl-click toggles and Shift-click selects a range. No drag-rectangle for now.
  Commands receive the list of selected items, so "any of these", "all of these" and "none of these" are single commands (any/none: one
  condition holding all the events; all: one condition per event). The same selection will build groups ("Save as group…").
* **The event tracker is a view.** Its tiles light at the playhead and each can be delayed like any view. It lists the events the user
  tracks (empty by default, or the project's `track:` list), grouped by the project's scopes, and below them a collapsible
  "Other events" section with every event the project names as a grayed tile that does not light. An event is moved between the two with
  the commands Track this event and Remove from tracker. Grayed tiles can be selected and filtered by, so a filter never needs an event
  to be tracked, and the event dialog is no longer a way to create a condition. A tile shows the state of any condition it is part of.
  The video's corner badges are removed once the tracker exists.
* **Clicking a tile** selects it. A double-click is bound to a list of commands, the first that applies runs (`[seek, only_with_event]`),
  so on a tile it adds the filter.
* **Details with several items** show a table with one row per selected item and its brief figures, and the full details of the row the
  user clicks in the panel. There is no primary item and no tabs (tabs do not scale to dozens of units).
* **Editing a condition.** The chips remain as the list of active conditions (they show a group such as "C0 or C1" and its window, which
  tile outlines cannot). Clicking a chip selects its events; if the user then changes the selection the chip shows "Update | Revert".
  Nothing changes until Update, and there is no hidden editing mode: the selection is the ordinary one.
* **Clip windows.** Each event has a "before" and an "after" time (ms), with a project default and per-event values in the project, and
  user overrides saved in the workspace. For an interval event the anchor says what the window is cut around: the **whole interval**
  (before the start to after the end), which is the default because the end of a touch matters as much as the start, or just the
  **start** or the **end** (needed when windows must share one alignment point, as when averaging responses to contact onset). With
  several tiles each event uses its own window and overlapping windows merge, so nothing requested is left out.
