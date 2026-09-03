"""Configuration loading and argument parsing shared by the host CLIs.
Precedence: built-ins -> config/host.toml -> config/host.local.toml -> CLI."""

import argparse
from pathlib import Path

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


def _config_bootstrap_parser():
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--config", metavar="PATH")
    local = parser.add_mutually_exclusive_group()
    local.add_argument("--local-config", metavar="PATH")
    local.add_argument("--no-local-config", action="store_true")
    return parser


def load_host_file_config_from_argv(argv=None):
    """A custom --config uses a sibling host.local.toml unless --local-config/--no-local-config says otherwise."""
    known, _unknown = _config_bootstrap_parser().parse_known_args(argv)
    shared_path = (Path(known.config) if known.config else
                   config.default_host_config_path())
    if known.no_local_config:
        local_path = None
    elif known.local_config:
        local_path = Path(known.local_config)
    else:
        local_path = shared_path.with_name(config.HOST_LOCAL_CONFIG_FILENAME)
    return (config.load_host_file_config(shared_path, local_path=local_path),
            shared_path, local_path)


def add_host_config_arguments(parser, *, shared_path=None, local_path=None):
    parser.add_argument(
        "--config", metavar="PATH", default=str(shared_path) if shared_path else None,
        help="shared host TOML (default: config/host.toml)")
    local = parser.add_mutually_exclusive_group()
    local.add_argument(
        "--local-config", metavar="PATH",
        default=str(local_path) if local_path else None,
        help="optional machine-local TOML (default: sibling host.local.toml)")
    local.add_argument(
        "--no-local-config", action="store_true",
        help="do not load host.local.toml")
    parser.add_argument(
        "--print-effective-config", action="store_true",
        help="print the safe effective host configuration and exit")


def add_host_arguments(parser, *, option_defaults=None, ldn_defaults=None,
                       trust_pia_default=True, live_default=True,
                       scene_help="LDN scene; default uses the configured FRLG scene"):
    option_defaults = option_defaults or config.HostOptions()
    ldn_defaults = ldn_defaults or config.LdnConfig(phy="auto")
    parser.epilog = "\n\n".join(
        part for part in (parser.epilog, WIFI_ADAPTER_HELP) if part)

    config.add_identity_arguments(parser)
    parser.add_argument(
        "--trust-pia", action=argparse.BooleanOptionalAction,
        default=trust_pia_default,
        help="use Pia-backed send-once block delivery (recommended); "
             "--no-trust-pia enables diagnostic RFU retransmits")
    parser.add_argument("--verbose", action="store_true",
                        help="show detailed protocol logging instead of milestones")
    parser.add_argument(
        "--live", action=argparse.BooleanOptionalAction, default=live_default,
        help="host for a real Switch")
    parser.add_argument("--password", default="",
                        help="LDN passphrase hex; default uses the FRLG emulator value")
    parser.add_argument("--phy", default=ldn_defaults.phy,
                        help="Wi-Fi phy; explicit phyN overrides --adapter")
    parser.add_argument(
        "--adapter", default=getattr(ldn_defaults, "adapter", None),
        help="named Wi-Fi adapter profile used while --phy is auto")
    parser.add_argument("--keys", default=ldn_defaults.keys_path)
    comm_id_default = (None if ldn_defaults.local_comm_id is None
                       else f"{ldn_defaults.local_comm_id:x}")
    parser.add_argument("--comm-id", default=comm_id_default,
                        help="LDN local_communication_id in hexadecimal")
    parser.add_argument("--capture", metavar="FILE",
                        default=ldn_defaults.capture_path,
                        help="record an optional JSONL protocol diagnostic")
    parser.add_argument("--channel", type=int, default=option_defaults.channel,
                        choices=[*range(1, 15), 36, 40, 44, 48], metavar="1-14|36|40|44|48")
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
    try:
        profile = config.profile_from_overrides(
            ot=args.ot, version=args.version, language=args.language,
            trainer_id=args.id)
        ldn = config.LdnConfig(
            password=parse_hex_bytes(parser, "--password", args.password),
            phy=args.phy,
            adapter=args.adapter,
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
            # Only the trade host defines --union-room; the Mystery Gift host shares this parser.
            union_room=getattr(args, "union_room", False),
            union_room_activity=config.resolve_union_room_activity(
                getattr(args, "union_room_activity", None)),
            hold_beacon=getattr(args, "hold_beacon", False),
            union_room_keepalive=getattr(args, "union_room_keepalive", 0),
            union_room_board_type=config.resolve_board_type(getattr(args, "board_type", None)),
            union_room_board_level=getattr(args, "board_level", None),
        )
    except ValueError as exc:
        parser.error(str(exc))
    return profile, ldn, options


def effective_host_file_config(args):
    """Parsers carry the TOML values as defaults, so args are already the final layer; passwords never enter HostFileConfig."""
    return config.BUILTIN_HOST_FILE_CONFIG.with_overrides({
        "host": {
            "live": args.live,
            "adapter": args.adapter or "none",
            "trust_pia": args.trust_pia,
            "channel": args.channel,
            "scene_id": args.scene,
            "max_participants": args.max_participants,
            "skip_preflight": args.skip_preflight,
            "skip_encryption": args.skip_encryption,
            "accept_decrypted_ccmp": args.accept_decrypted_ccmp,
            "native_nonce_sequence": args.native_nonce_sequence,
            "session_response_first": args.session_response_first,
        },
        "ldn": {
            "phy": args.phy,
            "keys_path": args.keys,
            "local_comm_id": parse_hex_int_for_display(args.comm_id),
            "capture_path": args.capture,
        },
    })


def parse_hex_int_for_display(value):
    if value is None:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def format_effective_config(args):
    result = effective_host_file_config(args)
    lines = ["[host]"]
    for name in (
            "live", "adapter", "trust_pia", "channel", "scene_id",
            "max_participants", "skip_preflight", "skip_encryption",
            "accept_decrypted_ccmp", "native_nonce_sequence",
            "session_response_first"):
        value = getattr(result, name)
        if value is not None:
            lines.append(_format_config_value(name, value))
    lines.append("")
    lines.append("[ldn]")
    lines.append(_format_config_value("phy", result.phy))
    lines.append('keys_path = "<redacted>"')
    if result.local_comm_id is not None:
        lines.append(f'local_comm_id = "0x{result.local_comm_id:x}"')
    if result.capture_path is not None:
        lines.append('capture_path = "<redacted>"')
    if args.password:
        lines.append('password = "<redacted>"')
    return "\n".join(lines) + "\n"


def _format_config_value(name, value):
    if isinstance(value, str):
        return f'{name} = "{value}"'
    if isinstance(value, bool):
        return f"{name} = {'true' if value else 'false'}"
    return f"{name} = {value}"
