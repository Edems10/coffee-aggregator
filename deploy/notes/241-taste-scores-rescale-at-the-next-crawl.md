# 0.13.3 rescales taste scores stated out of another number — rows change at the next crawl

`body`, `bitterness`, `acidity` and `sweetness` stated as `a/b` are now stored as
`a * 5 / b`, rounded half up, so `5/10` is 3 and `3/3` is 5; a decimal `a` such as
`1,5/5` is no longer cut to 1. Run `update.sh` as the user that owns
`/opt/coffee-aggregator`, **not with `sudo`**: under `sudo` the pull fails because
root has no GitHub key (see `deploy/README.md`, *Updating*). There is no migration
and no backfill, and nothing else to run.

**No stored row changes until its next crawl.** A scoring fix reaches a coffee
when the crawl upserts it. Delisted rows are never crawled again and keep the old
score. On the 2026-10-17 crawl 79 stored scores changed, at 75 coffees: 74 at
`nejkafe` and 1 at `penerini`.

What to check after the next crawl, from the directory compose reads its
configuration from. Each query lists coffees still holding the old, wrongly scaled
score, so each should return no rows once both shops have crawled. A shop that
failed keeps its old scores until its next good crawl.

    cd /opt/coffee-aggregator/deploy
    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT site, external_id, raw_attributes->>'ACIDITA' AS stated, acidity
         FROM coffee
         WHERE site = 'penerini' AND delisted_at IS NULL
           AND raw_attributes->>'ACIDITA' = '1/3' AND acidity IS DISTINCT FROM 2"

    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT site, external_id, raw_attributes->>'SLADKOST' AS stated, sweetness
         FROM coffee
         WHERE site = 'nejkafe' AND delisted_at IS NULL
           AND raw_attributes->>'SLADKOST' = '5/10' AND sweetness IS DISTINCT FROM 3"

The first expects `1/3` to be stored as 2 and the second `5/10` as 3. A row coming
back means that coffee has not been crawled since the deploy.

## Rolling back

The code is rolled back by the previous commit checked out in
`/opt/coffee-aggregator` and rebuilt. No schema changed. Rows crawled on 0.13.3
keep the rescaled scores until the next crawl on the older code rewrites them, so
a rollback followed by a crawl restores the old, wrongly scaled values.
