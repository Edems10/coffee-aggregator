from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from coffee_contracts import COFFEE_STATE, CoffeeState, check, coffee_from_json, to_json

from coffee_aggregator import product_kind
from coffee_aggregator.models import Coffee, Species
from coffee_aggregator.pack_group import pack_group_key
from coffee_aggregator.sinks import outbox
from coffee_aggregator.sinks.postgres import COLUMNS, MANAGED_COLUMNS, PostgresSink
from conftest import delisted_row, make_coffee
from test_postgres_sink import FakeConnection

FIRST_SEEN = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
#: The ``coffee.state`` fields the contract gained in 3.3.0 and this producer holds
#: back at their defaults until each publish pull request releases them.
HELD_BACK: dict[str, object] = {
    "description": None,
    "origin_farm": None,
    "origin_producer": None,
    "origin_washing_station": None,
    "altitude_max_m": None,
    "body": None,
    "acidity": None,
    "sweetness": None,
    "bitterness": None,
    "brewing_methods": [],
}
#: A row the kind decider and the seed loader have not reached.
NOT_DECIDED = outbox.StoredFields(FIRST_SEEN, None, None)
#: A row a seed has decided.
DECIDED = outbox.StoredFields(FIRST_SEEN, "beans", product_kind.SEED_SOURCE)


def _rows(
    *coffees: Coffee, stored: outbox.StoredFields = NOT_DECIDED
) -> list[tuple[str, str, str]]:
    return outbox.event_rows_for(coffees, {(c.site, c.external_id): stored for c in coffees})


def _payload(row: tuple[str, str, str]) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(row[2])
    return loaded


def test_state_carries_what_a_consumer_can_act_on() -> None:
    row = _rows(make_coffee(site="demo", external_id="42"))[0]

    assert row[0] == "coffee.v2.catalogue.demo.42"
    assert row[1] == COFFEE_STATE
    payload = _payload(row)
    assert payload["type"] == COFFEE_STATE
    assert payload["name"] == "Kuba Serrano Superior"
    assert payload["origin_country"] == "CU"
    assert payload["roast_level"] == "medium"
    assert payload["flavor_notes"] == ["kakao", "karamel"]
    assert payload["observed_at"] == "2026-09-12T10:00:00+00:00"
    assert payload["delisted_at"] is None
    assert payload["first_seen_at"] == "2026-09-01T08:00:00+00:00"


def test_the_payload_round_trips_through_the_contract() -> None:
    coffee = make_coffee(site="demo", external_id="42")
    state = coffee_from_json(_rows(coffee)[0][2])

    assert state.key == "demo/42"
    assert state.observed_at == datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    assert state.is_delisted is False


def test_the_crawl_event_fills_every_field_the_row_holds() -> None:
    """A field that state_for leaves out publishes as null, which is how #142 went unseen.

    Every contract field is set on the coffee or read back from the row, so the
    only ones allowed to stay empty are ``delisted_at``, which a crawl never sets,
    ``price_history``, a series this producer does not fill, and the ten fields
    held back until their publish pull requests.
    """
    coffee = make_coffee(
        site="demo",
        external_id="42",
        roaster="Demo Roastery",
        decaf=True,
        species=Species(arabica_pct=80, robusta_pct=20),
        price_per_kg_eur=49.95,
    )
    state = outbox.state_for(coffee, DECIDED)

    empty = sorted(
        name
        for name, value in asdict(state).items()
        if (value is None or value == [])
        and name not in {"delisted_at", "price_history", *HELD_BACK}
    )
    assert empty == []


@pytest.mark.parametrize("name", sorted(HELD_BACK))
def test_a_held_back_field_publishes_its_default_on_the_crawl_event(name: str) -> None:
    coffee = make_coffee()
    coffee.taste.body = 7
    coffee.taste.brewing_methods = ["zrnková", "Espresso"]
    assert coffee.description

    payload = _validated(outbox.state_for(coffee, DECIDED))

    assert payload[name] == HELD_BACK[name]


