"""NWB file access.

Objects inside the file are addressed by path, for example
"intervals/trials" or "processing/behavior/licks". Each read opens the file,
copies out only what was asked for, and closes it again, so nothing large stays
in memory and nothing is read that was not requested.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import numpy as np

from syncviz.resources import EventSeries, IntervalSeries, LazyTimeSeries, TimeSeries
from syncviz.sources import DataEntry, MissingDataError, Source

_TIME_COLUMNS = {"start_time", "stop_time"}
LAZY_MIN_SAMPLES = 5_000_000      # a series with at least this many samples stays in the file


class NWBSource(Source):
    def __init__(self, path: str | Path, lazy_min_samples: int = LAZY_MIN_SAMPLES) -> None:
        self.path = Path(path)
        self.lazy_min_samples = lazy_min_samples
        self._h5 = None                      # read-only handle kept open while lazy series are in use

    def _h5file(self):
        if self._h5 is None:
            import h5py

            self._h5 = h5py.File(self.path, "r")
        return self._h5

    def close(self) -> None:
        if self._h5 is not None:
            self._h5.close()
            self._h5 = None

    def _open(self):
        # Imported lazily so discovering the plugin doesn't pay pynwb's import cost.
        from pynwb import NWBHDF5IO

        return NWBHDF5IO(str(self.path), "r", load_namespaces=True)

    def describe(self) -> list[str]:
        """Paths of the objects in the file, without reading any data."""
        with self._open() as io:
            nwb = io.read()
            names = [f"acquisition/{name}" for name in nwb.acquisition]
            for module_name, module in nwb.processing.items():
                names += [f"processing/{module_name}/{name}" for name in module.data_interfaces]
            names += [f"intervals/{name}" for name in nwb.intervals]
            return names

    def catalog(self) -> list[DataEntry]:
        """Time intervals, event containers and one-dimensional time series in the file."""
        from pynwb import TimeSeries as NWBTimeSeries
        from pynwb.behavior import BehavioralEvents
        from pynwb.epoch import TimeIntervals

        def plottable(ts) -> bool:
            return len(getattr(ts.data, "shape", ())) == 1

        entries: list[DataEntry] = []
        with self._open() as io:
            nwb = io.read()
            objects = [(f"acquisition/{n}", o) for n, o in nwb.acquisition.items()]
            for module_name, module in nwb.processing.items():
                objects += [(f"processing/{module_name}/{n}", o) for n, o in module.data_interfaces.items()]
            objects += [(f"intervals/{n}", o) for n, o in nwb.intervals.items()]
            for path, obj in objects:
                if isinstance(obj, TimeIntervals):
                    entries.append(DataEntry(path, "intervals"))
                elif hasattr(obj, "time_series"):
                    members = tuple(n for n, ts in obj.time_series.items() if plottable(ts))
                    if members:
                        kind = "events" if isinstance(obj, BehavioralEvents) else "timeseries"
                        entries.append(DataEntry(path, kind, members))
                elif isinstance(obj, NWBTimeSeries) and plottable(obj):
                    entries.append(DataEntry(path, "timeseries", (obj.name,)))
        return entries

    @staticmethod
    def _resolve(nwb, path: str) -> Any:
        head, *rest = path.split("/")
        try:
            if head == "acquisition":
                return nwb.acquisition[rest[0]]
            if head == "processing":
                return nwb.processing[rest[0]][rest[1]]
            if head == "intervals":
                return nwb.intervals[rest[0]]
        except (KeyError, IndexError):
            pass
        raise MissingDataError(f"no object at {path!r}")

    def read_intervals(self, path: str) -> IntervalSeries:
        """A TimeIntervals table (trials, contacts, ...) as an IntervalSeries.

        Columns other than start/stop become attributes. Columns that are not
        plain per-row values (such as references to other objects) are skipped.
        """
        with self._open() as io:
            table = self._resolve(io.read(), path)
            df = table.to_dataframe()
            starts = df["start_time"].to_numpy(dtype=float)
            stops = df["stop_time"].to_numpy(dtype=float)
            order = np.argsort(starts, kind="stable")
            attributes = {}
            for column in df.columns:
                if column in _TIME_COLUMNS:
                    continue
                values = df[column].to_numpy()
                if values.dtype == object and not all(
                    isinstance(v, (str, bool, int, float, np.generic)) for v in values
                ):
                    continue
                attributes[column] = values[order]
            return IntervalSeries(starts[order], stops[order], attributes, name=path)

    def read_events(self, path: str) -> dict[str, EventSeries]:
        """A BehavioralEvents container (or single series) as EventSeries by name."""
        with self._open() as io:
            obj = self._resolve(io.read(), path)
            series = obj.time_series if hasattr(obj, "time_series") else {obj.name: obj}
            return {
                name: EventSeries(times=np.asarray(ts.timestamps[:], dtype=float), name=f"{path}/{name}")
                for name, ts in series.items()
            }

    def read_timeseries(self, path: str, only: Iterable[str] | None = None) -> dict[str, TimeSeries]:
        """A container of time series (or a single one) as TimeSeries by name.

        `only` restricts which members are read, so large unused members stay on disk.
        """
        wanted = None if only is None else set(only)
        with self._open() as io:
            obj = self._resolve(io.read(), path)
            members = obj.time_series if hasattr(obj, "time_series") else {obj.name: obj}
            if wanted is not None and not wanted <= set(members):
                raise KeyError(f"{path!r} has no member(s) {sorted(wanted - set(members))}")
            out = {}
            for name, ts in members.items():
                if wanted is not None and name not in wanted:
                    continue
                scale = float(getattr(ts, "conversion", 1.0) or 1.0)
                offset = float(getattr(ts, "offset", 0.0) or 0.0)
                if len(ts.data.shape) == 1 and ts.data.shape[0] >= self.lazy_min_samples:
                    out[name] = self._lazy(ts, scale, offset, f"{path}/{name}")
                    continue
                if ts.timestamps is not None:
                    times = np.asarray(ts.timestamps[:], dtype=float)
                else:
                    times = ts.starting_time + np.arange(len(ts.data)) / ts.rate
                values = np.asarray(ts.data[:])
                if scale != 1.0 or offset != 0.0:
                    values = values.astype(float) * scale + offset
                out[name] = TimeSeries(times=times, values=values, unit=ts.unit or "", name=f"{path}/{name}")
            return out

    def _lazy(self, ts, scale: float, offset: float, name: str) -> LazyTimeSeries:
        """A series left in the file: its samples (and explicit timestamps) are read a window at a time."""
        h5 = self._h5file()
        data = h5[ts.data.name]
        common = dict(scale=scale, offset=offset, unit=ts.unit or "", name=name)
        if ts.timestamps is not None:
            return LazyTimeSeries(data, times=h5[ts.timestamps.name], **common)
        return LazyTimeSeries(data, start=float(ts.starting_time), rate=float(ts.rate), **common)
