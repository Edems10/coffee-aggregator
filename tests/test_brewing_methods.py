from __future__ import annotations

import pytest

from coffee_aggregator.labels import (
    BREWING_METHODS,
    F_BREWING,
    LABEL_MAP,
    Labels,
    brewing_methods,
    option_list,
    parse_roast,
    parse_taste,
)
from coffee_aggregator.labels.terms import BREWING_METHOD_TERMS, BREWING_METHOD_WORDS
from coffee_aggregator.models import RoastProfile


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Espresso", "espresso"),
        ("espreso", "espresso"),
        ("páka", "espresso"),
        ("Pákový kávovar", "espresso"),
        ("Domáce espresso", "espresso"),
        ("moderné espresso", "espresso"),
        ("moka", "moka"),
        ("Mokka", "moka"),
        ("Mocca", "moka"),
        ("Moka konvička", "moka"),
        ("mokka kanvica", "moka"),
        ("Moka konvice", "moka"),
        ("koťogo", "moka"),
        ("Bialetti", "moka"),
        ("filtr", "filter"),
        ("Filter", "filter"),
        ("Filtrovaná káva", "filter"),
        ("Překapávač", "filter"),
        ("prekapávač", "filter"),
        ("Dripper", "filter"),
        ("drip", "filter"),
        ("V60", "filter"),
        ("Chemex", "filter"),
        ("Batch brew", "filter"),
        ("pour over", "filter"),
        ("Kalita", "filter"),
        ("French press", "french_press"),
        ("frenchpress", "french_press"),
        ("French-press", "french_press"),
        ("Aeropress", "aeropress"),
        ("turek", "turkish"),
        ("Český turek", "turkish"),
        ("Turecká káva", "turkish"),
        ("džezva", "turkish"),
        ("dzezva", "turkish"),
        ("jezva", "turkish"),
        ("ibrik", "turkish"),
        ("automat", "automatic"),
        ("Automatický kávovar", "automatic"),
        ("Automatické kávovary", "automatic"),
        ("plnoautomat", "automatic"),
        ("cold brew", "cold_brew"),
        ("Cold-brew", "cold_brew"),
    ],
)
def test_every_spelling_maps_to_its_method(value: str, expected: str) -> None:
    assert brewing_methods([value]) == [expected]


@pytest.mark.parametrize(
    "value",
    [
        "zrnko",
        "zrnková",
        "Zrnková káva",
        "Celá zrna",
        "Zrno (bez mletia)",
        "NEMLÍT - chci zrnka",
        "Standardní mletí",
        "bez mletia +€0",
        "Zalévaná",
        "Zalievaná",
        "Zalievanie",
        "mletá na zalévanou kávu",
        "Mletá káva do kávovaru",
        "Kávovar",
        "alternativní příprava",
        "alternatívne prípravy",
        "cappuccino",
        "vakuum pot)",
        "01",
        "",
    ],
)
def test_a_grind_an_ambiguous_word_or_an_unlisted_method_names_nothing(value: str) -> None:
    assert brewing_methods([value]) == []


def test_an_item_naming_two_methods_keeps_both_in_the_order_it_names_them() -> None:
    assert brewing_methods(["espresso (automat)"]) == ["espresso", "automatic"]
    assert brewing_methods(["automatické kávovary a koťogo"]) == ["automatic", "moka"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("namlet na french press", ["french_press"]),
        ("jemné mletie — espresso (domáca páka) +€0", ["espresso"]),
        ("veľmi jemné mletie — zalievaná káva +€0", []),
        ("Velmi jemně mletá - pro džezvu - 250g", ["turkish"]),
        ('Zaliju si "na turka"', ["turkish"]),
        ("Batch brew - Moccamaster", ["filter"]),
        ("Turecko", []),
        ("Coldbrew", ["cold_brew"]),
        ("turecké", ["turkish"]),
        ("tureckou kávu", ["turkish"]),
        ("Moccamaster", []),
    ],
)
def test_a_grind_phrase_keeps_the_method_it_names(value: str, expected: list[str]) -> None:
    assert brewing_methods([value]) == expected


@pytest.mark.parametrize(
    "value",
    [
        "Nevhodné pro espresso",
        "není vhodná na turka",
        "Není vhodné pro french press",
        "nie je vhodná na filter",
        "nedoporučujeme na espresso",
        "neodporúčame pre moka",
        "not suitable for aeropress",
        "ne pro espresso",
        "ne na espresso",
        "Není pro espresso",
        "Nelze použít na espresso",
        "Nehodí se na espresso",
        "Nepoužívejte v moka konvičce",
        "Není určena pro espresso",
        "Nie je určená na espresso",
    ],
)
def test_a_negated_suitability_statement_never_stores_the_method_it_negates(value: str) -> None:
    assert brewing_methods([value]) == []


@pytest.mark.parametrize(
    "value",
    [
        "Dolce Gusto espresso kapsle",
        "Instant espresso",
        "Nespresso kapsuly",
        "rozpustná káva na espresso",
    ],
)
def test_a_capsule_or_instant_product_names_no_method(value: str) -> None:
    assert brewing_methods([value]) == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("jemně na espresso", ["espresso"]),
        ("jemné pro espresso", ["espresso"]),
        ("stredne na filter", ["filter"]),
    ],
)
def test_a_negation_phrase_must_start_a_word(value: str, expected: list[str]) -> None:
    assert brewing_methods([value]) == expected


def test_a_negated_item_does_not_take_its_neighbours_with_it() -> None:
    assert brewing_methods(["Nevhodné pro espresso", "filtr"]) == ["filter"]


def test_a_bracketed_list_collapses_to_each_method_once_in_first_appearance_order() -> None:
    values = option_list("Espresso, espreso, Filter (chemex, V60)")
    assert brewing_methods(values) == ["espresso", "filter"]


def test_a_shared_spelling_across_shops_is_one_value() -> None:
    assert brewing_methods(["French press", "frenchpress", "FRENCH PRESS"]) == ["french_press"]


def test_every_term_belongs_to_a_method_and_every_method_has_terms() -> None:
    assert set(BREWING_METHOD_TERMS) == set(BREWING_METHODS)
    assert set(BREWING_METHOD_WORDS) <= set(BREWING_METHODS)
    assert all(BREWING_METHOD_TERMS[method] for method in BREWING_METHODS)


def test_the_vocabulary_is_exactly_the_eight_the_owner_chose() -> None:
    assert set(BREWING_METHODS) == {
        "espresso",
        "moka",
        "filter",
        "french_press",
        "aeropress",
        "turkish",
        "automatic",
        "cold_brew",
    }


def test_the_shared_parser_stores_the_closed_vocabulary() -> None:
    labels = Labels()
    labels.add("Doporučená příprava", "Espresso, espreso, Filter (chemex, V60), zrnková", LABEL_MAP)
    assert parse_taste(labels, None).brewing_methods == ["espresso", "filter"]


def test_the_roast_profile_still_reads_the_shops_own_brewing_words() -> None:
    labels = Labels()
    labels.add("Doporučená příprava", "Espresso, Filter (chemex, V60)", LABEL_MAP)
    assert labels.get(F_BREWING) == "Espresso, Filter (chemex, V60)"
    assert parse_roast(labels, []).profile is RoastProfile.OMNI
