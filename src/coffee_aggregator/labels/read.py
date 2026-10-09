from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from coffee_aggregator import normalize
from coffee_aggregator.labels.collect import plausible_pack, plausible_weight
from coffee_aggregator.labels.terms import (
    F_ACIDITY,
    F_ALTITUDE,
    F_BEST_BEFORE,
    F_BITTERNESS,
    F_BODY,
    F_BREWING,
    F_COUNTRY,
    F_DECAF,
    F_FARM,
    F_FLAVOR,
    F_HARVEST,
    F_PRODUCER,
    F_REGION,
    F_ROAST,
    F_ROAST_DATE,
    F_SCA,
    F_SPECIES,
    F_STATION,
    F_SWEETNESS,
    F_VARIETY,
    F_WEIGHT,
)
from coffee_aggregator.models import (
    DEFAULT_TASTE_SCALE_MAX,
    Origin,
    Roast,
    Species,
    Taste,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from coffee_aggregator.labels.collect import Labels
    from coffee_aggregator.models import Variant

__all__ = [
    "bar",
    "headline_weight",
    "is_decaf",
    "notes_from_text",
    "option_list",
    "parse_origin",
    "parse_roast",
    "parse_species",
    "parse_taste",
    "score",
    "specialty_grade",
    "stated_pack",
    "stated_weight",
]

_MIN_SCA_SCORE: Final = 50.0
_SPECIALTY_SCORE: Final = 80.0
_MAX_SCA_SCORE: Final = 100.0
_MAX_NOTE_LENGTH: Final = 32
_MIN_NOTES: Final = 2
_MAX_NOTES: Final = 8

#: The ``"+10 Kč"`` / ``"+0,50 €"`` surcharge a shop appends to a variant option.
_PRICE_SUFFIX_RE: Final = re.compile(
    r"\s*[+\-−]\s*\d[\d\s.,]*\s*(?:kč|kc|czk|eur|€|\$|zl|huf)\s*$",
    re.IGNORECASE,
)


def option_list(text: str | None) -> list[str]:
    """Split an option list and drop the price surcharge each option carries.

    A shop renders a paid variant axis as ``"Espresso +10 Kč"``; the money is a
    property of the shop's pricing, not of the brewing method.

    Args:
        text: The joined option labels, or any other enumeration.

    Returns:
        The items, surcharges removed, empty ones dropped.
    """
    cleaned = (_PRICE_SUFFIX_RE.sub("", item).strip() for item in normalize.split_list(text))
    return [item for item in cleaned if item]


def notes_from_text(text: str | None) -> list[str]:
    """Read flavour notes from a value that is really a list of them.

    Roasteries very often use the short description for nothing but the cup
    notes (``"Citrusy • Sušená slivka • Tmavé kakao"``), so a summary that splits
    into a handful of short, sentence-free fragments is treated as such a list.

    Args:
        text: The short description, or the value of a "flavour" parameter.

    Returns:
        The notes, or an empty list when the text is ordinary prose.
    """
    items = option_list(text)
    if not _MIN_NOTES <= len(items) <= _MAX_NOTES:
        return []
    if any(len(item) > _MAX_NOTE_LENGTH or "." in item for item in items):
        return []
    return items


def score(labels: Labels) -> float | None:
    """Read a cupping score, rejecting values outside the SCA range.

    Args:
        labels: Every labelled value on the page.

    Returns:
        The score, or None.
    """
    value = normalize.parse_float(labels.get(F_SCA))
    if value is None or not _MIN_SCA_SCORE <= value <= _MAX_SCA_SCORE:
        return None
    return value


def bar(labels: Labels, field_name: str) -> int | None:
    """Read a sensory bar, in points when the shop draws one and in words when not.

    Half the shops publish "Telo: 4/5" and the other half "Telo: vysoké"; both
    end up on the same 1-5 scale so the two are comparable.

    Args:
        labels: Every labelled value on the page.
        field_name: One of the ``F_BODY``/``F_ACIDITY``/… constants.

    Returns:
        The value on the 0-5 scale, or None when the page states neither.
    """
    value = labels.get(field_name)
    points = normalize.parse_int(value)
    if points is not None and 0 <= points <= DEFAULT_TASTE_SCALE_MAX:
        return points
    return normalize.parse_intensity(value)


def parse_taste(labels: Labels, summary: str | None) -> Taste:
    """Build the sensory part of the model.

    Args:
        labels: Every labelled value on the page.
        summary: The short description, used when no label names the notes.

    Returns:
        The taste block.
    """
    # Both sources go through the same guard: a shop that writes a whole
    # sentence into its "Chuťový profil" row states tasting_text, not a list of
    # notes, and a one-sentence bucket would poison every cross-shop grouping.
    notes = notes_from_text(labels.get(F_FLAVOR)) or notes_from_text(summary)
    return Taste(
        body=bar(labels, F_BODY),
        bitterness=bar(labels, F_BITTERNESS),
        acidity=bar(labels, F_ACIDITY),
        sweetness=bar(labels, F_SWEETNESS),
        scale_max=DEFAULT_TASTE_SCALE_MAX,
        flavor_notes=notes,
        tasting_text=labels.get(F_FLAVOR),
        brewing_methods=option_list(labels.get(F_BREWING)),
        sca_score=score(labels),
    )


def parse_roast(labels: Labels, categories: list[str]) -> Roast:
    """Build the roast part of the model.

    Args:
        labels: Every labelled value on the page.
        categories: The breadcrumb trail, which usually names espresso/filter.

    Returns:
        The roast block.
    """
    raw = labels.get(F_ROAST)
    sources = " ".join(
        value for value in (raw, labels.get(F_BREWING), *categories) if value is not None
    )
    return Roast(
        level=normalize.normalize_roast_level(raw),
        raw=raw,
        profile=normalize.normalize_roast_profile(sources),
        roast_date=normalize.parse_date_dmy(labels.get(F_ROAST_DATE)),
        best_before=normalize.parse_date_dmy(labels.get(F_BEST_BEFORE)),
    )


def parse_origin(labels: Labels, name: str, *, blend: bool) -> Origin:
    """Build the origin part of the model.

    Args:
        labels: Every labelled value on the page.
        name: The product name — for single origins the most reliable source.
        blend: Whether the product is a blend, in which case no single country
            is claimed.

    Returns:
        The origin block.
    """
    altitude_raw = labels.get(F_ALTITUDE)
    low, high = normalize.parse_altitude(altitude_raw)
    country = None
    if not blend:
        country = normalize.detect_country(labels.get(F_COUNTRY)) or normalize.detect_country(name)
    return Origin(
        country=country,
        region=labels.get(F_REGION),
        farm=labels.get(F_FARM),
        producer=labels.get(F_PRODUCER),
        washing_station=labels.get(F_STATION),
        altitude_min_m=low,
        altitude_max_m=high,
        altitude_raw=altitude_raw,
        variety=normalize.clean_variety(normalize.split_list(labels.get(F_VARIETY))),
        harvest=labels.get(F_HARVEST),
    )


def parse_species(labels: Labels, name: str) -> Species:
    """Build the arabica/robusta split.

    Args:
        labels: Every labelled value on the page.
        name: The product name, which often carries the word "blend".

    Returns:
        The species block.
    """
    raw = labels.get(F_SPECIES)
    arabica, robusta = normalize.parse_species(raw)
    return Species(
        arabica_pct=arabica,
        robusta_pct=robusta,
        other=raw,
        is_blend=normalize.detect_blend(f"{name} {raw or ''}", arabica, robusta),
    )


def specialty_grade(name: str, categories: list[str], cupping: float | None) -> bool | None:
    """Decide whether the product is specialty-grade coffee.

    Args:
        name: The product name.
        categories: The breadcrumb trail.
        cupping: The cupping score, when the page states one.

    Returns:
        True when the page says so outright or cups at 80+, else None — a shop
        that never mentions grading has not said the coffee is commodity.
    """
    if cupping is not None:
        return cupping >= _SPECIALTY_SCORE
    blob = normalize.fold(" ".join([name, *categories]))
    return True if "specialty" in blob or "speciality" in blob else None


def is_decaf(labels: Labels, name: str, categories: list[str]) -> bool:
    """Decide whether the product is decaffeinated.

    Args:
        labels: Every labelled value on the page.
        name: The product name.
        categories: The breadcrumb trail.

    Returns:
        True when any of the three says so.
    """
    blob = normalize.fold(" ".join([name, labels.get(F_DECAF) or "", *categories]))
    return "bezkofein" in blob or "decaf" in blob or "bez kofein" in blob


def stated_weight(text: str | None) -> int | None:
    """Read a weight a shop states outright, refusing a list of sizes.

    ``"250 g"`` is a statement about this bag; ``"250 g, 500 g, 1 kg"`` is the
    shop's size axis rendered into one cell, and reading its first entry is how
    ``ripit.sk`` reported 1000 g against a price for 250 g.

    Args:
        text: The value of a weight label, or a product name.

    Returns:
        The weight in grams, or None when the text states none or states several.

    """
    if not text:
        return None
    weights = {
        grams
        for item in normalize.split_list(text)
        if plausible_weight(grams := normalize.parse_weight_grams(item))
    }
    if len(weights) == 1:
        return weights.pop()
    if weights:
        return None
    # Nothing survived the split, which is what "0,25 kg" looks like once the
    # comma is read as a list separator; the undivided text still states a size.
    whole = normalize.parse_weight_grams(text)
    return whole if plausible_weight(whole) else None


def stated_pack(text: str | None) -> int | None:
    """Read the total weight a text states for one package, refusing a size list.

    The same rule as :func:`stated_weight`, with two differences: a multiplier
    the text spells out is multiplied through, and the result may be far larger
    than a bag, because a carton is what some shops sell.

    Args:
        text: The value of a weight label, or a product name.

    Returns:
        The weight in grams, or None when the text states none or states several.
    """
    if not text:
        return None
    weights = {
        grams
        for item in normalize.split_list(text)
        if plausible_pack(grams := normalize.parse_pack_grams(item))
    }
    if len(weights) == 1:
        return weights.pop()
    if weights:
        return None
    whole = normalize.parse_pack_grams(text)
    return whole if plausible_pack(whole) else None


def headline_weight(
    labels: Labels,
    name: str,
    variants: Sequence[Variant],
    *,
    price: float | None = None,
    fallback: str | None = None,
) -> int | None:
    """Work out the weight the headline price refers to.

    ``price_per_kg`` is the number every product is ranked on, so this is the
    one reading three platforms may not each invent for themselves. The
    precedence, most trustworthy first:

    1. a *multiplied* pack the product name spells out — "4x75 g", "3x100 g",
       a carton, a tasting set — because a multiplier is the one thing an
       option cannot state: a shop that sells the whole pack as one option
       still labels that option with the size of one bag inside it;
    2. the weight of the packaging option whose price *is* the headline price,
       when exactly one weight carries that price. The option select is the
       shop saying what this very price buys, which is the same offer
       :attr:`~coffee_aggregator.models.Coffee.price_basis` divides by; reading
       the two from different places is what let 35 of 3678 rows store a weight
       that contradicts their own published ``price_per_kg``;
    3. any other pack the product name spells out that is larger than the
       weight label, because then the label is one bag and the name is what
       the price buys. Only a name that states one size at all: a second size
       belongs to a second article, and the bundled grinder is not what is
       being weighed, unless the sizes reconcile: a carton that also spells
       out the bags inside it ("5 kg (20x250g)") states one article twice;
    4. a weight the shop *states* on a weight label, when it states exactly one
       — several mean the label is really the size axis, not this bag;
    5. a weight the product name states, for the shops whose "Brasil 1000 g" is
       the only place the size is written at all;
    6. the weight of the cheapest priced variant, since every platform quotes
       the cheapest variant as the headline price of a variable product;
    7. the smallest weight any variant states, when no variant is priced;
    8. a caller-supplied last resort, such as Shoptet's parcel weight.

    Args:
        labels: Every labelled value the page states.
        name: The product name.
        variants: The parsed variants, in the platform's own order.
        price: The headline price, which names the variant it belongs to.
        fallback: A last-resort weight text, believed only when nothing else
            states a size.

    Returns:
        The weight in grams, or None.
    """
    one = _one_package(labels, name, variants, price=price, fallback=fallback)
    # "Illy Intenso 36 ks" is thirty-six tins and the page states the size of
    # one of them, never of the case. Three spellings across two shops agree
    # once the count is applied — 36 ks, 12 ks and "250g 12ks" all land within
    # 30 CZK/kg of each other — and disagree wildly without it.
    count = normalize.parse_pack_count(name)
    if one is None or count is None:
        return one
    whole = one * count
    # A count that produces something no shop sells was not a count.
    return whole if plausible_pack(whole) else one


def _one_package(
    labels: Labels,
    name: str,
    variants: Sequence[Variant],
    *,
    price: float | None,
    fallback: str | None,
) -> int | None:
    """Return the weight of a single package, before any count is applied.

    Args:
        labels: Every labelled value the page states.
        name: The product name.
        variants: The parsed variants, in the platform's own order.
        price: The headline price.
        fallback: A last-resort weight text.

    Returns:
        The weight in grams, or None.
    """
    from_label = stated_weight(labels.get(F_WEIGHT))
    # A name that states more than the weight label is naming the pack while the
    # label names one bag inside it, and the price buys the pack. kava.cz sells
    # the same coffee as 1 kg, 6 kg and 24 kg on three pages that all carry a
    # 1 kg label; believing the label made the 24 kg carton 24 times too dear.
    from_pack = _pack_the_name_states(name, from_label)
    # A multiplier the name spells out is the one thing an option cannot say.
    # lighthousecoffee sells "degustačný balíček 4x75 g" as a single
    # "4x75 gramov" option, and that option's weight is one of the four bags
    # the price buys; reading it would publish a per-kilogram price four times
    # too high, which is what #30 and #52 measured and fixed.
    if from_pack is not None and from_pack != stated_weight(name):
        return from_pack
    named_by_price = _weight_priced_exactly(variants, price)
    if named_by_price is not None:
        return named_by_price
    if from_pack is not None:
        return from_pack
    if from_label is not None:
        return from_label
    from_name = stated_weight(name)
    if from_name is not None:
        return from_name
    return _weight_no_statement_settles(variants, fallback)


def _pack_the_name_states(name: str, from_label: int | None) -> int | None:
    """Return the package weight the product name spells out, when it names one.

    Args:
        name: The product name.
        from_label: The weight a label states, which a name only overrules by
            stating something larger.

    Returns:
        The weight in grams, or None when the name does not name the package.
    """
    from_pack = stated_pack(name)
    if from_pack is None or not _one_article(name):
        return None
    return from_pack if from_label is None or from_pack > from_label else None


def _weight_no_statement_settles(
    variants: Sequence[Variant],
    fallback: str | None,
) -> int | None:
    """Return the weight to use when neither the name nor a label states one.

    Args:
        variants: The parsed variants.
        fallback: A last-resort weight text, such as Shoptet's parcel weight.

    Returns:
        The weight in grams, or None.
    """
    from_variants = _weight_of_cheapest_variant(variants) or _smallest_variant_weight(variants)
    return from_variants if from_variants is not None else stated_weight(fallback)


def _one_article(name: str) -> bool:
    """Say whether a name states a size for one article rather than for several.

    "Mlýnek s násypkou 1 kg + káva 250 g" states two sizes belonging to two
    different things, and the larger one is the grinder; believing it over the
    250 g label priced the coffee at a quarter of its true per-kilogram price.
    Counting the sizes was the first answer to that, and it was too blunt: a
    carton that restates its own total — "BANUA Café 5 kg (20x250g)" — also
    states two, and refusing them left it on the 250 g label at twenty times
    its true per-kilogram price (#70). Of 3816 live products, 12 names state
    two sizes: 10 are one shop's size axis ("250g – 500g") and 2 are cartons
    whose multiplication reconciles them.

    Args:
        name: The product name.

    Returns:
        True when the name states at most one distinct weight, or states
        several that describe one package.
    """
    sizes = set(normalize.parse_weights_grams(name))
    return len(sizes) <= 1 or _restates_its_own_total(name, sizes)


def _restates_its_own_total(name: str, sizes: set[int]) -> bool:
    """Say whether a name's several sizes are one multipack written twice.

    "BANUA Café 5 kg (20x250g)" names the carton and the bag inside it, and the
    multiplication reconciles the two: 20 x 250 g is exactly the 5 kg the same
    name states. A bundle's sizes never reconcile that way, which is what tells
    the carton apart from the grinder #27 was written for.

    Args:
        name: The product name.
        sizes: The distinct weights the name states.

    Returns:
        True when every size the name states is either one package of a
        multiplication it spells out or that multiplication's total.
    """
    multiplied = normalize.parse_multiplied_pack_grams(name)
    if multiplied is None:
        return False
    each, total = multiplied
    return total in sizes and sizes <= {each, total}


def _weight_priced_exactly(variants: Sequence[Variant], price: float | None) -> int | None:
    """Return the weight of the option that costs exactly the headline price.

    vrescaffe's ``/terra-100g-2/`` is named "Terra 100g" and every one of its
    six options states 1000 g at the one price the page shows; believing the
    name stored a bag ten times too light beside a per-kilogram price taken
    from the options. The name is the shop's error and the options are not.

    Args:
        variants: The parsed variants.
        price: The headline price, or None when the platform states none.

    Returns:
        The weight in grams, or None when the options do not settle it — no
        price to match, none matching, or two sizes sharing it.
    """
    if price is None:
        return None
    exact = {
        variant.weight_g
        for variant in variants
        if variant.price == price and plausible_weight(variant.weight_g)
    }
    return exact.pop() if len(exact) == 1 else None


def _weight_of_cheapest_variant(variants: Sequence[Variant]) -> int | None:
    """Return the weight of the cheapest option a shop prices.

    Args:
        variants: The parsed variants.

    Returns:
        The weight in grams, or None when no priced variant settles it.
    """
    priced = [
        variant
        for variant in variants
        if variant.price is not None and plausible_weight(variant.weight_g)
    ]
    if not priced:
        return None
    return min(priced, key=lambda variant: variant.price or 0.0).weight_g


def _smallest_variant_weight(variants: Sequence[Variant]) -> int | None:
    """Return the smallest size a shop lists, for a ladder it prices nowhere.

    Args:
        variants: The parsed variants.

    Returns:
        The weight in grams, or None when no variant states a usable one.
    """
    weights = [
        grams for variant in variants if plausible_weight(grams := variant.weight_g) and grams
    ]
    return min(weights) if weights else None
