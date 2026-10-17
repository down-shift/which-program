from package.rules import unique_items


def test_preserves_first_occurrence_order():
    assert unique_items([3, 1, 3, 2, 1]) == [3, 1, 2]


def test_accepts_generator_and_preserves_case():
    assert unique_items(x for x in ["b", "A", "b", "a", "A"]) == ["b", "A", "a"]


def test_mixed_hashable_types():
    assert unique_items(["x", 2, (1,), "x", 2]) == ["x", 2, (1,)]


def test_does_not_modify_input():
    items = [2, 1, 2]
    assert unique_items(items) == [2, 1]
    assert items == [2, 1, 2]
