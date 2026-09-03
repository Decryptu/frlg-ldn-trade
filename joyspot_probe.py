#!/usr/bin/env python3
"""Advertise one experimental FRLG JoySpot discovery candidate over LDN (research only; the supported
distributor is frlgmg_host.py). Advertises until Ctrl-C and records whether the Switch joins; never starts Pia,
RFU or the gift protocol, so a join is allowed to time out."""

import argparse
import os
import sys
import time


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

BUNDLED_LDN = os.path.join(PROJECT_ROOT, "vendor", "LDN")
if os.path.isdir(os.path.join(BUNDLED_LDN, "ldn")):
    sys.path.insert(0, BUNDLED_LDN)

from frlgsim.config import DEFAULT_TRAINER  # noqa: E402
from frlgsim.joyspot_discovery import (  # noqa: E402
    JOYSPOT_CANDIDATES,
    JOYSPOT_STAGES,
    candidate_by_name,
    candidates_for_stage,
)
from frlgsim.joyspot_probe import (  # noqa: E402
    JoySpotProbeApplication,
    JoySpotProbeConfig,
)


class _ProbeLog:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.started = time.monotonic()

    def _prefix(self):
        return f"[{time.monotonic() - self.started:7.1f}s]"

    def __call__(self, *parts):
        if self.verbose:
            print(self._prefix(), *parts)

    def info(self, *parts):
        print(self._prefix(), *parts)


def build_parser():
    names = tuple(candidate.name for candidate in JOYSPOT_CANDIDATES)
    matrix = "\n".join(
        f"  {candidate.stage}  {candidate.name:<28} {candidate.description}"
        for candidate in JOYSPOT_CANDIDATES)
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Bounded candidate order:\n" + matrix,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--candidate", choices=names, default=names[0],
        help=f"one controlled advertisement to run (default: {names[0]})")
    selection.add_argument(
        "--all-candidates", action="store_true",
        help="run one stage interactively, asking Y/N after each candidate")
    parser.add_argument(
        "--stage", choices=JOYSPOT_STAGES + ("all",), default="1.2",
        help="which retained experiment --all-candidates runs; every stage ends "
             "with the Friend positive control (default: 1.2)")
    parser.add_argument(
        "--list-candidates", action="store_true",
        help="print the ordered Stage 1 matrix and exit")
    parser.add_argument(
        "--live", action="store_true",
        help="acknowledge that this creates a real LDN network")
    parser.add_argument(
        "--phy", default="auto",
        help="Wi-Fi phy; default selects an AP-capable phy")
    parser.add_argument("--keys", default="~/.switch/prod.keys")
    parser.add_argument(
        "--password", default="",
        help="LDN passphrase hex; default uses the FRLG emulator value")
    parser.add_argument(
        "--capture", metavar="FILE",
        help="optional JSONL advertisement/join trace")
    parser.add_argument(
        "--channel", type=int, choices=range(1, 15), default=1,
        metavar="1-14")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument(
        "--skip-encryption", "--skip_encryption", action="store_true",
        help="delegate transmit CCMP to mac80211/hardware; over-air frames "
             "remain encrypted")
    parser.add_argument(
        "--accept-decrypted-ccmp", "--accept_decrypted_ccmp",
        action="store_true",
        help="accept hardware-decrypted RX frames that retain their CCMP "
             "header and MIC (TP-Link Archer T3U/rtw88_8822bu profile)")
    parser.add_argument(
        "--verbose", action="store_true",
        help="include detailed LDN, interface, and advertisement logging")
    return parser


def _password(parser, value):
    if not value:
        return None
    try:
        return bytes.fromhex(value)
    except ValueError:
        parser.error("--password must contain hexadecimal bytes")


def _print_candidates():
    for index, candidate in enumerate(JOYSPOT_CANDIDATES, 1):
        print(f"{index:2}. {candidate.name:<28} "
              f"[{candidate.stage}] {candidate.description}")


