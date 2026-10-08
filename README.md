# Sync Visualizer

A desktop application for exploring synchronized scientific data from multiple
temporal sources. Different formats, sampling rates and clocks are mapped onto
one shared timeline that you can move through interactively.

The first demonstration uses a mouse whisker / neural recording dataset. It is
a *configuration* of the framework, not part of it. See [docs/design.md](docs/design.md).

## Layout

```text
packages/
  syncviz/        core: resources, time mappings, synchronization, plugin discovery, UI
  syncviz-nwb/    plugin: NWB source (pynwb)
  syncviz-video/  plugin: video source and sync-signal detectors (PyAV)
projects/         project configs (YAML) — describe experiments, don't implement them
tests/
docs/design.md    architecture
```

Plugins are separate packages. They register themselves through Python entry
points (`syncviz.sources`, `syncviz.processors`, `syncviz.sync_methods`,
`syncviz.views`), and the core never imports them directly. Any plugin can later
move to its own repository unchanged.

## Setup

With [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run pytest
```

Or with plain pip:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e packages/syncviz -e packages/syncviz-nwb -e packages/syncviz-video pytest
pytest
```

Data files (`*.nwb`, video) are ignored by git; put them in `data/`.
