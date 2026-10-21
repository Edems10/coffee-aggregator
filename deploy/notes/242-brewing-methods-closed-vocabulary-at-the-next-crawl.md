# 0.14.0 puts `brewing_methods` on eight values — rows change at the next crawl

`brewing_methods` now holds only `espresso`, `moka`, `filter`, `french_press`,
`aeropress`, `turkish`, `automatic` and `cold_brew`, instead of the shop's own words.
Run `update.sh` as the user that owns `/opt/coffee-aggregator`, **not with `sudo`**:
under `sudo` the pull fails because root has no GitHub key (see `deploy/README.md`,
*Updating*). There is no migration and no backfill, and nothing else to run.

**No stored row changes until its next crawl.** A parsing fix rewrites nothing
already stored; the crawl's upsert writes the new list. Delisted rows are never
crawled again and keep the shop's own words, so a query over the whole table will
still find them.

## What the coverage report will say

`db/coverage.py` counts a coffee as having `brewing_methods` when its list is not
empty, and files a high finding when a shop's fill falls 20 points or more below its
own median over at least 8 rows. The finding names the aggregator versions, so it
reads `... ; aggregator 0.13.x -> 0.14.0 over the window`: that is this release,
not the shop.

Read against the 2026-10-17 local crawl, three shops cross the line on the first
night: `coffegarden` (100% to 0%, its only item was `zrnková`), `redfawn` (43% to
14%, sentences about the roast) and `labcafe` (38% to 12%, two sentences about the
blend). `eshop` falls too but has 7 rows, below the 8 a finding needs. Across the
whole catalogue the fill goes from 1 899 to 1 852 of 3 734 bean rows. Those falls
are the grinds and the sentences leaving, which is the intent; nobody needs to chase
them. A fall at a shop that is not named here, on the night of this deploy, is worth
a look.

## What to check after the next crawl

From the directory compose reads its configuration from. The query scans every
listed (not delisted) coffee and returns each distinct stored value outside the
eight, so it has no re-read filter: once every shop has crawled it should return no
rows.

    cd /opt/coffee-aggregator/deploy
    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT item, count(*)
         FROM coffee, jsonb_array_elements_text(brewing_methods) AS item
         WHERE delisted_at IS NULL
           AND item NOT IN ('espresso', 'moka', 'filter', 'french_press',
                            'aeropress', 'turkish', 'automatic', 'cold_brew')
         GROUP BY item ORDER BY count(*) DESC"

A row means that coffee has not been crawled since the deploy, or its shop's crawl
failed and keeps the old words until its next good one. Delisted rows are excluded
from the query and keep the shop's words for good; they can never fail the
contract's `check`, because the later publish pull request emits only values from the
closed set, filtered at publish time.

## Rolling back

The code is rolled back by the previous commit checked out in
`/opt/coffee-aggregator` and rebuilt. No schema changed. Rows crawled on 0.14.0 keep
the eight values until the next crawl on the older code rewrites them, so a rollback
followed by a crawl restores the shop's own words, grinds and fragments included.
