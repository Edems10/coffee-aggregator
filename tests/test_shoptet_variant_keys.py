from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, cast

import pytest
from bs4 import BeautifulSoup

from coffee_aggregator.sites.base import ProductRef
from conftest import adapter_for

if TYPE_CHECKING:
    from collections.abc import Callable

    from bs4 import Tag

    from coffee_aggregator.models import Coffee, Variant
    from coffee_aggregator.platforms.shoptet import ShoptetSite

#: site, saved page, expected ``{sku: grams}`` as the page's own variant keys state them.
PAGES = {
    "botacoffee": (
        "detail_rwanda_gicumbi.html",
        {
            "5524/ZRN": 70,
            "5524/250": 250,
            "5524/251": 250,
            "5524/252": 250,
            "5524/253": 250,
            "5524/254": 250,
            "5524/255": 250,
            "5524/1 K": 1000,
        },
    ),
    "daliacoffee": (
        "detail_kenya_embu.html",
        {
            "1077/250/ST": 250,
            "1077/250/SV": 250,
            "1077/500": 500,
            "1077/501": 500,
            "1077/100": 1000,
            "1077/502": 1000,
        },
    ),
    "pepecoffee": (
        "detail_espresso_blend_office.html",
        {"69/503": 200, "69/250": 200, "69/504": 500, "69/505": 1000},
    ),
    "jungleroastery": (
        "detail_colombia_penas.html",
        {"106/252": 250, "106/250": 250, "106/251": 1000, "106/100": 1000},
    ),
}


def _html(fixture_html: Callable[[str, str], str], site_id: str) -> str:
    return fixture_html(f"shoptet_{site_id}", PAGES[site_id][0])


def _coffee(site_id: str, html: str) -> Coffee:
    site = cast("ShoptetSite", adapter_for(site_id))
    ref = ProductRef(site_id=site_id, external_id="1", url=f"{site.base_url}p/")
    coffee = site.parse_product(html, ref)
    assert coffee is not None
    return coffee


def _by_sku(coffee: Coffee) -> dict[str | None, Variant]:
    return {variant.external_id: variant for variant in coffee.variants}


def _weights(coffee: Coffee) -> dict[str | None, int | None]:
    return {sku: variant.weight_g for sku, variant in _by_sku(coffee).items()}


def _edit(html: str, change: Callable[[BeautifulSoup], None]) -> str:
    soup = BeautifulSoup(html, "html.parser")
    change(soup)
    return str(soup)


def _is_variant_data(script: object) -> bool:
    return "necessaryVariantData" in cast("Tag", script).get_text()


def _rewrite_variant_data(
    soup: BeautifulSoup, change: Callable[[dict[str, dict[str, str]]], object]
) -> None:
    script = next(tag for tag in soup.find_all("script") if _is_variant_data(tag))
    source = script.get_text()
    start = source.index("{", source.index("necessaryVariantData"))
    data, end = json.JSONDecoder().raw_decode(source, start)
    change(data)
    script.string = source[:start] + json.dumps(data) + source[end:]


def _drop_variant_data(soup: BeautifulSoup) -> None:
    for script in soup.find_all("script"):
        if _is_variant_data(script):
            script.decompose()


@pytest.mark.parametrize("site_id", sorted(PAGES))
def test_each_variant_weighs_what_its_key_says(
    site_id: str, fixture_html: Callable[[str, str], str]
) -> None:
    """The size parameter's value names the weight, whatever the sku suffix suggests."""
    coffee = _coffee(site_id, _html(fixture_html, site_id))

    assert _weights(coffee) == PAGES[site_id][1]


def test_a_radio_axis_names_the_70_g_pack(fixture_html: Callable[[str, str], str]) -> None:
    """botacoffee's 115 Kc option is a 70 g pack, named by a hidden span, not a select."""
    coffee = _coffee("botacoffee", _html(fixture_html, "botacoffee"))
    variants = _by_sku(coffee)

    assert (variants["5524/ZRN"].weight_g, variants["5524/ZRN"].price) == (70, 115.0)
    assert variants["5524/ZRN"].label == "70 g / Zrnková káva"
    assert variants["5524/1 K"].label == "1 kg / Zrnková káva"
    assert variants["5524/255"].label == "250 g / Velmi jemně mletá (český turek, džezva)"


def test_the_sku_suffix_does_not_decide_the_weight(
    fixture_html: Callable[[str, str], str],
) -> None:
    """Both suffixes mislead: `/100` is the 1000 g bag, `/250` the 200 g ground one."""
    dalia = _by_sku(_coffee("daliacoffee", _html(fixture_html, "daliacoffee")))
    pepe = _by_sku(_coffee("pepecoffee", _html(fixture_html, "pepecoffee")))

    assert (dalia["1077/100"].weight_g, dalia["1077/100"].price) == (1000, 1260.0)
    assert dalia["1077/250/SV"].label == "250 g / Světlé (filtr)"
    assert (pepe["69/250"].weight_g, pepe["69/250"].label) == (200, "200 g / Mletá")


