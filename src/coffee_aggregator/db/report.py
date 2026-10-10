from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from statistics import median
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

from coffee_aggregator.labels import named_pack
from coffee_aggregator.normalize import parse_weights_grams

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date

    from coffee_aggregator.db.connect import Connection, Cursor

logger = logging.getLogger(__name__)

#: A shop is broken, dark or mis-parsed; somebody should look tonight.
HIGH: Final = "high"
#: Worth reading, nobody has to act: a price moved, a variant flipped.
LOW: Final = "low"

NO_PRODUCTS: Final = "no-products"
WRITE_DROP: Final = "write-drop"
PARSE_GAP: Final = "parse-gap"
WEIGHT_CHANGE: Final = "weight-change"
PRICE_JUMP: Final = "price-jump"
NEW_FAILURES: Final = "new-failures"
CONTRADICTORY_DUPLICATE: Final = "contradictory-duplicate"
NAME_WEIGHT_CONTRADICTION: Final = "name-weight-contradiction"
REFUSED_WEIGHT: Final = "refused-weight"

#: How much of its own recent median a shop may write before it is a drop.
#: Measured over 2026-10-01 and 2026-10-02, 230 shop-days with a baseline: the
#: lowest ratio reached by a shop that was not broken was 0.79 (kmen, 61 -> 48,
#: a fortnight's coffees sold out), then 0.86 and 0.91. Half is 1.6x below that
#: floor, and still catches the case this report exists for: 126 -> 4 is 0.03.
WRITE_DROP_RATIO: Final = 0.5
#: The median a ratio needs before it means anything. Ten of 157 shops carry a
#: median under five products, where one sold-out coffee is a 25% "drop"; a
#: four-product shop is not broken for being small, and when it really does go
#: dark ``no-products`` says so without needing a ratio.
MIN_BASELINE_WRITTEN: Final = 5

#: Share of the pages a shop fetched that may fail to become rows. Across all
#: 472 recorded runs of 2026-09-30, 10-01 and 10-02, ``fetched`` equalled
#: ``written`` exactly, every time: the measured floor is a clean 1.0, so any
#: loss at all is already an anomaly and the threshold only has to keep one
#: rotten product page on a 500-product shop out of the report.
PARSE_GAP_LOST_SHARE: Final = 0.10
#: ...and the same guard in absolute terms, for small shops.
MIN_PARSE_GAP_LOST: Final = 3

#: How far a price must move overnight to be news. Of the 3794 products priced
#: on both 2026-10-01 and 10-02, 54 moved at an unchanged weight: 43 by 10% or
#: more, 8 by 15% or more, 5 by 20%, none by 25%. Ten per cent is a flood, and
#: the mass between 10% and 15% is one event seen many times -- a 12.4% list
#: change across every coffee at coffeeport and lighthousecoffee, two shops
#: sharing a catalogue. Fifteen per cent leaves 8 products in 2 shops.
PRICE_JUMP_SHARE: Final = 0.15

#: Products of one shop that turn a pile of per-product findings into one
#: per-shop finding. Shop-wide repricings are the dominant pattern in the data
#: (the 12.4% change above touched 13 products in each of two shops), and they
#: are one decision, not thirteen.
ROLLUP_PRODUCTS: Final = 3

#: Share of a run's shops writing nothing that makes it one finding about the
#: run rather than one per shop. On 2026-09-30 the five-minute test run left 79
#: of 157 shops dark (50%); the two full runs left 2 (1.3%). Anywhere between
#: the two does as a boundary.
DARK_RUN_SHARE: Final = 0.10
#: ...with a floor, so ``crawl --site one-shop`` writing nothing is reported as
#: that one shop and not as "100% of the catalogue".
MIN_DARK_SHOPS: Final = 5

#: Failures that count as a sharp rise, both at once: this many, and this many
#: times the shop's own recent median. One closed category costs one
#: ``disallowed`` on a healthy shop and must not be news.
FAILURE_RISE_MIN: Final = 3
FAILURE_RISE_FACTOR: Final = 2.0
#: Share of discovery a failure count has to reach to be called high. Below it
#: the shop still delivered its catalogue and the failures are a nuisance.
FAILURE_HIGH_SHARE: Final = 0.10
#: The two figures a contradiction is read from, under the names its detail uses.
_PRICE_PER_KG: Final = "price_per_kg"
_WEIGHT_G: Final = "weight_g"
#: How far apart two live rows of one shop, under one name, must sit to
#: contradict each other. Ten is an order of magnitude, and the test is
#: inclusive: 121 and 1 210 CZK/kg are exactly ten apart, and so are the 100 g
#: and 1 000 g rows of vrescaffe's ``Terra 100g``, the one real hit on the
#: live export of 9 October 2026.
CONTRADICTION_FACTOR: Final = 10

#: Grams in a kilogram, for the only comparable price a shop publishes.
_GRAMS_PER_KG: Final = 1000

_SEVERITY_ORDER: Final[dict[str, int]] = {HIGH: 0, LOW: 1}

_RUNS_SQL = """
SELECT site, started_at, discovered, fetched, parsed, skipped_non_coffee,
       failed, disallowed, written, delisted, complete, discovery_ok,
       deadline_reached, errors
FROM crawl_run
WHERE started_at >= %s AND started_at < %s
ORDER BY site, started_at
"""

_PRICES_SQL = """
SELECT h.site, h.external_id, h.seen_on, h.price, h.currency, h.weight_g, c.name
FROM price_history h
LEFT JOIN coffee c ON c.site = h.site AND c.external_id = h.external_id
WHERE h.seen_on >= %s AND h.seen_on <= %s
ORDER BY h.site, h.external_id, h.seen_on
"""

