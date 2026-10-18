# Create `/var/lib/coffee-aggregator` before the next deploy

`update.sh` now prints the deploy notes before it builds, and it works out which
ones are new from the commit the last successful run finished with. That commit
is kept in `/var/lib/coffee-aggregator/deployed`, a directory the deploy user
must be able to write and `/var/lib` does not let it create for itself.

Run once, as root, on the server, replacing `<deploy-user>` with the login that
owns `/opt/coffee-aggregator`:

    sudo install -d -o <deploy-user> -m 755 /var/lib/coffee-aggregator

Until it exists nothing fails: every deploy prints every note in the checkout,
including the ones already done, and says why on stderr —

    update: /var/lib/coffee-aggregator cannot be created or written by <deploy-user>; nothing will be recorded

Once it exists, the first run records the commit it deployed, and the run after
that prints only the notes added since. Nothing to check afterwards beyond the
file appearing:

    ls -l /var/lib/coffee-aggregator/deployed
