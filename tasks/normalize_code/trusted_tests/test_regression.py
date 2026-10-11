from package.rules import normalize_code

def test_whitespace_case_and_punctuation():
    assert normalize_code("  a_b  /c ") == "A_B-/C"

def test_whitespace_only():
    assert normalize_code(" \t\n") == ""
