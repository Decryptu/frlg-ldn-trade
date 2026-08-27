#!/usr/bin/env bash
# Deploy one committed desktop revision to a Pi through SSH and a Pi-local bare
# Git repository.  No GitHub connection, rsync, virtual environment, keys, or
# ignored runtime/reference data are involved.
set -euo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
SSH_HOST=${PI_SSH_HOST:-}
SSH_USER=${PI_SSH_USER:-}
PI_PATH=${PI_PROJECT_PATH:-}
PI_REPO=${PI_BARE_REPO:-}
BRANCH=deploy
RUN_TESTS=true
INSTALL_MT7601U_AP=false

usage() {
    cat <<'USAGE'
Usage: scripts/deploy_pi.sh --host SSH_ALIAS [options]

Options:
  --host HOST       SSH config alias or tunnel hostname (or PI_SSH_HOST)
  --user USER       remote user, unless the SSH alias already sets one
  --path PATH       absolute Pi checkout path (default: /home/USER/frlg-ldn-trade)
  --repo PATH       absolute Pi bare-repository path (default: /home/USER/repos/frlg-ldn-trade.git)
  --branch NAME     deployment branch (default: deploy)
  --install-mt7601u-ap
                    after deployment, explicitly install the custom MT7601U
                    AP-mode DKMS module on the Pi (uses sudo and APT)
  --skip-tests      do not run the local static configuration tests

The local worktree must be entirely clean. The remote checkout only performs a
fast-forward merge from the Pi-local bare repository; it is never force-reset.
USAGE
}

while (($#)); do
    case "$1" in
        --host) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; SSH_HOST=$2; shift ;;
        --user) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; SSH_USER=$2; shift ;;
        --path) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; PI_PATH=$2; shift ;;
        --repo) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; PI_REPO=$2; shift ;;
        --branch) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; BRANCH=$2; shift ;;
        --install-mt7601u-ap) INSTALL_MT7601U_AP=true ;;
        --skip-tests) RUN_TESTS=false ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

[[ -n "$SSH_HOST" ]] || { printf '--host (or PI_SSH_HOST) is required.\n' >&2; exit 2; }
SSH_TARGET=$SSH_HOST
if [[ -n "$SSH_USER" ]]; then
    SSH_TARGET="$SSH_USER@$SSH_HOST"
fi
if [[ -z "$PI_PATH" || -z "$PI_REPO" ]]; then
    [[ -n "$SSH_USER" ]] || {
        printf '--path and --repo are required unless --user provides their safe defaults.\n' >&2
        exit 2
    }
    PI_PATH=${PI_PATH:-"/home/$SSH_USER/frlg-ldn-trade"}
    PI_REPO=${PI_REPO:-"/home/$SSH_USER/repos/frlg-ldn-trade.git"}
fi
[[ "$PI_PATH" == /* && "$PI_REPO" == /* ]] || {
    printf '--path and --repo must be absolute remote paths.\n' >&2; exit 2;
}

if [[ -n $(git -C "$PROJECT_ROOT" status --porcelain --untracked-files=all) ]]; then
    printf 'Refusing to deploy a dirty worktree. Commit, stash, or remove local changes first.\n' >&2
    exit 1
fi
if [[ "$RUN_TESTS" == true ]]; then
    TEST_PYTHON=${PYTHON:-"$PROJECT_ROOT/.venv/bin/python"}
    [[ -x "$TEST_PYTHON" ]] || TEST_PYTHON=python3
    (
        cd "$PROJECT_ROOT"
        PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
            "$TEST_PYTHON" tests/test_host_file_config.py
        PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
            "$TEST_PYTHON" tests/test_documentation.py
        PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
            "$TEST_PYTHON" tests/test_pi_scripts.py
        PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
            "$TEST_PYTHON" tests/test_switch_key_installer.py
    )
fi

# Set up only a bare repository.  The working checkout is created after the
# committed branch has been pushed, so a Pi never receives arbitrary desktop
# files through SSH.
ssh "$SSH_TARGET" bash -s -- "$PI_REPO" <<'REMOTE_SETUP'
set -euo pipefail
repo=$1
if [[ -e "$repo" && ! -d "$repo" ]]; then
    printf 'Remote bare-repo path exists but is not a directory: %s\n' "$repo" >&2
    exit 1
fi
if [[ ! -d "$repo" ]]; then
    mkdir -p "$(dirname "$repo")"
    git init --bare "$repo"
fi
git -C "$repo" rev-parse --is-bare-repository | grep -qx true
REMOTE_SETUP

git -C "$PROJECT_ROOT" push "$SSH_TARGET:$PI_REPO" "HEAD:refs/heads/$BRANCH"

ssh "$SSH_TARGET" bash -s -- "$PI_REPO" "$PI_PATH" "$BRANCH" <<'REMOTE_UPDATE'
set -euo pipefail
repo=$1
worktree=$2
branch=$3
if [[ ! -e "$worktree/.git" ]]; then
    if [[ -e "$worktree" ]]; then
        printf 'Remote checkout path exists but is not a Git checkout: %s\n' "$worktree" >&2
        exit 1
    fi
    mkdir -p "$(dirname "$worktree")"
    git clone --branch "$branch" "$repo" "$worktree"
fi
"$worktree/scripts/update_pi.sh" --branch "$branch"
REMOTE_UPDATE

if [[ "$INSTALL_MT7601U_AP" == true ]]; then
    # Allocate a TTY so the remote sudo prompt remains usable.  This is kept
    # opt-in: ordinary code deployment must not alter kernel modules or APT.
    ssh -t "$SSH_TARGET" \
        "cd '$PI_PATH' && ./scripts/setup_pi.sh --install-mt7601u-ap --no-networkmanager"
fi

printf 'Deployed %s to %s:%s\n' \
    "$(git -C "$PROJECT_ROOT" rev-parse --short HEAD)" "$SSH_TARGET" "$PI_PATH"
printf 'On the Pi, run: %s/scripts/preflight_pi.sh\n' "$PI_PATH"
