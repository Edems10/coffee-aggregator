from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urljoin

import pytest

from coffee_aggregator.http import FetchError, FetchResult
from coffee_aggregator.sites import get as get_site
from conftest import FIXTURE_ROOT

if TYPE_CHECKING:
    from coffee_aggregator.http import PoliteFetcher
    from coffee_aggregator.models import Coffee
    from coffee_aggregator.platforms.woocommerce import WooSite

FIXTURES = FIXTURE_ROOT / "variation_prices"
VARIATION_MARK = "type=variation"


class Shop:
    """Serves canned Store API pages and records every URL asked for."""

    def __init__(self, bodies: dict[str, str], fail: tuple[str, ...] = ()) -> None:
        self.bodies = bodies
        self.fail = fail
        self.requested: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.requested.append(url)
        if any(marker in url for marker in self.fail):
            raise FetchError(url, "HTTP 500")
        return FetchResult(
            url, url, 200, self.bodies.get(url, "[]"), from_cache=False, elapsed_s=0.0
        )

    @property
    def variation_requests(self) -> list[str]:
        return [url for url in self.requested if VARIATION_MARK in url]


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text("utf-8")


def items(name: str) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", json.loads(fixture(name)))


def site_of(site_id: str) -> WooSite:
    return cast("WooSite", get_site(site_id))


def serve(
    site: WooSite, products: list[dict[str, Any]], variations: str, fail: tuple[str, ...] = ()
) -> Shop:
    """One page of products in the shop's first category, everything else empty."""
    first = site.config.api_category_ids[0]
    return Shop(
        {site.api_url(1, first): json.dumps(products), **_variations(site, products, variations)},
        fail=fail,
    )


def variations_url(site: WooSite, ids: list[str]) -> str:
    base = urljoin(site.base_url, "wp-json/wc/store/v1/products")
    return f"{base}?type=variation&per_page=100&include={','.join(ids)}"


def _variations(site: WooSite, products: list[dict[str, Any]], listing: str) -> dict[str, str]:
    ids = [
        str(entry["id"])
        for product in products
        if len(product["variations"]) > 1
        for entry in product["variations"]
    ]
    return {variations_url(site, ids[:100]): listing} if ids else {}


def crawl(site: WooSite, shop: Shop) -> list[Coffee]:
    refs = list(site.discover(cast("PoliteFetcher", shop)))
    coffees = [site.parse_product("", ref) for ref in refs]
    return [coffee for coffee in coffees if coffee is not None]


def prices_of(coffee: Coffee) -> list[tuple[int | None, float | None]]:
    return [(variant.weight_g, variant.price) for variant in coffee.variants]


# --- the target: seriouscoffee 3532 -------------------------------------------


def test_each_variation_of_a_variable_product_carries_its_own_price() -> None:
    site = site_of("seriouscoffee")
    shop = serve(
        site,
        items("seriouscoffee_3532_product.json"),
        fixture("seriouscoffee_3532_variations.json"),
    )

    (coffee,) = crawl(site, shop)

    assert prices_of(coffee) == [(250, 10.9), (1000, 27.9)]
    assert {variant.currency for variant in coffee.variants} == {"EUR"}


def test_a_variable_product_is_stored_under_its_250_g_option() -> None:
    site = site_of("seriouscoffee")
    shop = serve(
        site,
        items("seriouscoffee_3532_product.json"),
        fixture("seriouscoffee_3532_variations.json"),
    )

    (coffee,) = crawl(site, shop)

    assert (coffee.price, coffee.weight_g, coffee.currency) == (10.9, 250, "EUR")


def test_the_option_nearest_250_g_is_stored_when_it_is_not_the_cheapest() -> None:
    """The listing's range minimum is the 1000 g bag here, which the chooser must not follow."""
    site = site_of("seriouscoffee")
    listing = items("seriouscoffee_3532_variations.json")
    prices = {"4206": "1990", "4207": "1090"}
    for entry in listing:
        entry["prices"]["price"] = prices[str(entry["id"])]
        entry["prices"]["regular_price"] = prices[str(entry["id"])]
    product = items("seriouscoffee_3532_product.json")[0]
    product["prices"]["price"] = "1090"
    shop = serve(site, [product], json.dumps(listing))

    (coffee,) = crawl(site, shop)

    assert (coffee.price, coffee.weight_g) == (19.9, 250)


def test_one_request_reads_the_variations_of_every_product() -> None:
    site = site_of("seriouscoffee")
    shop = serve(
        site,
        items("seriouscoffee_3532_product.json"),
        fixture("seriouscoffee_3532_variations.json"),
    )

    crawl(site, shop)

    assert shop.variation_requests == [
        (
            "https://www.seriouscoffee.sk/wp-json/wc/store/v1/products"
            "?type=variation&per_page=100&include=4206,4207"
        )
    ]


