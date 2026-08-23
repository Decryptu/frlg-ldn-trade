"""Shared argument parsing and configuration construction for host CLIs."""

import argparse

from . import config


WIFI_ADAPTER_HELP = """Wi-Fi adapter profiles proven for hosting:
  ALFA AWUS036ACHM (mt76x0u):
    --skip-encryption --no-accept-decrypted-ccmp
  TP-Link Archer T3U, USB 2357:012d (rtw88_8822bu):
    --skip-encryption --accept-decrypted-ccmp

--skip-encryption delegates transmit CCMP to mac80211/hardware; frames remain
encrypted over the air. --accept-decrypted-ccmp is only for drivers that expose
decrypted receive plaintext while retaining the CCMP header and MIC.
"""


def add_host_arguments(parser, *, option_defaults=None, ldn_defaults=None,
                       scene_help="LDN scene; default uses the configured FRLG scene"):
    """Add identity, lifecycle, LDN, and Pia options shared by host programs."""
    option_defaults = option_defaults or config.HostOptions()
    ldn_defaults = ldn_defaults or config.LdnConfig(phy="auto")
    parser.epilog = "\n\n".join(
        part for part in (parser.epilog, WIFI_ADAPTER_HELP) if part)

    config.add_identity_arguments(parser)
    parser.add_argument(
        "--trust-pia", action=argparse.BooleanOptionalAction, default=True,
        help="use Pia-backed send-once block delivery (recommended); "
             "--no-trust-pia enables diagnostic RFU retransmits")
    parser.add_argument("--verbose", action="store_true",
                        help="show detailed protocol logging instead of milestones")
    parser.add_argument("--live", action="store_true", required=True,
                        help="host for a real Switch")
    parser.add_argument("--password", default="",
                        help="LDN passphrase hex; default uses the FRLG emulator value")
    parser.add_argument("--phy", default=ldn_defaults.phy,
                        help="Wi-Fi phy; default selects an AP-capable phy")
    parser.add_argument("--keys", default=ldn_defaults.keys_path)
    parser.add_argument("--comm-id", help="LDN local_communication_id in hexadecimal")
    parser.add_argument("--capture", metavar="FILE",
                        default=ldn_defaults.capture_path,
                        help="record an optional JSONL protocol diagnostic")
    parser.add_argument("--channel", type=int, default=option_defaults.channel,
                        choices=range(1, 15), metavar="1-14")
    parser.add_argument("--scene", type=int, default=option_defaults.scene_id,
                        help=scene_help)
    parser.add_argument("--max-participants", type=int,
                        default=option_defaults.max_participants,
                        choices=range(2, 9), metavar="2-8")
    parser.add_argument("--skip-preflight", action=argparse.BooleanOptionalAction,
                        default=option_defaults.skip_preflight)
    parser.add_argument(
        "--skip-encryption", "--skip_encryption",
        action=argparse.BooleanOptionalAction,
        default=option_defaults.skip_encryption,
        help="delegate transmit CCMP to mac80211/hardware; over-air frames "
             "remain encrypted")
    parser.add_argument(
        "--accept-decrypted-ccmp", "--accept_decrypted_ccmp",
        action=argparse.BooleanOptionalAction,
        default=option_defaults.accept_decrypted_ccmp,
        help="accept hardware-decrypted RX frames that retain their CCMP "
             "header and MIC (TP-Link Archer T3U/rtw88_8822bu profile)")
    parser.add_argument(
        "--native-nonce-sequence", "--native_nonce_sequence",
        action=argparse.BooleanOptionalAction,
        default=option_defaults.native_nonce_sequence,
        help="use FireRed's session-wide incrementing Pia nonce")
    parser.add_argument(
        "--session-response-first", action=argparse.BooleanOptionalAction,
        default=option_defaults.session_response_first,
        help="send Session type 2 unicast before type 5 broadcast")


def parse_hex_bytes(parser, option, value):
    if not value:
        return None
    try:
        return bytes.fromhex(value)
    except ValueError:
        parser.error(f"{option} must contain hexadecimal bytes")


def parse_hex_int(parser, option, value):
    if value is None:
        return None
    try:
        return int(value, 16)
    except ValueError:
        parser.error(f"{option} must be a hexadecimal integer")


def build_host_config(parser, args):
    """Build the shared profile, LDN config, and host options from parsed args."""
    try:
        profile = config.profile_from_overrides(
            ot=args.ot, version=args.version, trainer_id=args.id)
        ldn = config.LdnConfig(
            password=parse_hex_bytes(parser, "--password", args.password),
            phy=args.phy,
            keys_path=args.keys,
            local_comm_id=parse_hex_int(parser, "--comm-id", args.comm_id),
            capture_path=args.capture,
        )
        options = config.HostOptions(
            channel=args.channel,
            scene_id=args.scene,
            max_participants=args.max_participants,
            skip_preflight=args.skip_preflight,
            skip_encryption=args.skip_encryption,
            accept_decrypted_ccmp=args.accept_decrypted_ccmp,
            native_nonce_sequence=args.native_nonce_sequence,
            session_response_first=args.session_response_first,
        )
    except ValueError as exc:
        parser.error(str(exc))
    return profile, ldn, options
