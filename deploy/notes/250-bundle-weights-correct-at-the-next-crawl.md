# 0.14.3 stores a bundle option's total weight — corrected at the next crawl

0.14.3 reads an option such as `3x 1kg` or `500g+500g` as the weight the price
buys. A re-parse of the cached Shoptet pages on 2026-10-22 moved 65 variants in
7 shops, and a live crawl of the other platforms moved 10 variants in 2 shops.
Run `update.sh` as the user that owns `/opt/coffee-aggregator`, **not with
`sudo`**: the pull fails under `sudo` because root has no GitHub key (see
`deploy/README.md`, *Updating*). There is nothing else to run, and no migration.

**No row changes until the shop's next crawl.** A parsing fix rewrites nothing
already stored; the crawl's upsert writes the corrected weights and per-kilogram
prices. Delisted rows are never crawled again and keep what they have.

The next crawl starts a new price-history point for the 7 products whose
`weight_g` changes (`ambere` 6, `lighthousecoffee` 1). Their per-kilogram price
falls to a half or a quarter of what is stored (`ambere/153` 1 458 to 729 Kč,
`lighthousecoffee/480` 167.20 to 41.80 Kč); the fall is recorded, not reset.
Seventeen Shoptet variants and two WooCommerce ones whose total exceeds 5 000 g
(`mohaji` `6x 1kg`, `melodyroastery` `20x 500g`, `longberry` `10x1kg`) store no
weight afterwards, where they stored one bag's.

What to check after the next crawl of the affected shops, from the directory
compose reads its configuration from:

    cd /opt/coffee-aggregator/deploy
    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT c.site, v.label, v.weight_g
         FROM coffee c JOIN coffee_variant v
           ON v.site = c.site AND v.external_id = c.external_id
         WHERE c.site IN ('ambere', 'ciernaperla', 'coffeespot', 'johnnycoffee',
                          'lighthousecoffee', 'longberry', 'melodyroastery',
                          'mohaji', 'zhanecafe')
           AND c.delisted_at IS NULL
           AND v.label ~* '[0-9] *(kg|g)? *[x+] *[0-9]'
         ORDER BY c.site, v.label"

Every `3x 1kg` row reads 3000, every `2x 250g` row 500 and every `500g+500g` row
1000; a `6x 1kg`, `20x 500g` or `10x1kg` row reads NULL. Before the fix each of
them read one bag's weight. `ciernaperla`'s `1x100g ARABIKA Prémiová rada,
2x100g ARABIKA komoditná` stays 100, because one label naming two different
packs is not read as a sum.

## Rolling back

Check the previous commit out in `/opt/coffee-aggregator` and rebuild. Nothing
in the schema changed. The older code stores one bag's weight for these options
again at the next crawl of the shops.
