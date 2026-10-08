from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

import pytest
from bs4 import BeautifulSoup

from coffee_aggregator import adapters as kit
from coffee_aggregator.http import FetchResult
from coffee_aggregator.labels import F_BODY, F_COUNTRY, F_ROAST
from coffee_aggregator.sites.base import ProductRef

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from coffee_aggregator.http import PoliteFetcher

ID_RE = re.compile(r"/detail/(?P<id>\d+)/")


class FakeFetcher:
    """Serves canned pages, optionally redirecting anything it does not know."""

    def __init__(self, bodies: dict[str, str], redirect_to: str | None = None) -> None:
        self.bodies = bodies
        self.redirect_to = redirect_to
        self.requested: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.requested.append(url)
        known = url in self.bodies
        final = url if known or self.redirect_to is None else self.redirect_to
        return FetchResult(url, final, 200, self.bodies.get(url, ""), from_cache=False, elapsed_s=0)

    def fetch_many(self, urls: Sequence[str]) -> list[FetchResult]:
        return [self.get(url) for url in urls]

    def fetch_each(self, urls: Sequence[str]) -> Iterator[FetchResult]:
        return iter(self.fetch_many(urls))


def as_fetcher(fake: FakeFetcher) -> PoliteFetcher:
    return cast("PoliteFetcher", fake)


def refs_named(*names: str) -> list[ProductRef]:
    return [ProductRef(site_id="s", external_id=name, url=f"/{name}") for name in names]


# --------------------------------------------------------------------- payload


def test_a_broken_payload_costs_one_record_not_the_run() -> None:
    assert kit.json_object("{not json") == {}
    assert kit.json_object("[1, 2]") == {}
    assert kit.json_object('{"a": 1}') == {"a": 1}


def test_records_keeps_only_the_mappings_of_a_list() -> None:
    assert kit.records([{"a": 1}, "no", 3, {}]) == [{"a": 1}, {}]
    assert kit.records({"a": 1}) == []
    assert kit.records(None) == []


def test_numbers_narrow_without_believing_a_boolean() -> None:
    assert kit.as_number(True) is None
    assert kit.as_number(7) == 7.0
    assert kit.as_number("7") is None


def test_the_first_product_of_a_data_layer_record_is_found() -> None:
    assert kit.first_record({"products": [{"id": 1}, {"id": 2}]}, "products") == {"id": 1}
    assert kit.first_record({"products": []}, "products") == {}
    assert kit.first_record("nonsense", "products") == {}


def test_a_localised_field_falls_back_to_any_language() -> None:
    assert kit.localised({"cs": "Káva", "en": "Coffee"}, "cs") == "Káva"
    assert kit.localised({"en": "Coffee"}, "cs") == "Coffee"
    assert kit.localised("plain", "cs") == "plain"
    assert kit.localised({}, "cs") is None


def test_shop_codes_survive_as_strings_whatever_type_they_arrive_as() -> None:
    record = {"EAN": 8_594_000_000_001, "code": " A1 ", "missing": None}
    assert kit.strings(record, ("EAN", "code", "missing")) == {
        "EAN": "8594000000001",
        "CODE": "A1",
    }


# ------------------------------------------------------------------------ refs


def test_an_id_is_read_out_of_the_url_rather_than_rebuilt() -> None:
    assert kit.id_from("https://x.sk/detail/668/kava", ID_RE) == "668"
    assert kit.id_from("https://x.sk/kosik/", ID_RE) is None
    assert kit.id_from(None, ID_RE) is None


def test_a_sitemap_yields_one_reference_per_distinct_product() -> None:
    xml = """<?xml version="1.0"?><urlset>
      <url><loc>https://x.sk/detail/1/a</loc></url>
      <url><loc>https://x.sk/detail/1/a?utm=1</loc></url>
      <url><loc>https://x.sk/o-nas</loc></url>
      <url><loc>https://x.sk/detail/2/b</loc></url>
    </urlset>"""
    refs = kit.sitemap_refs(xml, "shop", ID_RE)
    assert [ref.external_id for ref in refs] == ["1", "2"]
    assert all(ref.site_id == "shop" for ref in refs)


def test_a_currency_never_outlives_the_price_it_belongs_to() -> None:
    assert kit.product_ref("s", "1", "/1", price=9.5, currency="EUR").currency == "EUR"
    assert kit.product_ref("s", "1", "/1", currency="EUR").currency is None


