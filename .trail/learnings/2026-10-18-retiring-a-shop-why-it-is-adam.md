---
title: "Retiring a shop: why it is a CLI command, not a migration"
author: Adam
date: 2026-10-18
branch: ft/214-retire-a-shop-that-stopped-selling
touches:
  - src/coffee_aggregator/sinks/postgres.py
  - src/coffee_aggregator/cli.py
  - src/coffee_aggregator/sites/loader.py
---

## What it is

A shop that has closed leaves its coffees listed forever, and two things make
that hard to fix.

`mark_delisted` (`sinks/postgres.py`) refuses an empty `seen_external_ids` set
on purpose: an empty set means the run saw nothing, which is a broken crawl and
not an empty catalogue. That guard is correct and must not be weakened — it is
also why the rows are stuck.

The outbox is written by **application code**, not a trigger: `_stamp_locked`
builds `outbox.event_rows_from_db(stamped)` and inserts the rows in the same
transaction as the UPDATE. So a plain SQL migration setting `delisted_at` would
update the aggregator's table and publish **nothing**, leaving `coffee-api` and
the website serving coffees the database calls gone, with nothing reporting the
disagreement.

## What we did

`coffee-aggregator retire --site <shop> [--yes]` (#214), going through
`PostgresSink.retire` → `_stamp_locked(RETIRE_SQL, ...)` — the same body the
crawl's delisting uses, so the events ride along by construction rather than by
a second code path that could drift.

## Tried and ruled out

- A SQL migration: publishes nothing, see above.
- Reaching `DELIST_SQL` with an empty array (it does delist everything, because
  `x = ANY('{}')` is false): `RETIRE_SQL` is spelled out instead, so the
  statement that empties a shop is readable on its own.
- Deleting `goodtimes.toml`: a deleted config vanishes silently and is how
  somebody re-adds the shop next year — and it would make the retire impossible,
  because the guard reads that file.

## Watch out

The guard is `sites.switched_off(site_id)`, which reads the shop's TOML
`disabled` reason; the registry cannot answer, because a switched-off shop is
simply absent from it. That fixes the order on the server: **switch the shop
off and deploy first, then retire.** Without `--yes` nothing is written.
Nothing is ever deleted — `delisted_at` is a stamp and the upsert clears it, so
a shop that comes back is restored by crawling it.
