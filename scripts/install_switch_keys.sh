#!/usr/bin/env bash
# Install Nintendo Switch prod.keys without relying on sudo's idea of $HOME.
#
# This script deliberately does not validate, display, or log key contents.
set -euo pipefail

program_name=${0##*/}

usage() {
    cat <<EOF
Usage:
  $program_name --source ABSOLUTE_PATH [--destination ABSOLUTE_PATH]
  $program_name --stdin [--destination ABSOLUTE_PATH]

Install Switch prod.keys for the invoking user.  When started through sudo,
the original sudo user is the installation owner; root's home is never used
implicitly.  The default destination is that user's ~/.switch/prod.keys.

Exactly one source is required:
  --source PATH       Read an existing regular file (must be an absolute path).
  --stdin             Read the file from standard input.
  --destination PATH  Absolute destination below the install user's home.
  --help              Show this help.

The target directory is mode 0700 and the key file is mode 0600.  Existing
identical files are left in place.  Key material is never printed.
EOF
}

die() {
    printf '%s: %s\n' "$program_name" "$*" >&2
    exit 2
}

# Never read a user-supplied source file as root. Under sudo, restart before
# parsing so the original argument vector is preserved. stdin is inherited
# without buffering or printing its contents.
if ((EUID == 0)) && [[ -n ${SUDO_USER:-} && $SUDO_USER != root ]]; then
    command -v runuser >/dev/null || die 'runuser is required when invoking through sudo'
    exec runuser -u "$SUDO_USER" -- env -u SUDO_USER "$0" "$@"
fi

source_path=''
read_stdin=false
destination=''

while (($#)); do
    case $1 in
        --source)
            (($# >= 2)) || die '--source needs a path'
            source_path=$2
            shift 2
            ;;
        --stdin)
            read_stdin=true
            shift
            ;;
        --destination)
            (($# >= 2)) || die '--destination needs a path'
            destination=$2
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
done

[[ -n $source_path || $read_stdin == true ]] || die 'choose --source or --stdin'
[[ -z $source_path || $read_stdin == false ]] || die 'choose only one source'

install_user=$(id -un)

install_home=$(getent passwd "$install_user" | cut -d: -f6) || \
    die "cannot determine home for $install_user"
[[ -n $install_home && $install_home == /* ]] || die "cannot determine home for $install_user"
install_uid=$(id -u "$install_user")
install_gid=$(id -g "$install_user")

if [[ -z $destination ]]; then
    destination=$install_home/.switch/prod.keys
fi
[[ $destination == /* ]] || die '--destination must be an absolute path'
case $destination in
    "$install_home"/*) ;;
    *) die '--destination must be below the install user home directory' ;;
esac

target_dir=$(dirname "$destination")
[[ $target_dir != "$install_home" ]] || die '--destination must be in a directory below the home directory'

if [[ -e $target_dir && ! -d $target_dir ]]; then
    die "destination parent is not a directory: $target_dir"
fi
if [[ -L $target_dir ]]; then
    die "destination parent must not be a symlink: $target_dir"
fi

umask 077
mkdir -p "$target_dir"
chmod 0700 "$target_dir"
if ((EUID == 0)); then
    chown "$install_uid:$install_gid" "$target_dir"
fi

if [[ -e $destination && ! -f $destination ]]; then
    die "destination is not a regular file: $destination"
fi
[[ ! -L $destination ]] || die "destination must not be a symlink: $destination"

temporary=$(mktemp "$target_dir/.prod.keys.XXXXXX")
cleanup() {
    rm -f -- "$temporary"
}
trap cleanup EXIT HUP INT TERM
chmod 0600 "$temporary"

if [[ -n $source_path ]]; then
    [[ $source_path == /* ]] || die '--source must be an absolute path'
    [[ -f $source_path && ! -L $source_path && -r $source_path ]] || \
        die 'source must be a readable, non-symlink regular file'
    cp -- "$source_path" "$temporary"
else
    # dd does not echo data and copes with a stream that has no trailing newline.
    dd of="$temporary" bs=65536 status=none
fi

[[ -s $temporary ]] || die 'refusing to install an empty key file'
chmod 0600 "$temporary"
if ((EUID == 0)); then
    chown "$install_uid:$install_gid" "$temporary"
fi

if [[ -f $destination ]] && cmp -s -- "$temporary" "$destination"; then
    chmod 0600 "$destination"
    if ((EUID == 0)); then
        chown "$install_uid:$install_gid" "$destination"
    fi
    printf 'Switch keys already installed at %s (owner %s, mode 0600).\n' \
        "$destination" "$install_user"
    exit 0
fi

mv -f -- "$temporary" "$destination"
trap - EXIT HUP INT TERM
chmod 0600 "$destination"
if ((EUID == 0)); then
    chown "$install_uid:$install_gid" "$destination"
fi
printf 'Installed Switch keys at %s (owner %s, mode 0600).\n' \
    "$destination" "$install_user"
