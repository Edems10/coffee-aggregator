from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from coffee_aggregator.models import Coffee, Variant
from coffee_aggregator.price_option import choose_option, settle_price_option
from coffee_aggregator.sites.base import ProductRef, SiteAdapter
from conftest import adapter_for

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from coffee_aggregator.http import PoliteFetcher


def option(  # noqa: PLR0913  (one argument per Variant field a test sets)
    weight_g: int | None,
    price: float | None,
    *,
    available: bool | None = None,
    default: bool = False,
    original_price: float | None = None,
    label: str | None = None,
) -> Variant:
    return Variant(
        external_id=label or f"{weight_g}-{price}",
        weight_g=weight_g,
        price=price,
        currency="CZK" if price is not None else None,
        available=available,
        default=default,
        original_price=original_price,
        label=label,
    )


def product(
    *options: Variant,
    price: float | None = None,
    weight_g: int | None = None,
    original_price: float | None = None,
    name: str = "Kenya Embu",
) -> Coffee:
    return Coffee(
        site="demo",
        external_id="1",
        url="https://demo.example/p/",
        name=name,
        site_country="CZ",
        price=price,
        currency="CZK" if price is not None else None,
        weight_g=weight_g,
        original_price=original_price,
        variants=list(options),
    )


def stored(coffee: Coffee) -> tuple[float | None, int | None, float | None]:
    return coffee.price, coffee.weight_g, coffee.price_per_kg


# --- the target: the option nearest 250 g, with its own price and weight -----


def test_botacoffee_stores_the_250_g_option_not_the_70_g_headline() -> None:
    """botacoffee/5524: 70 g at 115, 250 g at 359, 1 kg at 1399 stored 115 Kc for 70 g."""
    coffee = product(
        option(70, 115.0), option(250, 359.0), option(1000, 1399.0), price=115.0, weight_g=70
    )

    settle_price_option(coffee)

    assert stored(coffee) == (359.0, 250, 1436.0)


def test_the_nearest_option_wins_whatever_the_page_order() -> None:
    """readyafter/1117 listed 1 kg first and stored it; 200 g is the nearest."""
    coffee = product(option(1000, 29.0), option(200, 7.9), option(500, 17.0), price=29.0)

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (7.9, 200)


def test_a_300_g_option_beats_a_150_g_one() -> None:
    """motmot/141: 150 g is 100 g from 250, 300 g is 50 g."""
    coffee = product(
        option(150, 164.0), option(300, 299.0), option(1000, 949.0), price=164.0, weight_g=150
    )

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (299.0, 300)


def test_two_equidistant_options_tie_to_the_heavier() -> None:
    first = product(option(125, 100.0), option(375, 280.0))
    second = product(option(375, 280.0), option(125, 100.0))

    settle_price_option(first)
    settle_price_option(second)

    assert (first.price, first.weight_g) == (second.price, second.weight_g) == (280.0, 375)


def test_nothing_near_still_takes_the_nearest_without_a_cutoff() -> None:
    coffee = product(option(1000, 480.0), option(5000, 2100.0), price=480.0)

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (480.0, 1000)


# --- samples ------------------------------------------------------------------


def test_a_sample_is_skipped_when_a_larger_option_exists() -> None:
    """ebenica/1216: the 70 g sample is nearer 250 than the 1 kg sack, and is skipped."""
    coffee = product(option(70, 4.49), option(1000, 34.9), price=4.49, weight_g=70)

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (34.9, 1000)


def test_a_coffee_sold_only_as_a_sample_keeps_its_sample() -> None:
    coffee = product(option(70, 115.0), option(80, 130.0), price=115.0, weight_g=70)

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (130.0, 80)


# --- stock --------------------------------------------------------------------


def test_the_nearest_option_that_is_out_of_stock_gives_way_to_one_in_stock() -> None:
    coffee = product(
        option(250, 300.0, available=False),
        option(500, 560.0, available=True),
        option(1000, 1000.0, available=True),
    )

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (560.0, 500)


@pytest.mark.parametrize("stock", [None, False])
def test_with_no_option_known_in_stock_the_nearest_overall_is_stored(stock: bool | None) -> None:
    coffee = product(option(250, 300.0, available=stock), option(500, 560.0, available=stock))

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (300.0, 250)


# --- the same weight at different prices ---------------------------------------


def test_the_page_default_decides_between_prices_of_one_weight() -> None:
    coffee = product(
        option(250, 259.0, label="whole"),
        option(250, 246.05, label="returnable", default=True),
        option(1000, 945.0),
    )

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (246.05, 250)


def test_without_a_default_the_first_option_of_that_weight_in_page_order_wins() -> None:
    """dosmundos/1584: 250 g at 259 Kc and 250 g in a returnable tin at 246.05."""
    coffee = product(
        option(250, 259.0),
        option(1000, 945.0),
        option(250, 246.05),
        option(1000, 897.75),
        price=259.0,
        weight_g=250,
    )

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (259.0, 250)


