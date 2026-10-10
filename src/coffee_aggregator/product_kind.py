# The kinds a product can be, and the sources a kind can come from. Plain strings
# rather than an enum, because they are written to a text column and read back
# out of CSV, where an enum would be converted at every edge.
#
# `beans` is the only kind the catalogue serves: one specific roasted coffee, whole
# bean or ground. The other kinds are recorded and kept out of that view, so a
# change of mind about a product's kind is a change to one column, never a delete.
#
# `unknown` is a verdict, not a missing value: a reviewer looked and could not tell
# what the product is, and the decider never writes it. NULL in product_kind says
# nothing has placed the row yet, so the decider tries it again on every crawl. The
# two must stay apart, or a row nobody has reviewed looks the same as one that was
# tried and failed.

from __future__ import annotations

from typing import Final

PRODUCT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "beans",
        "capsules",
        "instant",
        "green",
        "ready_to_drink",
        "sampler",
        "kit",
        "equipment",
        "merch",
        "food",
        "service",
        "cosmetics",
        "not_a_product",
        "other_drink",
        "test",
        "unknown",
    }
)

# A labelled row that no reviewer looked at again. The seed is a starting fill
# rather than a verdict, so it keeps its own source and is not filed under a rule
# that never ran.
SEED_SOURCE: Final = "seed"

# A labelled row a reviewer then checked (the `reviewed` column of the seed). It is
# kept apart from SEED_SOURCE because a checked answer should carry more weight
# than one nobody looked at again.
SEED_REVIEWED_SOURCE: Final = "seed-reviewed"
