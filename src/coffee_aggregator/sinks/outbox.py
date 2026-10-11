from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, NamedTuple

from coffee_contracts import COFFEE_STATE, CoffeeState, SubjectError, catalogue, to_json

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    import psycopg

    from coffee_aggregator.models import Coffee

logger = logging.getLogger(__name__)

#: The columns an outbox row is written with; the database fills in ``id``,
#: ``created_at`` and, when the publisher has sent it, ``published_at``.
OUTBOX_COLUMNS: tuple[str, ...] = ("subject", "event_type", "payload")

#: ``%s::jsonb`` rather than a psycopg ``Jsonb`` adapter: the payload is already
#: the bytes :func:`coffee_contracts.to_json` produced, and handing the driver a
#: dict instead would put our own ``json.dumps`` between the contract and the
#: wire — a second serialiser nobody would think to keep in step.
OUTBOX_SQL = (
    f"INSERT INTO outbox ({', '.join(OUTBOX_COLUMNS)}) "  # noqa: S608  (a module constant)
    "VALUES (%s, %s, %s::jsonb)"
)

#: Every field of :class:`~coffee_contracts.CoffeeState`, in declaration order.
STATE_FIELDS: tuple[str, ...] = tuple(CoffeeState.__dataclass_fields__)

#: Where a field is read from when a :class:`CoffeeState` is rebuilt out of the
#: ``coffee`` table rather than out of a freshly parsed product. Everything not
#: named here is a column of the same name, which a test asserts.
_EXPRESSION_FOR: dict[str, str] = {
    # `scraped_at` is nullable — a row written before the column existed, or by
    # an adapter that never set it — while `last_seen_at` is NOT NULL. The event
    # has to say when the catalogue last saw the coffee, and "null" is not an
    # answer a consumer can order by.
    "observed_at": "coalesce(scraped_at, last_seen_at)",
}

#: The ``RETURNING``/``SELECT`` list that produces a row :func:`state_from_row`
#: can read, in the order it expects.
STATE_EXPRESSIONS: tuple[str, ...] = tuple(_EXPRESSION_FOR.get(name, name) for name in STATE_FIELDS)
STATE_SELECT: str = ", ".join(STATE_EXPRESSIONS)

#: ``numeric`` columns arrive as :class:`~decimal.Decimal`, which the contract's
#: encoder refuses outright rather than guess a representation for.
_FLOAT_FIELDS = frozenset({"price", "price_per_kg_eur", "sca_score"})
#: ``jsonb`` columns arrive as lists, or as None where the crawl stored nothing.
_LIST_FIELDS = frozenset({"variety", "flavor_notes"})

#: The three fields of an event that no parsed coffee carries: the INSERT stamps
#: ``first_seen_at`` and its conflict branch keeps it, and the kind columns are
#: written by the kind decider and the seed loader, never by the upsert.
STORED_FIELDS_SQL: str = (
    "SELECT c.site, c.external_id, c.first_seen_at, c.product_kind, c.product_kind_source "
    "FROM coffee c JOIN unnest(%s::text[], %s::text[]) AS k(site, external_id) "
    "USING (site, external_id)"
)


class StoredFields(NamedTuple):
    """The database-held values of the fields a crawl cannot supply, once its write is in.

    Attributes:
        first_seen_at: When the catalogue first stored the coffee.
        product_kind: The decided kind, or None while undecided.
        product_kind_source: How ``product_kind`` was decided, or None.
    """

    first_seen_at: datetime
    product_kind: str | None
    product_kind_source: str | None


def state_for(coffee: Coffee, stored: StoredFields) -> CoffeeState:
    """Build the event a freshly crawled coffee is published as.

    The event carries the subset of the row a consumer can act on — what the
    coffee is, where to buy it and what a kilogram of it costs — and not the
    provenance columns, the raw attributes or the per-shop prices, which are the
    catalogue's own bookkeeping.

    Every value comes from the parsed coffee, except ``first_seen_at``,
    ``product_kind`` and ``product_kind_source``, which come from ``stored``: only
    the database can give those. The rest is not read back, because a float written
    to a ``numeric`` column comes back with fifteen significant digits, and a read-back
    would move any field the parse left unrounded, where this change moves three.

    Args:
        coffee: The coffee the crawl just parsed.
        stored: What the database holds for it after the upsert and the kind
            decisions; see :func:`read_stored_fields`.

    Returns:
        Its current state, with ``delisted_at`` unset: a crawl only ever sees
        coffees that are still listed.
    """
    return CoffeeState(
        site=coffee.site,
        external_id=coffee.external_id,
        observed_at=coffee.scraped_at,
        name=coffee.name,
        url=coffee.url,
        roaster=coffee.roaster_name,
        origin_country=coffee.origin.country,
        origin_region=coffee.origin.region,
        process_method=str(coffee.processing.method),
        roast_level=str(coffee.roast.level),
        roast_profile=str(coffee.roast.profile),
        variety=list(coffee.origin.variety),
        altitude_min_m=coffee.origin.altitude_min_m,
        flavor_notes=list(coffee.taste.flavor_notes),
        tasting_text=coffee.taste.tasting_text,
        sca_score=coffee.taste.sca_score,
        weight_g=coffee.weight_g,
        price=coffee.price,
        currency=coffee.currency,
        price_per_kg_eur=coffee.price_per_kg_eur,
        available=coffee.available,
        decaf=coffee.decaf,
        arabica_pct=coffee.species.arabica_pct,
        robusta_pct=coffee.species.robusta_pct,
        first_seen_at=stored.first_seen_at,
        product_kind=stored.product_kind,
        product_kind_source=stored.product_kind_source,
    )


