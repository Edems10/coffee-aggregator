from __future__ import annotations

import os
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from coffee_aggregator.db.coverage import (
    COVERAGE_DROP,
    MIN_COVERAGE_ROWS,
    TABLE,
    coverage_findings,
)
from coffee_aggregator.db.report import HIGH, findings

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    import psycopg

    from coffee_aggregator.db.report import Finding

DSN = os.environ.get("TEST_DATABASE_URL", "")
DAY = date(2026, 10, 17)
EARLIEST = DAY - timedelta(days=7)
VERSION = "0.6.0"

_INSERT_SQL = (
    f"INSERT INTO {TABLE} (day, site, field, rows, known, version) "  # noqa: S608  (a constant)
    "VALUES (%s, %s, %s, %s, %s, %s)"
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="set TEST_DATABASE_URL to run the PostgreSQL tests"),
]


@pytest.fixture
def connection() -> Iterator[psycopg.Connection[Any]]:
    """An empty ``crawl_coverage`` on a migrated database."""
    from coffee_aggregator.sinks.postgres import PostgresSink  # noqa: PLC0415  (optional path)

    sink = PostgresSink(DSN)
    sink.init_schema()
    _empty(sink.connection)
    yield sink.connection
    _empty(sink.connection)
    sink.close()


def _empty(live: psycopg.Connection[Any]) -> None:
    with live.cursor() as cursor:
        cursor.execute(f"TRUNCATE {TABLE}")
    live.commit()


def seed(  # noqa: PLR0913  (one argument per column)
    live: psycopg.Connection[Any],
    site: str,
    field: str,
    *,
    baseline: tuple[int, int],
    tonight: tuple[int, int] | None,
    days: int = 3,
    version: str = VERSION,
    baseline_version: str | None = None,
) -> None:
    """Write a shop-field's recent nights, then tonight's."""
    rows, known = baseline
    written = [
        (DAY - timedelta(days=offset), site, field, rows, known, baseline_version or version)
        for offset in range(1, days + 1)
    ]
    if tonight is not None:
        written.append((DAY, site, field, tonight[0], tonight[1], version))
    with live.cursor() as cursor:
        cursor.executemany(_INSERT_SQL, written)
    live.commit()


def found(live: psycopg.Connection[Any]) -> list[Finding]:
    return coverage_findings(live, day=DAY, earliest=EARLIEST)


def sites(result: Sequence[Finding]) -> list[str]:
    return [one.site for one in result]


def test_the_field_a_shop_stopped_publishing_is_one_finding(
    connection: psycopg.Connection[Any],
) -> None:
    seed(connection, "ajvencoffee", "origin_country", baseline=(10, 7), tonight=(11, 0))

    result = found(connection)

    assert sites(result) == ["ajvencoffee"]
    assert result[0].kind == COVERAGE_DROP
    assert result[0].severity == HIGH
    assert result[0].detail["field"] == "origin_country"
    assert result[0].detail["drop_points"] == 70.0


def test_a_twenty_eight_point_fall_is_why_the_threshold_is_not_thirty(
    connection: psycopg.Connection[Any],
) -> None:
    seed(connection, "ohmybean", "origin_country", baseline=(26, 17), tonight=(27, 10))

    result = found(connection)

    assert sites(result) == ["ohmybean"]
    assert result[0].detail["drop_points"] == 28.3


def test_a_field_the_shop_never_published_is_never_a_finding(
    connection: psycopg.Connection[Any],
) -> None:
    seed(connection, "kavaoliver", "sca_score", baseline=(20, 0), tonight=(20, 0))

    assert found(connection) == []


def test_a_field_the_shop_never_published_is_not_a_finding_on_any_night(
    connection: psycopg.Connection[Any],
) -> None:
    for day_rows in ((20, 0), (31, 0), (18, 0)):
        _empty(connection)
        seed(connection, "kavaoliver", "sca_score", baseline=(20, 0), tonight=day_rows)

        assert found(connection) == []


def test_a_shop_below_the_row_floor_is_noise_and_not_a_finding(
    connection: psycopg.Connection[Any],
) -> None:
    seed(connection, "tinyshop", "roast_level", baseline=(6, 4), tonight=(6, 1))

    assert found(connection) == []
    assert MIN_COVERAGE_ROWS == 8


def test_a_fall_of_exactly_twenty_points_is_reported(
    connection: psycopg.Connection[Any],
) -> None:
    seed(connection, "borderline", "process_method", baseline=(10, 10), tonight=(10, 8))

    result = found(connection)

    assert sites(result) == ["borderline"]
    assert result[0].detail["drop_points"] == 20.0


def test_a_fall_of_nineteen_points_is_not(connection: psycopg.Connection[Any]) -> None:
    seed(connection, "borderline", "process_method", baseline=(100, 100), tonight=(100, 81))

    assert found(connection) == []


def test_three_fallen_fields_at_one_shop_are_one_rolled_up_finding(
    connection: psycopg.Connection[Any],
) -> None:
    for field in ("flavor_notes", "origin_country", "roast_level"):
        seed(connection, "ajvencoffee", field, baseline=(11, 8), tonight=(11, 0))

    result = found(connection)

    assert len(result) == 1
    assert result[0].site == "ajvencoffee"
    assert [one["field"] for one in result[0].detail["fields"]] == [
        "flavor_notes",
        "origin_country",
        "roast_level",
    ]
    assert "flavor_notes, origin_country, roast_level" in result[0].summary


def test_every_finding_names_the_aggregator_version_that_measured_tonight(
    connection: psycopg.Connection[Any],
) -> None:
    seed(connection, "ajvencoffee", "origin_country", baseline=(10, 7), tonight=(11, 0))
    seed(
        connection,
        "grinders",
        "brewing_methods",
        baseline=(40, 40),
        tonight=(41, 0),
        baseline_version="0.5.0",
    )
    for field in ("flavor_notes", "origin_region", "roast_level"):
        seed(connection, "bartcoffee", field, baseline=(11, 8), tonight=(11, 0))

    result = found(connection)

    assert len(result) == 3
    for one in result:
        assert one.detail["version"] == VERSION
    deploy = next(one for one in result if one.site == "grinders")
    assert deploy.detail["baseline_versions"] == ["0.5.0"]
    assert "aggregator 0.5.0 -> 0.6.0 over the window" in deploy.summary


def test_the_report_asks_for_the_coverage_it_was_given(
    connection: psycopg.Connection[Any],
) -> None:
    seed(connection, "ajvencoffee", "origin_country", baseline=(10, 7), tonight=(11, 0))

    result = findings(connection, day=DAY, history_days=7)

    assert [one.site for one in result if one.kind == COVERAGE_DROP] == ["ajvencoffee"]
