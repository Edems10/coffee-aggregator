# 0.12.0 adds `pack_group_key` — it fills on the next crawl and nothing publishes it yet

Migration `0.12.0_pack_group_key` adds two nullable columns to `coffee`,
`pack_group_key` and `pack_group_key_source`. Run `update.sh` as the user that
owns `/opt/coffee-aggregator`, **not with `sudo`**: it runs the migration itself,
and under `sudo` the pull fails because root has no GitHub key (see
`deploy/README.md`, *Updating*). There is nothing else to run.

**No row has a key until its next crawl.** A key needs Python, so the migration
backfills nothing: every row starts NULL and takes its key when the crawl
upserts it. Delisted rows are never crawled again and stay NULL, which is
harmless. A rule change later reaches rows the same way, at their next crawl.

**Nothing reaches consumers.** The key is stored and not published: the
catalogue event does not carry it, and the publish is a later pull request
(#225) that waits for the `coffee-contracts` release. Deploying this changes
nothing a consumer can see.

What to check after the next crawl, from the directory compose reads its
configuration from:

    cd /opt/coffee-aggregator/deploy
    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT count(*) FILTER (WHERE pack_group_key IS NULL) AS without_key,
                count(*) AS listed
         FROM coffee WHERE delisted_at IS NULL"

`without_key` should fall to the few coffees whose name and URL give nothing to
build a key from, and to the shops that did not finish the crawl. A shop that
failed keeps the NULLs it had until its next good crawl.

## Rolling back

The code is rolled back by the previous commit checked out in
`/opt/coffee-aggregator` and rebuilt. The two columns can stay: nothing reads
them, and the older code's INSERT does not name them.
