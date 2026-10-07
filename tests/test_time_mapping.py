import numpy as np
import pytest

from syncviz.core import LinearTimeMapping, TimeMapping


def test_fit_recovers_known_linear_mapping():
    native = np.array([0.0, 1.0, 2.0, 5.0, 10.0])
    shared = 3.5 + 1.0002 * native

    mapping = LinearTimeMapping.fit(native, shared)

    assert mapping.offset == pytest.approx(3.5)
    assert mapping.scale == pytest.approx(1.0002)


def test_round_trip():
    mapping = LinearTimeMapping(offset=-12.0, scale=0.999)
    t = np.linspace(0, 100, 7)

    np.testing.assert_allclose(mapping.to_native(mapping.to_shared(t)), t)


def test_satisfies_protocol():
    assert isinstance(LinearTimeMapping.identity(), TimeMapping)


@pytest.mark.parametrize(
    "native, shared",
    [([1.0], [2.0]), ([1.0, 2.0], [1.0, 2.0, 3.0])],
)
def test_fit_rejects_bad_input(native, shared):
    with pytest.raises(ValueError):
        LinearTimeMapping.fit(native, shared)


def test_zero_scale_rejected():
    with pytest.raises(ValueError):
        LinearTimeMapping(scale=0.0)