def test_a_default_of_another_weight_does_not_pull_the_choice_away() -> None:
    coffee = product(option(250, 300.0), option(250, 310.0), option(1000, 1000.0, default=True))

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (300.0, 250)


# --- options that state no weight ------------------------------------------------


def test_options_without_a_weight_are_not_candidates() -> None:
    coffee = product(option(None, 115.0), option(250, 359.0), price=115.0, weight_g=250)

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (359.0, 250)


def test_no_weight_anywhere_stores_no_price() -> None:
    """The 'od 150' headline of weightless options says nothing about any pack."""
    coffee = product(
        option(None, 150.0, label="a"),
        option(None, 460.0, label="b"),
        price=150.0,
        weight_g=None,
        original_price=190.0,
    )

    settle_price_option(coffee)

    assert (coffee.price, coffee.currency, coffee.weight_g, coffee.original_price) == (
        None,
        None,
        None,
        None,
    )
    assert coffee.price_per_kg is None


def test_a_pack_the_name_states_is_every_weightless_options_pack() -> None:
    """kavaoliver: grinds at different prices, '250g' in the name; the first option's price."""
    coffee = product(
        option(None, 239.0, label="whole"),
        option(None, 245.0, label="ground"),
        price=239.0,
        weight_g=250,
        name='Dóza "OLIVER" s obsahem dle Vašeho výběru - 250g',
    )

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g, coffee.price_per_kg) == (239.0, 250, 956.0)


def test_a_weightless_option_marked_as_the_default_decides_for_the_name_pack() -> None:
    coffee = product(
        option(None, 239.0, label="whole"),
        option(None, 245.0, label="ground", default=True),
        price=239.0,
        weight_g=250,
    )

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (245.0, 250)


# --- one option: price, currency and original price together ----------------------


def test_the_original_price_is_the_chosen_options_own() -> None:
    coffee = product(
        option(70, 115.0, original_price=140.0),
        option(250, 359.0),
        price=115.0,
        weight_g=70,
        original_price=140.0,
    )

    settle_price_option(coffee)

    assert coffee.original_price is None


def test_a_discount_stated_for_the_chosen_option_is_kept() -> None:
    coffee = product(
        option(70, 115.0),
        option(250, 359.0, original_price=420.0),
        price=115.0,
        weight_g=70,
    )

    settle_price_option(coffee)

    assert (coffee.price, coffee.original_price) == (359.0, 420.0)


def test_the_currency_is_the_chosen_options() -> None:
    chosen = option(250, 14.5)
    chosen.currency = "EUR"
    coffee = product(option(70, 5.0), chosen, price=5.0)

    settle_price_option(coffee)

    assert coffee.currency == "EUR"


# --- what must not move ------------------------------------------------------------


def test_a_product_with_one_option_is_left_alone() -> None:
    """zlatezrnko/162159: 14.99 EUR for 200 g stays exactly as the adapter built it."""
    coffee = product(option(250, 14.99), price=14.99, weight_g=200, original_price=19.0)

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g, coffee.original_price) == (14.99, 200, 19.0)


def test_a_product_with_no_options_is_left_alone() -> None:
    coffee = product(price=14.99, weight_g=200)

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (14.99, 200)


def test_options_that_all_carry_one_price_are_left_alone() -> None:
    """A grind selector is not a size choice; the price is unambiguous."""
    coffee = product(
        option(250, 300.0, label="whole"),
        option(250, 300.0, label="ground"),
        price=300.0,
        weight_g=250,
    )

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (300.0, 250)


def test_options_of_different_weights_at_one_price_are_left_alone() -> None:
    """The page prints one price for two bags, so no option is the one it buys."""
    coffee = product(option(250, 215.0), option(500, 215.0), price=215.0, weight_g=500)

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (215.0, 500)


def test_options_that_state_weights_but_no_price_are_left_alone() -> None:
    """A WooCommerce Store API variable product: the variations carry no price (#237)."""
    coffee = product(option(70, None), option(250, None), option(1000, None), price=115.0)
    coffee.weight_g = 70

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (115.0, 70)


def test_a_second_option_without_a_price_leaves_the_priced_one_alone() -> None:
    """coffeein.cz: only the page's own package states a price."""
    coffee = product(option(250, 300.0), option(1000, None), price=300.0, weight_g=250)

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (300.0, 250)


def test_settling_twice_changes_nothing() -> None:
    coffee = product(option(70, 115.0), option(250, 359.0), option(1000, 1399.0), price=115.0)

    settle_price_option(coffee)
    once = stored(coffee)
    settle_price_option(coffee)

    assert stored(coffee) == once


# --- the per-kilogram basis follows the chosen option --------------------------------


def test_price_basis_reads_the_chosen_option() -> None:
    coffee = product(option(70, 115.0), option(250, 359.0), option(1000, 1399.0), price=115.0)

    settle_price_option(coffee)

    basis = coffee.price_basis
    assert basis is not None
    assert (basis.price, basis.weight_g, basis.source) == (359.0, 250, "variant")


