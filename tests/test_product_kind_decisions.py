from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, cast

import pytest

from coffee_aggregator import normalize, product_kind, product_kind_rules
from coffee_aggregator.db import migrate
from coffee_aggregator.sinks import kind_decisions
from coffee_aggregator.sinks.postgres import PostgresSink
from conftest import make_coffee

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    import psycopg

    from coffee_aggregator.models import Coffee

DSN = os.environ.get("TEST_DATABASE_URL", "")
live = pytest.mark.skipif(not DSN, reason="set TEST_DATABASE_URL to run the PostgreSQL tests")
CAPSULE = "Kávové kapsle DEAD OR ALIVE 50ks - kompatibilní s Nespresso®"
PLAIN = "Ethiopia Yirgacheffe 1 kg"
_TABLES = (
    "crawl_finding",
    "outbox",
    "coffee_variant",
    "price_history",
    "crawl_run",
    "coffee",
    "fx_rates",
    migrate.VERSION_TABLE,
)


class _StoredCursor:
    """Answers the stored-state read from a fixed list and records what it was asked."""

    def __init__(self, stored: Sequence[tuple[str, str, str | None, str | None]]) -> None:
        self.stored = stored
        self.executed: list[tuple[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:  # noqa: ANN401  (psycopg's shape)
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[str, str, str | None, str | None]]:
        return list(self.stored)


@pytest.fixture
def decider_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    real = product_kind_rules.decide

    def spy(name: str, external_id: str) -> product_kind_rules.KindDecision | None:
        calls.append((name, external_id))
        return real(name, external_id)

    monkeypatch.setattr(product_kind_rules, "decide", spy)
    return calls


def _coffee(name: str, external_id: str = "1") -> Coffee:
    return make_coffee(external_id=external_id, name=name)


def _stored_hash(name: str) -> str:
    return normalize.product_name_hash(name)


def test_a_row_the_store_has_no_kind_for_is_decided_on_insert(
    decider_calls: list[tuple[str, str]],
) -> None:
    rows = kind_decisions.rows_for(
        cast("psycopg.Cursor[Any]", _StoredCursor([])), [_coffee(CAPSULE)]
    )
    assert rows == [
        ("capsules", "rule:capsule", _stored_hash(CAPSULE), "demo", "1", _stored_hash(CAPSULE))
    ]
    assert decider_calls == [(CAPSULE, "1")]


def test_a_decided_row_for_the_same_name_is_left_alone(
    decider_calls: list[tuple[str, str]],
) -> None:
    stored = [("demo", "1", "beans", _stored_hash(CAPSULE))]
    rows = kind_decisions.rows_for(
        cast("psycopg.Cursor[Any]", _StoredCursor(stored)), [_coffee(CAPSULE)]
    )
    assert rows == []
    assert decider_calls == []


def test_a_renamed_row_goes_back_to_the_decider(decider_calls: list[tuple[str, str]]) -> None:
    stored = [("demo", "1", "beans", _stored_hash(PLAIN))]
    rows = kind_decisions.rows_for(
        cast("psycopg.Cursor[Any]", _StoredCursor(stored)), [_coffee(CAPSULE)]
    )
    assert rows == [
        ("capsules", "rule:capsule", _stored_hash(CAPSULE), "demo", "1", _stored_hash(CAPSULE))
    ]
    assert decider_calls == [(CAPSULE, "1")]


def test_a_renamed_row_the_rules_cannot_place_keeps_its_old_kind(
    decider_calls: list[tuple[str, str]],
) -> None:
    stored = [("demo", "1", "capsules", _stored_hash(CAPSULE))]
    rows = kind_decisions.rows_for(
        cast("psycopg.Cursor[Any]", _StoredCursor(stored)), [_coffee(PLAIN)]
    )
    assert rows == []
    assert decider_calls == [(PLAIN, "1")]


def test_an_undecided_row_costs_no_write() -> None:
    rows = kind_decisions.rows_for(
        cast("psycopg.Cursor[Any]", _StoredCursor([("demo", "1", None, None)])),
        [_coffee(PLAIN)],
    )
    assert rows == []


@pytest.fixture
def store() -> Iterator[PostgresSink]:
    postgres = PostgresSink(DSN, chunk_size=1)
    _drop_everything(postgres)
    postgres.init_schema()
    yield postgres
    _drop_everything(postgres)
    postgres.close()


def _drop_everything(postgres: PostgresSink) -> None:
    with postgres.connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {', '.join(_TABLES)} CASCADE")
    postgres.connection.commit()


def _kind_of(postgres: PostgresSink, external_id: str = "1") -> tuple[Any, ...]:
    with postgres.connection.cursor() as cursor:
        cursor.execute(
            "SELECT product_kind, product_kind_source, product_kind_name_hash "
            "FROM coffee WHERE site = 'demo' AND external_id = %s",
            (external_id,),
        )
        row = cursor.fetchone()
    postgres.connection.commit()
    assert row is not None
    return tuple(row)


def _set_by_hand(postgres: PostgresSink, kind: str, source: str, name: str) -> None:
    """Stand in for the seed or a human review: a kind and the hash of the name it was given for."""
    with postgres.connection.cursor() as cursor:
        cursor.execute(
            "UPDATE coffee SET product_kind = %s, product_kind_source = %s, "
            "product_kind_name_hash = %s WHERE site = 'demo' AND external_id = '1'",
            (kind, source, _stored_hash(name)),
        )
    postgres.connection.commit()


@live
def test_a_crawl_decides_a_kind_for_a_new_row(store: PostgresSink) -> None:
    store.upsert([_coffee(CAPSULE)])
    assert _kind_of(store) == ("capsules", "rule:capsule", _stored_hash(CAPSULE))


@live
def test_a_stored_kind_survives_an_unchanged_crawl(
    store: PostgresSink, decider_calls: list[tuple[str, str]]
) -> None:
    store.upsert([_coffee(PLAIN)])
    _set_by_hand(store, "beans", product_kind.SEED_REVIEWED_SOURCE, PLAIN)
    decider_calls.clear()

    store.upsert([_coffee(PLAIN)])

    assert _kind_of(store) == ("beans", product_kind.SEED_REVIEWED_SOURCE, _stored_hash(PLAIN))
    assert decider_calls == []


@live
def test_a_human_kind_beats_a_rule_for_the_same_name(
    store: PostgresSink, decider_calls: list[tuple[str, str]]
) -> None:
    store.upsert([_coffee(CAPSULE)])
    _set_by_hand(store, "beans", product_kind.SEED_REVIEWED_SOURCE, CAPSULE)
    decider_calls.clear()

    store.upsert([_coffee(CAPSULE)])

    assert _kind_of(store)[0] == "beans"
    assert decider_calls == []


@live
def test_a_renamed_product_is_decided_again(
    store: PostgresSink, decider_calls: list[tuple[str, str]]
) -> None:
    store.upsert([_coffee(PLAIN)])
    _set_by_hand(store, "beans", product_kind.SEED_SOURCE, PLAIN)
    decider_calls.clear()

    store.upsert([_coffee(CAPSULE)])

    assert _kind_of(store) == ("capsules", "rule:capsule", _stored_hash(CAPSULE))
    assert decider_calls == [(CAPSULE, "1")]


@live
def test_a_crawl_never_clears_a_kind_the_rules_cannot_replace(store: PostgresSink) -> None:
    store.upsert([_coffee(CAPSULE)])
    store.upsert([_coffee(PLAIN)])
    assert _kind_of(store) == ("capsules", "rule:capsule", _stored_hash(CAPSULE))
