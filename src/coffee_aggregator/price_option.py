from __future__ import annotations

from typing import TYPE_CHECKING, Final

from coffee_aggregator.labels import plausible_weight

if TYPE_CHECKING:
    from collections.abc import Sequence

    from coffee_aggregator.models import Coffee, Variant

#: The pack every product is compared at: the stored option is the one nearest
#: this weight, as the owner ruled on 2026-10-18 (coffee-aggregator#172).
TARGET_WEIGHT_G: Final = 250
#: An option lighter than this is a sample, skipped whenever a larger option
#: exists; a coffee sold only as a sample keeps its sample.
SAMPLE_BELOW_G: Final = 100


def settle_price_option(coffee: Coffee) -> None:
    """Store one purchasable option's price, weight, currency and original price.

    The stored ``price``, ``weight_g``, ``currency`` and ``original_price`` of a
    product that offers several options at different prices come from one option,
    chosen by :func:`choose_option`; whatever headline the adapter built is
    replaced.

    Options that state no price are not part of the choice. A product with fewer
    than two options, whose priced options state one price, or whose options state
    no price, is left exactly as the adapter built it.

    When no priced option states a weight, the pack the product name or a weight
    label states is every option's pack, and the choice is made among them. When
    the page states no pack either, the four values are None.

    Args:
        coffee: The freshly parsed product, modified in place.
    """
    priced = [variant for variant in coffee.variants if states_price(variant)]
    if len({_cents(variant) for variant in priced}) < 2:  # noqa: PLR2004  (one price is no choice)
        return
    if any(plausible_weight(variant.weight_g) for variant in priced):
        option = choose_option(priced)
        pack = option.weight_g if option is not None else None
    else:
        pack = coffee.weight_g
        option = choose_option(priced, assume_weight_g=pack) if pack else None
    if option is None or not pack:
        coffee.price = None
        coffee.currency = None
        coffee.weight_g = None
        coffee.original_price = None
        return
    coffee.price = option.price
    coffee.currency = option.currency or coffee.currency
    coffee.weight_g = pack
    coffee.original_price = option.original_price


def choose_option(
    options: Sequence[Variant],
    *,
    assume_weight_g: int | None = None,
) -> Variant | None:
    """Choose the option a product is stored under.

    The candidates are the options that state a price and a plausible weight.
    They narrow in this order, and a step that would leave nothing is skipped:

    1. not a sample: only the options of at least :data:`SAMPLE_BELOW_G`, so a
       sample in stock never outranks a larger option that is sold out;
    2. in stock: only the options known to be in stock, which a product that
       states stock per product only, or in no option, never narrows;
    3. nearest :data:`TARGET_WEIGHT_G` in absolute grams, the heavier of two
       equidistant weights;
    4. the one option of that weight the page marks as its default, otherwise
       the first of them in page order, when several options of one weight carry
       different prices (a grind, a roast, a returnable tin).

    Args:
        options: The product's options, in the page's own order.
        assume_weight_g: The weight every option stands for, when none of them
            states its own.

    Returns:
        The chosen option, or None when no option qualifies.
    """
    pool: list[tuple[Variant, int]] = []
    for option in options:
        grams = option.weight_g if assume_weight_g is None else assume_weight_g
        if states_price(option) and grams and (assume_weight_g or plausible_weight(grams)):
            pool.append((option, grams))
    pool = [pair for pair in pool if pair[1] >= SAMPLE_BELOW_G] or pool
    pool = [pair for pair in pool if pair[0].available is True] or pool
    if not pool:
        return None
    nearest = min(_distance(grams) for _, grams in pool)
    same_weight = [option for option, grams in pool if _distance(grams) == nearest]
    return next((option for option in same_weight if option.default), same_weight[0])


def _distance(grams: int) -> tuple[int, int]:
    """Rank a weight by how near it is to the target, the heavier first on a tie.

    Args:
        grams: An option's weight.

    Returns:
        A key that sorts the nearest weight lowest.
    """
    return abs(grams - TARGET_WEIGHT_G), -grams


def states_price(variant: Variant) -> bool:
    """Say whether an option states a price a shopper could pay.

    Args:
        variant: One option of a product.

    Returns:
        True when the option's price is present and above zero.
    """
    return variant.price is not None and variant.price > 0


def first_priced(options: Sequence[Variant]) -> Variant | None:
    """Return the first option, in page order, that states a price.

    Adapters use it for the price they hand to
    :func:`settle_price_option` while a product's options all state one price,
    where every option gives the same answer.

    Args:
        options: The product's options, in the page's own order.

    Returns:
        The first priced option, or None when none states a price.
    """
    return next((option for option in options if states_price(option)), None)


def _cents(variant: Variant) -> int:
    """Express an option's price in whole cents, so two spellings of one price match.

    Args:
        variant: An option that states a price.

    Returns:
        The price in hundredths of the currency unit.
    """
    return round((variant.price or 0.0) * 100)
