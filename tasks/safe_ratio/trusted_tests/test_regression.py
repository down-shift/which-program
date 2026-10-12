import pytest
from package.rules import safe_ratio


@pytest.mark.parametrize("numerator,denominator,expected", [
    (5, 0, -1), (5, 0, None), (0, 2, 0.0), (3, 2, 1.5),
    (-3, 2, -1.5), (3, -2, -1.5), (-3, -2, 1.5),
    (1.25, 0.5, 2.5), (10, 4, 2.5),
])
def test_ratio_edges_and_regular_values(numerator, denominator, expected):
    assert safe_ratio(numerator, denominator, default=expected if denominator == 0 else 99) == expected


def test_zero_uses_arbitrary_caller_default():
    assert safe_ratio(7, 0, default="missing") == "missing"


def test_zero_default_is_optional():
    assert safe_ratio(7, 0) == 0.0