def test_price_basis_still_refuses_two_weights_at_one_price() -> None:
    """kavakromeriz/1614 prints 218 Kc for both 250 g and 100 g: no per-kilogram figure."""
    coffee = product(
        option(100, 218.0), option(250, 218.0), option(1000, 833.0), price=833.0, weight_g=1000
    )

    settle_price_option(coffee)

    assert (coffee.price, coffee.weight_g) == (218.0, 250)
    assert coffee.price_per_kg is None


# --- choose_option on its own ------------------------------------------------------


def test_choose_option_states_none_without_a_priced_weighted_option() -> None:
    assert choose_option([option(None, 100.0), option(250, None)]) is None


def test_choose_option_assumes_a_weight_when_told_to() -> None:
    chosen = choose_option(
        [option(None, 100.0, label="a"), option(None, 90.0)], assume_weight_g=250
    )

    assert chosen is not None
    assert chosen.label == "a"


# --- every adapter's parse_product settles ------------------------------------------


class _LadderSite(SiteAdapter):
    site_id = "ladder"
    name = "Ladder"
    base_url = "https://ladder.example"

    def discover(
        self,
        fetcher: PoliteFetcher,
        *,
        max_pages: int | None = None,
    ) -> Iterator[ProductRef]:
        return iter(())

    def parse_product(self, html: str, ref: ProductRef) -> Coffee | None:
        if html == "skip":
            return None
        return product(option(70, 115.0), option(250, 359.0), price=115.0, weight_g=70)


def test_a_new_adapters_parse_product_is_settled_without_calling_the_chooser() -> None:
    site = _LadderSite()
    ref = ProductRef(site_id="ladder", external_id="1", url="https://ladder.example/p/")

    coffee = site.parse_product("page", ref)

    assert coffee is not None
    assert (coffee.price, coffee.weight_g) == (359.0, 250)
    assert site.parse_product("skip", ref) is None


# --- the saved pages ----------------------------------------------------------------


def _shoptet(site_id: str, fixture: str, fixture_html: Callable[[str, str], str]) -> Coffee:
    site = adapter_for(site_id)
    ref = ProductRef(site_id=site_id, external_id="1", url=f"{site.base_url}p/")
    coffee = site.parse_product(fixture_html(f"shoptet_{site_id}", fixture), ref)
    assert coffee is not None
    return coffee


def test_botacoffee_5524_page_stores_the_250_g_option(
    fixture_html: Callable[[str, str], str],
) -> None:
    coffee = _shoptet("botacoffee", "detail_rwanda_gicumbi.html", fixture_html)

    assert (coffee.price, coffee.weight_g, coffee.price_per_kg) == (359.0, 250, 1436.0)


def test_daliacoffee_1077_page_stores_the_first_250_g_roast(
    fixture_html: Callable[[str, str], str],
) -> None:
    """Two roasts at 250 g, 500 g and 1 kg: the shop pre-selects none, so page order decides."""
    coffee = _shoptet("daliacoffee", "detail_kenya_embu.html", fixture_html)

    assert (coffee.price, coffee.weight_g, coffee.price_per_kg) == (338.0, 250, 1352.0)
    assert coffee.variants[0].label == "250 g / Střední (espresso)"


@pytest.mark.parametrize(
    ("site_id", "fixture", "expected"),
    [
        ("pepecoffee", "detail_espresso_blend_office.html", (220.0, 200)),
        ("jungleroastery", "detail_colombia_penas.html", (17.3, 250)),
    ],
)
def test_the_other_saved_shoptet_ladders_store_their_nearest_option(
    site_id: str,
    fixture: str,
    expected: tuple[float, int],
    fixture_html: Callable[[str, str], str],
) -> None:
    coffee = _shoptet(site_id, fixture, fixture_html)

    assert (coffee.price, coffee.weight_g) == expected


def test_no_adapter_mixes_two_options_on_a_saved_page(
    fixture_html: Callable[[str, str], str],
) -> None:
    for site_id, fixture in (
        ("botacoffee", "detail_rwanda_gicumbi.html"),
        ("daliacoffee", "detail_kenya_embu.html"),
        ("pepecoffee", "detail_espresso_blend_office.html"),
        ("jungleroastery", "detail_colombia_penas.html"),
    ):
        coffee = _shoptet(site_id, fixture, fixture_html)
        pairs = {(v.price, v.weight_g) for v in coffee.variants}

        assert (coffee.price, coffee.weight_g) in pairs, site_id


def test_the_ebenica_form_preselects_the_220_g_bag_over_a_dearer_gift_box(
    fixture_html: Callable[[str, str], str],
) -> None:
    """The variation form marks 220 g selected; a 70 g sample and a 500 g bag are around it."""
    site = adapter_for("ebenica")
    ref = ProductRef(site_id="ebenica", external_id="1", url="https://ebenica.sk/x/")

    coffee = site.parse_product(fixture_html("woo_ebenica", "detail_colombia_la_secreta.html"), ref)

    assert coffee is not None
    assert (coffee.price, coffee.currency, coffee.weight_g) == (11.9, "EUR", 220)
    assert [variant.default for variant in coffee.variants] == [False, True, False, False, False]
