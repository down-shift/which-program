from package.rules import safe_ratio

def test_fractional_ratio():
    assert safe_ratio(3, 2) == 1.5