#: The live catalogue as the night left it. A delisted row is a product the
#: shop no longer lists, and a row with no name cannot be matched to another.
_LIVE_SQL = """
SELECT site, external_id, name, weight_g, price_per_kg, currency
FROM coffee
WHERE delisted_at IS NULL AND name IS NOT NULL
ORDER BY site, name, external_id
"""

#: Where a night's findings are kept once they have been printed.
FINDING_TABLE = "crawl_finding"
#: Every column :func:`store` writes, in the order it binds them. ``id`` and
#: ``recorded_at`` are the table's own.
FINDING_COLUMNS: Final[tuple[str, ...]] = ("day", "kind", "site", "severity", "summary", "detail")

_DELETE_SQL = f"DELETE FROM {FINDING_TABLE} WHERE day = %s"  # noqa: S608  (a module constant)
_INSERT_SQL = (
    f"INSERT INTO {FINDING_TABLE} ({', '.join(FINDING_COLUMNS)}) "  # noqa: S608  (same)
    # The cast is explicit because the detail travels as a JSON string rather
    # than through the driver's Jsonb wrapper, and there is no implicit
    # text -> jsonb cast to lean on.
    "VALUES (%s, %s, %s, %s, %s, %s::jsonb)"
)


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing about a crawl that is worth a human's attention."""

    kind: str
    site: str
    summary: str
    detail: dict[str, Any]
    severity: str


def findings(connection: Connection, *, day: date, history_days: int = 7) -> list[Finding]:
    """Everything about ``day``'s crawl worth a human's attention.

    Every judgement here is a shop against its own recent history, never
    against an absolute figure: a shop that writes four coffees a day is not
    broken for being small, and one that wrote 126 yesterday and 4 today is
    broken however large 4 sounds. Two judgements need no history at all.
    :data:`PARSE_GAP` has an identity for its baseline rather than a history --
    every page a shop fetches becomes a row, in all 472 runs on record -- so it
    fires on the first day a parser rots. :data:`CONTRADICTORY_DUPLICATE`
    compares a shop's live rows with one another, and
    :data:`NAME_WEIGHT_CONTRADICTION` reads each live row against its own name,
    and :data:`REFUSED_WEIGHT` reads each row that stores no weight against the
    name it still states; none of them needs a past either.

    ``coverage-drop`` is deliberately absent. ``price_history`` carries price,
    currency, weight and availability and nothing else; ``origin_country``,
    ``process_method`` and ``flavor_notes`` live on ``coffee``, which is
    upserted in place, so by the time the report runs yesterday's values are
    gone. There is no history to compare a shop's coverage against, and a
    finding computed from today alone would be a finding about shop size.

    Args:
        connection: Something to read from; only ``SELECT`` is issued.
        day: The crawl day, as UTC dates -- the same calendar the generated
            ``price_history.seen_on`` column uses, so the two tables agree.
        history_days: How far back the baselines reach.

    Returns:
        The findings, most severe first and then by site; catalogue-wide ones
        carry an empty site and sort to the top of their severity. Every
        ``detail`` holds JSON-native values only.
    """
    earliest = day - timedelta(days=history_days)
    days = _read_days(connection, earliest, day)
    today = {one.site: one for one in days if one.day == day}
    history: dict[str, list[_SiteDay]] = defaultdict(list)
    for one in days:
        if one.day < day:
            history[one.site].append(one)

    found = _crawl_findings(today, history)
    pairs, listings = _read_prices(connection, earliest, day)
    found.extend(_price_findings(pairs))
    found.extend(_contradictions(listings))
    found.extend(_name_weight_contradictions(listings))
    found.extend(_refused_weight_findings(listings))
    return sorted(found, key=_order)


@runtime_checkable
class Writable(Protocol):
    """A database the day's findings can be written back into.

    Wider than :class:`~coffee_aggregator.db.connect.Connection` by exactly the
    two methods :func:`store` needs, and no wider: the delete and the inserts
    are one transaction, so the caller has to be something that can end one.
    """

    def cursor(self) -> Cursor:
        """Open a cursor on this connection.

        Returns:
            A cursor usable as a context manager.
        """
        ...

    def commit(self) -> None:
        """Make everything written since the last commit permanent."""
        ...

    def rollback(self) -> None:
        """Abandon everything written since the last commit."""
        ...


