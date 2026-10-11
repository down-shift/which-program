from package.rules import safe_ratio

def test_zero_uses_default():
    assert safe_ratio(5, 0, default=-1) == -1

def test_negative_fraction_is_not_truncated():
    assert safe_ratio(-3, 2) == -1.5
