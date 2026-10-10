# Narrow rules that decide a product's kind from its name and its external id.
#
# A marker here names a non-coffee kind beyond doubt, and a row that matches none of
# them stays undecided. The catalogue is about 95% coffee, so the job is finding the
# rest, never proving a row is coffee: a rule keyed on "does this look like coffee"
# deletes whole shops whose names carry no coffee words at all.
#
# Each marker was checked against the names of every bean in the labelled catalogue.
# The words that also name coffee are therefore absent: "filter", "cup", "cold brew",
# "chocolate", "sugar" and "nitro" each appear in real blend or origin names. "ml"
# counts only after a drink word, and a piece count only in brackets, for the same reason.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from coffee_aggregator import normalize

#: A plain lower-case slug, such as a category page's address, where a product id belongs.
#: A numeric id or a UUID has digits in it, so neither matches.
_SLUG_ID: Final = re.compile(r"[a-z]+(?:-[a-z]+)*")


@dataclass(frozen=True, slots=True)
class KindDecision:
    """A kind a rule decided, and the rule that decided it.

    Attributes:
        kind: A member of :data:`product_kind.PRODUCT_KINDS`.
        source: The value for ``product_kind_source``, naming the rule.
    """

    kind: str
    source: str


@dataclass(frozen=True, slots=True)
class _Rule:
    kind: str
    name: str
    pattern: re.Pattern[str]


def _rule(kind: str, name: str, pattern: str) -> _Rule:
    return _Rule(kind=kind, name=name, pattern=re.compile(pattern))


# Applied to the folded name, so the patterns are plain ASCII. Order decides between
# two rules that both match, and no two of these overlap in the labelled catalogue.
_RULES: Final[tuple[_Rule, ...]] = (
    _rule("test", "shop-test-product", r"\btest\b"),
    _rule("capsules", "capsule", r"\bkapsl|\bcapsul|\bnespresso\b"),
    _rule("instant", "instant", r"\binstant"),
    _rule(
        "ready_to_drink",
        "bottled-drink",
        r"\bready to drink\b|\b(cold brew|nitro)\b.*\d+(\.\d+)? ?ml\b",
    ),
    _rule("equipment", "paper-cup", r"\bpaper cup\b|\bespresso cup\b|\bpapi[ei]r\w*\s*(poh|kelim)"),
    _rule("equipment", "paper-filter", r"\bpaper\w* filt|\bpapi[ei]r\w* filt"),
    _rule("equipment", "piece-count", r"\(\d+ ?pcs\)"),
    _rule(
        "equipment",
        "machine-or-cleaner",
        r"\bkavovar\b|\bbialetti\b|\burnex\b|\bcafiza\b|\brinza\b",
    ),
    _rule("merch", "clothing", r"\btricko\b|\btriko\b|\bt[ -]?shirt\b|\bksiltovk\w*|\bsnapback\b"),
    _rule("merch", "sticker", r"\bnalep\w*|\bsticker"),
    _rule("merch", "bag", r"\btaska\b"),
    _rule("merch", "voucher", r"\bpoukaz|\bvoucher\b"),
    _rule("merch", "subscription", r"\bpredplatn\w*|\bsubscription\b"),
    _rule("food", "chocolate-covered", r"\bv (\w+ )?cokolad\w*"),
    _rule("food", "sugar", r"\bcukr\w*"),
    _rule("food", "bar", r"\btycink\w*"),
    _rule("service", "course", r"\bkurz(y|u|e)?\b"),
    _rule("service", "custom-roast", r"\bzakazk\w*"),
    _rule(
        "service",
        "white-label",
        r"\bwhite ?label|\bprivate label\b|\bvlastn\w* (logo|logem|znack)|\bpod vlastn\w* znack",
    ),
    _rule("cosmetics", "scrub-or-soap", r"\bmydl\w*|\bpeeling\w*|\bscrub\b"),
    _rule("other_drink", "rooibos", r"\brooibos\b"),
)


def decide(name: str, external_id: str) -> KindDecision | None:
    """Decide a product's kind from what the shop calls it.

    Args:
        name: The product name as the shop wrote it.
        external_id: The shop's id for the product.

    Returns:
        The kind and the rule that decided it, or None when no rule is sure. None is
        not a verdict that the row is coffee; the caller leaves the kind as it was.
    """
    if _SLUG_ID.fullmatch(external_id):
        return KindDecision(kind="not_a_product", source="rule:slug-id")
    folded = normalize.fold(name)
    for rule in _RULES:
        if rule.pattern.search(folded):
            return KindDecision(kind=rule.kind, source=f"rule:{rule.name}")
    return None
