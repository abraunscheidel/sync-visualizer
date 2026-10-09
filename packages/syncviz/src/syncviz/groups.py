"""Groups: a named set of items from one container, chosen by a rule or listed by hand (design doc 28.9, 28.16).

An item is one member of a container of event series, such as one unit of a recording's units. A group is a *predicate* over those items,
so it is not tied to one recording:

* a **rule** ("layer is 4", "depth from 700") is asked of each item's own attributes, so it picks the right items in every session,
  whichever units that session happens to have;
* a **list** of member ids belongs to the recording the ids come from.

A saved item filter and a group are the same thing. Nothing here knows what the items are; the attributes are whatever the source
attached to them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

from syncviz.resources.events import EventSeries


@dataclass(frozen=True)
class Group:
    name: str
    of: str                                                   # "source:path" of the container whose members are grouped
    where: dict = field(default_factory=dict)                 # rule: attribute -> value, list of values, or {min, max}; all must hold
    members: tuple[str, ...] | None = None                    # or the member ids, by hand (then `where` is not used)
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a group needs a name")
        if not self.where and self.members is None:
            raise ValueError(f"group {self.name!r} needs a rule or a list of members")

    @property
    def by_rule(self) -> bool:
        return self.members is None

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"of": self.of}
        if self.members is not None:
            out["members"] = list(self.members)
        else:
            out["where"] = dict(self.where)
        if self.description:
            out["description"] = self.description
        return out

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "Group":
        members = data.get("members")
        return cls(str(name), str(data["of"]), dict(data.get("where") or {}),
                   None if members is None else tuple(str(m) for m in members), str(data.get("description", "")))


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def value_matches(actual, wanted) -> bool:
    """Whether an item's attribute value satisfies one rule: equal to a value (compared as text when they are not numbers), one of a
    list of values, or inside `{min: , max: }` (either may be left out; both ends are included)."""
    if isinstance(wanted, dict):
        number = _number(actual)
        if number is None:
            return False
        low, high = wanted.get("min"), wanted.get("max")
        return (low is None or number >= float(low)) and (high is None or number <= float(high))
    if isinstance(wanted, (list, tuple, set)):
        return any(value_matches(actual, w) for w in wanted)
    a, w = _number(actual), _number(wanted)
    if a is not None and w is not None and not isinstance(actual, str):
        return a == w
    return str(actual) == str(wanted)


def members_of(group: Group, attributes: dict[str, dict]) -> list[str]:
    """The ids of the items of a container that belong to `group`, in the container's order. `attributes` maps each item id to its own
    attributes. A listed id the container does not have is simply not there."""
    if group.members is not None:
        wanted = set(group.members)
        return [item for item in attributes if item in wanted]
    return [item for item, values in attributes.items()
            if all(key in values and value_matches(values[key], wanted) for key, wanted in group.where.items())]


def rule_text(group: Group) -> str:
    """The group in words, for a list or a tooltip."""
    if group.members is not None:
        return ", ".join(group.members) if group.members else "no members"
    parts = []
    for key, wanted in group.where.items():
        if isinstance(wanted, dict):
            low, high = wanted.get("min"), wanted.get("max")
            parts.append(f"{key} from {low:g} to {high:g}" if low is not None and high is not None else
                         f"{key} at least {low:g}" if low is not None else f"{key} at most {high:g}")
        elif isinstance(wanted, (list, tuple, set)):
            parts.append(f"{key} is " + " or ".join(str(w) for w in wanted))
        else:
            parts.append(f"{key} is {wanted}")
    return " and ".join(parts)


def attribute_values(attributes: dict[str, dict]) -> dict[str, list]:
    """For choosing a rule: each attribute that items have, with the distinct values it takes (sorted; numbers stay numbers)."""
    seen: dict[str, set] = {}
    for values in attributes.values():
        for key, value in values.items():
            seen.setdefault(key, set()).add(value)
    out = {}
    for key, found in seen.items():
        try:
            out[key] = sorted(found)
        except TypeError:
            out[key] = sorted(found, key=str)
    return out


def merge_events(series: Iterable[EventSeries], name: str = "", members: Iterable[str] = ()) -> EventSeries:
    """One stream with every event of every series, in time order: 'a unit of this group fired'."""
    series = list(series)
    times = np.sort(np.concatenate([s.times for s in series])) if series else np.zeros(0)
    return EventSeries(times=times, name=name, metadata={"members": list(members)})


def check_names(groups: Iterable[Group], taken: Iterable[str]) -> None:
    """Group names must be unique and must not be the name of an event the project already has (both appear in the same lists)."""
    names = [g.name for g in groups]
    clash = sorted(set(n for n in names if names.count(n) > 1) | (set(names) & set(taken)))
    if clash:
        raise ValueError(f"group name(s) already in use: {', '.join(clash)}")
