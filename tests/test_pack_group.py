from __future__ import annotations

import pytest

from coffee_aggregator.pack_group import PACK_GROUP_KEY_SOURCE, pack_group_key

FATHERS = "https://fathers.example/kava/{kind}/uganda-zebigi"
KAVA = "Pellini Espresso Bar n°4 Crema Tradizionale"


def key(name: str, url: str | None = None, site: str = "s") -> str:
    return pack_group_key(site, name, url)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(f"{KAVA} 1 kg", f"{KAVA} 6 kg", id="kava-pellini-1-6-kg"),
        pytest.param(f"{KAVA} 1 kg", f"{KAVA} 24 kg", id="kava-pellini-1-24-kg"),
        pytest.param(
            "Středně hořká káva KLASA 100g",
            "Středně hořká káva KLASA 1000g",
            id="vrescaffe-kava-word-removed",
        ),
        pytest.param(
            "Illy Classico zrnková káva 250 g",
            "Illy Classico mletá 250 g",
            id="ground-is-the-same-coffee",
        ),
        pytest.param(
            "BANUA Café 250 g", "BANUA Café 5 kg (20x250g)", id="bundle-is-the-same-coffee"
        ),
        pytest.param("X 250g 6ks", "X 250 g", id="carton-is-the-same-coffee"),
        pytest.param("X 3x250g", "X 3 \u00d7 250 g", id="multiplication-sign"),
        pytest.param("X 12 kusů", "X", id="count-word-kusu"),
        pytest.param("X 1 kg", "X 1kg", id="spaced-and-glued-unit"),
        pytest.param("X pcs 6 pcs", "X pcs", id="count-in-pieces"),
        pytest.param("Blend 24/7 (500 g)", "Blend 24/7 (1 kg)", id="ratio-kept-weight-removed"),
        pytest.param("X Whole Bean 1 kg", "X Ground 250 g", id="english-form-words"),
        pytest.param("Brazílie Cerrado", "Brazilie Cerrado", id="diacritics-fold"),
        pytest.param("Brazílie  Cerrado!", "brazilie cerrado", id="case-and-punctuation"),
    ],
)
def test_the_same_coffee_shares_a_key(first: str, second: str) -> None:
    assert key(first) == key(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param("Brazil Santos decaf 250 g", "Brazil Santos 250 g", id="decaf"),
        pytest.param("Brazil Santos dekaf 250 g", "Brazil Santos 250 g", id="dekaf"),
        pytest.param("Colombia bez kofeinu 250g", "Colombia 250g", id="decaf-in-czech"),
        pytest.param("Colombia bezkofeinová káva", "Colombia káva", id="bezkofeinova"),
        pytest.param(
            "Kolumbie Huila (espresso) 250 g",
            "Kolumbie Huila (filtr) 1 kg",
            id="roast-word-in-the-name",
        ),
        pytest.param(
            "Lavazza Qualità Oro 1 kg", "Lavazza Qualità Rossa 1 kg", id="different-coffees"
        ),
        pytest.param("Blend 75/25 250 g", "Blend 25/75 250 g", id="ratio-is-not-a-weight"),
        pytest.param(f"{KAVA} 1 kg", "Pellini Espresso Bar n°3 Crema Tradizionale 1 kg", id="n4"),
    ],
)
def test_different_coffees_do_not_share_a_key(first: str, second: str) -> None:
    assert key(first) != key(second)


def test_decaf_words_survive_the_removals() -> None:
    assert key("Decaf zrnková káva 250 g") == "s/decaf"
    assert key("Colombia bez kofeinu mletá 250g") == "s/colombia bez kofeinu"


def test_the_url_tells_espresso_from_filter_when_the_name_does_not() -> None:
    espresso = key("Uganda – Zebigi", FATHERS.format(kind="espresso"))
    filtr = key("Uganda – Zebigi", FATHERS.format(kind="filtr"))
    assert espresso != filtr
    assert espresso.endswith("#espresso")
    assert filtr.endswith("#filter")


def test_a_roast_word_in_the_name_wins_over_the_url() -> None:
    assert key("Zen espresso", FATHERS.format(kind="filtr")) == "s/zen espresso"


@pytest.mark.parametrize(
    "url",
    [
        pytest.param(None, id="none"),
        pytest.param("", id="empty"),
        pytest.param("https://x.example/kava/uganda-zebigi", id="neither"),
        pytest.param("https://x.example/espresso/filtr/uganda-zebigi", id="both"),
        pytest.param("https://espresso.example/kava/uganda-zebigi", id="host-is-not-read"),
    ],
)
def test_a_url_that_states_one_roast_kind_only_adds_a_suffix(url: str | None) -> None:
    assert key("Uganda Zebigi", url) == "s/uganda zebigi"


def test_the_site_is_part_of_the_key() -> None:
    assert key("Honduras 250 g", site="a") != key("Honduras 250 g", site="b")


def test_a_name_of_removable_words_does_not_collapse_into_one_group() -> None:
    assert key("Káva 250 g") != key("Zrnková 1 kg")
    assert key("Káva 250 g") != ""


def test_the_rule_version_is_name_v1() -> None:
    assert PACK_GROUP_KEY_SOURCE == "name:v1"
