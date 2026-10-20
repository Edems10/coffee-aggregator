# 0.10.0 moves publishing to the v2 stream — check the consumers, drain, re-seed

From 0.10.0 every event goes to `coffee.v2.catalogue.<site>.<external_id>`,
the stream `CATALOGUE_V2`, and nothing more goes to the v1 stream (`CATALOGUE`).
The database does not change: no migration, no column. Until step 4 runs,
`CATALOGUE_V2` holds nothing from this producer; the site keeps serving the rows
its consumers already store the whole time.

Do the steps in order. The `docker compose` commands run from
`/opt/coffee-aggregator/deploy`, as everywhere else in `deploy/README.md`.

## 1. Check the consumers first — stop here if this fails

coffee-api and coffee-cupper must both be deployed at a version that pins
coffee-contracts `v3.1.0` or later, and bound to `CATALOGUE_V2`. Each logs the
stream it is bound to when it starts:

    bound to <stream>/<durable> as a pull consumer

Read that line in each one's start-up log. **Go on only if both say
`CATALOGUE_V2/…`.** If either says `CATALOGUE/…`, it still reads the v1 stream,
which this deploy stops feeding: do not deploy.

## 2. Stop the crawl and drain the outbox

    sudo systemctl stop coffee-aggregator.timer
    systemctl is-active coffee-aggregator.service

The second command must print `inactive`. If it prints `activating`, a crawl is
running: wait for it to finish and check again.

Then let the publisher send what is queued, re-running this until it prints 0:

    cd /opt/coffee-aggregator/deploy
    sudo docker compose --env-file /etc/coffee-aggregator/env exec -T db \
        psql -v ON_ERROR_STOP=1 -U coffee -d coffee -c \
        "SELECT count(*) FROM outbox WHERE published_at IS NULL"

The outbox stores each row's subject and payload when it is written, and the
publisher sends them verbatim. A row still unpublished at deploy would go out in
the v1 shape, to the v1 subject, after the deploy.

## 3. Deploy

    sudo /opt/coffee-aggregator/deploy/update.sh

## 4. Re-seed the v2 stream

    sudo docker compose --env-file /etc/coffee-aggregator/env run --rm \
        crawler republish --all

This is what fills `CATALOGUE_V2` from the catalogue. Since 0.9.1 the re-seed
includes delisted coffees, so it is also the step that re-sends every delisting
the consumers missed (#223): the stream and each consumer's store grow by the
delisted count — the `wc -l` of step 1 of
`deploy/notes/223-count-the-delistings-consumers-missed.md`.

The re-seed cannot be undone: read "Rolling back" in that note before running
it.

## 5. Verify the missed delistings arrived

Wait for the outbox to drain again (the query of step 2 printing 0), then re-run
step 2 of `deploy/notes/223-count-the-delistings-consumers-missed.md`.
`still_listed` should now be 0. Record the number on #169.

## 6. Restart the timer

    sudo systemctl start coffee-aggregator.timer
    systemctl list-timers coffee-aggregator.timer