# ------------------------------------------------------------------------ walk


def test_the_walk_stops_when_a_page_redirects_away() -> None:
    fake = FakeFetcher({"/1": "page one"}, redirect_to="/1")
    found = list(
        kit.walk_listing(as_fetcher(fake), ["/1", "/2", "/3"], lambda _text: refs_named("a"))
    )
    assert [ref.external_id for ref in found] == ["a"]
    assert fake.requested == ["/1", "/2"]


def test_a_paginated_walk_stops_at_the_first_page_that_adds_nothing() -> None:
    fake = FakeFetcher({"/1": "", "/2": "", "/3": ""})
    found = list(kit.walk_listing(as_fetcher(fake), ["/1", "/2", "/3"], lambda _t: refs_named("a")))
    assert [ref.external_id for ref in found] == ["a"]
    assert fake.requested == ["/1", "/2"]


def test_a_list_of_categories_keeps_walking_past_a_repeat() -> None:
    fake = FakeFetcher({"/1": "", "/2": "", "/3": ""})
    pages = iter([refs_named("a"), refs_named("a"), refs_named("b")])
    found = list(
        kit.walk_listing(
            as_fetcher(fake),
            ["/1", "/2", "/3"],
            lambda _text: next(pages),
            stop_when_stale=False,
        )
    )
    assert [ref.external_id for ref in found] == ["a", "b"]
    assert fake.requested == ["/1", "/2", "/3"]


# ----------------------------------------------------------------------- facts


def test_a_shop_overlay_wins_over_the_shared_vocabulary() -> None:
    label_map = kit.vocabulary({"lokalita": F_BODY})
    facts = kit.read_pairs([("Lokalita", "Gatara"), ("Pôvod", "Kolumbia")], label_map)
    assert facts.get(F_BODY) == "Gatara"
    assert facts.get(F_COUNTRY) == "Kolumbia"


def test_a_shop_gains_a_synonym_it_never_spelled_out() -> None:
    facts = kit.read_pairs([("Krajina pôvodu", "Kolumbia")], kit.vocabulary())
    assert facts.get(F_COUNTRY) == "Kolumbia"
    assert facts.raw == {"KRAJINA PÔVODU": "Kolumbia"}


def test_the_shop_s_own_spelling_stays_readable_for_the_rows_no_field_holds() -> None:
    facts = kit.read_pairs([("Chuť", "Čokoládová"), ("Charakteristika", "a - b")], kit.vocabulary())
    assert facts.pick("charakteristika") == "a - b"
    assert facts.pick("nothing", "chut") == "Čokoládová"
    assert facts.pick("nothing") is None


def test_an_implausible_value_stays_out_of_the_typed_field() -> None:
    facts = kit.read_pairs(
        [("Pražení", "Směs Arabiky a Robusty")],
        kit.vocabulary(),
    )
    assert facts.get(F_ROAST) is None
    assert facts.raw == {"PRAŽENÍ": "Směs Arabiky a Robusty"}


def test_a_bare_heading_claims_the_line_under_it_only_when_asked_to() -> None:
    lines = ["Pražení", "Světlé", "Tip našeho baristy", "Mlejte nahrubo."]
    with_headings, _ = kit.read_text(lines, kit.vocabulary())
    assert with_headings.get(F_ROAST) == "Světlé"
    without, prose = kit.read_text(lines, kit.vocabulary(), bare_labels=False)
    assert without.get(F_ROAST) is None
    assert prose == lines


def test_description_blocks_break_on_the_markup_not_on_the_text() -> None:
    soup = BeautifulSoup("<div><p>Pôvod: Kuba<br/>100 % Arabika</p></div>", "lxml")
    facts, prose = kit.read_blocks([soup.select_one("div")], kit.vocabulary())
    assert facts.get(F_COUNTRY) == "Kuba"
    assert prose == ["100 % Arabika"]


def test_table_rows_reads_two_columns_and_obeys_the_keep_predicate() -> None:
    soup = BeautifulSoup(
        "<table><tr><th>Země</th><td>Peru</td></tr>"
        "<tr><td>Odrůda</td><td>Caturra</td><td>note</td></tr>"
        "<tr><td>alone</td></tr></table>",
        "lxml",
    )

    assert list(kit.table_rows(soup.select("tr"))) == [
        ("Země", "Peru"),
        ("Odrůda", "Caturra"),
    ]
    assert list(kit.table_rows(soup.select("tr"), keep=lambda cells: len(cells) == 2)) == [
        ("Země", "Peru")
    ]


