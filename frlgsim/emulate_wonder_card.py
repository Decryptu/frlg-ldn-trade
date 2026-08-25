"""One-shot helper to try a Wonder Card in the emulator:

    python3 -m frlgsim.emulate_wonder_card --gift worlds-xp

Takes a gift from the Mystery Gift registry (`gift_registry.GIFT_REGISTRY`),
exports it as the WonderCard/Script `.bin` pair comradesean's
`pokemon-gen3-mysterygift-tool` reads, drops the pair into the injector app's
`Tickets/` folder, and (re)launches the injector so you can inject it onto a
save that you then load in the emulator.

The injector only scans `Tickets/` at startup, so this always relaunches it.
In the GUI: load the `.gba` + `.sav`, click **Edit** to unlock the preset
dropdown, pick this gift, and Save to inject.
"""

import glob
import os
import subprocess
import sys

from .gift_registry import GIFT_REGISTRY, add_flag_id_argument, resolve_flag_id
from .gift_to_bin import write_gift_bins
from .mystery_gift import crc16
from .save_inject import build_ram_script_struct

# Where the built injector lives.  Override with MG_INJECTOR_APP; otherwise we
# look next to the repo (tools/mgtool/build) and, as a last resort, sweep the
# temp scratchpads an earlier session may have built it in.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_NAME = "Mystery_Gift_Injector.app"


def _ticket_name(slug):
    """Injector display label is the first underscore-token, title-cased, so keep
    the slug in one token: 'worlds-xp' -> 'WORLDSXP_FRLG' -> 'Worldsxp - FRLG'.
    The filename must contain a game code (FRLG) for the tool to load it."""
    token = "".join(ch for ch in slug.upper() if ch.isalnum())
    return f"{token}_FRLG"


def find_injector_app():
    """Return the path to the injector .app bundle, or None if not built yet."""
    override = os.environ.get("MG_INJECTOR_APP")
    if override:
        return override if os.path.isdir(override) else None
    candidates = [
        os.path.join(_REPO_ROOT, "tools", "mgtool", "build", _APP_NAME),
    ]
    candidates += sorted(glob.glob(
        f"/private/tmp/claude-*/**/{_APP_NAME}", recursive=True))
    for path in candidates:
        if os.path.isdir(path):
            return path
    return None


def _tickets_dir(app_path):
    return os.path.join(app_path, "Contents", "MacOS", "Tickets")


def launch_injector(app_path):
    """Relaunch the injector so it re-scans Tickets/ (kills any running copy)."""
    subprocess.run(["pkill", "-f", "Mystery_Gift_Injector"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["open", app_path], check=True)


def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Export a registry gift to .bin and launch the injector to apply it.")
    ap.add_argument("-g", "--gift", default="worlds-xp",
                    choices=sorted(GIFT_REGISTRY.static_choices),
                    help="registry gift slug to emulate (default: worlds-xp)")
    add_flag_id_argument(ap)
    ap.add_argument("--no-launch", action="store_true",
                    help="write the .bin pair but do not (re)launch the injector")
    args = ap.parse_args(argv)

    flag_id = resolve_flag_id(args)
    card, script = GIFT_REGISTRY.build_static(args.gift, flag_id=flag_id)

    app_path = find_injector_app()
    if app_path is None:
        sys.exit(
            f"injector app not found. Build it (cmake) into tools/mgtool/build, "
            f"or set MG_INJECTOR_APP to its {_APP_NAME} path.")
    out_dir = _tickets_dir(app_path)

    name = _ticket_name(args.gift)
    wc_path, sc_path = write_gift_bins(out_dir, name, card, script)
    _, ram_crc = build_ram_script_struct(script)
    label = name.split("_", 1)[0].title()
    print(f"gift {args.gift!r} (flagId {flag_id}) -> ticket {name} "
          f"(shows as '{label} - FRLG')")
    print(f"  {wc_path}  (cardCrc=0x{crc16(card):04X})")
    print(f"  {sc_path}  (ramCrc=0x{ram_crc:04X})")

    if args.no_launch:
        print("skipped launch (--no-launch); relaunch the injector to see the ticket.")
        return
    launch_injector(app_path)
    print(f"launched {app_path}")
    print("In the GUI: load .gba + .sav, click Edit, pick the preset, and Save to inject.")


if __name__ == "__main__":
    _main()
