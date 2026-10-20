# 0.13.0 publishes `pack_group_key` — it reaches a consumer at each row's next crawl, not at the deploy

The catalogue event now carries `pack_group_key`, read from the column
0.12.0 added, and the pin moves to coffee-contracts `v3.2.0`. There is no
migration. Run `update.sh` as the user that owns `/opt/coffee-aggregator`,
**not with `sudo`**: under `sudo` the pull fails because root has no GitHub key
(see `deploy/README.md`, *Updating*).

**Nothing is sent at the deploy.** An event is queued when a crawl writes a row,
so a row's key travels at its next crawl after this deploy, and not before. A
delisted row is never crawled again, so it never sends one; it keeps whatever key
its consumer last stored, which is none.

**There is no replay.** `republish --all` does not carry the key. Both consumers
keep an event only when its `observed_at` is strictly newer than the state they
hold, and a re-seed repeats the `observed_at` a listed row already has, so a
consumer that holds the row drops the event. Do not run it to deliver keys.

**There is no deploy-order constraint** between this release and a consumer's move
to coffee-contracts `v3.2.0`. A consumer still on `v3.1.0` does not reject the
field: its schema allows additional properties and its reader drops keys it does
not know, so it simply loses the key. Each row then gets the key at its next crawl
after that consumer has moved to `v3.2.0` and has a column for it. The order of
the two deploys only decides when the keys start to arrive.

## Check that it arrived

On the aggregator, after a crawl, the events are in the outbox with the key. From
`/opt/coffee-aggregator/deploy`:

    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT count(*) FILTER (WHERE payload->>'pack_group_key' IS NOT NULL) AS with_key,
                count(*) AS events
         FROM outbox WHERE created_at > now() - interval '1 day'"

On a consumer, count the non-null keys in its own store. The connection details
and the table are the consumer's, not this repository's, so these are
placeholders; read the password from the environment or a `~/.pgpass`, never from
the command line:

    psql "host=<consumer-db-host> dbname=<consumer-db> user=<consumer-user>" -c \
        "SELECT count(*) FILTER (WHERE pack_group_key IS NOT NULL) AS with_key,
                count(*) AS held
         FROM <coffee-table>"

`with_key` grows as shops are crawled, and reaches the aggregator's own count of
non-null keys among its listed coffees once every shop has crawled once after both
deploys. A coffee whose name and URL give nothing to build a key from stays null,
and so does a shop whose crawl did not finish.

## Rolling back

The code is rolled back by the previous commit checked out in
`/opt/coffee-aggregator` and rebuilt. The field disappears from new events, and
consumers keep the last key they stored. The stored column stays, as it did in
0.12.0, and nothing reads it.
