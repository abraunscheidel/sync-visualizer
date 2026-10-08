"""One place that reads dates and times from text and writes them for people.

The standard is ISO 8601: dates as `2023-04-15`, date and time as `2023-04-15 10:15` (24-hour). It is unambiguous across
countries and sorts correctly as text. A project can choose another display (`display:` in the project file) by naming a
preset or giving a `strftime` pattern; reading is unaffected, so data is never changed, only how it is shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

# Names a project can use instead of writing a pattern.
DATE_PRESETS = {
    "iso": "%Y-%m-%d",             # 2023-04-15  (the default)
    "us": "%m/%d/%Y",              # 04/15/2023
    "eu": "%d/%m/%Y",              # 15/04/2023
    "long": "%d %B %Y",            # 15 April 2023
    "short": "%d %b %Y",           # 15 Apr 2023
}
DATETIME_PRESETS = {
    "iso": "%Y-%m-%d %H:%M",       # 2023-04-15 10:15  (the default)
    "iso-seconds": "%Y-%m-%d %H:%M:%S",
    "us": "%m/%d/%Y %I:%M %p",     # 04/15/2023 10:15 AM
    "eu": "%d/%m/%Y %H:%M",        # 15/04/2023 10:15
    "long": "%d %B %Y, %H:%M",     # 15 April 2023, 10:15
    "short": "%d %b %Y %H:%M",     # 15 Apr 2023 10:15
}

# Year, month, day in the order they are written in file names and metadata, with an optional time after them.
_PATTERN = re.compile(
    r"""^\s*(?P<y>\d{4})[-/_.]?(?P<m>\d{2})[-/_.]?(?P<d>\d{2})
        (?:[T\s_-]?(?P<H>\d{2}):?(?P<M>\d{2})(?::?(?P<S>\d{2})(?:\.\d+)?)?)?
        \s*(?P<tz>Z|[+-]\d{2}:?\d{2})?\s*$""",
    re.VERBOSE,
)


def parse_datetime(value) -> datetime | None:
    """A date or date and time in any common year-first form, or None if `value` is not one.

    Reads `20230415`, `2023-04-15`, `2023/04/15`, `2023_04_15`, `20230415T101530`, `2023-04-15 10:15:30`,
    `2023-04-15T10:15:30+02:00` and the like, and passes through `datetime` and `date` objects. Day-first and
    month-first spellings (`15/04/2023`) are ambiguous and are not guessed at."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    match = _PATTERN.match(str(value))
    if not match:
        return None
    parts = match.groupdict()
    try:
        moment = datetime(int(parts["y"]), int(parts["m"]), int(parts["d"]),
                          int(parts["H"] or 0), int(parts["M"] or 0), int(parts["S"] or 0))
    except ValueError:                                      # month 13, day 40, ...
        return None
    zone = parts["tz"]
    if zone:
        if zone == "Z":
            return moment.replace(tzinfo=timezone.utc)
        sign = -1 if zone[0] == "-" else 1
        digits = zone[1:].replace(":", "")
        from datetime import timedelta
        return moment.replace(tzinfo=timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))))
    return moment


@dataclass(frozen=True)
class DateFormat:
    """How dates and date-times are shown. Each is a preset name or a `strftime` pattern."""

    date: str = "iso"
    datetime: str = "iso"

    @classmethod
    def from_config(cls, config: dict | None) -> "DateFormat":
        config = config or {}
        return cls(str(config.get("date", "iso")), str(config.get("datetime", "iso")))

    def format_date(self, moment: datetime) -> str:
        return moment.strftime(DATE_PRESETS.get(self.date, self.date))

    def format_datetime(self, moment: datetime) -> str:
        text = moment.strftime(DATETIME_PRESETS.get(self.datetime, self.datetime))
        if moment.tzinfo is not None:                       # say which clock when the data does
            offset = moment.utcoffset()
            text += " UTC" if not offset else f" {moment.strftime('%z')[:3]}:{moment.strftime('%z')[3:]}"
        return text

    def show(self, value, kind: str = "auto") -> str:
        """`value` written for people. `kind` is "date", "datetime", or "auto" (a date unless it has a time of day).
        Text that is not a date is returned as it was."""
        moment = parse_datetime(value)
        if moment is None:
            return str(value)
        if kind == "date" or (kind == "auto" and not (moment.hour or moment.minute or moment.second) and not
                              isinstance(value, datetime)):
            return self.format_date(moment)
        return self.format_datetime(moment)


DEFAULT = DateFormat()
