from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from coffee_aggregator.http import FetchResult, parse_robots
from coffee_aggregator.sites import get as get_site
from conftest import FIXTURE_ROOT

if TYPE_CHECKING:
    from coffee_aggregator.http import PoliteFetcher
    from coffee_aggregator.platforms.shopify import ShopifySite

ROOT = FIXTURE_ROOT / "alfabet_shopify"
COLLECTIONS = ("sladke-jemne", "stavnate-svezi")
EXPECTED = {
    "15444404076892": (950.0, 1000, 1),
    "9503168790876": (425.0, 250, 4),
    "15808091849052": (375.0, 250, 2),
    "8424261091676": (425.0, 250, 4),
    "7311429828799": (425.0, 250, 4),
    "8424253620572": (425.0, 250, 4),
    "15733251342684": (375.0, 250, 4),
}


class CollectionFetcher:
    def __init__(self, site: ShopifySite) -> None:
        self.bodies = {
            site.page_url(f"collections/{handle}/products.json", 1): (
                ROOT / f"{handle}.json"
            ).read_text("utf-8")
            for handle in COLLECTIONS
        }
        self.requested: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.requested.append(url)
        return FetchResult(url, url, 200, self.bodies.get(url, '{"products": []}'), False, 0.0)


def test_alfabet_discovers_only_its_two_individual_coffee_collections() -> None:
    site = cast("ShopifySite", get_site("alfabet"))
    assert site.config.collections == list(COLLECTIONS)
    assert (site.kind, site.country, site.config.currency) == ("shopify", "CZ", "CZK")
    fetcher = CollectionFetcher(site)
    refs = list(site.discover(cast("PoliteFetcher", fetcher)))

    assert {ref.external_id for ref in refs} == set(EXPECTED)
    assert len(refs) == 7
    assert fetcher.requested == [
        site.page_url(f"collections/{handle}/products.json", page)
        for handle in COLLECTIONS
        for page in (1, 2)
    ]
    # The parent coffee and roast collections include these products; the two
    # configured flavour collections contain none of them.
    assert {ref.external_id for ref in refs}.isdisjoint(
        {"8793928073564", "14762910318940", "15326761222492", "15614616830300"}
    )

    for ref in refs:
        coffee = site.parse_product("", ref)
        assert coffee is not None
        price, weight, variants = EXPECTED[ref.external_id]
        assert (coffee.price, coffee.weight_g, len(coffee.variants)) == (price, weight, variants)
        assert coffee.currency == "CZK"
        assert coffee.price_per_kg == price * 1000 / weight
        assert coffee.available is True
        assert all(option.currency == "CZK" for option in coffee.variants)
        assert all(option.weight_g == weight for option in coffee.variants)
        assert coffee.url.startswith("https://alfabet.coffee/products/")


def test_alfabet_deduplicates_a_coffee_if_the_flavour_collections_overlap() -> None:
    site = cast("ShopifySite", get_site("alfabet"))
    fetcher = CollectionFetcher(site)
    first = site.page_url(f"collections/{COLLECTIONS[0]}/products.json", 1)
    second = site.page_url(f"collections/{COLLECTIONS[1]}/products.json", 1)
    body = json.loads(fetcher.bodies[second])
    body["products"].append(json.loads(fetcher.bodies[first])["products"][0])
    fetcher.bodies[second] = json.dumps(body)

    refs = list(site.discover(cast("PoliteFetcher", fetcher)))

    assert len(refs) == len({ref.external_id for ref in refs}) == 7


def test_alfabet_robots_permit_pagination_and_product_pages() -> None:
    site = cast("ShopifySite", get_site("alfabet"))
    rules = parse_robots((ROOT / "robots.txt").read_text("utf-8"))

    for source in site.sources():
        for page in (1, 2):
            assert rules.can_fetch("coffee-aggregator", site.page_url(source, page))
    assert rules.can_fetch("coffee-aggregator", "https://alfabet.coffee/products/machine-automat")
    assert not rules.can_fetch(
        "coffee-aggregator", "https://alfabet.coffee/collections/kava?sort_by=price-ascending"
    )
