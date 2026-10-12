from package.rules import normalize_code


def test_case_whitespace_and_punctuation_are_preserved():
    assert normalize_code("  a_b  /c ") == "A_B-/C"


def test_whitespace_only_is_empty():
    assert normalize_code(" \t\n") == ""


def test_tabs_newlines_and_repeated_whitespace_collapse():
    assert normalize_code(" ab\t\n12  ") == "AB-12"


def test_digits_and_existing_hyphens_remain():
    assert normalize_code("x-09  blue") == "X-09-BLUE"


def test_non_ascii_case_and_whitespace():
    assert normalize_code(" café\t42 ") == "CAFÉ-42"
