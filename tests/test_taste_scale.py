from __future__ import annotations

import pytest

from coffee_aggregator.labels import F_BODY, Labels, bar


def read(value: str | None) -> int | None:
    labels = Labels()
    if value is not None:
        labels.by_field[F_BODY] = value
    return bar(labels, F_BODY)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5/10", 3),
        ("1/10", 1),
        ("3/6", 3),
        ("1.5/5", 2),
        ("1,5/5", 2),
        ("1,5 / 5", 2),
        ("7/10", 4),
        ("0/5", 0),
        ("3/3", 5),
        ("8/8", 5),
        ("5 / 10", 3),
        ("Velmi nízká a příjemná (1.5/5) – káva je", 2),
        ("vysoká 3/10", 2),
    ],
)
def test_a_stated_scale_is_rescaled_to_five_rounding_half_up(value: str, expected: int) -> None:
    assert read(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "6/5",
        "4/3",
        "5.5/5",
        "1/0",
        "0/0",
        "vysoká 6/5",
        "střední, 4/3",
        "11/10",
        "střední, 11/10",
        "50%",
    ],
)
def test_a_stated_fraction_with_no_score_gives_none(value: str) -> None:
    assert read(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10/2024", None),
        ("2023/24", None),
        ("1/2 kg", 1),
        ("1/2kg", 1),
        ("1/10 g", 1),
        ("1/250 ml", 1),
        ("1/105 g", 1),
        ("vysoká, sklizeň 2023/24", 4),
        ("střední 2023/24", 3),
        ("1/2", 1),
    ],
)
def test_a_fraction_that_is_not_a_score_is_ignored(value: str, expected: int | None) -> None:
    assert read(value) == expected


def test_a_later_fraction_that_is_a_score_is_read() -> None:
    assert read("sklizeň 2023/24, intenzita 3/10") == 2


def test_the_first_fraction_that_is_a_score_decides() -> None:
    assert read("sklizeň 2023/24, 6/5, 3/10") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Velmi nízká", 2),
        ("vysoká", 4),
        ("střední", 3),
        ("4", 4),
        ("0", 0),
        ("4/5", 4),
        ("5/5", 5),
        ("Stredné, 50%", 3),
        ("●●○", None),
        ("", None),
        (None, None),
    ],
)
def test_a_value_without_a_stated_scale_reads_as_before(
    value: str | None, expected: int | None
) -> None:
    assert read(value) == expected