def test_a_second_axis_does_not_shift_the_weights(
    fixture_html: Callable[[str, str], str],
) -> None:
    """jungleroastery lists its roast axis first, so a positional zip put 1000 g on 250 g bags."""
    coffee = _coffee("jungleroastery", _html(fixture_html, "jungleroastery"))

    assert {(variant.weight_g, variant.price, variant.currency) for variant in coffee.variants} == {
        (250, 17.3, "EUR"),
        (1000, 57.0, "EUR"),
    }
    assert [variant.label for variant in coffee.variants] == [
        "Filter - Light roast / 1000 g",
        "Espresso - moderné / 1000 g",
        "Filter - Light roast / 250 g",
        "Espresso - moderné / 250 g",
    ]


def test_the_product_weight_follows_the_variant_that_carries_its_price(
    fixture_html: Callable[[str, str], str],
) -> None:
    """pepecoffee's nearest pack is 200 g; botacoffee's 70 g sample gives way to the 250 g bag."""
    pepe = _coffee("pepecoffee", _html(fixture_html, "pepecoffee"))
    bota = _coffee("botacoffee", _html(fixture_html, "botacoffee"))

    assert (pepe.price, pepe.weight_g) == (220.0, 200)
    assert (bota.price, bota.weight_g) == (359.0, 250)


def test_the_rendered_code_spans_resolve_a_key_without_the_shipped_data(
    fixture_html: Callable[[str, str], str],
) -> None:
    """botacoffee also prints each key on its code span, which is enough on its own."""

    coffee = _coffee("botacoffee", _edit(_html(fixture_html, "botacoffee"), _drop_variant_data))

    assert _weights(coffee) == PAGES["botacoffee"][1]


def test_the_shipped_data_resolves_a_key_without_the_code_spans(
    fixture_html: Callable[[str, str], str],
) -> None:
    """pepecoffee hides its code, so the variant data is the only place the sku meets its key."""
    html = _html(fixture_html, "pepecoffee")

    assert not re.search(r'class="p-code"', html)
    assert _weights(_coffee("pepecoffee", html)) == PAGES["pepecoffee"][1]


def test_an_offer_whose_key_is_unstated_keeps_the_sku_guess_and_no_other_variant_moves(
    fixture_html: Callable[[str, str], str],
) -> None:
    """The suffix guess is the last resort: only the offer the page cannot resolve uses it."""

    def forget_ground(soup: BeautifulSoup) -> None:
        _rewrite_variant_data(soup, lambda data: data.pop("18-306-21-240"))

    coffee = _coffee("pepecoffee", _edit(_html(fixture_html, "pepecoffee"), forget_ground))
    variants = _by_sku(coffee)

    assert (variants["69/250"].weight_g, variants["69/250"].label) == (250, "69/250")
    assert {sku: v.weight_g for sku, v in variants.items() if sku != "69/250"} == {
        "69/503": 200,
        "69/504": 500,
        "69/505": 1000,
    }


def test_a_sku_stated_under_two_keys_is_not_resolved(
    fixture_html: Callable[[str, str], str],
) -> None:
    """Two keys for one sku cannot both be its variant, so neither is believed."""

    def twice(soup: BeautifulSoup) -> None:
        _rewrite_variant_data(soup, lambda data: data["18-39-21-42"].update(code="69/503"))

    coffee = _coffee("pepecoffee", _edit(_html(fixture_html, "pepecoffee"), twice))
    variants = _by_sku(coffee)

    assert variants["69/503"].label == "69/503"
    assert variants["69/504"].weight_g == 500


def test_a_page_that_states_no_key_pairs_offers_with_the_select_by_position(
    fixture_html: Callable[[str, str], str],
) -> None:
    """Without keys the old positional pairing is all there is, and it is unchanged."""

    html = _edit(_html(fixture_html, "jungleroastery"), _drop_variant_data)
    coffee = _coffee("jungleroastery", html)

    assert [
        (variant.external_id, variant.weight_g, variant.label) for variant in coffee.variants
    ] == [
        ("106/251", 1000, "Filter - Light roast / 1000 g"),
        ("106/100", 250, "Filter - Light roast / 250 g"),
        ("106/252", 1000, "Espresso - moderné / 1000 g"),
        ("106/250", 250, "Espresso - moderné / 250 g"),
    ]


def test_prices_and_availability_ignore_the_keys(
    fixture_html: Callable[[str, str], str],
) -> None:
    """Naming a variant never touches what it costs or whether it is in stock."""

    def no_keys(soup: BeautifulSoup) -> None:
        _drop_variant_data(soup)
        for span in soup.select(".p-code .parameter-dependent"):
            span["class"] = "parameter-dependent"

    for site_id in PAGES:
        html = _html(fixture_html, site_id)
        keyed = _by_sku(_coffee(site_id, html))
        unkeyed = _by_sku(_coffee(site_id, _edit(html, no_keys)))
        assert {
            sku: (v.price, v.currency, v.available, v.availability_raw) for sku, v in keyed.items()
        } == {
            sku: (v.price, v.currency, v.available, v.availability_raw)
            for sku, v in unkeyed.items()
        }


