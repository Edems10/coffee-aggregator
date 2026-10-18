from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from coffee_aggregator import __version__
from coffee_aggregator.db import coverage, migrate, monitoring
from coffee_aggregator.db.monitoring import (
    COLUMNS,
    TABLE,
    NullMonitor,
    PostgresMonitor,
    build_monitor,
)
from coffee_aggregator.pipeline import RunReport

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    import psycopg

DSN = os.environ.get("TEST_DATABASE_URL", "")


def _report(site_id: str = "fake", **overrides: object) -> RunReport:
    started = datetime(2026, 9, 29, 2, 0, tzinfo=UTC)
    report = RunReport(
        site_id=site_id,
        discovered=12,
        fetched=11,
        parsed=10,
        skipped_non_coffee=1,
        failed=1,
        disallowed=0,
        written=10,
        delisted=2,
        duration_s=3.5,
        started_at=started,
        finished_at=datetime(2026, 9, 29, 2, 0, 3, tzinfo=UTC),
        errors=["fetch failed for https://x/1: HTTP 500"],
    )
    for key, value in overrides.items():
        setattr(report, key, value)
    return report


# --- offline -----------------------------------------------------------------


def test_the_columns_are_exactly_what_the_migration_creates() -> None:
    """The insert and the DDL are one contract; drift is a nightly crash."""
    declared = set(migrate.table_columns(TABLE))

    assert set(COLUMNS) <= declared
    # everything the pipeline does not fill has a default or is generated
    assert declared - set(COLUMNS) == {"id", "recorded_at"}


def test_every_column_maps_to_a_run_report_field() -> None:
    fields = set(RunReport.__dataclass_fields__) | {"site", "command", "version"}
    assert set(COLUMNS) <= fields | {"site_id"}


def test_the_null_monitor_records_nothing_and_answers_nothing() -> None:
    monitor = NullMonitor()
    monitor.record(_report())
    assert monitor.recent() == []
    assert monitor.recent(site="fake", limit=5) == []
    assert monitor.durations() == {}
    monitor.close()


def test_a_run_without_a_database_gets_the_null_monitor() -> None:
    assert isinstance(build_monitor(None), NullMonitor)
    assert isinstance(build_monitor(""), NullMonitor)


def test_a_run_with_a_database_gets_the_postgres_monitor() -> None:
    monitor = build_monitor("postgresql://fake/db", command="coffee-aggregator crawl --site all")
    assert isinstance(monitor, PostgresMonitor)
    assert monitor.command == "coffee-aggregator crawl --site all"


def test_a_monitor_never_takes_a_crawl_down_with_it(caplog: pytest.LogCaptureFixture) -> None:
    """A failed insert costs one row of history, never the night's data."""
    monitor = PostgresMonitor("postgresql://nobody@localhost:1/none", connect_timeout=1)
    with caplog.at_level("ERROR", logger="coffee_aggregator.db.monitoring"):
        monitor.record(_report())
    assert "could not record the run of fake" in caplog.text
    monitor.close()


def test_the_insert_binds_one_placeholder_per_column() -> None:
    assert monitoring._INSERT_SQL.count("%s") == len(COLUMNS)


def test_the_durations_query_matches_the_index_it_relies_on() -> None:
    """``DISTINCT ON`` is only one scan if it is ordered like the index."""
    assert "DISTINCT ON (site)" in monitoring._DURATIONS_SQL
    assert "ORDER BY site, started_at DESC" in monitoring._DURATIONS_SQL
    schema = (Path(monitoring.__file__).parent / "migrations" / "0001_initial.sql").read_text(
        "utf-8"
    )
    assert "crawl_run USING btree (site, started_at DESC)" in schema


def test_unreadable_history_never_takes_a_crawl_down_with_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Without history the crawl just runs in the order it was given."""
    monitor = PostgresMonitor("postgresql://nobody@localhost:1/none", connect_timeout=1)
    with caplog.at_level("ERROR", logger="coffee_aggregator.db.monitoring"):
        assert monitor.durations() == {}
    assert "could not read the run history" in caplog.text
    monitor.close()


# --- against a live PostgreSQL ------------------------------------------------

#: What an operator runs the morning after a crawl. It lives here so the
#: README's copy is checked against a real database rather than being prose.
EMPTY_TODAY_SQL = """
SELECT site,
       max(finished_at) AS last_finished,
       bool_and(discovery_ok) AS discovery_ok,
       sum(written) AS written
