from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from coffee_aggregator import normalize, product_kind
from coffee_aggregator.sinks.postgres import PostgresSink

if TYPE_CHECKING:
    from pathlib import Path

#: The columns the labelling pass writes. Compared as a set, so a file whose
#: columns were renamed fails here rather than loading the wrong one.
SEED_COLUMNS: Final[frozenset[str]] = frozenset(
    {"site", "external_id", "product_kind", "confidence", "why", "reviewed", "name", "url"}
)

#: An UPDATE and never an INSERT: a seed row whose coffee the crawl has not stored
#: is counted as skipped, not written as a bare row with no name or price.
_SET_KIND_SQL = (
    "UPDATE coffee SET product_kind = %s, product_kind_source = %s, "
    "product_kind_name_hash = %s WHERE site = %s AND external_id = %s"
)


class SeedError(ValueError):
    """The seed file is not one the loader can trust, so nothing was written."""


@dataclass(frozen=True, slots=True)
class SeedRow:
    """One labelled row, checked and ready to write.

    Attributes:
        site: The site id the coffee is stored under.
        external_id: The shop's id for the product.
        product_kind: A member of :data:`product_kind.PRODUCT_KINDS`.
        product_kind_source: :data:`product_kind.SEED_SOURCE` or
            :data:`product_kind.SEED_REVIEWED_SOURCE`.
        product_kind_name_hash: The hash of the name the label was given for.
    """

    site: str
    external_id: str
    product_kind: str
    product_kind_source: str
    product_kind_name_hash: str


@dataclass(frozen=True, slots=True)
class SeedResult:
    """How many seed rows were written and how many had no stored coffee.

    Attributes:
        written: Rows whose coffee is in the store and now carries the kind.
        skipped: Rows whose ``(site, external_id)`` is not in the store.
    """

    written: int
    skipped: int


def read_seed(path: Path) -> list[SeedRow]:
    """Read and check the labelled seed without touching the database.

    Every problem is collected before raising, so one run names all of them.

    Args:
        path: The labelling pass's CSV, read as UTF-8.

    Returns:
        One row per record of the file, in file order.

    Raises:
        SeedError: When the columns differ from :data:`SEED_COLUMNS`, a kind is not
            in the vocabulary, a name is empty, or a key appears twice.
    """
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or set(reader.fieldnames) != SEED_COLUMNS:
            found = sorted(reader.fieldnames or [])
            message = f"columns are {found}, expected {sorted(SEED_COLUMNS)}"
            raise SeedError(message)
        rows: list[SeedRow] = []
        problems: list[str] = []
        seen: set[tuple[str, str]] = set()
        for record in reader:
            line = reader.line_num
            # A short or long record would otherwise reach .strip() as None, or shift
            # a column into the wrong field; either is refused by name, not by crash.
            if None in record or None in record.values():
                problems.append(f"line {line}: does not have exactly {len(SEED_COLUMNS)} fields")
                continue
            site = record["site"].strip()
            external_id = record["external_id"].strip()
            kind = record["product_kind"].strip()
            name = record["name"].strip()
            if not site or not external_id:
                problems.append(f"line {line}: site and external_id are required")
                continue
            if (site, external_id) in seen:
                problems.append(f"line {line}: {site}/{external_id} appears twice")
                continue
            seen.add((site, external_id))
            if kind not in product_kind.PRODUCT_KINDS:
                problems.append(f"line {line}: unknown product_kind {kind!r}")
                continue
            if not name:
                problems.append(f"line {line}: {site}/{external_id} has no name to hash")
                continue
            rows.append(
                SeedRow(
                    site=site,
                    external_id=external_id,
                    product_kind=kind,
                    product_kind_source=(
                        product_kind.SEED_REVIEWED_SOURCE
                        if record["reviewed"].strip()
                        else product_kind.SEED_SOURCE
                    ),
                    product_kind_name_hash=normalize.product_name_hash(name),
                )
            )
    if problems:
        raise SeedError("; ".join(problems))
    return rows


def load_seed(dsn: str, path: Path) -> SeedResult:
    """Write the labelled kinds onto the coffees already in the store.

    The file is checked in full before the database is opened, so a bad seed
    writes nothing. The writes share one transaction.

    Args:
        dsn: A ``postgresql://`` connection string.
        path: The labelling pass's CSV.

    Returns:
        How many rows were written and how many were skipped.

    Raises:
        SeedError: When the file fails :func:`read_seed`.
        SchemaOutOfDateError: When the migration that adds the kind columns has not
            been applied.
    """
    rows = read_seed(path)
    sink = PostgresSink(dsn)
    try:
        sink.ensure_schema()
        return _write(sink, rows)
    finally:
        sink.close()


def _write(sink: PostgresSink, rows: list[SeedRow]) -> SeedResult:
    """Run the UPDATE for every row inside one transaction.

    Args:
        sink: A sink whose schema has been checked.
        rows: The checked seed rows.

    Returns:
        How many rows matched a stored coffee, and how many did not.
    """
    connection = sink.connection
    written = 0
    try:
        with connection.cursor() as cursor:
            for row in rows:
                cursor.execute(
                    _SET_KIND_SQL,
                    (
                        row.product_kind,
                        row.product_kind_source,
                        row.product_kind_name_hash,
                        row.site,
                        row.external_id,
                    ),
                )
                written += cursor.rowcount
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return SeedResult(written=written, skipped=len(rows) - written)
