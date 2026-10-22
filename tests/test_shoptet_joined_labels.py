from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from bs4 import BeautifulSoup

from coffee_aggregator.sites.base import ProductRef
from conftest import adapter_for

if TYPE_CHECKING:
    from collections.abc import Callable

    from coffee_aggregator.models import Coffee
    from coffee_aggregator.platforms.shoptet import ShoptetSite

HIPPOCAFE = ("hippocafe", "shoptet_hippocafe", "detail_culi_pearl.html")
CAFEGAPE = ("cafegape", "shoptet_cafegape", "detail_colombia_excelso.html")


def _coffee(page: tuple[str, str, str], fixture_html: Callable[[str, str], str]) -> Coffee:
    return _parse(page[0], fixture_html(page[1], page[2]))


def _parse(site_id: str, html: str) -> Coffee:
    site = cast("ShoptetSite", adapter_for(site_id))
    coffee = site.parse_product(html, ProductRef(site_id, "1", f"{site.base_url}p/"))
    assert coffee is not None
    return coffee


def _weights(coffee: Coffee) -> dict[str | None, int | None]:
    return {variant.external_id: variant.weight_g for variant in coffee.variants}


def test_hippocafe_names_the_weight_in_its_joined_label(
    fixture_html: Callable[[str, str], str],
) -> None:
    """`Druh kávy: Zrnková, Hmotnost: 250g` weighs 250 g; the sku suffix says nothing."""
    weights = _weights(_coffee(HIPPOCAFE, fixture_html))

    assert weights["77/ZRN3"] == 250
    assert weights["77/ZRN2"] == 150
    assert weights["77/ZRN5"] == 1000
    assert weights["77/ZRN4"] == 500
    assert weights["77/MLE3"] == 250


def test_cafegape_names_the_weight_in_its_size_label(
    fixture_html: Callable[[str, str], str],
) -> None:
    """`Velikost balení: 250 g` is the whole label of a shop with one parameter."""
    weights = _weights(_coffee(CAFEGAPE, fixture_html))

    assert weights == {"2166/503": 250, "2166/504": 500}


def test_the_weight_moves_no_price(fixture_html: Callable[[str, str], str]) -> None:
    hippocafe = _coffee(HIPPOCAFE, fixture_html)
    cafegape = _coffee(CAFEGAPE, fixture_html)

    assert {v.external_id: v.price for v in hippocafe.variants}["77/ZRN2"] == 199.0
    assert {v.external_id: v.price for v in cafegape.variants} == {
        "2166/503": 209.0,
        "2166/504": 399.0,
    }


def test_the_chooser_prices_the_250_g_option(fixture_html: Callable[[str, str], str]) -> None:
    """With weights read, hippocafe 77 is 330 Kč for 250 g and cafegape 2166 209 Kč."""
    hippocafe = _coffee(HIPPOCAFE, fixture_html)
    cafegape = _coffee(CAFEGAPE, fixture_html)

    assert (hippocafe.price, hippocafe.weight_g) == (330.0, 250)
    assert (cafegape.price, cafegape.weight_g) == (209.0, 250)
    assert cafegape.price_per_kg == 836.0


def test_the_variant_is_named_by_the_page_label(fixture_html: Callable[[str, str], str]) -> None:
    variants = {v.external_id: v for v in _coffee(HIPPOCAFE, fixture_html).variants}

    assert variants["77/ZRN3"].label == "Druh kávy: Zrnková, Hmotnost: 250g"


@pytest.mark.parametrize("axis", ["Hmotnost", "Velikost balení", "Množství", "Gramáž"])
def test_every_size_axis_the_vocabulary_knows_gives_a_weight(
    axis: str, fixture_html: Callable[[str, str], str]
) -> None:
    html = fixture_html(HIPPOCAFE[1], HIPPOCAFE[2]).replace("Hmotnost:", f"{axis}:")

    assert _weights(_parse("hippocafe", html))["77/ZRN3"] == 250


def test_a_decimal_comma_inside_the_size_is_not_a_separator(
    fixture_html: Callable[[str, str], str],
) -> None:
    html = fixture_html(HIPPOCAFE[1], HIPPOCAFE[2]).replace("Hmotnost: 250g", "Hmotnost: 0,25 kg")

    assert _weights(_parse("hippocafe", html))["77/ZRN3"] == 250


def test_a_label_without_a_size_axis_gives_no_weight(
    fixture_html: Callable[[str, str], str],
) -> None:
    """`Chuť: 250g` names no size, and the sku `77/ZRN3` states none either."""
    html = fixture_html(HIPPOCAFE[1], HIPPOCAFE[2]).replace("Hmotnost:", "Chuť:")
    coffee = _parse("hippocafe", html)

    assert set(_weights(coffee).values()) == {None}
    assert {v.external_id: v.price for v in coffee.variants}["77/ZRN3"] == 330.0


def test_a_page_without_tracking_data_gives_no_weight_and_keeps_its_prices(
    fixture_html: Callable[[str, str], str],
) -> None:
    """Without the sku-to-radio key nothing is matched by position."""
    soup = BeautifulSoup(fixture_html(HIPPOCAFE[1], HIPPOCAFE[2]), "html.parser")
    for script in soup.select("script#trackingScript"):
        script.decompose()
    coffee = _parse("hippocafe", str(soup))

    assert set(_weights(coffee).values()) == {None}
    assert {v.external_id: v.price for v in coffee.variants}["77/ZRN5"] == 1190.0


def test_a_radio_that_tracking_data_maps_to_another_sku_weighs_that_sku(
    fixture_html: Callable[[str, str], str],
) -> None:
    """The match goes through the radio value, so shuffled offers keep their own weight."""
    html = fixture_html(CAFEGAPE[1], CAFEGAPE[2])
    soup = BeautifulSoup(html, "html.parser")
    offers = soup.select("[itemprop=offers]")
    parent = offers[0].parent
    assert parent is not None
    parent.insert(parent.index(offers[0]), offers[1].extract())

    assert _weights(_parse("cafegape", str(soup))) == {"2166/504": 500, "2166/503": 250}
