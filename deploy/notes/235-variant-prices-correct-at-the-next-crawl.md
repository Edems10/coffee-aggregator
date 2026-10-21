# 0.13.1 corrects 63 variant prices of 34 coffees at `nordbeans` and `angrybeans` — at the next crawl

63 variant prices of 34 coffees at `nordbeans` and `angrybeans` were stored
without VAT, mostly 12 % under what the pages charge (one variant, `angrybeans`
379 at 1 kg, 21 %). 0.13.1 reads them with VAT. Run `update.sh` as the
user that owns `/opt/coffee-aggregator`, **not with `sudo`**: the pull fails
under `sudo` because root has no GitHub key (see `deploy/README.md`,
*Updating*). There is nothing else to run, and no migration.

**No row changes until the shop's next crawl.** A parsing fix rewrites nothing
already stored; the crawl's upsert writes the corrected price. Delisted rows are
never crawled again and keep what they have.

What to check after the next crawl of both shops, from the directory compose
reads its configuration from:

    cd /opt/coffee-aggregator/deploy
    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT c.site, count(*) AS variants,
                round(min(v.price / c.price), 3) AS lowest_ratio,
                round(max(v.price / c.price), 3) AS highest_ratio
         FROM coffee c JOIN coffee_variant v
           ON v.site = c.site AND v.external_id = c.external_id
         WHERE c.site IN ('nordbeans', 'angrybeans')
           AND c.delisted_at IS NULL AND v.weight_g = c.weight_g
           AND c.price > 0 AND v.price IS NOT NULL
         GROUP BY c.site"

Where a variant's weight is the product's weight, its price is the product's, so
both ratios should read `1.000`. Before the fix they read about `0.893`.

## Rolling back

Check the previous commit out in `/opt/coffee-aggregator` and rebuild. Nothing
in the schema changed. The older code writes the prices without VAT again at the
next crawl of the two shops, so a rollback brings the 0.893 ratio back.
