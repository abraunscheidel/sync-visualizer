import pytest

from syncviz import plugins
from syncviz.sources import Source


def test_nwb_source_discovered_via_entry_point():
    pytest.importorskip("syncviz_nwb")

    cls = plugins.load("sources", "nwb")

    assert issubclass(cls, Source)


def test_unknown_plugin_lists_available():
    with pytest.raises(KeyError, match="available"):
        plugins.load("sources", "does-not-exist")
