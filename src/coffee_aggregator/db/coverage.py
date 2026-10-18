from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median
from typing import TYPE_CHECKING, Any, Final

from coffee_aggregator.db.report import HIGH, ROLLUP_PRODUCTS, Finding

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    import psycopg

    from coffee_aggregator.db.connect import Connection

logger = logging.getLogger(__name__)

#: Where a night's counts are kept. One row per shop per field per day.
TABLE = "crawl_coverage"

#: The slug the report emits, and the one ``reporting/finding.py`` annotates.
COVERAGE_DROP: Final = "coverage-drop"

#: Fields whose nothing-known value is NULL, so presence is the whole test.
_NOT_NULL: Final[tuple[str, ...]] = (
    "roaster",
    "origin_country",
    "origin_region",
    "origin_farm",
    "origin_producer",
    "altitude_min_m",
    "harvest",
    "process_raw",
    "roast_raw",
    "roast_date",
    "best_before",
    "sca_score",
    "description",
    "origin_text",
    "tasting_text",
)

#: Fields that can never be NULL, because ``sinks/records.py:107-112`` writes
#: ``str(...)`` of a :class:`~enum.StrEnum` whose nothing-known member is the
#: literal ``"unknown"`` (``models.py:62,73,82``). On the 2026-10-17 crawl
#: ``roast_level`` held that string on 1 988 rows, ``process_method`` on 1 802
#: and ``roast_profile`` on 1 397, so ``count(col)/count(*)`` reports 100% for
#: all three for ever. They are the three fields most likely to rot and the
#: three a naive coverage metric cannot see, which is why this table exists.
_NOT_UNKNOWN: Final[tuple[str, ...]] = ("process_method", "roast_level", "roast_profile")

#: Fields that land as jsonb ``'[]'`` and never as NULL (``sinks/postgres.py``
#: :data:`~coffee_aggregator.sinks.postgres.KIND_COLUMNS` aside, the path is
#: ``records.py:105,123,125``). ``variety`` was an empty array on 2 098 rows of
#: the same crawl while reporting as filled.
_NON_EMPTY_ARRAY: Final[tuple[str, ...]] = (
    "variety",
    "flavor_notes",
    "brewing_methods",
    "process_methods",
    "certifications",
    "awards",
)

#: Every field measured, in the order :func:`record` binds the counts.
#:
#: Excluded on purpose: ``raw_attributes``, a jsonb *object* that
#: ``jsonb_array_length`` raises on, inside a write whose failure is swallowed,
#: so one copied formula would lose the whole night's coverage silently;
#: ``product_kind``, which has two sentinels and is written by the seed loader
#: rather than the crawl, so its coverage measures us; the FX-derived price
#: columns and the managed timestamps, which the pipeline fills rather than the
#: shop; and the page furniture (``images``, ``variants``, ``reviews``,
#: ``tags``, ``categories``), which says how a shop builds a page and not what
#: it publishes about a coffee.
FIELDS: Final[tuple[str, ...]] = (*_NOT_NULL, *_NOT_UNKNOWN, *_NON_EMPTY_ARRAY)

_KNOWN: Final[dict[str, str]] = {
    **{name: f"{name} IS NOT NULL" for name in _NOT_NULL},
    **{name: f"{name} IS NOT NULL AND {name} <> 'unknown'" for name in _NOT_UNKNOWN},
    **{name: f"coalesce(jsonb_array_length({name}), 0) > 0" for name in _NON_EMPTY_ARRAY},
}

#: One aggregate per shop over the rows that shop's crawl re-read tonight.
#:
#: ``last_seen_at >= <the run's started_at>`` rather than
#: ``delisted_at IS NULL``: ``mark_delisted`` is skipped on a partial or
#: unhealthy run, so the second counts stale rows nobody re-read and invents a
#: drop caused by the delisting not running. ``product_kind = 'beans'`` keeps a
#: shop's capsule share from moving its fill rate with no selector having
#: rotted.
_MEASURE_SQL = (
    "SELECT count(*), "  # noqa: S608  (a module constant built from :data:`FIELDS`)
    + ", ".join(f"count(*) FILTER (WHERE {_KNOWN[name]})" for name in FIELDS)
    + " FROM coffee WHERE site = %s AND product_kind = 'beans' AND last_seen_at >= %s"
)

