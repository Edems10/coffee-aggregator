from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from coffee_aggregator import normalize, product_kind, product_kind_seed
from coffee_aggregator.db import migrate
from coffee_aggregator.sinks.postgres import PostgresSink
from conftest import make_coffee

if TYPE_CHECKING:
    from collections.abc import Iterator

FIXTURE = Path(__file__).parent / "fixtures" / "product_kinds" / "seed.csv"
DSN = os.environ.get("TEST_DATABASE_URL", "")
HEADER = "site,external_id,product_kind,confidence,why,reviewed,name,url\n"
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
live = pytest.mark.skipif(not DSN, reason="set TEST_DATABASE_URL to run the PostgreSQL tests")


def _seed_file(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "seed.csv"
    path.write_text(HEADER + "".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def test_the_fixture_reads_into_the_vocabulary() -> None:
    rows = product_kind_seed.read_seed(FIXTURE)

    assert len(rows) == 8
    assert {row.product_kind for row in rows} <= product_kind.PRODUCT_KINDS
    by_id = {row.external_id: row for row in rows}
    assert by_id["1"].product_kind == "beans"
    assert by_id["1"].product_kind_source == product_kind.SEED_SOURCE
    assert by_id["4"].product_kind_source == product_kind.SEED_REVIEWED_SOURCE
    assert by_id["1"].product_kind_name_hash == normalize.product_name_hash(
        "Ethiopia Yirgacheffe 1 kg"
    )


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (
            ("demo,1,tea,high,why,,Some Tea,https://demo.example/tea",),
            "unknown product_kind 'tea'",
        ),
        (
            ("demo,1,beans,high,why,,   ,https://demo.example/blank",),
            "has no name to hash",
        ),
        (
            ("demo,1,beans,high",),
            "does not have exactly 8 fields",
        ),
        (
            (
                "demo,1,beans,high,why,,Espresso,https://demo.example/a",
                "demo,1,beans,high,why,,Espresso,https://demo.example/b",
            ),
            "appears twice",
        ),
    ],
)
def test_a_bad_row_refuses_the_whole_seed(
    tmp_path: Path, lines: tuple[str, ...], message: str
) -> None:
    with pytest.raises(product_kind_seed.SeedError, match=message):
        product_kind_seed.read_seed(_seed_file(tmp_path, *lines))


def test_every_problem_is_named_in_one_refusal(tmp_path: Path) -> None:
    path = _seed_file(
        tmp_path,
        "demo,1,tea,high,why,,Some Tea,https://demo.example/tea",
        "demo,2,beans,high,why,,   ,https://demo.example/blank",
    )
    with pytest.raises(product_kind_seed.SeedError) as raised:
        product_kind_seed.read_seed(path)
    assert "line 2" in str(raised.value)
    assert "line 3" in str(raised.value)


def test_a_renamed_column_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "seed.csv"
    path.write_text("site,external_id,kind,name\ndemo,1,beans,Espresso\n", encoding="utf-8")
    with pytest.raises(product_kind_seed.SeedError, match="columns are"):
        product_kind_seed.read_seed(path)


def test_the_name_hash_ignores_typesetting() -> None:
    base = normalize.product_name_hash("Guaxupé Dulce 1 kg")
    assert normalize.product_name_hash("guaxupe dulce 1 kg") == base
    assert normalize.product_name_hash("GUAXUPE-DULCE  1 KG") == base


def test_the_name_hash_separates_different_names() -> None:
    assert normalize.product_name_hash("Espresso 1 kg") != normalize.product_name_hash(
        "Espresso 250 g"
    )


def test_the_name_hash_is_pinned_to_its_value() -> None:
    """A changed algorithm would send every settled product back to review at once."""
    expected = hashlib.sha256(b"espresso 1 kg").hexdigest()
    assert normalize.product_name_hash("Espresso 1 kg") == expected


def _drop_everything(postgres: PostgresSink) -> None:
    with postgres.connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {', '.join(_TABLES)} CASCADE")
    postgres.connection.commit()


@pytest.fixture
def store() -> Iterator[PostgresSink]:
    postgres = PostgresSink(DSN, chunk_size=1)
    _drop_everything(postgres)
    postgres.init_schema()
    yield postgres
    _drop_everything(postgres)
    postgres.close()


def _rows(postgres: PostgresSink) -> dict[str, tuple[str, str | None, str | None, str | None]]:
    """The demo shop's rows: name, kind, kind source and kind name hash, by external id."""
    with postgres.connection.cursor() as cursor:
        cursor.execute(
            "SELECT external_id, name, product_kind, product_kind_source, "
            "product_kind_name_hash FROM coffee WHERE site = 'demo'"
        )
        fetched = cursor.fetchall()
    postgres.connection.commit()
    return {
        str(external_id): (str(name), kind, source, name_hash)
        for external_id, name, kind, source, name_hash in fetched
    }


@live
def test_the_seed_writes_the_rows_it_matches_and_skips_the_rest(store: PostgresSink) -> None:
    store.upsert([make_coffee(external_id=str(number)) for number in range(1, 8)])
    assert all(kind is None for _, kind, _, _ in _rows(store).values())

    result = product_kind_seed.load_seed(DSN, FIXTURE)

    assert result == product_kind_seed.SeedResult(written=7, skipped=1)
    rows = _rows(store)
    assert "99" not in rows
    assert rows["1"][1:] == (
        "beans",
        product_kind.SEED_SOURCE,
        normalize.product_name_hash("Ethiopia Yirgacheffe 1 kg"),
    )
    assert rows["4"][2] == product_kind.SEED_REVIEWED_SOURCE


@live
def test_a_crawl_does_not_clear_a_stored_kind(store: PostgresSink) -> None:
    store.upsert([make_coffee(external_id="1")])
    product_kind_seed.load_seed(DSN, FIXTURE)
    assert _rows(store)["1"][1] == "beans"

    store.upsert([make_coffee(external_id="1", name="Renamed on the shop page")])

    name, kind, source, name_hash = _rows(store)["1"]
    assert name == "Renamed on the shop page"
    assert kind == "beans"
    assert source == product_kind.SEED_SOURCE
    assert name_hash == normalize.product_name_hash("Ethiopia Yirgacheffe 1 kg")
