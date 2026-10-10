from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from coffee_aggregator import normalize, product_kind_rules

if TYPE_CHECKING:
    from collections.abc import Sequence

    import psycopg

    from coffee_aggregator.models import Coffee

#: The stored kind and name hash of every row in a chunk that is already in the store.
#: The keys are unnested into two arrays, so one statement reads a whole chunk.
STORED_SQL: Final = (
    "SELECT c.site, c.external_id, c.product_kind, c.product_kind_name_hash "
    "FROM coffee c JOIN unnest(%s::text[], %s::text[]) AS k(site, external_id) "
    "USING (site, external_id)"
)

#: The guard repeats the test the caller made. A seed loaded by another process
#: between the read and this write keeps the kind it was given, because its hash
#: is the current one.
SET_SQL: Final = (
    "UPDATE coffee SET product_kind = %s, product_kind_source = %s, "
    "product_kind_name_hash = %s WHERE site = %s AND external_id = %s "
    "AND (product_kind IS NULL OR product_kind_name_hash IS DISTINCT FROM %s)"
)


def rows_for(cursor: psycopg.Cursor[Any], chunk: Sequence[Coffee]) -> list[tuple[Any, ...]]:
    """Decide the kinds a chunk needs and return the parameters that write them.

    A row whose stored kind was decided for the name it has now is left alone, and
    the decider does not run on it. Every other row is decided afresh, and a rule's
    answer is written with the hash of the current name. When no rule is sure, nothing
    is written: an empty kind stays empty, and a stored kind stays as it was, so a
    crawl never clears a kind. The hash then still misses, and the next crawl asks again.

    Args:
        cursor: The cursor of the open transaction, read before the upsert.
        chunk: The coffees about to be written.

    Returns:
        One parameter tuple per row that :data:`SET_SQL` must write, in chunk order.
    """
    keys = [(coffee.site, coffee.external_id) for coffee in chunk]
    cursor.execute(STORED_SQL, ([site for site, _ in keys], [external for _, external in keys]))
    stored = {
        (str(site), str(external)): (kind, name_hash)
        for site, external, kind, name_hash in cursor.fetchall()
    }
    rows: list[tuple[Any, ...]] = []
    for coffee in chunk:
        current = normalize.product_name_hash(coffee.name)
        kind_now, hash_now = stored.get((coffee.site, coffee.external_id), (None, None))
        if kind_now is not None and hash_now == current:
            continue
        decision = product_kind_rules.decide(coffee.name, coffee.external_id)
        if decision is None:
            continue
        rows.append(
            (decision.kind, decision.source, current, coffee.site, coffee.external_id, current)
        )
    return rows
