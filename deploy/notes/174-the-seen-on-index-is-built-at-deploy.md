# 0.4.1 builds an index on `price_history` — run it away from the crawl

Migration `0.4.1_price_history_seen_on` creates `price_history_seen_on_idx` on
`price_history (seen_on, site, external_id)`. Nothing else in the release touches
the database, and the nightly report keeps reading the whole table until this
migration has run on the server — deploying the image alone changes no plan.

`CREATE INDEX` is plain, not `CONCURRENTLY`: the runner applies every migration
inside a transaction, and `CONCURRENTLY` cannot run in one. The plain form takes
a `SHARE` lock, so **writes to `price_history` are blocked while the index
builds**. On 1 241 000 rows — about a year of crawling — the build took 0.5 s on
a laptop container; allow a few seconds on the server's disk, and longer in
proportion if the table has grown past that.

The crawl is the only writer, and it runs at 05:00. So:

* Deploy at any hour that is not a crawl. If a crawl is running, wait for it to
  finish rather than letting the migration hold its lock against the upserts.
* Nothing needs a backfill and nothing needs re-crawling. The index covers rows
  that are already there the moment it is built.

Confirm it afterwards, on the server's database:

    psql "$DATABASE_URL" -c "\\di+ price_history_seen_on_idx"

It should report a btree of roughly 48 MB per million rows. Then check the plan
the report will use:

    psql "$DATABASE_URL" -c "EXPLAIN SELECT 1 FROM price_history
      WHERE seen_on >= CURRENT_DATE - 1 AND seen_on <= CURRENT_DATE"

It must print `Index Scan using price_history_seen_on_idx` with an `Index Cond`
on `seen_on`. A `Seq Scan` means the migration has not run or `ANALYZE` has not
caught up; `VACUUM ANALYZE price_history` and look again.

**Do not drop any index on this table on the strength of `idx_scan = 0`.**
`price_history_day_idx` reads as unused and is the arbiter of the crawl's
`ON CONFLICT (site, external_id, seen_on)`; an arbiter never increments
`idx_scan`. Dropping it would break every nightly upsert.