@pytest.mark.parametrize("name", sorted(HELD_BACK))
def test_a_held_back_field_is_selected_as_an_expression_not_read_from_its_column(name: str) -> None:
    expression = outbox.STATE_EXPRESSIONS[outbox.STATE_FIELDS.index(name)]
    row = list(delisted_row())
    row[outbox.STATE_FIELDS.index(name)] = None
    state = outbox.state_from_row(row)

    assert not expression.isidentifier()
    assert getattr(state, name) == HELD_BACK[name]
    assert _validated(state)[name] == HELD_BACK[name]


def test_a_decaf_coffee_publishes_decaf_true_and_its_species_split() -> None:
    coffee = make_coffee(decaf=True, species=Species(arabica_pct=80, robusta_pct=20))

    payload = _payload(_rows(coffee, stored=DECIDED)[0])

    assert payload["decaf"] is True
    assert payload["arabica_pct"] == 80
    assert payload["robusta_pct"] == 20


def test_the_first_seen_stamp_and_the_kind_come_from_the_stored_row() -> None:
    payload = _payload(_rows(make_coffee(), stored=DECIDED)[0])

    assert payload["first_seen_at"] == "2026-09-01T08:00:00+00:00"
    assert payload["product_kind"] == "beans"
    assert payload["product_kind_source"] == product_kind.SEED_SOURCE


def test_a_value_the_row_does_not_hold_publishes_null_not_a_default() -> None:
    """A null stays null: a stored false would assert a fact the shop never stated."""
    payload = _payload(_rows(make_coffee(decaf=None, species=Species()))[0])

    assert payload["decaf"] is None
    assert payload["arabica_pct"] is None
    assert payload["robusta_pct"] is None
    assert payload["product_kind"] is None
    assert payload["product_kind_source"] is None


def test_the_roaster_comes_from_the_brand_attribute_when_nothing_else_states_it() -> None:
    coffee = make_coffee(raw_attributes={"BRAND": "Doubleshot"})
    assert _payload(_rows(coffee)[0])["roaster"] == "Doubleshot"


def test_an_empty_external_id_is_skipped_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    """coffeein and nordbeans both fall back to "" when a listing gives no id.

    Raising here would abort the batch, send it down ``_retry_one_by_one`` and
    drop the coffee from the catalogue as well: a data regression caused by a
    messaging concern.
    """
    good = make_coffee(site="coffeein", external_id="7")
    bad = make_coffee(site="coffeein", external_id="", url="https://coffeein.sk/p/mystery")

    with caplog.at_level(logging.WARNING, logger=outbox.logger.name):
        rows = _rows(good, bad)

    assert [row[0] for row in rows] == ["coffee.v2.catalogue.coffeein.7"]
    assert "https://coffeein.sk/p/mystery" in caplog.text
    assert "external_id is empty" in caplog.text


def test_a_site_id_with_a_dot_is_skipped_too() -> None:
    """A dot is structure in a NATS subject, so it would silently widen a subscription."""
    assert _rows(make_coffee(site="demo.sk", external_id="7")) == []


def test_every_state_expression_reads_a_column_the_coffee_table_has() -> None:
    """The RETURNING list and the dataclass drift apart the moment one is edited alone."""
    known = {*COLUMNS, *MANAGED_COLUMNS}
    bare = [name for name in outbox.STATE_EXPRESSIONS if name.isidentifier()]
    assert set(bare) <= known
    assert len(outbox.STATE_EXPRESSIONS) == len(outbox.STATE_FIELDS)


def test_a_row_read_back_out_of_the_table_becomes_the_same_kind_of_event() -> None:
    state = outbox.state_from_row(delisted_row(external_id="9"))

    assert state.key == "demo/9"
    assert state.is_delisted
    assert state.price_minor == 999
    assert type(state.price_minor) is int
    assert state.price_per_kg_eur_cents == 4995
    assert state.sca_score == 84.5
    assert state.variety == ["Typica"]