def test_a_deeply_nested_variant_script_is_ignored_not_fatal(
    fixture_html: Callable[[str, str], str],
) -> None:
    """Script text is the page's, so a pathological object must not crash the parse."""

    def nested(soup: BeautifulSoup) -> None:
        script = next(tag for tag in soup.find_all("script") if _is_variant_data(tag))
        script.string = "necessaryVariantData = " + '{"a":' * 100_000 + "1" + "}" * 100_000

    coffee = _coffee("pepecoffee", _edit(_html(fixture_html, "pepecoffee"), nested))

    assert len(coffee.variants) == 4


@pytest.mark.parametrize(
    ("size_value", "grams"),
    [
        ("200g + 200g", 400),
        ("200g + 200 g", 400),
        ("2x200 g", 400),
        ("200g ( 0,2Kg)", 200),
        ("200 g (2x100g)", 200),
    ],
)
def test_a_size_value_that_states_several_bags_stores_their_total(
    size_value: str, grams: int, fixture_html: Callable[[str, str], str]
) -> None:
    """johnnycoffee's `/201` option reads "200g + 200g" and its price buys both bags."""

    def bundled(soup: BeautifulSoup) -> None:
        option = soup.select_one("select[name='parameterValueId[18]'] option[value='306']")
        assert option is not None
        option.string = size_value

    coffee = _coffee("pepecoffee", _edit(_html(fixture_html, "pepecoffee"), bundled))

    assert _weights(coffee) == {"69/503": grams, "69/250": grams, "69/504": 500, "69/505": 1000}
    assert [v.price for v in coffee.variants] == [
        v.price for v in _coffee("pepecoffee", _html(fixture_html, "pepecoffee")).variants
    ]


def test_a_positional_label_that_states_several_bags_stores_their_total(
    fixture_html: Callable[[str, str], str],
) -> None:
    """With no variant keys the offers take labels by position, and that label is read alike."""

    def bundled(soup: BeautifulSoup) -> None:
        _drop_variant_data(soup)
        option = soup.select_one("select[name='parameterValueId[18]'] option[value='20']")
        assert option is not None
        option.string = "3x 1kg"

    coffee = _coffee("jungleroastery", _edit(_html(fixture_html, "jungleroastery"), bundled))

    assert [(v.label, v.weight_g) for v in coffee.variants] == [
        ("Filter - Light roast / 3x 1kg", 3000),
        ("Filter - Light roast / 250 g", 250),
        ("Espresso - moderné / 3x 1kg", 3000),
        ("Espresso - moderné / 250 g", 250),
    ]


def _preselect(*values: tuple[str, str]) -> Callable[[BeautifulSoup], None]:
    def mark(soup: BeautifulSoup) -> None:
        for name, value in values:
            option = soup.select_one(
                f'select[name="parameterValueId[{name}]"] option[value="{value}"]'
            )
            assert option is not None
            option["selected"] = "selected"

    return mark


def test_the_variant_every_axis_preselects_is_the_page_default(
    fixture_html: Callable[[str, str], str],
) -> None:
    """Weight 250 g and the light roast both preselected name one offer."""
    html = _edit(_html(fixture_html, "daliacoffee"), _preselect(("17", "14"), ("20", "23")))

    coffee = _coffee("daliacoffee", html)

    assert [variant.external_id for variant in coffee.variants if variant.default] == [
        "1077/250/SV"
    ]


def test_a_page_that_preselects_one_axis_only_names_no_default(
    fixture_html: Callable[[str, str], str],
) -> None:
    html = _edit(_html(fixture_html, "daliacoffee"), _preselect(("17", "14")))

    coffee = _coffee("daliacoffee", html)

    assert not any(variant.default for variant in coffee.variants)


def test_a_page_that_preselects_nothing_names_no_default(
    fixture_html: Callable[[str, str], str],
) -> None:
    coffee = _coffee("daliacoffee", _html(fixture_html, "daliacoffee"))

    assert not any(variant.default for variant in coffee.variants)


def test_the_option_a_combined_select_marks_selected_is_the_page_default(
    fixture_html: Callable[[str, str], str],
) -> None:
    html = fixture_html("shoptet_birdsong", "detail_bolivie_teoponte.html")

    def mark(soup: BeautifulSoup) -> None:
        select = soup.select_one("select[name=priceId]")
        assert select is not None
        options = [option for option in select.select("option") if option.get("value")]
        options[1]["selected"] = "selected"

    plain = _coffee("birdsong", html)
    chosen = _coffee("birdsong", _edit(html, mark))

    assert not any(variant.default for variant in plain.variants)
    assert [variant.external_id for variant in chosen.variants if variant.default] == ["BTE-500"]
