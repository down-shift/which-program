from package.rules import unique_items


def test_removes_duplicates():
    assert unique_items([1, 1, 2, 2, 3]) == [1, 2, 3]


def test_empty_input():
    assert unique_items([]) == []
