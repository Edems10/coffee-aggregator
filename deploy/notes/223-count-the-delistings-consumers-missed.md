# Count the delistings the consumers missed before 0.9.1

Until 0.9.1 every delisting event — from a crawl that no longer saw a coffee,
and from `retire` — carried the same `observed_at` as the last state it
replaced. `coffee-api` and `coffee-cupper` keep an event only when it is
strictly newer than what they hold, so both threw every one of them away,
silently. The coffees are delisted in this database and still listed on the
site.

**Deploying this release fixes future delistings only.** Nothing already
delisted is sent again by the deploy. What corrects the lost ones is a re-seed:
`republish --all` now re-sends every coffee ever seen, delisted ones as
delisted, and a consumer still holding one as listed accepts the correction.

But this release still publishes on the **v1** stream (`CATALOGUE`); the
contract pin moves to v2 only in #169. Both consumers on `main` read only
`CATALOGUE_V2`, so a re-seed now would not reach them. The re-send that does is
the `republish --all` at the #169 cutover, which #169's deploy note carries.

So for this release: **count the damage now (steps 1 and 2) and record it on
#223, so the cutover's re-seed has a number to be checked against. Do not
republish (step 3) unless a consumer is still bound to the v1 stream.**

## 1. Export the delisted keys from the aggregator

On the aggregator's server:

    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -U coffee -d coffee -c \
        "\copy (SELECT site, external_id FROM coffee
                WHERE delisted_at IS NOT NULL ORDER BY site, external_id) to stdout" \
        > delisted-keys.tsv
    wc -l delisted-keys.tsv

`wc -l` is how many coffees the aggregator holds as delisted.

## 2. Count those keys that coffee-api still lists

Copy `delisted-keys.tsv` to wherever `psql` can reach coffee-api's database,
replace `<COFFEE_API_DATABASE_URL>` with its connection string, and run from
the directory holding the file:

    psql "<COFFEE_API_DATABASE_URL>" \
        -c "CREATE TEMP TABLE delisted_keys (site text, external_id text)" \
        -c "\copy delisted_keys from 'delisted-keys.tsv'" \
        -c "SELECT count(*) AS still_listed
            FROM coffee c JOIN delisted_keys k USING (site, external_id)
            WHERE c.delisted_at IS NULL"

The `-c` options run in one session, so the temporary table lives exactly as
long as the count needs it. `still_listed` is the size of the damage: coffees
the aggregator delisted that the site is still selling. Record it on #223.

A `still_listed` of 0 with a non-empty export means the consumer was never sent
those coffees at all, or already holds them as delisted — say which before
going further, because it contradicts what #223 found in the code.

## 3. Re-send — only if a consumer still reads the v1 stream

Each consumer logs which stream it is bound to when it starts:

    bound to <stream>/<durable> as a pull consumer

If that says `CATALOGUE_V2/…`, stop here: the re-send happens at the #169
cutover. If it says `CATALOGUE/…`, a re-seed now does reach that consumer, and
it is the step in `deploy/README.md`:

    sudo docker compose --env-file /etc/coffee-aggregator/env run --rm \
        crawler republish --all

Whenever it runs, the stream and each consumer's store grow by the delisted
count — the `wc -l` of step 1 — because a re-seed now carries every coffee ever
seen, not only the listed ones. Afterwards, step 2 run again should give a
`still_listed` of 0 for every consumer it reached.
