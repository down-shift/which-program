from package.rules import safe_ratio

def test_fractional_ratio():
    assert safe_ratio(3, 2) == 1.5

def test_negative_ratio_and_zero_fallback():
    assert safe_ratio(-3, 2) == -1.5
    assert safe_ratio(3, 0) == 0.0
