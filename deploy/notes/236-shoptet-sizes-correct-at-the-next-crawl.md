# 0.14.1 reads a Shoptet variant's size from its key — corrected at the next crawl

0.14.1 names each variant of a per-parameter Shoptet product by the parameter
values its key states and takes its weight from the size value. A crawl of the
96 live Shoptet shops on 2026-10-21 moved 2 106 variants in 20 shops (1 878
gained a weight, 228 changed one, none lost one) and 69 products' per-kilogram
price. Run `update.sh` as the user that owns `/opt/coffee-aggregator`, **not with
`sudo`**: the pull fails under `sudo` because root has no GitHub key (see
`deploy/README.md`, *Updating*). There is nothing else to run, and no migration.

**No row changes until the shop's next crawl.** A parsing fix rewrites nothing
already stored; the crawl's upsert writes the corrected weights, labels and
per-kilogram prices. Delisted rows are never crawled again and keep what they
have.

The next crawl starts a new price-history point for the 52 products whose
`weight_g` changes. The 12 `botacoffee` products that go from 250 g to the 70 g
pack keep their price, so their per-kilogram price jumps about 3.6 times (348
to 1 243); the jump is recorded, not reset. #172, which picks the option
nearest 250 g, moves these rows again.

What to check after the next crawl of the affected shops, from the directory
compose reads its configuration from:

    cd /opt/coffee-aggregator/deploy
    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT c.site, count(*) AS variants,
                count(*) FILTER (WHERE v.weight_g IS NULL) AS without_weight
         FROM coffee c JOIN coffee_variant v
           ON v.site = c.site AND v.external_id = c.external_id
         WHERE c.site IN ('ambere', 'analogprazirna', 'bartcoffee', 'belkocoffee',
                          'botacoffee', 'caffedelizia', 'coffeespot', 'daliacoffee',
                          'dibosco', 'donfranko', 'frolikovakava', 'gmcoffee',
                          'johnnycoffee', 'jungleroastery', 'kubaprazikavu',
                          'mrcoffee', 'namleto', 'orientcoffee', 'pepecoffee',
                          'praziarenvelkezaluzie')
           AND c.delisted_at IS NULL
         GROUP BY c.site ORDER BY c.site"

`without_weight` should be 0 at every shop except `coffeespot` (6),
`johnnycoffee` (4) and `praziarenvelkezaluzie` (7), whose pages state no size for
those variants. Before the fix it read 1 895 across the twenty shops.

## Rolling back

Check the previous commit out in `/opt/coffee-aggregator` and rebuild. Nothing
in the schema changed. The older code stores the guessed weights and the sku as
the label again at the next crawl of the shops.