def test_a_null_jsonb_column_becomes_an_empty_list() -> None:
    state = outbox.state_from_row(delisted_row(variety=None, flavor_notes=None))
    assert state.variety == []
    assert state.flavor_notes == []


def test_a_row_read_back_serialises() -> None:
    rows = outbox.event_rows_from_db([delisted_row(external_id="9")])
    assert _payload(rows[0])["price_minor"] == 999


def test_the_decimal_guard_is_load_bearing() -> None:
    """Without the coercion the contract's encoder refuses the event outright."""
    straight = CoffeeState(
        site="demo",
        external_id="9",
        observed_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC),
        sca_score=Decimal("84.5"),  # type: ignore[arg-type]
    )
    with pytest.raises(TypeError, match="Decimal is not part of the contract"):
        to_json(straight)


PICTURES = [
    "https://example.sk/img/1.jpg",
    "https://example.sk/img/3.jpg",
    "https://example.sk/img/2.jpg",
]


def test_the_pictures_are_published_in_page_order() -> None:
    payload = _payload(_rows(make_coffee(images=PICTURES), stored=DECIDED)[0])

    assert payload["images"] == PICTURES


def test_a_coffee_with_no_pictures_publishes_an_empty_list_not_null() -> None:
    payload = _payload(_rows(make_coffee(images=[]), stored=DECIDED)[0])

    assert payload["images"] == []


def test_the_pictures_survive_a_row_read_back_out_of_the_table() -> None:
    state = outbox.state_from_row(delisted_row(images=PICTURES))

    assert state.images == PICTURES
    assert (
        _payload(outbox.event_rows_from_db([delisted_row(images=PICTURES)])[0])["images"]
        == PICTURES
    )


def test_a_null_images_column_becomes_an_empty_list() -> None:
    """A row the crawl wrote before the column was filled holds NULL, not []."""
    assert outbox.state_from_row(delisted_row(images=None)).images == []


def test_an_event_written_before_pictures_reads_back_as_empty() -> None:
    """Payloads published before 0.3.0 have no ``images`` key and must still parse."""
    payload = _payload(_rows(make_coffee(), stored=DECIDED)[0])
    del payload["images"]

    assert coffee_from_json(json.dumps(payload)).images == []


def test_the_upsert_queues_one_event_per_coffee_in_the_same_transaction() -> None:
    connection = FakeConnection()
    sink = PostgresSink("postgresql://fake/db", chunk_size=10)
    sink._connection = connection  # type: ignore[assignment]
    sink._schema_checked = True

    sink.upsert([make_coffee(external_id="1"), make_coffee(external_id="2")])

    events = next(call for call in connection.calls if call[1] == outbox.OUTBOX_SQL)
    assert events[0] == "executemany"
    assert [row[0] for row in events[2]] == [
        "coffee.v2.catalogue.demo.1",
        "coffee.v2.catalogue.demo.2",
    ]
    assert connection.commits == 1


def test_a_coffee_with_no_id_is_still_stored_even_though_it_is_not_published() -> None:
    connection = FakeConnection()
    sink = PostgresSink("postgresql://fake/db", chunk_size=10)
    sink._connection = connection  # type: ignore[assignment]
    sink._schema_checked = True

    result = sink.upsert([make_coffee(external_id="")])

    assert result.written == 1
    assert result.failed == 0
    assert all(call[1] != outbox.OUTBOX_SQL for call in connection.calls)


def _validated(state: CoffeeState) -> dict[str, Any]:
    """Serialise an event and hold it to the contract's own validation, as the broker would."""
    payload: dict[str, Any] = json.loads(to_json(state))
    check(payload)
    assert coffee_from_json(to_json(state)) == state
    return payload