def store(connection: Writable, *, day: date, found: Sequence[Finding]) -> bool:
    """Replace ``day``'s stored findings with the ones just computed.

    The delete and the inserts are one transaction, which is what makes a
    second run of the same day replace its rows rather than double them. There
    is no unique constraint to upsert against on purpose: the only key the rows
    offer is ``(day, kind, site, summary)``, and ``summary`` is a sentence with
    the night's numbers in it, so a constraint over it would make the wording
    part of the schema.

    A failure is logged and swallowed, the same bargain
    :meth:`~coffee_aggregator.db.monitoring.PostgresMonitor.record` makes: the
    report is a read, and a history that can fail the nightly unit is worse
    than one with a night missing from it.

    Args:
        connection: Something to write to, with its own transaction.
        day: The crawl day the findings are about, as a UTC date.
        found: The findings, which may be empty -- an empty night still clears
            whatever an earlier run of the same day left behind.

    Returns:
        True when the day's rows are committed, False when nothing was stored.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(_DELETE_SQL, (day,))
            for finding in found:
                cursor.execute(
                    _INSERT_SQL,
                    (
                        day,
                        finding.kind,
                        finding.site,
                        finding.severity,
                        finding.summary,
                        json.dumps(finding.detail),
                    ),
                )
        connection.commit()
    except Exception:
        logger.exception("could not store the findings of %s", day)
        _abandon(connection)
        return False
    return True


def _abandon(connection: Writable) -> None:
    """Roll a failed write back, so the caller is not left holding it.

    Args:
        connection: The connection whose transaction failed.
    """
    try:
        connection.rollback()
    except Exception:  # noqa: BLE001  (the caller closes it either way)
        logger.warning("could not roll back after a failed finding write")


@dataclass(slots=True)
class _SiteDay:
    """One shop's whole day, with the day's runs folded into one row.

    A shop is normally crawled once a night, but a retry or a hand-run
    ``crawl --site x`` puts a second row in the table (2026-09-30 has one, for
    kafista). The counters are folded with ``max`` rather than summed: the two
    rows describe the same catalogue twice, so the better run is what the shop
    had, and summing would invent products.
    """

    site: str
    day: date
    discovered: int = 0
    fetched: int = 0
    parsed: int = 0
    skipped_non_coffee: int = 0
    failed: int = 0
    disallowed: int = 0
    written: int = 0
    delisted: int = 0
    complete: bool = False
    discovery_ok: bool = False
    deadline_reached: bool = False
    #: Whether any one run of the day saw the whole catalogue. A run cut off by
    #: its deadline is no baseline for the next day's comparison.
    usable: bool = False
    errors: list[str] = field(default_factory=list)

    def absorb(self, row: Sequence[Any]) -> None:
        """Fold one ``crawl_run`` row into this day.

        Args:
            row: One row in the order :data:`_RUNS_SQL` selects.
        """
        (
            _site,
            _started,
            discovered,
            fetched,
            parsed,
            skipped,
            failed,
            disallowed,
            written,
            delisted,
            complete,
            discovery_ok,
            deadline_reached,
            errors,
        ) = row
        self.discovered = max(self.discovered, int(discovered))
        self.fetched = max(self.fetched, int(fetched))
        self.parsed = max(self.parsed, int(parsed))
        self.skipped_non_coffee = max(self.skipped_non_coffee, int(skipped))
        self.failed = max(self.failed, int(failed))
        self.disallowed = max(self.disallowed, int(disallowed))
        self.written = max(self.written, int(written))
        self.delisted = max(self.delisted, int(delisted))
        self.complete = self.complete or bool(complete)
        self.discovery_ok = self.discovery_ok or bool(discovery_ok)
        self.deadline_reached = self.deadline_reached or bool(deadline_reached)
        self.usable = self.usable or (bool(discovery_ok) and not bool(deadline_reached))
        for message in errors or ():
            if message not in self.errors:
                self.errors.append(str(message))

    @property
    def counters(self) -> dict[str, Any]:
        """Return the day's figures, for a finding's ``detail``.

        Returns:
            A flat mapping of JSON-native values.
        """
        return {
            "discovered": self.discovered,
            "fetched": self.fetched,
            "parsed": self.parsed,
            "skipped_non_coffee": self.skipped_non_coffee,
            "failed": self.failed,
            "disallowed": self.disallowed,
            "written": self.written,
            "complete": self.complete,
            "discovery_ok": self.discovery_ok,
            "deadline_reached": self.deadline_reached,
        }


@dataclass(frozen=True, slots=True)
class _Pair:
    """One product as it was on the report's day and on the day before that."""

    site: str
    external_id: str
    name: str
    previous_day: date
    price_before: Decimal | None
    price_after: Decimal | None
    weight_before: int | None
    weight_after: int | None
    currency: str

    @property
    def weight_changed(self) -> bool:
        """Whether the headline variant is a different size than it was.

        Returns:
            True when the two weights differ, including when one is missing --
            a weight that stopped being parsed is the same kind of problem as a
            weight that changed.
        """
        return self.weight_before != self.weight_after

    @property
    def weight_lost(self) -> bool:
        """Whether one of the two days has no weight at all.

        Returns:
            True when either side is missing, which makes the per-kilogram
            price -- the only comparable one -- impossible to compute.
        """
        return self.weight_before is None or self.weight_after is None

    @property
    def price_move(self) -> float | None:
        """Return the overnight move of the shelf price.

        Returns:
            The proportional change, or None when either day has no price.
        """
        return _ratio(self.price_after, self.price_before)

    @property
    def per_kg_move(self) -> float | None:
        """Return the overnight move of the price per kilogram.

        Returns:
            The proportional change, or None when a weight is missing.
        """
        return _ratio(
            _per_kg(self.price_after, self.weight_after),
            _per_kg(self.price_before, self.weight_before),
        )

    @property
    def move(self) -> float | None:
        """Return the honest size of the move, per kilogram wherever possible.

        A variant flip from 250 g to 1000 g reads as +263% on the shelf price
        and is a 9% fall per kilogram. Weight changes are reported as their own
        kind and kept out of :data:`PRICE_JUMP`, so in practice the two figures
        agree here; preferring the per-kilogram one anyway means a weight
        change that slipped past that exclusion cannot be shouted about as a
        price rise it is not.

        Returns:
            The proportional change, or None when neither can be computed.
        """
        per_kg = self.per_kg_move
        return per_kg if per_kg is not None else self.price_move

    @property
    def figures(self) -> dict[str, Any]:
        """Return both days' prices and weights, for a finding's ``detail``.

        Returns:
            A flat mapping of JSON-native values.
        """
        return {
            "external_id": self.external_id,
            "name": self.name,
            "previous_day": self.previous_day.isoformat(),
            "currency": self.currency,
            "price_before": _number(self.price_before),
            "price_after": _number(self.price_after),
            "weight_before": self.weight_before,
            "weight_after": self.weight_after,
            "price_move": self.price_move,
            "per_kg_move": self.per_kg_move,
        }