_UPSERT_SQL = (
    f"INSERT INTO {TABLE} (day, site, field, rows, known, version) "  # noqa: S608  (same)
    "VALUES (%s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (day, site, field) DO UPDATE SET "
    "rows = EXCLUDED.rows, known = EXCLUDED.known, version = EXCLUDED.version"
)

_HISTORY_SQL = f"""
SELECT day, site, field, rows, known, version
FROM {TABLE}
WHERE day >= %s AND day <= %s
ORDER BY site, field, day
"""  # noqa: S608  (same)

#: Absolute fall in fill rate, in percentage points, that makes a field news.
#: Measured over the 1 538 shop-field pairs present on both 2026-09-30 and
#: 2026-10-17 with at least eight rows: p50 0.0, p75 0.0, p90 3.7, p95 8.3,
#: p97.5 13.8, p99 22.2, p99.5 39.3. Twenty sits at p99 and finds 5 events over
#: those 17 days; ten finds 17, of which twelve are single-digit-row wobble at
#: small shops, and thirty finds 3 and misses ohmybean's 28-point collapse. The
#: test is inclusive.
COVERAGE_DROP_POINTS: Final = 20.0

#: Rows a shop needs before its fill rate means anything. Over eight rows one
#: product moves the figure 12.5 points, so below that the metric is noise.
#: The sibling of :data:`~coffee_aggregator.db.report.MIN_BASELINE_WRITTEN`,
#: for the same measured reason.
MIN_COVERAGE_ROWS: Final = 8

#: Percent, as the fill rates are expressed.
_FULL: Final = 100.0


@dataclass(frozen=True, slots=True)
class _Night:
    """One shop-field-day as the table stores it."""

    day: date
    rows: int
    known: int
    version: str | None

    @property
    def fill(self) -> float:
        """The share of the night's rows that carried the field, in percent.

        Returns:
            A percentage, or 0.0 for a night with no rows.
        """
        return _FULL * self.known / self.rows if self.rows else 0.0


@dataclass(frozen=True, slots=True)
class _Fall:
    """One field of one shop that fell far enough to report."""

    site: str
    field: str
    tonight: _Night
    median_fill: float
    median_known: float
    baseline_days: int
    baseline_versions: tuple[str, ...]

    @property
    def points(self) -> float:
        """How far the fill rate fell against the shop's own median.

        Returns:
            The fall in percentage points, always positive.
        """
        return self.median_fill - self.tonight.fill

    @property
    def figures(self) -> dict[str, Any]:
        """The numbers behind this one field, for a machine.

        Returns:
            A JSON-native mapping, including the aggregator version that
            measured tonight and the distinct versions over the baseline.
        """
        return {
            "field": self.field,
            "rows": self.tonight.rows,
            "known": self.tonight.known,
            "fill_pct": round(self.tonight.fill, 1),
            "median_fill_pct": round(self.median_fill, 1),
            "median_known": self.median_known,
            "drop_points": round(self.points, 1),
            "baseline_days": self.baseline_days,
            "version": self.tonight.version,
            "baseline_versions": list(self.baseline_versions),
        }


