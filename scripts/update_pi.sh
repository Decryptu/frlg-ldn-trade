#!/usr/bin/env bash
# Fast-forward a Pi checkout from its local bare deployment remote.  This
# intentionally refuses any tracked or untracked working-tree changes.
set -euo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
BRANCH=deploy

usage() {
    printf 'Usage: scripts/update_pi.sh [--branch BRANCH]\n'
}

while (($#)); do
    case "$1" in
        --branch)
            [[ $# -ge 2 ]] || { usage >&2; exit 2; }
            BRANCH=$2
            shift
            ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [[ -n $(git -C "$PROJECT_ROOT" status --porcelain --untracked-files=all) ]]; then
    printf 'Refusing to update: the Pi checkout has changes. Commit/stash/remove them first.\n' >&2
    exit 1
fi
if ! git -C "$PROJECT_ROOT" remote get-url origin >/dev/null 2>&1; then
    printf 'Refusing to update: this checkout has no deployment origin remote.\n' >&2
    exit 1
fi
if [[ $(git -C "$PROJECT_ROOT" branch --show-current) != "$BRANCH" ]]; then
    printf 'Refusing to update: checkout is not on deployment branch %s.\n' "$BRANCH" >&2
    exit 1
fi

OLD_HEAD=$(git -C "$PROJECT_ROOT" rev-parse HEAD)
git -C "$PROJECT_ROOT" fetch origin "$BRANCH"
git -C "$PROJECT_ROOT" merge --ff-only FETCH_HEAD
NEW_HEAD=$(git -C "$PROJECT_ROOT" rev-parse HEAD)

if ! git -C "$PROJECT_ROOT" diff --quiet "$OLD_HEAD" "$NEW_HEAD" -- \
        requirements.txt requirements-dev.txt vendor/LDN; then
    # A code deployment may refresh the virtual environment but must not run
    # apt or alter NetworkManager configuration implicitly.
    "$PROJECT_ROOT/scripts/setup_pi.sh" --no-apt --no-networkmanager
fi
printf 'Pi checkout is now at %s\n' "$NEW_HEAD"
