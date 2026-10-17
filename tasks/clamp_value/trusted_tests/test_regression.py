import pytest
from package.rules import clamp_value


def test_reversed_bounds_are_rejected():
    for value in (-10, 2, 20):
        with pytest.raises(ValueError):
            clamp_value(value, 5, 1)


def test_equal_bounds():
    assert clamp_value(-5, 2, 2) == 2
    assert clamp_value(10, 2, 2) == 2


def test_negative_and_fractional_bounds():
    assert clamp_value(-9, -3.5, -0.5) == -3.5
    assert clamp_value(0, -3.5, -0.5) == -0.5
    assert clamp_value(-1.25, -3.5, -0.5) == -1.25
