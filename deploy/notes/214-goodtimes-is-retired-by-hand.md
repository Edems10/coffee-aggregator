# Delist the three `goodtimes` coffees after this deploy

`goodtimes` is switched off in this release, so the crawl stops visiting it the
moment the new image runs. That alone changes no stored row: its three coffees,
last seen on 2026-10-14, stay in the catalogue and stay on the site until
somebody delists them. The crawl cannot do it — a run that discovers nothing
delists nothing, on purpose — so this is the one step that has to be typed.

**Run it after the deploy, not before.** `retire` refuses a shop whose config
does not say it is disabled, and that line only exists in the image this deploy
builds.

## 1. See what it would do

    sudo docker compose --env-file /etc/coffee-aggregator/env run --rm \
        crawler retire --site goodtimes

It writes nothing without `--yes`. Expect three lines and a count:

    1138	Brazil Doce Diamantina	https://goodtimes.coffee/produkt/...
    ...
    goodtimes is disabled (the WordPress install is gone; ...) and has 3 listed coffee(s); re-run with --yes to delist them

**If the count is not 3, stop and say so.** Three is what the catalogue held on
2026-10-18; a different number means something changed since and the decision
needs re-reading. If it refuses with *"does not say it is disabled"*, the
container is running the old image — rebuild before anything else.

## 2. Delist them

    sudo docker compose --env-file /etc/coffee-aggregator/env run --rm \
        crawler retire --site goodtimes --yes

    delisted 3 coffee(s) of goodtimes and queued one event each; run publish to send them

The stamp and the three events are written in one transaction, so either both
landed or neither did. `coffee-publisher` runs continuously and drains the
outbox by itself; nothing further is needed unless it is down.

## 3. Check the coffees have actually left — the site, not just the database

The database half is the easy half, and it is not the half that matters:

    sudo docker compose --env-file /etc/coffee-aggregator/env run --rm \
        crawler retire --site goodtimes

Expect no product lines and `has 0 listed coffee(s); nothing to delist`.

Then check the three events reached the broker rather than sitting unpublished:

    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -U coffee -d coffee -c \
        "SELECT count(*) FILTER (WHERE published_at IS NULL) AS waiting,
                count(*) AS total
         FROM outbox WHERE subject LIKE 'coffee.v1.catalogue.goodtimes.%'"

`waiting` must be 0. If it is not, the publisher is down —
`docker compose logs publisher` — and the coffees are still on the site.

Finally, look at the site itself, which is the only check that answers the
question that was asked. Search the public catalogue for **Good Times Coffee
Roasters**; none of its three coffees should come back. A coffee still showing
there after `waiting` reached 0 is a consumer that is not applying
`delisted_at`, and that is a `coffee-api` bug, not a step missed here.

## Reversing it

Nothing was deleted. `delisted_at` is a stamp, and the upsert clears it, so if
the shop ever comes back the repair is to remove the `disabled` line from its
config and crawl it — not to edit a row.