def test_a_hundred_and_one_variations_cost_two_requests() -> None:
    site = site_of("seriouscoffee")
    product = items("seriouscoffee_3532_product.json")[0]
    template = items("seriouscoffee_3532_variations.json")[0]
    ids = [str(9000 + number) for number in range(101)]
    product["variations"] = [{"id": int(number), "attributes": []} for number in ids]
    records = [{**template, "id": int(number)} for number in ids]
    shop = serve(site, [product], "[]")
    shop.bodies[variations_url(site, ids[:100])] = json.dumps(records[:100])
    shop.bodies[variations_url(site, ids[100:])] = json.dumps(records[100:])

    (coffee,) = crawl(site, shop)

    sizes = [len(url.rsplit("include=", 1)[1].split(",")) for url in shop.variation_requests]
    assert sizes == [100, 1]
    assert {variant.price for variant in coffee.variants} == {27.9}


def test_the_variations_of_every_category_are_read_in_one_request() -> None:
    site = site_of("seriouscoffee")
    first = items("seriouscoffee_3532_product.json")[0]
    second = copy.deepcopy(first)
    second["id"] = 3533
    second["permalink"] = "https://www.seriouscoffee.sk/produkt/another/"
    second["variations"] = [{"id": 5206, "attributes": []}, {"id": 5207, "attributes": []}]
    listing = items("seriouscoffee_3532_variations.json")
    listing += [
        {**entry, "id": number, "parent": 3533}
        for entry, number in zip(listing, (5206, 5207), strict=True)
    ]
    ids = site.config.api_category_ids
    every = variations_url(site, ["4206", "4207", "5206", "5207"])
    shop = Shop(
        {
            site.api_url(1, ids[0]): json.dumps([first]),
            site.api_url(1, ids[1]): json.dumps([second]),
            every: json.dumps(listing),
        }
    )

    coffees = crawl(site, shop)

    assert shop.variation_requests == [every]
    assert [len([v for v in coffee.variants if v.price is not None]) for coffee in coffees] == [
        2,
        2,
    ]


# --- the counter-examples that must not change --------------------------------


def test_a_product_with_one_variation_is_not_asked_about() -> None:
    site = site_of("zlatezrnko")
    shop = serve(
        site,
        items("zlatezrnko_162159_product.json"),
        fixture("zlatezrnko_162159_variations.json"),
    )

    (coffee,) = crawl(site, shop)

    assert shop.variation_requests == []
    assert prices_of(coffee) == [(200, 14.99)]
    assert (coffee.price, coffee.weight_g) == (14.99, 200)


def test_a_simple_product_is_not_asked_about() -> None:
    site = site_of("seriouscoffee")
    product = items("seriouscoffee_3532_product.json")[0]
    product["variations"] = []
    shop = serve(site, [product], "[]")

    (coffee,) = crawl(site, shop)

    assert shop.variation_requests == []
    assert coffee.variants == []
    assert coffee.price == 10.9


def test_an_ignored_product_costs_no_variation_request() -> None:
    site = site_of("zlatezrnko")
    product = copy.deepcopy(items("seriouscoffee_3532_product.json")[0])
    product["name"] = "Kapsule Espresso"
    shop = serve(site, [product], fixture("seriouscoffee_3532_variations.json"))

    assert crawl(site, shop) == []
    assert shop.variation_requests == []


def test_a_listing_entry_of_another_parent_prices_nothing() -> None:
    site = site_of("seriouscoffee")
    listing = items("seriouscoffee_3532_variations.json")
    for entry in listing:
        entry["parent"] = 1
    shop = serve(site, items("seriouscoffee_3532_product.json"), json.dumps(listing))

    (coffee,) = crawl(site, shop)

    assert prices_of(coffee) == [(250, None), (1000, None)]


def test_a_product_whose_variations_are_not_all_priced_stays_unpriced() -> None:
    site = site_of("seriouscoffee")
    listing = items("seriouscoffee_3532_variations.json")
    shop = serve(
        site,
        items("seriouscoffee_3532_product.json"),
        json.dumps([entry for entry in listing if entry["id"] == 4207]),
    )

    (coffee,) = crawl(site, shop)

    assert prices_of(coffee) == [(250, None), (1000, None)]
    assert (coffee.price, coffee.weight_g) == (10.9, 250)


def test_a_variation_the_shop_prices_at_zero_leaves_the_whole_product_unpriced() -> None:
    """bonte's "price on request" bag: the price and weight stored stay one option's."""
    site = site_of("seriouscoffee")
    listing = items("seriouscoffee_3532_variations.json")
    for entry in listing:
        if entry["id"] == 4206:
            entry["prices"]["price"] = "0"
    shop = serve(site, items("seriouscoffee_3532_product.json"), json.dumps(listing))

    (coffee,) = crawl(site, shop)

    assert prices_of(coffee) == [(250, None), (1000, None)]
    assert (coffee.price, coffee.weight_g, coffee.currency) == (10.9, 250, "EUR")


