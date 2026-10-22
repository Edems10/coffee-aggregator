# 0.14.5 reads the weight of a joined Shoptet label — corrected at the next crawl

0.14.5 reads the weight of a Shoptet variant named by one hidden label that joins
every parameter (`Druh kávy: Zrnková, Hmotnost: 250g`). A re-parse of the 2 621
cached Shoptet pages on 2026-10-22 found 15 such pages (`cafegape` 10,
`hippocafe` 4, `eshopmakacoffee` 1) and moved 41 variants from no weight to one.
Run `update.sh` as the user that owns `/opt/coffee-aggregator`, **not with
`sudo`**: the pull fails under `sudo` because root has no GitHub key (see
`deploy/README.md`, *Updating*). There is nothing else to run, and no migration.

**Deploy 0.14.5 together with 0.14.4.** Without it, 0.14.4 stores no price for
eight products whose page states one.

**No row changes until the shop's next crawl.** A parsing fix rewrites nothing
already stored; the crawl's upsert writes the weights. Delisted rows are never
crawled again and keep what they have.

**Note 172's nine NULL-price products become one.** With both versions deployed,
`cafegape` 2166, 2172, 2211, 2241 and `hippocafe` 77, 83, 89, 107 keep a price at
the next crawl: 209 to 330 Kč for 250 g. Note
`172-prices-take-the-250g-option-at-the-next-crawl.md` says its second check query
"lists all nine"; after both versions it lists only the `cityroasters` drip
sachet `6644243988542`, a Shopify product this change does not touch. That is a
correct deploy, not a failed one.

The eight products' `weight_g` and per-kilogram prices go from NULL to a value at
the next crawl, which starts a new price-history point for each. The point is
recorded, not reset. If 0.14.4 is crawled alone first, those eight record a NULL
price point and then a price again once 0.14.5 is crawled.

What to check after the next crawl of `cafegape` and `hippocafe`, from the
directory compose reads its configuration from. It lists the eight with a price
and a weight:

    cd /opt/coffee-aggregator/deploy
    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT site, external_id, price, weight_g, price_per_kg
         FROM coffee
         WHERE delisted_at IS NULL
           AND (site, external_id) IN (('cafegape', '2166'), ('cafegape', '2172'),
                ('cafegape', '2211'), ('cafegape', '2241'), ('hippocafe', '77'),
                ('hippocafe', '83'), ('hippocafe', '89'), ('hippocafe', '107'))
         ORDER BY site, external_id"

Every row reads a price and 250 g, for example `hippocafe/77` 330 Kč, 1 320 Kč/kg
and `cafegape/2166` 209 Kč, 836 Kč/kg. Their variants carry the page's own label
(`Druh kávy: Zrnková, Hmotnost: 250g`) and a weight each; before, a variant was
named by its sku.

## Rolling back

Check the previous commit out in `/opt/coffee-aggregator` and rebuild. Nothing in
the schema changed. The older code reads no weight from these labels again at the
next crawl, so with 0.14.4 still deployed the eight products store no price.
