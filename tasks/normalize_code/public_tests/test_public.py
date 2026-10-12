from package.rules import normalize_code

def test_normalizes_common_code():
    assert normalize_code("  ab  12 ") == "AB-12"

def test_preserves_punctuation_and_underscores():
    assert normalize_code("  a_b / c  ") == "A_B-/-C"