def test_a_variation_with_a_malformed_minor_unit_does_not_stop_the_parse() -> None:
    site = site_of("seriouscoffee")
    listing = items("seriouscoffee_3532_variations.json")
    listing[0]["prices"]["currency_minor_unit"] = "two"
    shop = serve(site, items("seriouscoffee_3532_product.json"), json.dumps(listing))

    (coffee,) = crawl(site, shop)

    assert [weight for weight, _ in prices_of(coffee)] == [250, 1000]


def test_a_listing_that_ignores_include_prices_nothing() -> None:
    """A shop that answers with other products' variations: no id asked for comes back."""
    site = site_of("seriouscoffee")
    listing = items("seriouscoffee_3532_variations.json")
    for number, entry in enumerate(listing):
        entry["id"] = 100 + number
    shop = serve(site, items("seriouscoffee_3532_product.json"), json.dumps(listing))

    (coffee,) = crawl(site, shop)

    assert prices_of(coffee) == [(250, None), (1000, None)]
    assert len(shop.variation_requests) == 1


def many_variations(site: WooSite, count: int) -> tuple[dict[str, Any], list[str]]:
    """A product of `count` variations, and the ids it lists."""
    product = items("seriouscoffee_3532_product.json")[0]
    template = items("seriouscoffee_3532_variations.json")[0]
    ids = [str(9000 + number) for number in range(count)]
    product["variations"] = [{"id": int(number), "attributes": []} for number in ids]
    product["_records"] = [{**template, "id": int(number)} for number in ids]
    return product, ids


def test_a_failing_second_chunk_leaves_the_product_unpriced_and_the_crawl_going() -> None:
    site = site_of("seriouscoffee")
    product, ids = many_variations(site, 101)
    records = product.pop("_records")
    shop = serve(site, [product], "[]", fail=("include=9100",))
    shop.bodies[variations_url(site, ids[:100])] = json.dumps(records[:100])

    (coffee,) = crawl(site, shop)

    assert len(shop.variation_requests) == 2
    assert {variant.price for variant in coffee.variants} == {None}
    assert (coffee.price, coffee.currency) == (10.9, "EUR")


def test_a_caller_that_stops_after_one_product_does_not_walk_the_next_page() -> None:
    """--limit and a deadline stop consuming; a full window is priced and the walk halts."""
    site = site_of("seriouscoffee")
    product, ids = many_variations(site, 100)
    records = product.pop("_records")
    other = copy.deepcopy(items("seriouscoffee_3532_product.json")[0])
    other["id"] = 3533
    other["permalink"] = "https://www.seriouscoffee.sk/produkt/another/"
    category = site.config.api_category_ids[0]
    shop = Shop(
        {
            site.api_url(1, category): json.dumps([product]),
            site.api_url(2, category): json.dumps([other]),
            variations_url(site, ids): json.dumps(records),
        }
    )

    first = next(iter(site.discover(cast("PoliteFetcher", shop))))

    assert first.external_id == "3532"
    assert site.api_url(2, category) not in shop.requested
    assert len(shop.variation_requests) == 1


# --- a listing that fails is not a new way for a crawl to fail ----------------


@pytest.mark.parametrize(
    ("listing", "fail"),
    [
        pytest.param("[]", (), id="empty"),
        pytest.param("<html>blocked</html>", (), id="not-json"),
        pytest.param('{"code": "rest_forbidden"}', (), id="not-an-array"),
        pytest.param("[]", (VARIATION_MARK,), id="http-error"),
    ],
)
def test_a_failing_variation_listing_leaves_the_crawl_as_it_was(
    listing: str,
    fail: tuple[str, ...],
) -> None:
    site = site_of("seriouscoffee")
    shop = serve(site, items("seriouscoffee_3532_product.json"), listing, fail=fail)

    (coffee,) = crawl(site, shop)

    assert prices_of(coffee) == [(250, None), (1000, None)]
    assert (coffee.price, coffee.weight_g, coffee.currency) == (10.9, 250, "EUR")
    assert not [note for note in site.take_discovery_notes() if "variation" in note]


def test_a_failed_listing_is_asked_once_for_the_whole_shop() -> None:
    site = site_of("seriouscoffee")
    first = items("seriouscoffee_3532_product.json")[0]
    second = copy.deepcopy(first)
    second["id"] = 3533
    second["permalink"] = "https://www.seriouscoffee.sk/produkt/another/"
    ids = site.config.api_category_ids
    shop = Shop(
        {
            site.api_url(1, ids[0]): json.dumps([first]),
            site.api_url(1, ids[1]): json.dumps([second]),
        },
        fail=(VARIATION_MARK,),
    )

    coffees = crawl(site, shop)

    assert [coffee.external_id for coffee in coffees] == ["3532", "3533"]
    assert len(shop.variation_requests) == 1