def record(
    connection: psycopg.Connection[Any],
    *,
    site: str,
    started_at: datetime,
    version: str | None,
) -> int:
    """Measure what one shop published tonight and store the counts.

    The shop is measured over the rows its crawl re-read, which is why the
    run's own ``started_at`` is the window and not midnight: a second crawl of
    the same shop on the same day replaces the day's rows through the primary
    key rather than adding to them.

    Nothing is written for a shop whose crawl re-read no beans at all. A row of
    zeroes is not a measurement of a shop, and it would become a baseline that
    every later night is compared against.

    Args:
        connection: An open connection; the caller owns the transaction.
        site: The shop just crawled.
        started_at: When its run began, which bounds the rows counted and
            names the UTC day the counts belong to.
        version: The aggregator that performed the crawl, or None when it is
            not known.

    Returns:
        How many rows were written, which is either zero or ``len(FIELDS)``.
    """
    day = _utc_date(started_at)
    with connection.cursor() as cursor:
        cursor.execute(_MEASURE_SQL, (site, started_at))
        measured = cursor.fetchall()
        if not measured:
            return 0
        counts = measured[0]
        rows = int(counts[0])
        if not rows:
            logger.debug("no beans re-read for %s on %s; no coverage recorded", site, day)
            return 0
        cursor.executemany(
            _UPSERT_SQL,
            [
                (day, site, name, rows, int(known), version)
                for name, known in zip(FIELDS, counts[1:], strict=True)
            ],
        )
    return len(FIELDS)


def coverage_findings(connection: Connection, *, day: date, earliest: date) -> list[Finding]:
    """Report every shop whose field stopped being published.

    A shop is judged against its own recent median and never against the
    catalogue: ajvencoffee losing ``origin_country`` on 10 rows moves a
    3 773-row catalogue by 0.19 points, so a catalogue-wide ratio cannot see
    the event this finding exists for.

    Three guards, all measured: the night needs
    :data:`MIN_COVERAGE_ROWS` rows and so does the baseline, the fall has to
    reach :data:`COVERAGE_DROP_POINTS`, and the baseline's median ``known`` has
    to be above zero -- a field a shop never published is a ceiling, not a
    drop.

    Args:
        connection: Something to read from; only ``SELECT`` is issued.
        day: The crawl day being reported on, as a UTC date.
        earliest: The first day of the baseline window.

    Returns:
        One high finding per fallen field, or one per shop where a shop has
        :data:`~coffee_aggregator.db.report.ROLLUP_PRODUCTS` or more of them.
        Every ``detail`` holds JSON-native values only.
    """
    history = _read_coverage(connection, earliest, day)
    falls = [
        fall
        for (site, field), nights in sorted(history.items())
        if (fall := _fall(site, field, nights, day)) is not None
    ]
    by_site: dict[str, list[_Fall]] = defaultdict(list)
    for fall in falls:
        by_site[fall.site].append(fall)
    found: list[Finding] = []
    for site in sorted(by_site):
        group = sorted(by_site[site], key=lambda fall: fall.field)
        if len(group) >= ROLLUP_PRODUCTS:
            found.append(_rollup(site, group))
        else:
            found.extend(_finding(fall) for fall in group)
    return found


def _read_coverage(
    connection: Connection,
    earliest: date,
    day: date,
) -> dict[tuple[str, str], list[_Night]]:
    """Read the window's counts, grouped by shop and field.

    Args:
        connection: Something to read from.
        earliest: The first day of the baseline window.
        day: The report's day, the last day read.

    Returns:
        Every night recorded for each ``(site, field)``, oldest first.
    """
    with connection.cursor() as cursor:
        cursor.execute(_HISTORY_SQL, (earliest, day))
        rows = cursor.fetchall()
    grouped: dict[tuple[str, str], list[_Night]] = defaultdict(list)
    for row in rows:
        grouped[(str(row[1]), str(row[2]))].append(
            _Night(
                day=_as_date(row[0]),
                rows=int(row[3]),
                known=int(row[4]),
                version=None if row[5] is None else str(row[5]),
            )
        )
    for nights in grouped.values():
        nights.sort(key=lambda night: night.day)
    return grouped