@dataclass(frozen=True, slots=True)
class _Listing:
    """One live row of the catalogue, as the contradiction check reads it."""

    site: str
    external_id: str
    name: str
    weight_g: int | None
    price_per_kg: Decimal | None
    currency: str

    def figure(self, metric: str) -> Decimal | None:
        """Return one of the two figures a contradiction is read from.

        Args:
            metric: ``price_per_kg`` or ``weight_g``.

        Returns:
            The figure, or None when this row does not state it.
        """
        if metric == _PRICE_PER_KG:
            return self.price_per_kg
        return None if self.weight_g is None else Decimal(self.weight_g)


def _read_days(connection: Connection, earliest: date, day: date) -> list[_SiteDay]:
    """Read every run between two dates and fold it per shop per day.

    The window is bounded on ``started_at`` rather than on a cast of it so the
    index on that column is usable; the calendar day is worked out afterwards,
    in UTC, to match ``price_history.seen_on``.

    Args:
        connection: Something to read from.
        earliest: The first day of the baseline window.
        day: The report's day, the last day read.

    Returns:
        One entry per shop per day, in no particular order.
    """
    start = datetime.combine(earliest, time.min, UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, UTC)
    with connection.cursor() as cursor:
        cursor.execute(_RUNS_SQL, (start, end))
        rows = cursor.fetchall()

    folded: dict[tuple[str, date], _SiteDay] = {}
    for row in rows:
        site = str(row[0])
        when = _as_utc_date(row[1])
        key = (site, when)
        entry = folded.get(key)
        if entry is None:
            entry = _SiteDay(site=site, day=when)
            folded[key] = entry
        entry.absorb(row)
    return list(folded.values())


def _read_prices(
    connection: Connection,
    earliest: date,
    day: date,
) -> tuple[list[_Pair], list[_Listing]]:
    """Read the price history, pairing each product's day with its day before.

    The previous observation is the most recent one before ``day`` rather than
    yesterday's: a shop that failed yesterday would otherwise silently escape
    every comparison on the day it comes back. The live catalogue is read on
    the same cursor, straight after the prices.

    Args:
        connection: Something to read from.
        earliest: How far back to look for a previous observation.
        day: The report's day.

    Returns:
        One pair per product seen both on ``day`` and earlier in the window,
        and every live row of the catalogue.
    """
    with connection.cursor() as cursor:
        cursor.execute(_PRICES_SQL, (earliest, day))
        rows = cursor.fetchall()
        cursor.execute(_LIVE_SQL)
        live = cursor.fetchall()

    latest: dict[tuple[str, str], Sequence[Any]] = {}
    pairs: list[_Pair] = []
    for row in rows:
        key = (str(row[0]), str(row[1]))
        if _as_date(row[2]) != day:
            # The query is ordered by day, so this keeps the newest row before
            # the report's day and nothing else.
            latest[key] = row
            continue
        before = latest.get(key)
        if before is not None:
            pairs.append(_pair(before, row))
    listings = [
        _Listing(
            site=str(row[0]),
            external_id=str(row[1]),
            name=str(row[2]),
            weight_g=None if row[3] is None else int(row[3]),
            price_per_kg=row[4],
            currency=str(row[5] or ""),
        )
        for row in live
    ]
    return pairs, listings


def _pair(before: Sequence[Any], after: Sequence[Any]) -> _Pair:
    """Build one product's two-day comparison.

    Args:
        before: The earlier ``price_history`` row.
        after: The row of the report's day.

    Returns:
        The pair the price findings are read from.
    """
    return _Pair(
        site=str(after[0]),
        external_id=str(after[1]),
        name=str(after[6] or before[6] or ""),
        previous_day=_as_date(before[2]),
        price_before=before[3],
        price_after=after[3],
        weight_before=None if before[5] is None else int(before[5]),
        weight_after=None if after[5] is None else int(after[5]),
        currency=str(after[4] or before[4] or ""),
    )


def _crawl_findings(
    today: dict[str, _SiteDay],
    history: dict[str, list[_SiteDay]],
) -> list[Finding]:
    """Judge every shop's run against that shop's own recent runs.

    One shop gets at most one of :data:`NO_PRODUCTS`, :data:`PARSE_GAP` and
    :data:`WRITE_DROP`: they are the same symptom told at three depths, and a
    shop that wrote nothing is already the strongest thing that can be said
    about it. :data:`NEW_FAILURES` is allowed beside a write drop, because
    there it is the cause of one rather than a second report of it, but not
    beside :data:`NO_PRODUCTS`, which already carries the first error.

    Args:
        today: The report day's run of every shop that ran.
        history: Each shop's earlier days in the window.

    Returns:
        The findings about the runs, unsorted.
    """
    dark = sorted(site for site, one in today.items() if one.written == 0)
    found: list[Finding] = []
    if _is_dark_run(dark, today):
        found.append(_dark_run(dark, today))
    else:
        found.extend(_no_products(today[site], history.get(site, [])) for site in dark)

    silent = set(dark)
    for site in sorted(today):
        if site in silent:
            continue
        one = today[site]
        past = history.get(site, [])
        gap = _parse_gap(one)
        drop = None if gap is not None else _write_drop(one, past)
        found.extend(candidate for candidate in (gap, drop, _new_failures(one, past)) if candidate)
    return found


