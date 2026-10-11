from __future__ import annotations

import pytest

from coffee_aggregator.labels import LABEL_MAP, Labels, parse_origin, parse_species


def labelled(*pairs: tuple[str, str]) -> Labels:
    labels = Labels()
    for label, value in pairs:
        labels.add(label, value, LABEL_MAP)
    return labels


def is_blend(name: str, *pairs: tuple[str, str]) -> bool | None:
    return parse_species(labelled(*pairs), name).is_blend


# --- a page that states a blend says so ----------------------------------------


def test_a_species_split_across_two_species_is_a_blend() -> None:
    assert is_blend("Espresso", ("Druh", "90 % Arabika, 10 % Robusta")) is True


def test_the_word_smes_in_the_name_is_a_blend() -> None:
    assert is_blend("Kávová směs Espresso") is True


def test_a_kind_row_filing_the_coffee_among_blends_is_a_blend() -> None:
    assert is_blend("Káva Oliver Klasik 250g", ("KATEGORIE", "Kávové směsi")) is True


def test_a_general_information_row_stating_a_blend_is_a_blend() -> None:
    """The row that makes kavaoliver's Klasik, Premium and Excelent blends."""
    assert (
        is_blend(
            "Káva Oliver Klasik 250g",
            ("OBECNÉ INFORMACE", "Kávová směs: 3 druhů výběrových káv"),
        )
        is True
    )


def test_a_bare_smes_origin_is_a_blend_and_names_no_country() -> None:
    labels = labelled(("ZEMĚ PŮVODU", "Směs"))
    assert parse_species(labels, "Zrnková káva").is_blend is True
    assert parse_origin(labels, "Zrnková káva", blend=True).country is None


def test_the_shops_own_description_calling_it_a_blend_is_a_blend() -> None:
    assert (
        is_blend(
            "Káva Oliver Klasik 250g",
            ("OG_DESCRIPTION", "Perfektně sladěná kávová směs ze 3 druhů káv."),
        )
        is True
    )


def test_mixteca_in_a_description_is_not_a_mix() -> None:
    assert is_blend("Káva ze čtvrti", ("OG_DESCRIPTION", "Pěstitelé z oblasti Mixteca.")) is None


# --- a page that states nothing is unknown, never single origin ---------------


def test_a_page_stating_nothing_about_blending_gives_none_not_false() -> None:
    assert is_blend("Espresso Classic 250g") is None


def test_unrelated_labels_leave_the_blend_unknown() -> None:
    pairs = (("ODRŮDA", "coffea arabica"), ("ZPRACOVÁNÍ", "mokrá"))
    assert is_blend("Espresso Classic", *pairs) is None


def test_a_description_without_a_blend_word_leaves_it_unknown() -> None:
    assert is_blend("Espresso", ("OG_DESCRIPTION", "Sladká a jemná káva s tóny karamelu.")) is None


# --- a page stating single origin says false ----------------------------------


def test_a_single_origin_kind_row_is_false() -> None:
    assert is_blend("Brasil Santos", ("KATEGORIE", "Jednodruhové plantážní kávy")) is False


def test_a_single_origin_category_in_english_is_false() -> None:
    assert is_blend("Brazil Cerrado", ("KATEGORIE", "Výběrové kávy Single Origin")) is False


def test_a_single_origin_wording_in_the_origin_row_is_false() -> None:
    labels = labelled(("ZEMĚ PŮVODU A SLOŽENÍ", "100% Arabica z Kolumbie (Single Origin)."))
    assert parse_species(labels, "Výběrová instantní káva").is_blend is False


def test_one_origin_country_on_the_page_is_single_origin() -> None:
    assert is_blend("Colombia Suukala", ("ZEMĚ PŮVODU", "Kolumbie · Cauca")) is False


def test_a_single_country_in_the_name_is_single_origin() -> None:
    assert is_blend("Ethiopie Keramo G1") is False


def test_two_countries_in_the_name_are_not_single_origin() -> None:
    assert is_blend("Jacobs Fusion Brazil & Colombia") is None


def test_a_farm_name_alone_is_no_evidence_either_way() -> None:
    """A farm label can name two places, and a blend lists its components' farms."""
    labels = labelled(("FARMA", "Tolima a Valle Del Cauca"))
    assert parse_species(labels, "Espresso Automat").is_blend is None


def test_a_blend_lists_its_component_farms_and_stays_a_blend() -> None:
    labels = labelled(("FARMA", "Fazenda Sertao"), ("DRUH KÁVY", "Zmes / Blend"))
    assert parse_species(labels, "Dark Star Blend").is_blend is True


def test_a_meta_text_calling_it_single_origin_is_single_origin() -> None:
    labels = labelled(("META_DESCRIPTION", "Jednodruhová arabika z Brazílie bez kofeinu."))
    assert parse_species(labels, "Decaffeinated Coffee").is_blend is False


def test_a_meta_text_naming_two_countries_is_not_single_origin() -> None:
    labels = labelled(("OG_DESCRIPTION", "Káva z Kolumbie nebo z Etiopie."))
    assert parse_species(labels, "Espresso Morning").is_blend is None


def test_a_name_and_origin_row_naming_different_countries_are_not_single_origin() -> None:
    labels = labelled(("ZEMĚ PŮVODU", "Uganda"))
    assert parse_species(labels, "Kongo Kisunga 250g").is_blend is None


def test_one_species_at_100_percent_alone_is_unknown_not_single_origin() -> None:
    """A blend of one species from several origins reads the same as a single origin."""
    assert is_blend("Caffe Borbone 100% Arabica", ("DRUH", "100 % Arabika")) is None


def test_one_species_at_100_percent_with_a_named_country_is_single_origin() -> None:
    assert is_blend("Brazílie Santos", ("DRUH", "100 % Arabika")) is False


# --- contradictions and lists are not guessed at -------------------------------


def test_a_blend_and_a_single_origin_kind_contradict_to_none() -> None:
    assert (
        is_blend(
            "Espresso směs",
            ("KATEGORIE", "Jednodruhové kávy"),
        )
        is None
    )


def test_a_kind_row_listing_both_kinds_claims_nothing() -> None:
    assert is_blend("Espresso Morning", ("KATEGORIE", "Kávové směsi a jednodruhová káva")) is None


def test_a_tasting_set_is_not_judged_by_one_blend_word_about_a_member() -> None:
    assert (
        is_blend(
            "Ochutnávková sada espresso káv 3x70g",
            ("OG_DESCRIPTION", "Vyberte si espresso směs nebo jednodruhovou kávu."),
        )
        is None
    )


# --- the vocabulary keeps what it cannot use as a field ------------------------


@pytest.mark.parametrize("label", ["ZEMĚ PŮVODU", "Země původu"])
def test_an_implausible_origin_is_still_a_stated_value(label: str) -> None:
    labels = labelled((label, "Směs"))
    assert labels.get("country") is None
    assert labels.stated["country"] == ["Směs"]


# --- a count of varieties is not a share of the species -------------------------


def test_a_variety_count_before_the_species_name_is_not_a_percentage() -> None:
    # zlatezrnko's "Zmes 6-7 arabík" is a blend of six or seven arabica varieties.
    labels = labelled(("ARABIKA", "Zmes 6-7 arabík"))
    species = parse_species(labels, "Káva Zlaté Zrnko – Emília (Zmes 100% arabika)")
    assert (species.arabica_pct, species.robusta_pct) == (None, None)
    assert species.is_blend is True
