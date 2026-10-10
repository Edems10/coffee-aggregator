import pytest

from coffee_aggregator.labels import F_BREWING, F_GRIND, LABEL_MAP, Labels, stated_grind


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("zrnková", "whole"),
        ("chci zrnkovou", "whole"),
        ("celá zrna", "whole"),
        ("nemletá", "whole"),
        ("bez mletia", "whole"),
        ("Ne", "whole"),
        ("mletá", "ground"),
        ("namletá", "ground"),
        ("pomletá", "ground"),
        ("Áno", "ground"),
        ("zrnková nebo mletá", None),
        ("Espresso, Filtr", None),
        ("", None),
        (None, None),
    ],
)
def test_stated_grind_reads_only_a_grind_statement(value: str | None, expected: str | None) -> None:
    assert stated_grind(value) == expected


def test_a_grind_answer_is_kept_as_a_grind_statement() -> None:
    labels = Labels()
    labels.add("Mletí", "Ne", LABEL_MAP)
    assert labels.get(F_GRIND) == "Ne"
    assert labels.get(F_BREWING) is None


def test_a_grind_selector_offering_brewing_methods_stays_brewing() -> None:
    value = "Espresso +10 Kč, Filtr +10 Kč, Turek +10 Kč, Moka +10 Kč, French press +10 Kč"
    labels = Labels()
    labels.add("Kávu namelte na", value, LABEL_MAP)
    assert labels.get(F_BREWING) == value
    assert labels.get(F_GRIND) is None


def test_a_selector_offering_whole_and_ground_keeps_its_brewing_answers() -> None:
    value = "zrnková, mletá na zalévanou kávu, mletá na french press"
    labels = Labels()
    labels.add("Zrnkovou nebo mletou kávu?", value, LABEL_MAP)
    assert labels.get(F_BREWING) == value
    assert labels.get(F_GRIND) is None
