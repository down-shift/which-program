from package.rules import normalize_code

def test_normalizes_common_code():
    assert normalize_code("  ab  12 ") == "AB-12"