@pytest.mark.parametrize(
    ("price", "currency", "minor"),
    [
        (Decimal("349.00"), "CZK", 34900),
        (Decimal(287), "CZK", 28700),
        (Decimal(99899999990), "CZK", 9989999999000),
        (Decimal("9.99"), "EUR", 999),
    ],
)
def test_a_stored_price_is_published_in_exact_minor_units(
    price: Decimal, currency: str, minor: int, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=outbox.logger.name):
        state = outbox.state_from_row(delisted_row(price_minor=price, currency=currency))

    assert state.price_minor == minor
    assert type(state.price_minor) is int
    assert _validated(state)["price_minor"] == minor
    assert caplog.records == []


@pytest.mark.parametrize(
    ("price", "minor"), [(24.33, 2433), (0.29, 29), (4.35, 435), (0.1 + 0.2, None)]
)
def test_a_crawled_float_price_is_counted_as_the_shop_printed_it(
    price: float, minor: int | None
) -> None:
    """``int(0.29 * 100)`` is 28; the float goes through ``money.exact`` instead.

    ``0.1 + 0.2`` is ``0.30000000000000004``, which a shop never printed: it has
    more than two decimals, so it publishes null rather than a rounded 30.
    """
    state = outbox.state_for(make_coffee(price=price, currency="EUR"), DECIDED)

    assert state.price_minor == minor
    assert _validated(state)["price_minor"] == minor


def test_a_price_with_more_than_two_decimals_publishes_null_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=outbox.logger.name):
        state = outbox.state_from_row(
            delisted_row(site="demo", external_id="77", price_minor=Decimal("12.345"))
        )

    assert state.price_minor is None
    assert state.price_per_kg_eur_cents == 4995
    _validated(state)
    [record] = caplog.records
    for part in ("demo/77", "price_minor", "12.345"):
        assert part in record.getMessage()


@pytest.mark.parametrize("currency", ["USD", None])
def test_a_price_in_a_currency_with_no_known_exponent_publishes_null(
    currency: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=outbox.logger.name):
        state = outbox.state_from_row(
            delisted_row(external_id="5", price_minor=Decimal("10.00"), currency=currency)
        )

    assert state.price_minor is None
    _validated(state)
    [record] = caplog.records
    for part in ("demo/5", "price_minor", "10.00", str(currency)):
        assert part in record.getMessage()


def test_a_missing_price_is_null_without_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=outbox.logger.name):
        from_row = outbox.state_from_row(
            delisted_row(price_minor=None, price_per_kg_eur_cents=None)
        )
        crawled = outbox.state_for(make_coffee(price=None, price_per_kg_eur=None), DECIDED)

    assert (from_row.price_minor, from_row.price_per_kg_eur_cents) == (None, None)
    assert (crawled.price_minor, crawled.price_per_kg_eur_cents) == (None, None)
    _validated(from_row)
    _validated(crawled)
    assert caplog.records == []


def test_the_price_per_kilogram_is_published_in_euro_cents() -> None:
    state = outbox.state_from_row(
        delisted_row(price_per_kg_eur_cents=Decimal("24.50"), currency="CZK")
    )

    assert state.price_per_kg_eur_cents == 2450
    assert _validated(state)["price_per_kg_eur_cents"] == 2450


def test_every_event_carries_an_empty_price_history_on_the_v2_subject() -> None:
    crawled = _rows(make_coffee(external_id="1"), stored=DECIDED)[0]
    republished = outbox.event_rows_from_db([delisted_row(external_id="2")])[0]

    for subject, _, payload in (crawled, republished):
        assert subject.startswith("coffee.v2.catalogue.")
        assert json.loads(payload)["price_history"] == []
        check(json.loads(payload))


