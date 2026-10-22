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

**Extra requests.** A crawl makes about one more request per 100 variations of a
shop's multi-variation products, to
`/wp-json/wc/store/v1/products?type=variation&per_page=100&include=…`, through the
same polite fetcher: robots.txt, the host's delay and the cache all apply.
Measured on 2026-10-22 against 44 of the 47 Store API configs it is 56 requests
per daily crawl for 2 964 variations with the walk batched whole, and 59 for the
windows the code uses (replayed offline over the same saved products; `bonte` and
`prazirnagrain` need 6 each, `kavaloka` 5, `aurelica`, `caffe4u` and `kmen` 2, the
rest 1 and `lubezna` and `networkcafe` none). `goodtimes` and `spiritcoffee` are
switched off and `moritzcafe` was not measured. A shop that states a crawl-delay
pays it per request: `caffeoro` states 30 s, so its one request adds about 30 s;
the others use the 1 s default. A listing that fails costs one request and a
warning in the log (`variation prices unavailable`), and the shop's variations
stay unpriced.

**Discovery now holds products back.** A shop's products are yielded in windows of
up to 100 variations instead of one by one, so a shop is walked up to a window
ahead of what the pipeline has consumed. A `--limit` run of a shop that lists fewer
than 100 variations walks all of its listing pages (a few requests) and makes one
variations request before it yields the first product; a larger shop stops within
a window. A `--deadline` that expires during that walk is noticed when the window is
yielded, not mid-walk; delisting stays blocked either way, so no row is lost.

**Rows that move.** Re-parsing the 878 saved Store API products of the 44 shops
with and without the variation prices moves 86 products in 9 shops to the option
nearest 250 g: `bonte` 36, `kavaloka` 17, `prazirnagrain` 11, `frisnakava` 10,
`naturpark12` 5, `longberry` 3, `kmen` 2, `caffe4u` 1 and `ciernaperla` 1;
`seriouscoffee` stores the same row as before. Two `twohands` rows (`2355`, `2479`)
also lose an `original_price` of 16.01 EUR beside a price of 16.00, so 88 rows in 10
shops change something. Per kilogram of the 86, 8 go up, 69 go down, 6 keep their
figure and 3 have none before or after. Examples: `kavaloka/9059` goes from 83 Kč
per 100 g (830 Kč/kg) to 208 Kč per 250 g (832 Kč/kg), `frisnakava/2427` from 8.00
EUR per 100 g (80 EUR/kg) to 19.90 EUR per 250 g (79.60 EUR/kg) and `bonte/9992`
from 7.90 EUR per 125 g (63.20 EUR/kg) to 14.90 EUR per 250 g (59.60 EUR/kg). The 3
shops not measured may move rows of their own. A product whose variation the shop
prices at `"0"` is left as it was (`bonte/7956` and `bonte/4749` keep 7.90 EUR for
125 g).

The next crawl starts a new price-history point for each moved product. The jump
is recorded, not reset, and not flagged, as in note 172: nothing on the site reads
price history yet, and a query that reads `price_history` across the crawl day
sees every one of these products step once.

What to check after the next crawl of the shops, from the directory compose reads
its configuration from. This one shows the change worked: `seriouscoffee/3532`
reads 10.90 EUR, 250 g, EUR and 2 priced variants (10.90 EUR / 250 g and
27.90 EUR / 1000 g), and the second lists, per shop, how many products have priced
variants; on the measured catalogue `bonte` reads 36, `kavaloka` 17, `prazirnagrain`
11 and `frisnakava` 11:

    cd /opt/coffee-aggregator/deploy
    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT c.site, c.external_id, c.price, c.weight_g, c.currency,
                (SELECT count(*) FROM coffee_variant v
                 WHERE v.site = c.site AND v.external_id = c.external_id
                   AND v.price IS NOT NULL) AS priced_variants
         FROM coffee c
         WHERE c.site = 'seriouscoffee' AND c.external_id = '3532'"
    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT c.site, count(*) AS products_with_priced_variants
         FROM coffee c
         WHERE c.delisted_at IS NULL
           AND c.site IN ('bonte', 'kavaloka', 'prazirnagrain', 'frisnakava')
           AND (SELECT count(*) FROM coffee_variant v
                WHERE v.site = c.site AND v.external_id = c.external_id
                  AND v.price IS NOT NULL) > 1
         GROUP BY c.site ORDER BY c.site"

A shop whose line is missing or reads 0 had its variations listing fail; the crawl's
log says `variation prices unavailable`. The negative check is note 172's, unchanged:
it returns no rows when every stored price and weight is one option's. Neither query
was run for this note.

## Rolling back

Check the previous commit out in `/opt/coffee-aggregator` and rebuild. Nothing in
the schema changed. The older code stores no variation price again at the next
crawl, so the moved products return to the range minimum and the price history
steps once more.