def _is_dark_run(dark: Sequence[str], today: dict[str, _SiteDay]) -> bool:
    """Whether so many shops wrote nothing that the run itself is the news.

    Args:
        dark: The shops that wrote nothing.
        today: Every shop that ran.

    Returns:
        True when the empty shops should be one finding instead of many.
    """
    return len(dark) >= MIN_DARK_SHOPS and len(dark) >= DARK_RUN_SHARE * len(today)


def _dark_run(dark: Sequence[str], today: dict[str, _SiteDay]) -> Finding:
    """Report a run where a large part of the catalogue came back empty.

    Half a catalogue writing nothing has one cause, not seventy-nine of them,
    and seventy-nine findings are seventy-nine nobody reads. The count of runs
    cut off by their deadline is in the line because on the one such night on
    record -- a five-minute test crawl -- it was the whole explanation.

    Args:
        dark: The shops that wrote nothing.
        today: Every shop that ran.

    Returns:
        One catalogue-wide finding carrying the list in its detail.
    """
    cut_off = sorted(site for site in dark if today[site].deadline_reached)
    how_many = "all" if len(cut_off) == len(dark) else str(len(cut_off))
    tail = f", {how_many} of them cut off by the deadline" if cut_off else ""
    return Finding(
        kind=NO_PRODUCTS,
        site="",
        summary=f"{len(dark)} of {len(today)} shops wrote nothing{tail}",
        detail={
            "shops": len(today),
            "dark": len(dark),
            "deadline_reached": len(cut_off),
            "sites": list(dark),
        },
        severity=HIGH,
    )


def _no_products(one: _SiteDay, past: Sequence[_SiteDay]) -> Finding:
    """Report a shop that stored not one product.

    Args:
        one: The shop's day.
        past: Its earlier days in the window.

    Returns:
        A high finding naming the first error and what the shop last wrote.
    """
    error = one.errors[0] if one.errors else ""
    last = next((other for other in sorted(past, key=_by_day, reverse=True) if other.written), None)
    reason = _dark_reason(one, error)
    was = f"; last wrote {last.written} on {last.day.isoformat()}" if last else ""
    return Finding(
        kind=NO_PRODUCTS,
        site=one.site,
        summary=f"{one.site} wrote nothing: {reason}{was}",
        detail={
            **one.counters,
            "error": error,
            "last_written": last.written if last else None,
            "last_written_on": last.day.isoformat() if last else None,
        },
        severity=HIGH,
    )


def _dark_reason(one: _SiteDay, error: str) -> str:
    """Say, in one clause, as much as the counters know about why.

    Args:
        one: The shop's day.
        error: Its first error, or an empty string.

    Returns:
        A fragment for the summary line.
    """
    disallowed = one.disallowed
    reasons = (
        (bool(error), error),
        (
            bool(disallowed and not one.discovered),
            f"robots.txt disallowed it before anything was discovered ({disallowed} page)",
        ),
        (
            bool(disallowed),
            f"robots.txt disallowed {disallowed} of {one.discovered} discovered",
        ),
        (
            bool(one.discovered and not one.fetched),
            f"all {one.discovered} discovered products were skipped as non-coffee",
        ),
        (
            bool(one.discovered),
            f"discovered {one.discovered}, fetched {one.fetched}, kept none",
        ),
        (one.deadline_reached, "the run stopped on its deadline before discovery"),
    )
    fallback = "discovery returned no products and reported no error"
    return next((text for matches, text in reasons if matches), fallback)


def _write_drop(one: _SiteDay, past: Sequence[_SiteDay]) -> Finding | None:
    """Report a shop that wrote far less than it usually does.

    A run cut off by its own deadline is skipped: the shortfall is then the
    deadline's, not the shop's, and on a truncated night that exemption is the
    difference between one finding and eighty-three.

    Args:
        one: The shop's day.
        past: Its earlier days in the window.

    Returns:
        A high finding, or None when the shop wrote what it normally does.
    """
    baseline = [other.written for other in past if other.usable]
    if one.deadline_reached or not baseline:
        return None
    usual = median(baseline)
    if usual < MIN_BASELINE_WRITTEN or one.written > WRITE_DROP_RATIO * usual:
        return None
    return Finding(
        kind=WRITE_DROP,
        site=one.site,
        summary=(
            f"{one.site} wrote {one.written}, against a median of {usual:g} "
            f"over its last {len(baseline)} full runs"
        ),
        detail={
            **one.counters,
            "median_written": usual,
            "baseline_days": len(baseline),
            "ratio": round(one.written / usual, 3),
        },
        severity=HIGH,
    )


def _parse_gap(one: _SiteDay) -> Finding | None:
    """Report pages that came back from a shop and did not become rows.

    This one needs no history. In all 472 runs on record ``written`` equals
    ``fetched`` exactly: the shop answering and the row appearing are the same
    event, so a gap between them is the parser, the non-coffee filter or the
    sink, and never the shop being quiet.

    Args:
        one: The shop's day.

    Returns:
        A high finding, or None when every fetched page became a row.
    """
    lost = one.fetched - one.written
    if lost < MIN_PARSE_GAP_LOST or lost < PARSE_GAP_LOST_SHARE * one.fetched:
        return None
    return Finding(
        kind=PARSE_GAP,
        site=one.site,
        summary=(
            f"{one.site} fetched {one.fetched} pages and wrote {one.written}: "
            f"{lost} were parsed or stored into nothing"
        ),
        detail={**one.counters, "lost": lost, "kept": round(one.written / one.fetched, 3)},
        severity=HIGH,
    )


