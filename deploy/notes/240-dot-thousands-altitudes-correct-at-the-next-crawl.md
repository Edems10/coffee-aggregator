# 0.13.2 corrects single altitudes written as `1.200 m` — at the next crawl

A single altitude written with a dot as the thousands separator (`1.200 m.n.m.`,
`1.500 m.a.s.l`) was stored as the three digits after the dot, so 200 m and 500
m instead of 1200 m and 1500 m. A local crawl of 2026-10-17 had 15 rows of this
kind. 0.13.2 reads them as thousands. Run `update.sh` as the user that owns
`/opt/coffee-aggregator`, **not with `sudo`** (see `deploy/README.md`,
*Updating*). There is nothing else to run, and no migration.

**No row changes until the coffee's next crawl.** A parsing fix rewrites nothing
already stored; the crawl's upsert writes the corrected altitude. Delisted rows
are never crawled again and keep what they have.

What to check after the next crawl of all shops, from the directory compose
reads its configuration from. It should return no rows:

    cd /opt/coffee-aggregator/deploy
    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT site, altitude_raw, altitude_min_m, altitude_max_m
         FROM coffee
         WHERE delisted_at IS NULL
           AND altitude_raw ~ '(^|[^0-9])[0-9]{1,2}\.[0-9]{3}([^0-9]|$)'
           AND altitude_min_m = altitude_max_m
           AND altitude_min_m < 1000"

Only single values are checked: a range such as `950 - 1.250 m n. m.` starts
under 1000 m legitimately and is left out by the `altitude_min_m = altitude_max_m`
condition. A listed row that is returned belongs to a coffee whose shop has not
been crawled since the deploy.

## Rolling back

Check the previous commit out in `/opt/coffee-aggregator` and rebuild. Nothing
in the schema changed. The older code writes the three-digit figure again at the
next crawl of each affected coffee.