def _fall(site: str, field: str, nights: Sequence[_Night], day: date) -> _Fall | None:
    """Judge one shop's field against its own recent median.

    Args:
        site: The shop.
        field: The column being measured.
        nights: Every night recorded for the pair inside the window.
        day: The report's day.

    Returns:
        The fall, or None when there is no night, no baseline, too few rows,
        nothing the shop ever published, or no fall large enough.
    """
    tonight = next((night for night in nights if night.day == day), None)
    baseline = [night for night in nights if night.day < day and night.rows]
    if tonight is None or not baseline or tonight.rows < MIN_COVERAGE_ROWS:
        return None
    median_known = median(night.known for night in baseline)
    if median_known <= 0 or median(night.rows for night in baseline) < MIN_COVERAGE_ROWS:
        return None
    median_fill = median(night.fill for night in baseline)
    if median_fill - tonight.fill < COVERAGE_DROP_POINTS:
        return None
    return _Fall(
        site=site,
        field=field,
        tonight=tonight,
        median_fill=median_fill,
        median_known=median_known,
        baseline_days=len(baseline),
        baseline_versions=tuple(
            sorted({night.version for night in baseline if night.version is not None})
        ),
    )


def _finding(fall: _Fall) -> Finding:
    """Report one field one shop stopped publishing.

    Args:
        fall: The field and its two figures.

    Returns:
        A high finding naming the shop, the field and the fall.
    """
    return Finding(
        kind=COVERAGE_DROP,
        site=fall.site,
        summary=(
            f"{fall.site} / {fall.field}: stated on {fall.tonight.fill:.0f}% of "
            f"{fall.tonight.rows} rows, against a median of {fall.median_fill:.0f}% "
            f"over its last {fall.baseline_days} days{_versions(fall)}"
        ),
        detail=fall.figures,
        severity=HIGH,
    )


def _rollup(site: str, group: Sequence[_Fall]) -> Finding:
    """Report a shop that stopped publishing several fields at once.

    Args:
        site: The shop.
        group: Its fallen fields.

    Returns:
        One high finding naming them all: several fields going at once is one
        page template, not one problem per column.
    """
    first = group[0]
    return Finding(
        kind=COVERAGE_DROP,
        site=site,
        summary=(
            f"{site}: {len(group)} fields lost coverage over "
            f"{first.tonight.rows} rows ({', '.join(fall.field for fall in group)})"
            f"{_versions(first)}"
        ),
        detail={
            "fields": [fall.figures for fall in group],
            "rows": first.tonight.rows,
            "version": first.tonight.version,
            "baseline_versions": list(first.baseline_versions),
        },
        severity=HIGH,
    )


def _versions(fall: _Fall) -> str:
    """Name the aggregator versions when a deploy sits inside the window.

    Three of the five collapses measured over 2026-09-30 to 2026-10-17 were our
    own deploy rather than a shop: #97 moved grind words out of
    ``brewing_methods`` and three shops lost most of it on the next crawl. A
    step that reads the same at many shops on the night of a release and at one
    shop on an ordinary night is the distinction this clause carries.

    Args:
        fall: The field and the versions around it.

    Returns:
        A clause naming the versions, or ``""`` when the window ran on one
        build and the step is therefore the shop's.
    """
    tonight = fall.tonight.version
    before = [version for version in fall.baseline_versions if version != tonight]
    if tonight is None or not before:
        return ""
    return f"; aggregator {', '.join(before)} -> {tonight} over the window"


def _utc_date(value: datetime) -> date:
    """Return the UTC calendar day a timestamp falls on.

    Args:
        value: A timestamp, aware or naive; a naive one is already UTC.

    Returns:
        The date, on the same calendar ``price_history.seen_on`` uses.
    """
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(UTC).date()


def _as_date(value: date | datetime) -> date:
    """Return a plain date, whatever the driver handed back.

    Args:
        value: A date, or a timestamp standing in for one.

    Returns:
        The date itself.
    """
    return value.date() if isinstance(value, datetime) else value