def _new_failures(one: _SiteDay, past: Sequence[_SiteDay]) -> Finding | None:
    """Report failures a shop was not having before.

    Error strings are compared verbatim, which is what the data supports: the
    one error that survived a night on record -- kavypitel's 404 on a category
    it has removed -- repeated character for character, so a fresh string is a
    fresh problem rather than a different product id.

    Args:
        one: The shop's day.
        past: Its earlier days in the window.

    Returns:
        A finding, high when the failures took a real share of discovery with
        them, or None when nothing is new.
    """
    count = one.failed + one.disallowed
    if not count:
        return None
    before = {message for other in past for message in other.errors}
    fresh = [message for message in one.errors if message not in before]
    prior = [other.failed + other.disallowed for other in past]
    rose = (
        bool(prior)
        and count >= FAILURE_RISE_MIN
        and count >= FAILURE_RISE_FACTOR * max(median(prior), 1)
    )
    if not fresh and not rose:
        return None
    severe = not one.discovery_ok or count >= FAILURE_HIGH_SHARE * max(one.discovered, 1)
    headline = fresh[0] if fresh else f"{count} failures, against {median(prior):g} before"
    return Finding(
        kind=NEW_FAILURES,
        site=one.site,
        summary=f"{one.site}: {count} failed or disallowed pages -- {headline}",
        detail={
            **one.counters,
            "failures": count,
            "median_failures_before": median(prior) if prior else None,
            "new_errors": fresh,
        },
        severity=HIGH if severe else LOW,
    )


def _price_findings(pairs: Sequence[_Pair]) -> list[Finding]:
    """Judge what happened to every product that was priced on both days.

    Args:
        pairs: Each product's two days.

    Returns:
        The weight changes and the price jumps, unsorted.
    """
    weight = [pair for pair in pairs if pair.weight_changed]
    flipped = {(pair.site, pair.external_id) for pair in weight}
    jumps = [
        pair
        for pair in pairs
        if (pair.site, pair.external_id) not in flipped and _is_jump(pair.move)
    ]
    return [
        *_rolled(weight, _weight_finding, _weight_rollup),
        *_rolled(jumps, _jump_finding, _jump_rollup),
    ]


def _is_jump(move: float | None) -> bool:
    """Whether a move is large enough to report.

    Args:
        move: The proportional change, or None.

    Returns:
        True when it reaches :data:`PRICE_JUMP_SHARE` in either direction.
    """
    return move is not None and abs(move) >= PRICE_JUMP_SHARE


def _rolled(
    pairs: Sequence[_Pair],
    single: Callable[[_Pair], Finding],
    many: Callable[[str, Sequence[_Pair]], Finding],
) -> list[Finding]:
    """Report a shop's products one by one, or as one shop-wide finding.

    Args:
        pairs: The products that tripped one kind.
        single: Builds the finding for one product.
        many: Builds the one finding for a shop's whole group.

    Returns:
        One finding per product, or one per shop where a shop has enough of
        them that they are plainly one event.
    """
    by_site: dict[str, list[_Pair]] = defaultdict(list)
    for pair in pairs:
        by_site[pair.site].append(pair)
    found: list[Finding] = []
    for site in sorted(by_site):
        group = sorted(by_site[site], key=lambda pair: pair.external_id)
        if len(group) >= ROLLUP_PRODUCTS:
            found.append(many(site, group))
        else:
            found.extend(single(pair) for pair in group)
    return found


def _weight_finding(pair: _Pair) -> Finding:
    """Report one product whose headline variant is a different size.

    Args:
        pair: The product's two days.

    Returns:
        A finding; high when a weight went missing, because then no comparable
        price can be computed for the product at all.
    """
    return Finding(
        kind=WEIGHT_CHANGE,
        site=pair.site,
        summary=(
            f"{pair.site} / {pair.name}: {_amount(pair.price_before, pair.currency)}"
            f"/{_grams(pair.weight_before)} -> {_amount(pair.price_after, pair.currency)}"
            f"/{_grams(pair.weight_after)}{_both_moves(pair)}"
        ),
        detail=pair.figures,
        severity=HIGH if pair.weight_lost else LOW,
    )


def _weight_rollup(site: str, group: Sequence[_Pair]) -> Finding:
    """Report a shop whose weights changed across several products at once.

    Args:
        site: The shop.
        group: Its products that changed weight.

    Returns:
        One high finding: several weights moving on one night is the shop's
        variant list or our parsing of it, and either way it is one problem.
    """
    lost = sum(1 for pair in group if pair.weight_lost)
    return Finding(
        kind=WEIGHT_CHANGE,
        site=site,
        summary=(
            f"{site}: {len(group)} products changed weight overnight"
            f"{f', {lost} of them lost it entirely' if lost else ''}"
        ),
        detail={"products": [pair.figures for pair in group], "weight_lost": lost},
        severity=HIGH,
    )


def _jump_finding(pair: _Pair) -> Finding:
    """Report one product whose price moved overnight.

    Args:
        pair: The product's two days.

    Returns:
        A low finding: a price move is news about the shop, not a fault.
    """
    move = pair.move
    return Finding(
        kind=PRICE_JUMP,
        site=pair.site,
        summary=(
            f"{pair.site} / {pair.name}: {_amount(pair.price_before, pair.currency)} -> "
            f"{_amount(pair.price_after, pair.currency)} per {_grams(pair.weight_after)} "
            f"({_percent(move)})"
        ),
        detail={**pair.figures, "move": move},
        severity=LOW,
    )


