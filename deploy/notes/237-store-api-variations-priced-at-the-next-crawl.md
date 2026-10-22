# 0.14.6 prices every WooCommerce Store API variation — corrected at the next crawl

0.14.6 reads each Store API shop's variations listing and gives every variation
its own price, so #172's rule (the option nearest 250 g) now applies to the
WooCommerce shops too. Run `update.sh` as the user that owns
`/opt/coffee-aggregator`, **not with `sudo`**: the pull fails under `sudo`
because root has no GitHub key (see `deploy/README.md`, *Updating*). There is
nothing else to run, and no migration.

**It feeds 0.14.4's chooser.** Without 0.14.4 deployed the variation prices are
stored on the variants and no product row moves.

**No row changes until the shop's next crawl.** A parsing fix rewrites nothing
already stored; the crawl's upsert writes the new option. Delisted rows are
never crawled again and keep what they have.

**Extra requests.** A crawl makes one more request per 100 variations of a shop's
multi-variation products, to `/wp-json/wc/store/v1/products?type=variation&per_page=100&include=…`,
through the same polite fetcher: robots.txt, the host's delay and the cache all
apply. Measured on 2026-10-22 against 44 Store API shops it is 56 requests per
daily crawl for 2 964 variations (36 shops one request, `bonte` and `kavaloka`
five, `prazirnagrain` four, `aurelica`, `caffe4u` and `kmen` two, `lubezna` and
`networkcafe` none). A shop that states a crawl-delay pays it per request:
`caffeoro` states 30 s, so its one request adds about 30 s; the others use the
1 s default. A listing that fails costs one request and a warning in the log
(`variation prices unavailable`) and the shop's variations stay unpriced, as before.

**Rows that move.** Re-parsing one live fetch of six shops moves 46 products in
`kavaloka` 17, `prazirnagrain` 11, `frisnakava` 10, `naturpark12` 5 and
`longberry` 3 to the option nearest 250 g (`seriouscoffee` stores the same row as
before). Per kilogram, 7 go up, 33 go down and 6 keep their figure; for example
`kavaloka/9059` goes from 83 Kč per 100 g (830 Kč/kg) to 208 Kč per 250 g (832 Kč/kg)
and `frisnakava/2427` from 8.00 EUR per 100 g (80 EUR/kg) to 19.90 EUR per 250 g
(79.60 EUR/kg). The other shops were not re-parsed and may move rows of their own.

The next crawl starts a new price-history point for each moved product. The jump
is recorded, not reset, and not flagged, as in note 172: nothing on the site reads
price history yet, and a query that reads `price_history` across the crawl day
sees every one of these products step once.

What to check after the next crawl of the shops, from the directory compose reads
its configuration from. It returns no rows:

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

This is note 172's check, unchanged; it was not run again for this note. A row it
lists carries a price and a weight that no single option states. `seriouscoffee/3532`
reads 10.90 EUR and 250 g, and its variants 10.90 EUR / 250 g and 27.90 EUR / 1000 g.

## Rolling back

Check the previous commit out in `/opt/coffee-aggregator` and rebuild. Nothing in
the schema changed. The older code stores no variation price again at the next
crawl, so the moved products return to the range minimum and the price history
steps once more.