FROM crawl_run
WHERE started_at >= date_trunc('day', now())
GROUP BY site
HAVING sum(written) = 0
ORDER BY site
"""


def test_the_readme_documents_the_same_query() -> None:
    """A runbook query that drifts from the one that was tested is worse than none."""
    readme = Path(__file__).resolve().parent.parent / "README.md"
    folded = re.sub(r"\s+", " ", readme.read_text("utf-8"))

    assert re.sub(r"\s+", " ", EMPTY_TODAY_SQL).strip() in folded


live = pytest.mark.skipif(not DSN, reason="set TEST_DATABASE_URL to run the PostgreSQL tests")


@pytest.fixture
def monitor() -> Iterator[PostgresMonitor]:
    """A monitor on an empty ``crawl_run`` table.

    The table is emptied rather than dropped: re-applying ``0001_initial`` over
    a database that already has it is not what the runner is for — a migration
    is applied once and recorded — so the fixture leaves the schema alone and
    only owns the rows.
    """
    from coffee_aggregator.sinks.postgres import PostgresSink  # noqa: PLC0415  (optional path)

    sink = PostgresSink(DSN)
    sink.init_schema()
    sink.close()
    recorder = PostgresMonitor(DSN, command="coffee-aggregator crawl --site all")
    _empty(recorder.connection)
    yield recorder
    _empty(recorder.connection)
    recorder.close()


def _empty(connection: psycopg.Connection[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE {TABLE}")
        cursor.execute(f"TRUNCATE {coverage.TABLE}")
        cursor.execute("DELETE FROM coffee WHERE site = %s", (_SHOP,))
    connection.commit()


#: The shop the coverage tests own, kept out of every other test's rows.
_SHOP = "coverage-shop"

_COFFEE_SQL = (
    "INSERT INTO coffee (site, external_id, product_kind, last_seen_at, "
    "origin_country, roast_level, variety) VALUES (%s, %s, %s, %s, %s, %s, %s)"
)


def _beans(
    connection: psycopg.Connection[Any],
    rows: Sequence[tuple[str, str, str | None, str, str]],
    *,
    last_seen: datetime,
) -> None:
    """Write the shop's catalogue as the crawl would have left it."""
    with connection.cursor() as cursor:
        cursor.executemany(
            _COFFEE_SQL,
            [
                (_SHOP, external_id, kind, last_seen, origin, roast, variety)
                for external_id, kind, origin, roast, variety in rows
            ],
        )
    connection.commit()


def _coverage(connection: psycopg.Connection[Any]) -> dict[str, tuple[int, int, str | None]]:
    """Every coverage row written for the shop, keyed by field."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT field, rows, known, version FROM {coverage.TABLE} "  # noqa: S608  (a constant)
            "WHERE site = %s",
            (_SHOP,),
        )
        return {row[0]: (row[1], row[2], row[3]) for row in cursor.fetchall()}


@pytest.mark.integration
@live
def test_a_fresh_table_has_no_runs(monitor: PostgresMonitor) -> None:
    assert monitor.recent() == []


@pytest.mark.integration
@live
def test_a_recorded_run_reads_back_whole(monitor: PostgresMonitor) -> None:
    monitor.record(_report())

    rows = monitor.recent()

    assert len(rows) == 1
    row = rows[0]
    assert row["site"] == "fake"
    assert row["written"] == 10
    assert row["errors"] == ["fetch failed for https://x/1: HTTP 500"]
    assert row["command"] == "coffee-aggregator crawl --site all"
    assert row["complete"] is True
    assert row["deadline_reached"] is False
    assert float(row["duration_s"]) == 3.5


@pytest.mark.integration
@live
def test_recent_filters_by_site_and_honours_the_limit(monitor: PostgresMonitor) -> None:
    for index in range(3):
        monitor.record(_report(site_id=f"shop{index}"))
    monitor.record(_report(site_id="shop0", written=0))

    assert len(monitor.recent()) == 4
    assert len(monitor.recent(site="shop0")) == 2
    assert len(monitor.recent(limit=1)) == 1
    assert {row["site"] for row in monitor.recent(site="shop1")} == {"shop1"}


@pytest.mark.integration
@live
def test_durations_returns_the_newest_usable_row_per_shop(monitor: PostgresMonitor) -> None:
    """What the scheduler reads: last night per shop, crashes left out."""
    older = datetime(2026, 9, 28, 2, 0, tzinfo=UTC)
    newer = datetime(2026, 9, 29, 2, 0, tzinfo=UTC)
    monitor.record(_report(site_id="kava", started_at=older, duration_s=10.0))
    monitor.record(_report(site_id="kava", started_at=newer, duration_s=894.0))
    monitor.record(_report(site_id="tiny", started_at=newer, duration_s=3.0))
    monitor.record(_report(site_id="crashed", started_at=newer, discovery_ok=False))
    monitor.record(_report(site_id="never-ran", started_at=newer, duration_s=0.0))

    assert monitor.durations() == {"kava": 894.0, "tiny": 3.0}


@pytest.mark.integration
@live
def test_the_operators_query_finds_the_shops_that_wrote_nothing(monitor: PostgresMonitor) -> None:
    """The query the README documents, run against real rows."""
    now = datetime.now(UTC)
    monitor.record(_report(site_id="healthy", started_at=now, finished_at=now))
    monitor.record(_report(site_id="rotted", written=0, started_at=now, finished_at=now))
    monitor.record(_report(site_id="broken", written=0, discovery_ok=False, started_at=now))

    with monitor.connection.cursor() as cursor:
        cursor.execute(EMPTY_TODAY_SQL)
        rows = cursor.fetchall()

    assert [row[0] for row in rows] == ["broken", "rotted"]


@pytest.mark.integration
@live
def test_a_clean_run_records_what_the_shop_published(monitor: PostgresMonitor) -> None:
    """One row per measured field, counted by that field's own sentinel."""
    started = datetime.now(UTC)
    _beans(
        monitor.connection,
        [
            ("1", "beans", "Ethiopia", "light", '["Bourbon"]'),
            ("2", "beans", None, "unknown", "[]"),
            ("3", "beans", "Brazil", "unknown", "[]"),
            ("4", "capsules", "Kenya", "medium", '["SL28"]'),
        ],
        last_seen=started,
    )

    monitor.record(_report(site_id=_SHOP, started_at=started, finished_at=started))

    written = _coverage(monitor.connection)
    assert len(written) == len(coverage.FIELDS)
    assert written["origin_country"] == (3, 2, __version__)
    # the StrEnum sentinel is the string 'unknown', not NULL, and jsonb '[]'
    # is not NULL either; neither counts as something the shop published
    assert written["roast_level"] == (3, 1, __version__)
    assert written["variety"] == (3, 1, __version__)
    assert written["sca_score"] == (3, 0, __version__)