# ----------------------------------------------------------------------- build


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Skladom", True),
        ("Skladem (3 ks)", True),
        ("Na skladě", True),
        ("Na sklade", True),
        ("Dostupné", True),
        ("IHNED K ODESLÁNÍ", True),
        ("In stock", True),
        ("Není skladem", False),
        ("Nie je skladom", False),
        ("Není na skladě", False),
        ("Nie je na sklade", False),
        ("Vyprodáno", False),
        ("Vypredané", False),
        ("Vyprodané", False),
        ("Nedostupné", False),
        ("Out of stock", False),
        ("Sold out", False),
        ("", None),
        ("Doručíme do Vianoc", None),
    ],
)
def test_the_stock_wording_of_both_languages_is_read_the_same_way(
    text: str,
    expected: bool | None,
) -> None:
    assert kit.stock_state(text) is expected


def test_a_negation_wins_over_the_word_it_negates() -> None:
    assert kit.stock_state("Skladem", "Není skladem") is False


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Hmotnost: 1kg - Není skladem (42 €)", False),
        ("Hmotnosť: 250g - Nie je skladom (18 €)", False),
        ("Hmotnost: 500 g - Není na skladě (310 Kč)", False),
        ("Hmotnosť: 1kg - Nie je na sklade (34 €)", False),
        ("Hmotnosť: 500g - Skladom >5 ks (34 €)", True),
        ("Hmotnost: 250 g - Skladem (262 Kč)", True),
        ("Hmotnost: 3000g - IHNED K ODESLÁNÍ (4 290 Kč)", True),
    ],
)
def test_a_negation_inside_a_variant_label_is_not_read_as_in_stock(
    label: str,
    expected: bool,
) -> None:
    """A bare "sklad" stem once read every row of this table as in stock.

    The stem lived in Shoptet's own copy of this vocabulary, so every negated
    wording on the largest platform's 47 shops stored ``available = True``.
    """
    assert kit.stock_state(label) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://schema.org/InStock", True),
        # A pre-order and a limited run are listed for sale: the owner's call,
        # with a banner on the web front end telling a pre-order apart.
        ("https://schema.org/PreOrder", True),
        ("https://schema.org/LimitedAvailability", True),
        ("https://schema.org/OutOfStock", False),
        ("https://schema.org/SoldOut", False),
        ("https://schema.org/Discontinued", False),
        ("https://schema.org/BackOrder", False),
        ("https://schema.org/PreSale", False),
        ("InStock", True),
        ("", None),
        (None, None),
    ],
)
def test_a_schema_availability_reads_one_closed_vocabulary(
    value: str | None,
    expected: bool | None,
) -> None:
    assert kit.schema_stock(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://schema.org/InStock", "InStock"),
        ("https://schema.org/PreOrder", "PreOrder"),
        ("https://schema.org/LimitedAvailability", "LimitedAvailability"),
        ("http://schema.org/OutOfStock", "OutOfStock"),
        ("  https://schema.org/SoldOut  ", "SoldOut"),
        ("InStock", "InStock"),
        # The vocabulary is closed, so an unknown word reads as sold out; it is
        # still what the shop wrote, and dropping it would leave the row saying
        # the page stated nothing.
        ("Dostupné", "Dostupné"),
        ("", None),
        (None, None),
    ],
)
def test_the_schema_token_is_kept_as_the_page_named_it(
    value: str | None,
    expected: str | None,
) -> None:
    """``PreOrder`` and ``LimitedAvailability`` both read True; only the token tells them apart."""
    assert kit.schema_token(value) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Hmotnosť: 500g - Skladom >5 ks (34 €)", "Skladom >5 ks"),
        ("Hmotnost: 3000g - IHNED K ODESLÁNÍ (4 290 Kč)", "IHNED K ODESLÁNÍ"),
        ("Hmotnost: 250 g - Skladem (262 Kč)", "Skladem"),
        ("Hmotnost: 1kg - Není skladem (42 €)", "Není skladem"),
        (
            "Druh kávy: Zrnková, Hmotnost: 250g - Momentálně nedostupné (240 Kč)",
            "Momentálně nedostupné",
        ),
        # A label that states a grind and a weight states nothing about stock,
        # and 164 of the catalogue's 658 dashed variant labels are of this kind.
        ("Varianta: bez mletí / 500g", None),
        ("Obal: vratný obal", None),
        ("", None),
        (None, None),
    ],
)
def test_the_stated_stock_wording_is_cut_out_of_the_label_it_arrives_in(
    label: str | None,
    expected: str | None,
) -> None:
    assert kit.stock_wording(label) == expected


