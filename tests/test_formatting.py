"""Dates and times: read from the forms data comes in, shown in one standard way the project can change."""

from datetime import date, datetime, timezone

import pytest

from syncviz.formatting import DateFormat, parse_datetime


@pytest.mark.parametrize("text", ["20230415", "2023-04-15", "2023/04/15", "2023_04_15", "2023.04.15"])
def test_a_date_is_read_in_every_year_first_spelling(text):
    assert parse_datetime(text) == datetime(2023, 4, 15)


@pytest.mark.parametrize("text", ["20230415T101530", "2023-04-15 10:15:30", "2023-04-15T10:15:30", "20230415_101530"])
def test_a_date_and_time_is_read_with_or_without_separators(text):
    assert parse_datetime(text) == datetime(2023, 4, 15, 10, 15, 30)


def test_a_time_zone_is_kept():
    assert parse_datetime("2023-04-15T10:15:30Z").utcoffset().total_seconds() == 0
    assert parse_datetime("2023-04-15T10:15:30+02:00").utcoffset().total_seconds() == 7200
    assert parse_datetime("2023-04-15 10:15 -0530").utcoffset().total_seconds() == -19800


@pytest.mark.parametrize("text", ["15/04/2023", "04/15/2023", "soon", "", "2023-13-40", "219CR", "12345678"])
def test_ambiguous_or_impossible_text_is_not_guessed_at(text):
    assert parse_datetime(text) is None


def test_objects_pass_through():
    assert parse_datetime(date(2023, 4, 15)) == datetime(2023, 4, 15)
    moment = datetime(2023, 4, 15, 9, 5, tzinfo=timezone.utc)
    assert parse_datetime(moment) is moment


def test_the_standard_is_iso_8601_with_a_24_hour_clock():
    fmt = DateFormat()
    assert fmt.show("20230415", "date") == "2023-04-15"
    assert fmt.show("20230415T214500", "datetime") == "2023-04-15 21:45"
    assert fmt.show(datetime(2023, 4, 15, 21, 45, tzinfo=timezone.utc)) == "2023-04-15 21:45 UTC"


def test_auto_shows_a_date_alone_unless_there_is_a_time_of_day():
    fmt = DateFormat()
    assert fmt.show("20230415") == "2023-04-15" and fmt.show("20230415T0830") == "2023-04-15 08:30"


def test_a_project_picks_a_preset_or_its_own_pattern():
    assert DateFormat.from_config({"date": "eu"}).show("20230415", "date") == "15/04/2023"
    assert DateFormat.from_config({"date": "long"}).show("20230415", "date") == "15 April 2023"
    assert DateFormat.from_config({"date": "%b %d, %Y"}).show("20230415", "date") == "Apr 15, 2023"
    assert DateFormat.from_config({"datetime": "us"}).show("20230415T214500", "datetime") == "04/15/2023 09:45 PM"
    assert DateFormat.from_config(None) == DateFormat()


def test_text_that_is_not_a_date_is_shown_as_it_was():
    assert DateFormat().show("219CR", "date") == "219CR"


# -- in a project --------------------------------------------------------------------------------------------------
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pynwb")

from PySide6.QtWidgets import QApplication

from syncviz_app.app import build_window
from syncviz_app.project import load_project

from test_collections import _write_session


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _project(tmp_path, extra=""):
    data = tmp_path / "data"
    for mouse, day in [("219CR", "20230415"), ("219CR", "20230502"), ("229CR", "20230502")]:
        (data / f"sub-{mouse}").mkdir(parents=True, exist_ok=True)
        _write_session(data / f"sub-{mouse}" / f"sub-{mouse}_ses-{day}.nwb", [(0, 2.0, "convex")])
    (tmp_path / "project.yaml").write_text(f"""
name: dated
sources:
  session: {{type: nwb, path: "{{path}}"}}
collections:
  label: Session
  from: {{glob: "data/*/*.nwb"}}
  attributes: {{mouse: 'sub-([^_/]+)_', day: 'ses-(\\d{{8}})'}}
  attribute_types: {{day: date}}
  attribute_labels: {{mouse: {{label: Mouse, plural: mice}}}}
  title: "{{mouse}} · {{day}}"
{extra}
segmentations:
  trials: {{label: Trial, from: "session:intervals/trials"}}
views: []
""", encoding="utf-8")
    return tmp_path / "project.yaml"


def test_the_picker_names_a_session_by_its_attributes_with_dates_in_the_standard_form(tmp_path):
    titles = [c.title for c in load_project(_project(tmp_path)).collections]
    assert titles == ["219CR · 2023-04-15", "219CR · 2023-05-02", "229CR · 2023-05-02"]


def test_the_projects_display_setting_changes_every_date(tmp_path, qapp):
    path = _project(tmp_path, "display: {date: long}")
    assert load_project(path).collections[0].title == "219CR · 15 April 2023"
    window = build_window(path, use_workspace=False)
    try:
        box = window.collection_bar._filters["day"]
        assert [box.itemText(i) for i in range(box.count())][1:] == ["15 April 2023 (1 session)", "02 May 2023 (2 sessions)"]
        assert box.itemData(1) == "20230415"                                  # the value filtered on is untouched
    finally:
        window.close()


def test_a_date_in_a_units_metadata_is_shown_in_the_standard_form():
    from syncviz.inspection import metadata_fields
    fields = metadata_fields({"recorded": datetime(2023, 4, 15, 21, 45), "day": date(2023, 4, 15), "depth": 437.0})
    assert {f.name: f.value for f in fields} == {"recorded": "2023-04-15 21:45", "day": "2023-04-15", "depth": "437"}
