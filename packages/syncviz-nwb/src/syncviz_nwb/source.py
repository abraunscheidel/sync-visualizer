"""NWB file access."""

from __future__ import annotations

from pathlib import Path

from syncviz.sources import Source


class NWBSource(Source):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def describe(self) -> list[str]:
        # Imported lazily so discovering the plugin doesn't pay pynwb's import cost.
        from pynwb import NWBHDF5IO

        with NWBHDF5IO(str(self.path), "r") as io:
            nwb = io.read()
            names = [f"acquisition/{name}" for name in nwb.acquisition]
            for module_name, module in nwb.processing.items():
                names += [f"processing/{module_name}/{name}" for name in module.data_interfaces]
            return names
