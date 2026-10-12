# Add the sudoers line before deploying 0.3.3

`update.sh --crawl` now starts the crawl through `sudo -n`. Without this line on the
server the deploy still completes, then the script exits 1 saying the crawl did not start.

Run once, as root, on the server, replacing `<deploy-user>` with the login that owns
`/opt/coffee-aggregator`:

    sudo tee /etc/sudoers.d/coffee-aggregator >/dev/null <<'SUDO'
    <deploy-user> ALL=(root) NOPASSWD: /usr/bin/systemctl start --no-block coffee-aggregator.service
    SUDO
    sudo chmod 440 /etc/sudoers.d/coffee-aggregator
    sudo visudo -cf /etc/sudoers.d/coffee-aggregator

`visudo -cf` must print `parsed OK`. Then, as the deploy user, confirm the line works:

    sudo -n -l /usr/bin/systemctl start --no-block coffee-aggregator.service

It must print the command, not a password prompt. Then run `update.sh --crawl` as the
deploy user, without `sudo`.