def test_an_amount_too_large_to_scale_publishes_null_instead_of_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``scaleb`` raises ``decimal.Overflow`` here, which is no ``InvalidOperation``."""
    with caplog.at_level(logging.WARNING, logger=outbox.logger.name):
        minor = outbox.minor_units(
            Decimal("1E+999999999"), "CZK", site="demo", external_id="8", field="price_minor"
        )

    assert minor is None
    [record] = caplog.records
    assert "demo/8" in record.getMessage()


def test_a_crawled_price_in_an_unknown_currency_publishes_null_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    coffee = make_coffee(site="demo", external_id="31", price=10.0, currency="USD")
    with caplog.at_level(logging.WARNING, logger=outbox.logger.name):
        state = outbox.state_for(coffee, DECIDED)

    assert state.price_minor is None
    _validated(state)
    [record] = caplog.records
    for part in ("demo/31", "price_minor", "USD"):
        assert part in record.getMessage()


def test_a_crawled_price_with_more_than_two_decimals_publishes_null_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    coffee = make_coffee(site="demo", external_id="32", price=12.345, currency="CZK")
    with caplog.at_level(logging.WARNING, logger=outbox.logger.name):
        state = outbox.state_for(coffee, DECIDED)

    assert state.price_minor is None
    _validated(state)
    [record] = caplog.records
    for part in ("demo/32", "price_minor", "12.345"):
        assert part in record.getMessage()


PELLINI = "Pellini Espresso Bar n°4 Crema Tradizionale 1 kg"
ZEBIGI_URL = "https://fathers.example/kava/{kind}/uganda-zebigi"


def _valid_payload(*coffees: Coffee) -> list[dict[str, Any]]:
    return [_validated(outbox.state_for(coffee, NOT_DECIDED)) for coffee in coffees]


def test_the_crawl_event_carries_the_pack_group_key_the_function_builds() -> None:
    coffee = make_coffee(site="kava", name=PELLINI)
    row = _rows(coffee)[0]
    payload = _valid_payload(coffee)[0]

    assert payload["pack_group_key"] == pack_group_key("kava", PELLINI, coffee.url)
    assert payload["pack_group_key"] == "kava/pellini espresso bar n 4 crema tradizionale"
    assert row[0].startswith("coffee.v2.catalogue.kava.")


def test_the_pack_group_key_source_never_reaches_the_wire() -> None:
    payload = _valid_payload(make_coffee(site="kava", name=PELLINI))[0]

    assert "pack_group_key_source" not in payload
    assert not [key for key in payload if key.startswith("pack_group") and key != "pack_group_key"]


@pytest.mark.parametrize("name", ["", "   "])
def test_a_name_with_nothing_in_it_publishes_a_null_key_not_a_bare_site(name: str) -> None:
    coffee = make_coffee(site="kava", name=name, url=None)
    payload = _valid_payload(coffee)[0]

    assert payload["pack_group_key"] is None
    assert payload["pack_group_key"] not in {"", "kava/"}


def test_an_espresso_and_a_filter_listing_of_one_name_publish_two_keys() -> None:
    espresso, filtr = _valid_payload(
        make_coffee(
            site="fathers",
            external_id="1",
            name="Uganda – Zebigi",
            url=ZEBIGI_URL.format(kind="espresso"),
        ),
        make_coffee(
            site="fathers",
            external_id="2",
            name="Uganda – Zebigi",
            url=ZEBIGI_URL.format(kind="filtr"),
        ),
    )

    assert espresso["pack_group_key"].endswith("~espresso")
    assert filtr["pack_group_key"].endswith("~filter")
    assert espresso["pack_group_key"] != filtr["pack_group_key"]


def test_a_row_stored_before_the_key_existed_publishes_null() -> None:
    state = outbox.state_from_row(delisted_row(pack_group_key=None))
    payload = _validated(state)

    assert payload["pack_group_key"] is None


def test_a_row_read_back_publishes_the_key_it_stores() -> None:
    state = outbox.state_from_row(delisted_row(pack_group_key="demo/kuba serrano superior"))
    payload = _validated(state)

    assert payload["pack_group_key"] == "demo/kuba serrano superior"