def _jump_rollup(site: str, group: Sequence[_Pair]) -> Finding:
    """Report a shop that repriced several coffees on the same night.

    Args:
        site: The shop.
        group: Its products that moved.

    Returns:
        One low finding naming the spread and the direction split.
    """
    moves = [pair.move or 0.0 for pair in group]
    down = sum(1 for move in moves if move < 0)
    return Finding(
        kind=PRICE_JUMP,
        site=site,
        summary=(
            f"{site}: {len(group)} products moved {_percent(min(moves, key=abs))} to "
            f"{_percent(max(moves, key=abs))} overnight ({down} down, {len(group) - down} up)"
        ),
        detail={
            "products": [{**pair.figures, "move": pair.move} for pair in group],
            "down": down,
            "up": len(group) - down,
        },
        severity=LOW,
    )


def _both_moves(pair: _Pair) -> str:
    """Say what the shelf price did and what the comparable price did.

    The whole point of the kind: 375 CZK per 250 g becoming 1363 CZK per
    1000 g reads as a 263% rise and is a 9% fall per kilogram.

    Args:
        pair: The product's two days.

    Returns:
        A parenthesised fragment, or an empty string when neither is known.
    """
    if pair.price_move == 0.0 and pair.per_kg_move is None:
        return " (at an unchanged price)"
    parts = [
        f"{label} {_percent(move)}"
        for label, move in (("price", pair.price_move), ("per kg", pair.per_kg_move))
        if move is not None
    ]
    return f" ({', '.join(parts)})" if parts else ""


def _contradictions(listings: Sequence[_Listing]) -> list[Finding]:
    """Flag a shop's live rows that share a name and are an order of magnitude apart.

    Args:
        listings: Every live row of the catalogue.

    Returns:
        One finding per shop, name and figure that contradict each other, in
        no particular order.
    """
    # BANUA Café 5 kg (20x250g) went out at 17 160 CZK/kg against a true 858.
    # Its weight was read as one 250 g pack rather than 5 kg, so every kilogram
    # price was twenty times too high, and it sat at the top of the dearest-
    # per-kilogram panel until somebody noticed by eye. Its name is unique in
    # its shop, so this comparison cannot see that shape. Catching it means
    # setting a row against the shop's other products, which is a different
    # finding and not a lower factor here.
    by_name: dict[tuple[str, str], list[_Listing]] = defaultdict(list)
    for listing in listings:
        by_name[listing.site, listing.name].append(listing)
    found: list[Finding] = []
    for (site, name), group in sorted(by_name.items()):
        if len(group) <= 1:
            continue
        for metric in (_PRICE_PER_KG, _WEIGHT_G):
            contradiction = _contradiction(site, name, group, metric)
            if contradiction is not None:
                found.append(contradiction)
    return found


def _contradiction(
    site: str,
    name: str,
    group: Sequence[_Listing],
    metric: str,
) -> Finding | None:
    """Compare one figure across the live rows that share a name in one shop.

    Args:
        site: The shop.
        name: The name its rows share.
        group: Those rows, at least two of them.
        metric: ``price_per_kg`` or ``weight_g``.

    Returns:
        A high finding when the largest figure is at least
        :data:`CONTRADICTION_FACTOR` times the smallest, or None. Rows that do
        not state the figure, or state zero, are left out of the comparison.
    """
    known = [
        (one, figure) for one in group if (figure := one.figure(metric)) is not None and figure > 0
    ]
    if len(known) <= 1:
        return None
    low_row, low = min(known, key=lambda pair: pair[1])
    high_row, high = max(known, key=lambda pair: pair[1])
    if high < CONTRADICTION_FACTOR * low:
        return None
    ratio = float(high / low)
    currency = low_row.currency
    return Finding(
        kind=CONTRADICTORY_DUPLICATE,
        site=site,
        summary=(
            f"{site} / {name}: {_show(low, metric, currency)} and "
            f"{_show(high, metric, currency)}, {ratio:g}x apart"
        ),
        detail={
            "name": name,
            "metric": metric,
            "currency": currency,
            "external_ids": [one.external_id for one, _ in known],
            "low": _number(low),
            "low_external_id": low_row.external_id,
            "high": _number(high),
            "high_external_id": high_row.external_id,
            "ratio": round(ratio, 2),
        },
        severity=HIGH,
    )


def _refused_weight_findings(listings: Sequence[_Listing]) -> list[Finding]:
    """Flag a live row that stores no weight although its name states one pack.

    :func:`coffee_aggregator.labels.headline_weight` leaves the weight empty
    only when a weight label contradicts a one-pack name and no option settles
    which bag is priced. Such a refusal is otherwise invisible: the name-weight
    rule compares a row with its stored weight, and there is none to compare.

    Args:
        listings: Every live row of the catalogue.

    Returns:
        One low finding per row that stores no weight and whose name states
        exactly one pack, counts excluded.
    """
    found: list[Finding] = []
    for listing in listings:
        if listing.weight_g is not None:
            continue
        stated = named_pack(listing.name)
        if stated is None:
            continue
        found.append(
            Finding(
                kind=REFUSED_WEIGHT,
                site=listing.site,
                summary=(
                    f"{listing.site} / {listing.name}: name states {_grams(stated)}, "
                    "row stores no weight: the page's weight label contradicts it"
                ),
                detail={
                    "name": listing.name,
                    "external_id": listing.external_id,
                    "stated_g": stated,
                    "rule": "refused-label",
                },
                severity=LOW,
            )
        )
    return found


