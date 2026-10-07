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
