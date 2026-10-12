#!/usr/bin/env bash
# Pull, rebuild, migrate — the three steps a deployment needs, in the one order
# that works.
#
# The rebuild is the step that is easy to forget and silent when forgotten: the
# containers run an image that was built once, so `git pull` on its own changes
# nothing at all and the crawl keeps running yesterday's code.
#
# This script is not a root job. The pull needs the GitHub key of the user that
# owns the checkout, and root has none, so under sudo the first pull fails. The
# one step that needs root is starting the crawl unit, and that alone runs under
# `sudo -n`, which the sudoers line in deploy/README.md allows and nothing else.
set -euo pipefail

REPO="${REPO:-/opt/coffee-aggregator}"
ENV_FILE="${ENV_FILE:-/etc/coffee-aggregator/env}"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO}/deploy/compose.yml}"
crawl=no

usage() {
    cat <<'TXT'
usage: update.sh [--crawl]

  --crawl   start a crawl when the update is done, instead of leaving it to the
            05:00 timer. It runs in the background; follow it with
            journalctl -u coffee-aggregator.service -f
TXT
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --crawl) crawl=yes ;;
        -h | --help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
    shift
done

compose() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

# Starts the crawl unit, as root if this is root, otherwise through `sudo -n`.
# `-n` is what stops this hanging: without it sudo waits for a password on a
# captured stdout that nobody can answer, and the run looks clean. A refusal, or
# a failed start, exits 1 and prints the command to run by hand, because a crawl
# that did not start must never be reported as one that did.
start_crawl() {
    local unit=coffee-aggregator.service
    if [[ $EUID -eq 0 ]]; then
        systemctl start --no-block "$unit" && return 0
    elif sudo -n systemctl start --no-block "$unit"; then
        return 0
    fi
    echo "update: the crawl did not start: sudo -n was refused or systemctl failed" >&2
    echo "update: the sudoers line is in deploy/README.md; to start it by hand, run:" >&2
    echo "update:   sudo systemctl start --no-block ${unit}" >&2
    exit 1
}

# A server that was edited by hand is a server whose next pull conflicts, and
# the middle of a deployment is the worst moment to find that out.
if [[ -n "$(git -C "$REPO" status --porcelain)" ]]; then
    echo "update: ${REPO} has uncommitted changes; nothing was pulled" >&2
    git -C "$REPO" status --short >&2
    exit 1
fi

before="$(git -C "$REPO" rev-parse HEAD)"
git -C "$REPO" fetch --quiet origin
target="$(git -C "$REPO" rev-parse '@{u}')"

if [[ "$before" == "$target" ]]; then
    echo "update: already at $(git -C "$REPO" log --oneline -1)"
else
    # --ff-only, so a server that somehow diverged stops here rather than
    # producing a merge commit nobody will ever review.
    git -C "$REPO" merge --ff-only --quiet "$target"
    echo "update: pulled $(git -C "$REPO" rev-list --count "${before}..${target}") commit(s)"
    git -C "$REPO" log --oneline --no-decorate "${before}..${target}"
fi

# Unconditional: when nothing was pulled this is a few cached seconds, and when
# something was it is the whole point. The database and the table browser come
# up too, so a change to compose.yml itself takes effect.
echo "update: building the crawler image"
compose --profile crawler build
compose up -d

# Idempotent: prints what it applied, or that there was nothing to apply. It has
# to run before any crawl — a sink writing a column the schema does not have yet
# fails the whole run.
echo "update: applying migrations"
compose run --rm crawler init-db

if [[ "$crawl" == yes ]]; then
    echo "update: starting a crawl in the background"
    start_crawl
    echo "update: follow it with  journalctl -u coffee-aggregator.service -f"
else
    echo "update: done; the 05:00 timer will pick this up"
fi