def state_from_row(row: Sequence[Any]) -> CoffeeState:
    """Rebuild an event from a row selected with :data:`STATE_SELECT`.

    This is the path a delisting and a ``republish`` take: the coffee is in the
    table and no longer in hand, so the event is read back out of the columns
    the crawl wrote.

    Args:
        row: The values of :data:`STATE_EXPRESSIONS`, in that order.

    Returns:
        The event.
    """
    values: dict[str, Any] = {}
    for name, value in zip(STATE_FIELDS, row, strict=True):
        if name in _LIST_FIELDS:
            values[name] = list(value or ())
        elif name in _FLOAT_FIELDS and value is not None:
            values[name] = float(value)
        else:
            values[name] = value
    return CoffeeState(**values)


def event_rows(states: Iterable[CoffeeState]) -> list[tuple[str, str, str]]:
    """Turn events into the parameters of :data:`OUTBOX_SQL`, skipping the unroutable.

    An event whose subject cannot be formed is dropped with a warning instead of
    raising. ``coffeein`` and ``nordbeans`` both fall back to ``""`` when the
    listing gave them no product id, and an empty token has no subject. Raising
    here would abort the enclosing batch, send it down
    :meth:`~coffee_aggregator.sinks.postgres.PostgresSink._retry_one_by_one` and
    lose the coffee from the catalogue as well — a data regression caused by a
    messaging concern, which is the wrong way round.

    Args:
        states: The events to store.

    Returns:
        One ``(subject, event_type, payload)`` tuple per publishable event.
    """
    rows: list[tuple[str, str, str]] = []
    for state in states:
        try:
            subject = catalogue(state.site, state.external_id)
        except SubjectError as exc:
            logger.warning(
                "not publishing %s: %s",
                state.url or f"{state.site}/{state.external_id}",
                exc,
            )
            continue
        rows.append((subject, COFFEE_STATE, to_json(state).decode()))
    return rows


def read_stored_fields(
    cursor: psycopg.Cursor[Any], chunk: Sequence[Coffee]
) -> dict[tuple[str, str], StoredFields]:
    """Read back the database-owned fields of a chunk, inside its transaction.

    Call it after the upsert and the kind decisions, so each value is the one the
    row holds once the write is in, and ``first_seen_at`` is the stamp the INSERT wrote.

    Args:
        cursor: The cursor of the open transaction.
        chunk: The coffees the chunk wrote.

    Returns:
        The stored fields of each coffee, keyed by ``(site, external_id)``.
    """
    keys = [(coffee.site, coffee.external_id) for coffee in chunk]
    cursor.execute(
        STORED_FIELDS_SQL, ([site for site, _ in keys], [external for _, external in keys])
    )
    return {
        (str(site), str(external)): StoredFields(first_seen_at, product_kind, source)
        for site, external, first_seen_at, product_kind, source in cursor.fetchall()
    }


def event_rows_for(
    coffees: Iterable[Coffee], stored: Mapping[tuple[str, str], StoredFields]
) -> list[tuple[str, str, str]]:
    """Turn crawled coffees into outbox rows.

    Args:
        coffees: The chunk being written.
        stored: What :func:`read_stored_fields` read back for the chunk.

    Returns:
        One row per coffee that has a subject; see :func:`event_rows`.

    Raises:
        KeyError: A coffee of the chunk was not read back. The read runs in the
            same transaction as the upsert, so this means the write did not land.
    """
    return event_rows(
        state_for(coffee, stored[(coffee.site, coffee.external_id)]) for coffee in coffees
    )


def event_rows_from_db(rows: Iterable[Sequence[Any]]) -> list[tuple[str, str, str]]:
    """Turn rows selected with :data:`STATE_SELECT` into outbox rows.

    Args:
        rows: What a ``RETURNING`` or a ``SELECT`` of :data:`STATE_EXPRESSIONS`
            handed back.

    Returns:
        One row per coffee that has a subject; see :func:`event_rows`.
    """
    return event_rows(state_from_row(row) for row in rows)
