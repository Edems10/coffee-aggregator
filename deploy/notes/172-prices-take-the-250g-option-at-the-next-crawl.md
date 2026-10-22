# 0.14.4 stores the option nearest 250 g — corrected at the next crawl

0.14.4 stores every product that offers several packages at different prices
under one of them, the option nearest 250 g, with that option's own price,
weight, currency and original price. A re-parse of the 2 621 cached Shoptet pages
and a crawl of the other platforms on 2026-10-22 moved 450 products in 48 shops
(439 of them to a different weight) and left 2 455 untouched. Run `update.sh` as
the user that owns `/opt/coffee-aggregator`, **not with `sudo`**: the pull fails
under `sudo` because root has no GitHub key (see `deploy/README.md`, *Updating*).
There is nothing else to run, and no migration.

**No row changes until the shop's next crawl.** A parsing fix rewrites nothing
already stored; the crawl's upsert writes the new option, and the next crawl of a
shop is when its rows move. Delisted rows are never crawled again and keep what
they have.

The next crawl starts a new price-history point for each of the 450 products. Per
kilogram, 205 go up, 196 go down, one loses its figure and 48 keep it (`botacoffee`
goes from the 70 g sample at about 1 243 Kč/kg to the 250 g bag, `danielasroastery`
from its 100 g option at about 2 170 Kč/kg to its 250 g one at about 1 340). The
jump is recorded, not reset, and not flagged: this is the owner's decision on #172
(2026-10-21), because nothing on the site reads price history yet and a reset would
destroy the only record. A query that reads `price_history` across the crawl day
sees every one of these products step once.

**Nine products go to NULL price.** No option of theirs states a weight and the
name does not either, so the "from" price they stored said nothing about any pack.
Their `price`, `weight_g`, per-kilogram prices, `currency` and `original_price`
are NULL after the next crawl, and their events carry `price_minor` null:
`cafegape` 2166, 2172, 2211, 2241; `cityroasters` 6644243988542; `hippocafe` 77, 83,
89, 107. They keep every other field.

What to check after the next crawl of the affected shops, from the directory
compose reads its configuration from. This query was run once on an `init-db`
scratch database before it was written here; it returns no rows after the crawl:

    cd /opt/coffee-aggregator/deploy
    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT c.site, c.external_id, c.price, c.weight_g
         FROM coffee c
         WHERE c.delisted_at IS NULL AND c.price IS NOT NULL AND c.weight_g IS NOT NULL
           AND EXISTS (SELECT 1 FROM coffee_variant v
                       WHERE v.site = c.site AND v.external_id = c.external_id
                         AND v.price IS NOT NULL AND v.weight_g IS NOT NULL)
           AND NOT EXISTS (SELECT 1 FROM coffee_variant v
                           WHERE v.site = c.site AND v.external_id = c.external_id
                             AND v.price = c.price AND v.weight_g = c.weight_g)
         ORDER BY c.site, c.external_id"

Any row it lists carries a price and a weight that no single option states. The
nine NULL-price products read:

    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT site, external_id, name FROM coffee
         WHERE delisted_at IS NULL AND price IS NULL
           AND (site, external_id) IN (('cafegape', '2166'), ('cafegape', '2172'),
                ('cafegape', '2211'), ('cafegape', '2241'),
                ('cityroasters', '6644243988542'), ('hippocafe', '77'),
                ('hippocafe', '83'), ('hippocafe', '89'), ('hippocafe', '107'))
         ORDER BY site, external_id"

It lists all nine once their shops have been crawled. Every `botacoffee` row that
lists a 250 g option reads 250 g afterwards.

## Rolling back

Check the previous commit out in `/opt/coffee-aggregator` and rebuild. Nothing in
the schema changed. The older code stores each shop's own headline price and weight
again at the next crawl of the shops, so the price history steps once more.
