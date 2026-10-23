from __future__ import annotations

import json
import tomllib
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest

from coffee_aggregator import sites
from coffee_aggregator.http import FetchResult, parse_robots
from coffee_aggregator.platforms.common import PlatformConfigError
from coffee_aggregator.platforms.shopify import ShopifyConfig, ShopifySite, _variant_weight
from coffee_aggregator.sites import CONFIG_DIR
from coffee_aggregator.sites import get as get_site
from conftest import FIXTURE_ROOT

if TYPE_CHECKING:
    from coffee_aggregator.http import PoliteFetcher
    from coffee_aggregator.models import Coffee

ROOT = FIXTURE_ROOT / "labohemecafe_shopify"
SOURCE = "collections/vsechny-kavy/products.json"
PERU = "peru-dwight-aguilar-5"
MOCHA = "mocha-java"


def _items() -> list[dict[str, Any]]:
    return cast(
        "list[dict[str, Any]]", json.loads((ROOT / "vsechny-kavy.json").read_text())["products"]
    )


def _parse(site: ShopifySite, item: dict[str, Any]) -> Coffee:
    ref = site._ref(item)
    assert ref is not None
    coffee = site.parse_product("", ref)
    assert coffee is not None
    return coffee


def _product(handle: str) -> dict[str, Any]:
    return next(item for item in _items() if item["handle"] == handle)


class CollectionFetcher:
    def __init__(self, site: ShopifySite) -> None:
        self.url = site.page_url(SOURCE, 1)
        self.body = (ROOT / "vsechny-kavy.json").read_text("utf-8")
        self.requested: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.requested.append(url)
        return FetchResult(
            url, url, 200, self.body if url == self.url else '{"products": []}', False, 0.0
        )


def test_labohemecafe_discovers_the_bean_collection_without_cascara() -> None:
    site = cast("ShopifySite", get_site("labohemecafe"))
    assert site.sources() == [SOURCE]
    assert (site.country, site.config.currency, site.config.variant_weight_source) == (
        "CZ",
        "CZK",
        "title",
    )
    fetcher = CollectionFetcher(site)
    refs = list(site.discover(cast("PoliteFetcher", fetcher)))
    assert len(refs) == len({ref.external_id for ref in refs}) == 19
    assert "8794861830485" not in {ref.external_id for ref in refs}
    assert fetcher.requested == [site.page_url(SOURCE, page) for page in (1, 2)]
    coffees = [site.parse_product("", ref) for ref in refs]
    assert sum(len(coffee.variants) for coffee in coffees if coffee is not None) == 37
    for coffee in coffees:
        assert coffee is not None
        assert coffee.price is not None
        assert coffee.weight_g is not None
        assert coffee.currency == "CZK"
        assert coffee.price_per_kg is not None
        assert coffee.available is True
        assert all(option.currency == "CZK" for option in coffee.variants)
        assert all(
            option.price is not None and option.weight_g is not None for option in coffee.variants
        )
        assert "cascara" not in coffee.name.lower()


def test_labohemecafe_peru_uses_the_150_g_option_instead_of_shipping_weight() -> None:
    site = cast("ShopifySite", get_site("labohemecafe"))
    item = _product(PERU)
    assert item["variants"][0]["grams"] == 226
    coffee = _parse(site, item)
    assert (coffee.price, coffee.currency, coffee.weight_g, coffee.price_per_kg) == (
        649.0,
        "CZK",
        150,
        4326.67,
    )
    assert [(option.label, option.price, option.weight_g) for option in coffee.variants] == [
        ("150 g", 649.0, 150)
    ]


def test_labohemecafe_mocha_retains_each_options_own_price_and_net_size() -> None:
    site = cast("ShopifySite", get_site("labohemecafe"))
    item = _product(MOCHA)
    assert [option["grams"] for option in item["variants"]] == [226, 226]
    coffee = _parse(site, item)
    assert [(option.label, option.price, option.weight_g) for option in coffee.variants] == [
        ("226 g", 299.0, 226),
        ("1 kg", 1229.0, 1000),
    ]
    assert (coffee.price, coffee.weight_g, coffee.price_per_kg) == (299.0, 226, 1323.01)
    item["variants"][0]["available"] = False
    coffee = _parse(site, item)
    assert (coffee.price, coffee.weight_g, coffee.price_per_kg) == (1229.0, 1000, 1229.0)


