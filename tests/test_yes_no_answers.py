from __future__ import annotations

import pytest

from coffee_aggregator.labels import F_DECAF, F_GRIND, LABEL_MAP, Labels, is_decaf, stated_grind
from coffee_aggregator.labels.collect import Answer


@pytest.mark.parametrize(
    ("label", "value", "expected"),
    [
        ("Decaf - bez kofeínu", "Nie", False),
        ("Decaf - bez kofeínu", "Áno", True),
        ("Decaf - bez kofeínu", "Ne", False),
        ("Decaf - bez kofeínu", "Ano", True),
        ("Decaf - bez kofeínu", "No", False),
        ("Decaf - bez kofeínu", "Yes", True),
        ("Decaf - bez kofeínu", "Espresso", None),
        ("Bezkofeinová káva", "Ne", False),
        ("Obsah kofeinu", "Nie", None),
        ("Obsah kofeinu", "Áno", None),
    ],
)
def test_a_decaf_question_is_answered_by_its_value(
    label: str, value: str, expected: bool | None
) -> None:
    """A yes or no under a label that asks about decaf is an answer; under any other it is none."""
    labels = Labels()
    labels.add(label, value, LABEL_MAP)
    assert is_decaf(labels, "Panama Geisha", []) is expected


def test_a_no_never_overrules_decaf_wording_in_the_name() -> None:
    labels = Labels()
    labels.add("Decaf - bez kofeínu", "Nie", LABEL_MAP)
    assert is_decaf(labels, "Bezkofeinová Etiopie", []) is True


def test_an_empty_answer_is_neither_yes_nor_no() -> None:
    labels = Labels()
    labels.add("Decaf - bez kofeínu", "", LABEL_MAP)
    assert labels.answer(F_DECAF) is None
    assert is_decaf(labels, "Panama Geisha", []) is None


def test_a_field_reader_sees_the_label_its_value_answers() -> None:
    labels = Labels()
    labels.add("KÁVU NAMELTE NA", "Ne", LABEL_MAP)
    labels.add("Decaf - bez kofeínu", "Nie", LABEL_MAP)
    assert labels.answer(F_GRIND) == Answer("KÁVU NAMELTE NA", "Ne")
    assert labels.answer(F_DECAF) == Answer("Decaf - bez kofeínu", "Nie")
    assert Labels().answer(F_DECAF) is None


def test_ne_is_whole_bean_under_grind_and_caffeinated_under_decaf() -> None:
    """The same word answers two questions, and the two readings are opposite."""
    grind = Labels()
    grind.add("KÁVU NAMELTE NA", "Ne", LABEL_MAP)
    decaf = Labels()
    decaf.add("Decaf - bez kofeínu", "Ne", LABEL_MAP)
    assert stated_grind(grind.get(F_GRIND)) == "whole"
    assert is_decaf(decaf, "Panama Geisha", []) is False