def test_the_wording_kept_is_the_one_the_reading_came_from() -> None:
    """``stock_state`` tests the negations first, so the provenance has to as well."""
    assert kit.stock_state("Skladem", "Není skladem") is False
    assert kit.stock_wording("Skladem", "Není skladem") == "Není skladem"


def test_a_package_reads_its_weight_off_its_own_label() -> None:
    variant = kit.package(
        external_id="1",
        url="/1",
        label="Hmotnost: 250g",
        price=219.0,
        currency="CZK",
    )
    assert variant.weight_g == 250
    assert variant.currency == "CZK"


def test_a_package_without_a_price_states_no_currency() -> None:
    variant = kit.package(external_id="1", url="/1", label="1 kg", price=None, currency="CZK")
    assert variant.weight_g == 1000
    assert variant.currency is None


def test_a_stated_weight_beats_the_label() -> None:
    variant = kit.package(
        external_id="1",
        url="/1",
        label="velké balení",
        price=None,
        currency="CZK",
        weight_g=500,
    )
    assert variant.weight_g == 500


def test_page_metadata_only_ever_fills_a_gap() -> None:
    raw = {"KRAJINA": "Kuba"}
    kit.keep(raw, {"KRAJINA": "Brazílie", "OG_TITLE": "Kuba Serrano", "EMPTY": ""})
    assert raw == {"KRAJINA": "Kuba", "OG_TITLE": "Kuba Serrano"}


def test_a_gallery_drops_the_badges_and_the_repeats() -> None:
    urls = kit.gallery(
        "https://x.sk/",
        ["/img/a.jpg", "/img/a.jpg", "/images/gta/badge.png", None, "/img/b.jpg"],
        keep_when=lambda url: "/images/gta/" not in url,
    )
    assert urls == ["https://x.sk/img/a.jpg", "https://x.sk/img/b.jpg"]


# ------------------------------------------------------------------- microdata


MICRODATA = """
<div class="box" itemprop="aggregateRating">
  <span itemprop="ratingValue" content="4.7">4,7</span>
  <span itemprop="reviewCount">12</span>
  <span itemprop="bestRating" content="10"></span>
</div>
<ul id="reviews">
  <li itemprop="review">
    <span itemprop="author"><span itemprop="name">Jana</span></span>
    <meta itemprop="datePublished" content="2026-01-02"/>
    <div itemprop="reviewRating"><span itemprop="ratingValue" content="5">5</span></div>
    <p itemprop="description">Skvelá káva.</p>
  </li>
</ul>
"""


def test_an_aggregate_rating_is_read_with_the_scale_it_states() -> None:
    soup = BeautifulSoup(MICRODATA, "lxml")
    assert kit.ratings(soup.select_one("div.box")) == (4.7, 12, 10)


def test_an_unstated_scale_falls_back_to_five() -> None:
    soup = BeautifulSoup('<div><span itemprop="ratingValue">4</span></div>', "lxml")
    assert kit.ratings(soup.select_one("div")) == (4.0, None, 5)


def test_reviews_come_back_with_author_date_stars_and_text() -> None:
    soup = BeautifulSoup(MICRODATA, "lxml")
    reviews = kit.reviews(soup.select_one("#reviews"))
    assert len(reviews) == 1
    assert reviews[0].author == "Jana"
    assert reviews[0].rating == 5.0
    assert reviews[0].text == "Skvelá káva."
    assert reviews[0].date is not None
    assert reviews[0].date.isoformat() == "2026-01-02"


def test_a_page_with_no_reviews_returns_none_of_them() -> None:
    assert kit.reviews(None) == []
    assert kit.reviews(BeautifulSoup("<div></div>", "lxml")) == []