@pytest.mark.integration
@live
def test_a_row_the_crawl_did_not_re_read_is_not_counted(monitor: PostgresMonitor) -> None:
    started = datetime.now(UTC)
    _beans(
        monitor.connection,
        [("1", "beans", "Ethiopia", "light", '["Bourbon"]')],
        last_seen=started - timedelta(days=2),
    )
    _beans(monitor.connection, [("2", "beans", "Brazil", "light", "[]")], last_seen=started)

    monitor.record(_report(site_id=_SHOP, started_at=started, finished_at=started))

    assert _coverage(monitor.connection)["origin_country"] == (1, 1, __version__)


@pytest.mark.integration
@live
@pytest.mark.parametrize("flaw", [{"complete": False}, {"discovery_ok": False}])
def test_a_run_that_did_not_finish_cleanly_records_no_coverage(
    monitor: PostgresMonitor,
    flaw: dict[str, bool],
) -> None:
    """A truncated night would be a diluted baseline a real night is judged against."""
    started = datetime.now(UTC)
    _beans(monitor.connection, [("1", "beans", "Ethiopia", "light", "[]")], last_seen=started)

    monitor.record(_report(site_id=_SHOP, started_at=started, finished_at=started, **flaw))

    assert _coverage(monitor.connection) == {}
    assert len(monitor.recent(site=_SHOP)) == 1


@pytest.mark.integration
@live
def test_re_running_a_night_replaces_its_coverage_rather_than_doubling_it(
    monitor: PostgresMonitor,
) -> None:
    started = datetime.now(UTC)
    _beans(monitor.connection, [("1", "beans", "Ethiopia", "light", "[]")], last_seen=started)
    monitor.record(_report(site_id=_SHOP, started_at=started, finished_at=started))
    _beans(monitor.connection, [("2", "beans", None, "light", "[]")], last_seen=started)

    monitor.record(_report(site_id=_SHOP, started_at=started, finished_at=started))

    written = _coverage(monitor.connection)
    assert len(written) == len(coverage.FIELDS)
    assert written["origin_country"] == (2, 1, __version__)


@pytest.mark.integration
@live
def test_a_shop_that_re_read_nothing_records_no_coverage(monitor: PostgresMonitor) -> None:
    started = datetime.now(UTC)

    monitor.record(_report(site_id=_SHOP, started_at=started, finished_at=started))

    assert _coverage(monitor.connection) == {}
