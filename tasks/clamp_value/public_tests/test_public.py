from package.rules import clamp_value


def test_clamps_both_bounds():
    assert clamp_value(-2, 0, 10) == 0
    assert clamp_value(12, 0, 10) == 10


def test_preserves_in_range_fraction():
    assert clamp_value(2.75, 0, 10) == 2.75