@pytest.mark.parametrize(
    "title",
    [None, "", "Default Title", "250g/500g", "250 g - 500 g", "250g + 500g", "0 g", "999999 kg"],
)
def test_title_mode_does_not_fall_back_to_shipping_name_or_description(title: str | None) -> None:
    site = cast("ShopifySite", get_site("labohemecafe"))
    item = _product(PERU)
    item["title"] = "Peru 226 g"
    item["body_html"] += "<p>Hmotnost: 226 g</p>"
    item["variants"][0]["title"] = title
    coffee = _parse(site, item)
    assert coffee.variants[0].weight_g is None
    assert coffee.weight_g is None
    assert coffee.price_per_kg is None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("150 g", 150),
        ("1 kg", 1000),
        ("0,25 kg / zrno", 250),
        ("1000g (1Kg)", 1000),
        ("3x1000g", 3000),
        ("500g+500g", 1000),
        ("1000g (4x250g)", 1000),
        ("250-500g", None),
        ("250g / 1kg", None),
        ("2x250g + 100g", None),
    ],
)
def test_title_mode_observes_option_parser_boundaries(title: str, expected: int | None) -> None:
    assert _variant_weight({"title": title, "grams": 226}, source="title") == expected


def test_shipping_first_stays_the_default_for_every_existing_shop() -> None:
    assert _variant_weight({"title": "150 g", "grams": 226}) == 226
    assert _variant_weight({"title": "1 kg", "grams": 0}) == 1000
    for site in sites.all_sites():
        if isinstance(site, ShopifySite) and site.site_id != "labohemecafe":
            assert site.config.variant_weight_source == "grams"
    site = cast("ShopifySite", get_site("labohemecafe"))
    legacy = ShopifySite(replace(site.config, variant_weight_source="grams"))
    assert _parse(legacy, _product(PERU)).weight_g == 226


@pytest.mark.parametrize("source", ["shipping", "TITLE", "", None, 1, True, ["title"]])
def test_a_misspelled_or_malformed_weight_source_is_rejected(source: object) -> None:
    config = tomllib.loads((CONFIG_DIR / "labohemecafe.toml").read_text())
    config["variant_weight_source"] = source
    with pytest.raises(PlatformConfigError, match="variant_weight_source must be grams or title"):
        ShopifyConfig.from_mapping(config, CONFIG_DIR / "labohemecafe.toml")


def test_labohemecafe_robots_permit_collection_pages_and_the_real_products() -> None:
    site = cast("ShopifySite", get_site("labohemecafe"))
    rules = parse_robots((ROOT / "robots.txt").read_text())
    for page in (1, 2):
        assert rules.can_fetch("coffee-aggregator", site.page_url(SOURCE, page))
    for handle in (PERU, MOCHA):
        assert rules.can_fetch("coffee-aggregator", f"{site.base_url}products/{handle}")
    assert not rules.can_fetch(
        "coffee-aggregator", f"{site.base_url}collections/vsechny-kavy?sort_by=price-ascending"
    )


@pytest.mark.parametrize(
    "title",
    [
        "250–500 g",
        "250 / 500 g",
        "2 x 250g / 4 x 250g",
        "2x250g / 3x250g",
        "2x250g + 250g",
        "2x250g + 2x250g",
        "500g + 2x500g",
    ],
)
def test_strict_titles_reject_partial_readings_through_the_product_parser(title: str) -> None:
    site = cast("ShopifySite", get_site("labohemecafe"))
    item = _product(PERU)
    item["variants"][0]["title"] = title
    coffee = _parse(site, item)
    assert coffee.variants[0].weight_g is None
    assert coffee.weight_g is None
    assert coffee.price_per_kg is None
    assert coffee.price == 649.0
    legacy = ShopifySite(replace(site.config, variant_weight_source="grams"))
    unchanged = _parse(legacy, item)
    assert unchanged.variants[0].weight_g == 226
    assert unchanged.weight_g == 226
    assert unchanged.price_per_kg == 2871.68


@pytest.mark.parametrize(
    ("title", "weight"),
    [
        ("150 g", 150),
        ("1 kg", 1000),
        ("0.25 kg / zrno", 250),
        ("1000g (1Kg)", 1000),
        ("3x1000g", 3000),
        ("500g+500g", 1000),
        ("1000g (4x250g)", 1000),
    ],
)
def test_strict_title_completeness_retains_supported_pack_shapes(title: str, weight: int) -> None:
    site = cast("ShopifySite", get_site("labohemecafe"))
    item = _product(PERU)
    item["variants"][0]["title"] = title
    coffee = _parse(site, item)
    assert coffee.variants[0].weight_g == weight
    assert coffee.weight_g == weight
    assert coffee.price == 649.0
    assert coffee.price_per_kg == round(649000 / weight, 2)