def _capture_path_for_candidate(base_path, candidate_name):
    if base_path is None:
        return None
    stem, suffix = os.path.splitext(base_path)
    if not suffix:
        stem, suffix = base_path, ".jsonl"
    return f"{stem}_{candidate_name}{suffix}"


def _candidate_menu(candidate):
    return "Friend" if candidate.friend_control else "Wireless Communication"


def _prompt_candidate_visible(candidate):
    menu = _candidate_menu(candidate)
    print()
    print(f"Candidate {candidate.name!r} is live.")
    print(f"On the Switch use Mystery Gift -> Wonder Cards -> {menu}.")
    print("Back out to the Wonder Cards menu and re-enter it for this candidate: "
          "each one is a brand-new LDN network, so a stale scan list can hide it.")
    if candidate.friend_control:
        print("This is the final Friend positive control, not a JoySpot candidate.")
    else:
        print("Answer Y for ANY reaction, including SE_BOO (the error jingle) - that "
              "means the serial matched and only the card/idle flags are wrong.")
    while True:
        answer = input(
            f"Can the Switch see or react to {candidate.name!r}? [Y/N]: "
        ).strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer Y or N.")


def _probe_config(args, parser, candidate, capture_path):
    return JoySpotProbeConfig(
        candidate=candidate,
        phy=args.phy,
        keys_path=args.keys,
        password=_password(parser, args.password),
        channel=args.channel,
        capture_path=capture_path,
        skip_preflight=args.skip_preflight,
        skip_encryption=args.skip_encryption,
        accept_decrypted_ccmp=args.accept_decrypted_ccmp,
    )


def _print_sweep_summary(stage, results):
    print(f"\nJoySpot Stage {stage} all-candidate summary")
    print(f"{'candidate':<28} {'visible':<8} {'LDN join'}")
    for candidate, visible, joined in results:
        print(
            f"{candidate.name:<28} "
            f"{('YES' if visible else 'NO'):<8} "
            f"{'YES' if joined else 'NO'}")
    controls = [row for row in results if row[0].friend_control]
    if controls and not controls[-1][1]:
        print("\nWARNING: the Friend positive control was NOT visible. Treat every "
              "silent Wireless result in this run as inconclusive (radio, record "
              "format, or menu procedure), not as evidence about the serial.")


def _run_all_candidates(args, parser, log):
    results = []
    candidates = candidates_for_stage(args.stage)
    try:
        for index, candidate in enumerate(candidates, 1):
            print("\n" + "=" * 72)
            print(
                f"Starting candidate {index}/{len(candidates)}: "
                f"{candidate.name}")
            if index > 1:
                print("Wait for the Switch's scan result to refresh before answering.")

            config = _probe_config(
                args,
                parser,
                candidate,
                _capture_path_for_candidate(args.capture, candidate.name),
            )
            observation = {}

            def decide():
                visible = _prompt_candidate_visible(candidate)
                observation["visible"] = visible
                return visible

            # Each iteration rebuilds the whole LDN/AP environment so no scan or auth state carries over.
            joined = JoySpotProbeApplication(
                config, DEFAULT_TRAINER, log=log).run(decision_prompt=decide)
            results.append((candidate, observation["visible"], joined))
    except (KeyboardInterrupt, EOFError):
        print("\nCandidate sweep aborted; the active network was cleaned up.")
        if results:
            _print_sweep_summary(args.stage, results)
        return 130

    _print_sweep_summary(args.stage, results)
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_candidates:
        _print_candidates()
        return 0
    if not args.live:
        parser.error("the discovery probe requires --live")
    if os.geteuid() != 0:
        parser.error("live LDN hosting requires root; run with sudo -E")

    log = _ProbeLog(args.verbose)
    if args.all_candidates:
        return _run_all_candidates(args, parser, log)

    config = _probe_config(
        args, parser, candidate_by_name(args.candidate), args.capture)
    JoySpotProbeApplication(config, DEFAULT_TRAINER, log=log).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
