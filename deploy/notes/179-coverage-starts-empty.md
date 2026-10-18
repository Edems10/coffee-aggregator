# 0.6.0 starts `crawl_coverage` empty — the first nights report nothing

Migration `0.6.0_crawl_coverage` creates one new table. `update.sh` already runs
the migrations, so there is nothing extra to run and nothing to backfill: the
history this table holds is the history the database never kept, and no stored
row can be read backwards into it.

**The first nights produce no `coverage-drop` finding at all, and that is not a
failure.** A finding is a shop's field against that shop's own recent median,
so it needs a baseline, and the baseline only exists once a few nights have
been recorded. The report's window is 7 days by default, so expect silence on
night one, and expect it to stay quiet after that too — the threshold found 5
events across 152 shops over seventeen days.

What to check the morning after the first crawl, on the server's database:

    psql "$DATABASE_URL" -c "SELECT count(*), count(DISTINCT site), min(day)
      FROM crawl_coverage"

Expect 24 rows per shop that crawled cleanly — roughly 3 650 across ~152 shops —
all on one `day`, all carrying the version in `version`. A shop missing from it
either re-read no beans or did not finish `complete AND discovery_ok`; both are
deliberate, and `coffee-aggregator runs --site <shop>` says which.

If the table is empty after a full crawl, the write is failing and being
swallowed. It logs: look for `could not record the coverage of <shop>` in the
journal before suspecting the migration.

Nothing else in the release touches the database, and nothing needs
re-crawling.
