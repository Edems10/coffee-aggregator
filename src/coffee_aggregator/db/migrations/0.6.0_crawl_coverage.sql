-- What each shop published on each crawl day, as counts rather than values.
--
-- `coffee` is upserted in place and `sinks/postgres.py:UPSERT_SQL` carries no
-- COALESCE, so a crawl whose selector rotted overwrites the value yesterday's
-- crawl read correctly and leaves nothing behind saying it ever held one. On
-- 2026-10-17 ajvencoffee's `origin_country` went 70% -> 0% over 11 rows and
-- ohmybean's 65% -> 37% over 27, with row counts up, prices right and zero
-- failures: all nine finding kinds stayed silent, correctly, and the data
-- rotted anyway. This table is the history those comparisons needed.
--
-- One row per (day, site, field), which is the primary key, so re-running a
-- night replaces its rows rather than doubling them; the write is an upsert on
-- that key. 24 fields over ~152 shops is ~3 650 integers a night.
--
-- `version` is here rather than joined from `crawl_run` when the report runs.
-- The version that produced a measurement is a property of that measurement,
-- and `report --day <past date>` is a separate invocation that may run on a
-- different day from a different build; joining would record the version that
-- summarised the night instead of the one that performed it. That is the same
-- line 0.4.0_crawl_run_version.sql draws between a run and a finding, and a
-- coverage row sits on the run side of it. Nullable, with no default: a row
-- written by a version nobody recorded says NULL where '' would assert one.
--
-- `raw_attributes` is not among the fields and must not be added. It is a
-- jsonb *object*, so `jsonb_array_length` raises on it, and the write sits
-- inside `monitoring.record`'s swallow-everything handler: one formula copied
-- from the jsonb-array fields would make the whole night's coverage fail
-- *silently* -- the drift detector built to catch silent failure failing
-- silently. `product_kind` is out for a different reason: two sentinels, and
-- written by the seed loader rather than the crawl, so its coverage measures
-- us.
--
-- A row is written only for a run that finished `complete AND discovery_ok`.
-- `mark_delisted` is skipped on a partial or unhealthy run (pipeline.py:286,
-- 365-368), so a truncated night records a diluted fill rate that is later
-- used as a baseline, and the drop it invents belongs to the delisting that
-- did not run. For the same reason `rows` counts what the crawl re-read that
-- night -- `last_seen_at >= <the run's started_at>` -- and not
-- `delisted_at IS NULL`.
CREATE TABLE IF NOT EXISTS crawl_coverage (
    day date NOT NULL,
    site text NOT NULL,
    field text NOT NULL,
    rows integer NOT NULL,
    known integer NOT NULL,
    version text,
    PRIMARY KEY (day, site, field)
);