def _name_weight_contradictions(listings: Sequence[_Listing]) -> list[Finding]:
    """Flag a live row whose name states a weight ten times the one it stores.

    Args:
        listings: Every live row of the catalogue.

    Returns:
        One high finding per row whose name's largest stated weight is at least
        :data:`CONTRADICTION_FACTOR` times its ``weight_g``. A row that stores no
        weight, or whose name states none, cannot contradict it and is skipped.
    """
    # BANUA Café 5 kg (20x250g) was stored as one 250 g pack rather than 5 kg, so
    # its 17 160 CZK/kg was 858 in truth. Its name is unique at kava, so no
    # comparison between rows could reach it. The row disagrees with its own
    # name, which needs no neighbours, so a shop with one product is checked the
    # same way as one with four hundred.
    # Only the largest weight a name states is read. The 250g inside that name is
    # the bag inside the pack and agrees with the row, so requiring every stated
    # weight to disagree would clear the very row this rule exists to catch.
    # The reverse direction is deliberately not read: on the live export it fired
    # on ten correct multipacks ("Illy ... 250g 12ks" stored at 3000 g) for two
    # real suspects.
    found: list[Finding] = []
    for listing in listings:
        if listing.weight_g is None or listing.weight_g <= 0:
            continue
        stated = parse_weights_grams(listing.name)
        if not stated:
            continue
        largest = max(stated)
        if largest < CONTRADICTION_FACTOR * listing.weight_g:
            continue
        ratio = largest / listing.weight_g
        found.append(
            Finding(
                kind=NAME_WEIGHT_CONTRADICTION,
                site=listing.site,
                summary=(
                    f"{listing.site} / {listing.name}: name states {_grams(largest)}, "
                    f"row stores {_grams(listing.weight_g)}, {round(ratio, 1):g}x apart"
                ),
                detail={
                    "name": listing.name,
                    "external_id": listing.external_id,
                    "weight_g": listing.weight_g,
                    "stated_g": largest,
                    "stated_weights_g": stated,
                    "ratio": round(ratio, 2),
                    "rule": "name-weight-token",
                },
                severity=HIGH,
            )
        )
    return found


def _show(figure: Decimal, metric: str, currency: str) -> str:
    """Format one of a contradiction's figures for its summary line.

    Args:
        figure: The figure, as :meth:`_Listing.figure` returned it.
        metric: ``price_per_kg`` or ``weight_g``.
        currency: The shop's currency, which a price is written in.

    Returns:
        ``"121 CZK/kg"`` for a price, ``"100 g"`` for a weight.
    """
    if metric == _PRICE_PER_KG:
        return f"{_amount(figure, currency)}/kg"
    return _grams(int(figure))


def _ratio(after: float | Decimal | None, before: float | Decimal | None) -> float | None:
    """Return the proportional change between two figures.

    Args:
        after: The later figure.
        before: The earlier one.

    Returns:
        ``after / before - 1``, or None when either is missing or the earlier
        one is zero.
    """
    if after is None or before is None or not float(before):
        return None
    return float(after) / float(before) - 1.0


def _per_kg(price: Decimal | None, weight_g: int | None) -> float | None:
    """Return the price of a kilogram of a product.

    Args:
        price: What the shop charges for the pack.
        weight_g: What the pack holds.

    Returns:
        The price per kilogram, or None when either is missing.
    """
    if price is None or not weight_g:
        return None
    return float(price) * _GRAMS_PER_KG / weight_g


def _amount(price: Decimal | None, currency: str) -> str:
    """Format a price for a summary line.

    Args:
        price: The figure, if there is one.
        currency: Its currency code.

    Returns:
        ``"375 CZK"``, or ``"no price"``.
    """
    if price is None:
        return "no price"
    return f"{float(price):g} {currency}".strip()


def _grams(weight_g: int | None) -> str:
    """Format a pack size for a summary line.

    Args:
        weight_g: The size, if it was parsed.

    Returns:
        ``"250 g"``, or ``"unknown weight"``.
    """
    return f"{weight_g} g" if weight_g else "unknown weight"


def _percent(move: float | None) -> str:
    """Format a proportional change for a summary line.

    Args:
        move: The change, if it could be computed.

    Returns:
        ``"+12.4%"``, or ``"n/a"``.
    """
    return f"{move * 100:+.1f}%" if move is not None else "n/a"


def _number(price: Decimal | None) -> float | None:
    """Turn a database numeric into something JSON can carry.

    Args:
        price: The figure, if there is one.

    Returns:
        The same figure as a float, or None.
    """
    return None if price is None else float(price)


def _as_utc_date(value: datetime) -> date:
    """Return the UTC calendar day a timestamp falls on.

    Args:
        value: A timestamp, with or without a timezone.

    Returns:
        The day, on the same calendar ``price_history.seen_on`` is generated
        with, so a run and the rows it wrote are never a day apart.
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


def _by_day(one: _SiteDay) -> date:
    """Return a shop-day's date, for sorting.

    Args:
        one: The shop's day.

    Returns:
        Its date.
    """
    return one.day


def _order(finding: Finding) -> tuple[int, str, str, str]:
    """Return the sort key: most severe first, then by site.

    Args:
        finding: The finding to place.

    Returns:
        A tuple that puts high above low, catalogue-wide findings above named
        shops within a severity, and ties in a stable order.
    """
    return (
        _SEVERITY_ORDER.get(finding.severity, len(_SEVERITY_ORDER)),
        finding.site,
        finding.kind,
        finding.summary,
    )
