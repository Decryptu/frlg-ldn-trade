import argparse
from dataclasses import dataclass, field, replace
from pathlib import Path
import tomllib
from typing import Any, Mapping

from . import (beacon, charmap, gift_registry, linkplayer, ni, stamp_rally,
               uroom_chat, wonder_card)


VERSIONS = {
    "firered": linkplayer.VERSION_FIRE_RED,
    "leafgreen": linkplayer.VERSION_LEAF_GREEN,
}
# Japanese is absent: its kana table shares byte values with the accented Latin range in charmap.py.
LANGUAGES = {
    "english": linkplayer.LANGUAGE_ENGLISH,
    "french": linkplayer.LANGUAGE_FRENCH,
    "italian": linkplayer.LANGUAGE_ITALIAN,
    "german": linkplayer.LANGUAGE_GERMAN,
    "spanish": linkplayer.LANGUAGE_SPANISH,
}

MysteryGiftDistribution = stamp_rally.MysteryGiftDistribution


@dataclass(frozen=True)
class TrainerProfile:
    name: str
    tid: int
    sid: int
    gender: int = 0
    version: str = "leafgreen"
    language: str = "english"
    has_national_dex: bool = True
    has_completed_game: bool = True

    def __post_init__(self):
        if not isinstance(self.name, str):
            raise ValueError("trainer name must be a string")
        encoded = charmap.encode(self.name)
        if not self.name or charmap.decode(encoded) != self.name:
            raise ValueError("trainer name contains unsupported Gen III characters")
        if len(encoded) > 7:
            raise ValueError("trainer name must encode to at most 7 Gen III characters")
        if (type(self.tid) is not int or type(self.sid) is not int
                or not 0 <= self.tid <= 0xFFFF or not 0 <= self.sid <= 0xFFFF):
            raise ValueError("TID and SID must each fit in 16 bits")
        if type(self.gender) is not int or self.gender not in (0, 1):
            raise ValueError("gender must be 0 (male) or 1 (female)")
        if self.version not in VERSIONS:
            raise ValueError(f"version must be one of {', '.join(VERSIONS)}")
        if self.language not in LANGUAGES:
            raise ValueError(f"language must be one of {', '.join(LANGUAGES)}")
        if type(self.has_national_dex) is not bool:
            raise ValueError("has_national_dex must be a bool")
        if type(self.has_completed_game) is not bool:
            raise ValueError("has_completed_game must be a bool")

    @property
    def trainer_id(self):
        return (self.sid << 16) | self.tid

    @property
    def progress_flags(self):
        return ((1 if self.has_national_dex else 0)
                | (0x10 if self.has_completed_game else 0))

    @property
    def discovery_name(self):
        return self.name

    @property
    def discovery_trainer_id(self):
        return self.tid

    @property
    def session_name(self):
        return self.name

    def to_link_player(self):
        return linkplayer.LinkPlayer(
            name=self.name,
            trainer_id=self.trainer_id,
            version=VERSIONS[self.version],
            progress_flags=self.progress_flags,
            progress_flags_copy=self.progress_flags,
            gender=self.gender,
            player_id=0,
            language=LANGUAGES[self.language],
        )

    def build_link_player_block(self, *, name_pad=0x00):
        return linkplayer.build_block(self.to_link_player(), name_pad=name_pad)

    def build_trainer_card(self, mon_species=None, *, name_pad=0x00):
        return linkplayer.build_trainer_card(
            self.to_link_player(), mon_species=mon_species, name_pad=name_pad)

    def build_rfu_game_data(self, activity, *, started=True):
        return ni.build_game_data(
            VERSIONS[self.version], self.tid, self.name,
            language=LANGUAGES[self.language], activity=activity,
            started=started)


DEFAULT_TRAINER = TrainerProfile(
    name="PkCamp", tid=0x8822, sid=0x47ED, gender=0,
    version="leafgreen", language="english",
    has_national_dex=True, has_completed_game=True)


@dataclass(frozen=True)
class TradePlan:
    party_paths: tuple
    output_path: str = "received.pk3"
    output_size: int = 100
    output_format: str = "pk3"
    trade_slot: int = 1
    offered_slots: tuple | None = None
    trades: int = 1
    anim_delay: int | None = None
    player_ids_repeat_frames: int | None = None
    link_player_idle_frames: int | None = None
    trust_pia: bool = False

    def __post_init__(self):
        if not 1 <= len(self.party_paths) <= 6:
            raise ValueError("party must contain 1..6 Pokemon files")
        if not 1 <= self.trades <= 6 or self.trades > len(self.party_paths):
            raise ValueError("trades must be 1..6 and cannot exceed party size")
        if self.output_size not in (80, 100):
            raise ValueError("output_size must be 80 or 100")
        if self.output_format not in ("pk3", "ek3"):
            raise ValueError("output_format must be pk3 or ek3")
        if type(self.trade_slot) is not int or not 0 <= self.trade_slot < len(self.party_paths):
            raise ValueError("trade_slot must reference the configured party")
        if self.anim_delay is not None \
                and (type(self.anim_delay) is not int or self.anim_delay < 0):
            raise ValueError("anim_delay must be a non-negative integer")
        if (self.player_ids_repeat_frames is not None
                and (type(self.player_ids_repeat_frames) is not int
                     or not 1 <= self.player_ids_repeat_frames <= 600)):
            raise ValueError("player_ids_repeat_frames must be between 1 and 600")
        if (self.link_player_idle_frames is not None
                and (type(self.link_player_idle_frames) is not int
                     or not 0 <= self.link_player_idle_frames <= 600)):
            raise ValueError("link_player_idle_frames must be between 0 and 600")
        if self.offered_slots is not None:
            if len(self.offered_slots) != self.trades:
                raise ValueError("offered_slots must contain one slot per trade")
            if len(set(self.offered_slots)) != len(self.offered_slots):
                raise ValueError("offered_slots must be distinct")
            if any(type(slot) is not int or not 0 <= slot < len(self.party_paths)
                   for slot in self.offered_slots):
                raise ValueError("offered_slots must reference the configured party")


@dataclass(frozen=True)
class LdnConfig:
    password: bytes | None = None
    phy: str = "phy0"
    # Resolved to a concrete phy at runtime when ``phy`` is "auto".
    adapter: str | None = None
    keys_path: str = "~/.switch/prod.keys"
    local_comm_id: int | None = None
    capture_path: str | None = None

    def __post_init__(self):
        if self.password is not None and not isinstance(self.password, bytes):
            raise ValueError("password must be bytes or None")
        if self.adapter is not None and (
                not isinstance(self.adapter, str) or not self.adapter):
            raise ValueError("adapter must be a non-empty string or None")
        if self.local_comm_id is not None and (
                type(self.local_comm_id) is not int
                or not 0 <= self.local_comm_id <= 0xFFFFFFFFFFFFFFFF):
            raise ValueError("local_comm_id must fit in 64 bits")


@dataclass(frozen=True)
class JoinerOptions:
    live: bool = True
    replay_path: str | None = None
    self_id: int = 1
    decline: bool = False
    refuse_illegit: bool = False
    compress: bool = False
    pace_ms: int = 0
    connect_id: bytes | None = None

    def __post_init__(self):
        if self.live == bool(self.replay_path):
            raise ValueError("select exactly one of live mode or replay_path")
        if self.self_id != 1:
            raise ValueError("joiner self_id must be 1")
        if self.connect_id is not None and len(self.connect_id) != 2:
            raise ValueError("connect_id must contain exactly two bytes")


@dataclass(frozen=True)
class HostOptions:
    channel: int = 1
    scene_id: int | None = None
    max_participants: int = 6
    skip_preflight: bool = False
    skip_encryption: bool = False
    accept_decrypted_ccmp: bool = False
    native_nonce_sequence: bool = False
    session_response_first: bool = False
    # Host for the Union Room (the middle NPC on Pokemon Center 2F) instead of the trade centre:
    # bare IN_UNION_ROOM advertisement, no parent NI, SEND_PACKET prompt, room trade flow.
    union_room: bool = False
    # Which activity --union-room advertises. None = ACTIVITY_SEARCH, the form Task_InitUnionRoom
    # looks for (the screen before entering). A console already standing in the room runs
    # Task_RunUnionRoom and searches with the RESUME list, which accepts IN_UNION_ROOM | activity.
    union_room_activity: int | None = None
    # After the child's name NI, re-present a parent NI_START for this many VBlanks before the first
    # UNI frame. The room child 'D's after five unanswered parent frames and only enters UNI 480
    # frames after our last NI_START (its NI fail counter), so 0 never connects; 120 is proven.
    union_room_keepalive: int = 0
    # Trading board: the type we ask for in return (beacon.TYPE_NAMES value). None = no
    # registration, so the console's board does not list us. Species and level come from the
    # offered party mon unless union_room_board_level overrides the level.
    union_room_board_type: int | None = None
    union_room_board_level: int | None = None
    # Accept the room's "Tchat" instead of declining it, and the lines to send once the chat opens.
    union_room_chat: bool = False
    chat_messages: tuple = ()

    def __post_init__(self):
        # LDN channels: 2.4 GHz 1/6/11 and 5 GHz 36/40/44/48 [kinnay LDN wiki, WLAN Channels].
        if type(self.channel) is not int or not (1 <= self.channel <= 14 or self.channel in (36, 40, 44, 48)):
            raise ValueError("channel must be 1..14 or one of 36, 40, 44, 48")
        if type(self.max_participants) is not int or not 2 <= self.max_participants <= 8:
            raise ValueError("max_participants must be 2..8")
        if self.scene_id is not None and (
                type(self.scene_id) is not int or not 0 <= self.scene_id <= 0xFFFF):
            raise ValueError("scene_id must fit in 16 bits")
        for text in self.chat_messages:
            uroom_chat.check_text(text)


# --union-room-activity names, resolved to the packed activity field.
#   search    Task_InitUnionRoom advertises ACTIVITY_SEARCH and its search (LINK_GROUP_UNION_ROOM_INIT)
#             accepts only ACTIVITY_SEARCH. This is the screen BEFORE entering the room.
#   in-room*  Task_RunUnionRoom sets sPlayerCurrActivity = IN_UNION_ROOM and searches with
#             LINK_GROUP_UNION_ROOM_RESUME, which accepts IN_UNION_ROOM | activity. This is a console
#             standing in the room. [src/union_room.c:2664, src/data/union_room.h:407-418]
UNION_ROOM_ACTIVITIES = {
    "search": beacon.ACTIVITY_SEARCH,
    "in-room": beacon.IN_UNION_ROOM | 0,                      # IN_UNION_ROOM | ACTIVITY_NONE
    "in-room-trade": beacon.IN_UNION_ROOM | beacon.ACTIVITY_TRADE,
    "in-room-chat": beacon.IN_UNION_ROOM | 5,                 # ACTIVITY_CHAT
}


def resolve_board_type(name):
    if name is None:
        return None
    try:
        return beacon.TYPE_NAMES[name]
    except KeyError:
        raise ValueError("board type must be one of " + ", ".join(sorted(beacon.TYPE_NAMES)))


def resolve_union_room_activity(name):
    # Default to the in-room form: it is the only one proven to get a console past
    # IsPartnerActivityIncompatible (u03). "search" remains untested.
    if name is None:
        return UNION_ROOM_ACTIVITIES["in-room"]
    try:
        return UNION_ROOM_ACTIVITIES[name]
    except KeyError:
        raise ValueError(
            "union_room_activity must be one of "
            + ", ".join(sorted(UNION_ROOM_ACTIVITIES)))


HOST_CONFIG_FILENAME = "host.toml"
HOST_LOCAL_CONFIG_FILENAME = "host.local.toml"


@dataclass(frozen=True)
class HostFileConfig:
    """Strict ``[host]`` / ``[ldn]`` TOML sections; the local file overrides the tracked one."""

    live: bool = True
    adapter: str = "tplink-archer-t3u"
    trust_pia: bool = True
    channel: int = 1
    scene_id: int | None = None
    max_participants: int = 6
    skip_preflight: bool = False
    skip_encryption: bool = True
    accept_decrypted_ccmp: bool = True
    native_nonce_sequence: bool = True
    session_response_first: bool = True
    phy: str = "auto"
    keys_path: str = "~/.switch/prod.keys"
    local_comm_id: int | None = None
    capture_path: str | None = None

    def __post_init__(self):
        _require_bool("host.live", self.live)
        _require_nonempty_string("host.adapter", self.adapter)
        _require_bool("host.trust_pia", self.trust_pia)
        if self.channel not in (36, 40, 44, 48):
            _require_int_range("host.channel", self.channel, 1, 14)
        if self.scene_id is not None:
            _require_int_range("host.scene_id", self.scene_id, 0, 0xFFFF)
        _require_int_range("host.max_participants", self.max_participants, 2, 8)
        _require_bool("host.skip_preflight", self.skip_preflight)
        _require_bool("host.skip_encryption", self.skip_encryption)
        _require_bool("host.accept_decrypted_ccmp", self.accept_decrypted_ccmp)
        _require_bool("host.native_nonce_sequence", self.native_nonce_sequence)
        _require_bool("host.session_response_first", self.session_response_first)
        _require_nonempty_string("ldn.phy", self.phy)
        _require_nonempty_string("ldn.keys_path", self.keys_path)
        if self.local_comm_id is not None:
            _require_int_range("ldn.local_comm_id", self.local_comm_id, 0,
                               0xFFFFFFFFFFFFFFFF)
        if self.capture_path is not None:
            _require_nonempty_string("ldn.capture_path", self.capture_path)

    def to_host_options(self):
        return HostOptions(
            channel=self.channel,
            scene_id=self.scene_id,
            max_participants=self.max_participants,
            skip_preflight=self.skip_preflight,
            skip_encryption=self.skip_encryption,
            accept_decrypted_ccmp=self.accept_decrypted_ccmp,
            native_nonce_sequence=self.native_nonce_sequence,
            session_response_first=self.session_response_first,
        )

    def to_ldn_config(self):
        return LdnConfig(
            phy=self.phy,
            adapter=self.adapter,
            keys_path=self.keys_path,
            local_comm_id=self.local_comm_id,
            capture_path=self.capture_path,
        )

    def with_overrides(self, overrides: Mapping[str, Mapping[str, Any]] | None):
        return _apply_host_config_layer(self, overrides, source="overrides")


_HOST_TOML_FIELDS = frozenset({
    "live", "adapter", "trust_pia", "channel", "scene_id",
    "max_participants", "skip_preflight", "skip_encryption",
    "accept_decrypted_ccmp", "native_nonce_sequence",
    "session_response_first",
})
_LDN_TOML_FIELDS = frozenset({
    "phy", "keys_path", "local_comm_id", "capture_path",
})
_TOP_LEVEL_TOML_SECTIONS = frozenset({"host", "ldn"})


def project_config_directory():
    return Path(__file__).resolve().parent.parent / "config"


def default_host_config_path():
    return project_config_directory() / HOST_CONFIG_FILENAME


def default_host_local_config_path():
    return project_config_directory() / HOST_LOCAL_CONFIG_FILENAME


def load_host_file_config(config_path, *, local_path=None, overrides=None):
    """Layers: builtin < config_path (required) < local_path (optional) < overrides."""
    result = BUILTIN_HOST_FILE_CONFIG
    result = _apply_host_config_layer(
        result, _read_host_toml(Path(config_path), required=True),
        source=str(config_path))
    if local_path is not None:
        local_path = Path(local_path)
        if local_path.is_file():
            result = _apply_host_config_layer(
                result, _read_host_toml(local_path, required=False),
                source=str(local_path))
        elif local_path.exists():
            raise ValueError(f"host local configuration is not a file: {local_path}")
    return _apply_host_config_layer(result, overrides, source="overrides")


def load_project_host_file_config(*, overrides=None):
    return load_host_file_config(
        default_host_config_path(),
        local_path=default_host_local_config_path(),
        overrides=overrides,
    )


def _read_host_toml(path, *, required):
    if not path.is_file():
        if required:
            raise ValueError(f"host configuration file does not exist: {path}")
        return {}
    try:
        with path.open("rb") as source:
            raw = tomllib.load(source)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML in host configuration {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"host configuration must be a TOML table: {path}")
    return raw


def _apply_host_config_layer(base, layer, *, source):
    if layer is None:
        return base
    if not isinstance(layer, Mapping):
        raise ValueError(f"{source} host configuration must be a mapping")

    unexpected = set(layer) - _TOP_LEVEL_TOML_SECTIONS
    if unexpected:
        raise ValueError(
            f"{source} has unknown host configuration section(s): "
            f"{', '.join(sorted(unexpected))}")

    values = {}
    for section, allowed in (("host", _HOST_TOML_FIELDS), ("ldn", _LDN_TOML_FIELDS)):
        section_values = layer.get(section, {})
        if not isinstance(section_values, Mapping):
            raise ValueError(f"{source} [{section}] must be a TOML table")
        unexpected = set(section_values) - allowed
        if unexpected:
            raise ValueError(
                f"{source} [{section}] has unknown key(s): "
                f"{', '.join(sorted(unexpected))}")
        values.update(section_values)
    try:
        return replace(base, **values)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {source} host configuration: {exc}") from exc


def _require_bool(name, value):
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")


def _require_nonempty_string(name, value):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_int_range(name, value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer between {lower} and {upper}")


BUILTIN_HOST_FILE_CONFIG = HostFileConfig()


@dataclass(frozen=True)
class TradeRunConfig:
    profile: TrainerProfile
    plan: TradePlan
    ldn: LdnConfig
    role: JoinerOptions | HostOptions


@dataclass(frozen=True)
class MysteryGiftPayload:
    gift: str = wonder_card.GIFT_CELEBI
    flag_id: int | None = None

    def __post_init__(self):
        choices = gift_registry.GIFT_REGISTRY.live_choices
        if self.gift not in choices:
            raise ValueError(
                f"gift must be one of {', '.join(choices)}")
        if self.flag_id is None:
            object.__setattr__(self, "flag_id",
                               gift_registry.GIFT_REGISTRY.default_flag_id(self.gift))
        wonder_card.flag_for_flag_id(self.flag_id)

    @property
    def receipt_flag(self):
        return wonder_card.flag_for_flag_id(self.flag_id)

    def build(self):
        distribution = self.build_distribution()
        return distribution.card, distribution.ram_script

    def build_distribution(self):
        return gift_registry.GIFT_REGISTRY.build_distribution(
            self.gift, flag_id=self.flag_id)


def _mystery_gift_host_defaults():
    return HostOptions(
        skip_encryption=True,
        native_nonce_sequence=True,
        session_response_first=True,
    )


@dataclass(frozen=True)
class MysteryGiftRunConfig:
    profile: TrainerProfile = DEFAULT_TRAINER
    payload: MysteryGiftPayload = field(default_factory=MysteryGiftPayload)
    ldn: LdnConfig = field(default_factory=lambda: LdnConfig(phy="auto"))
    role: HostOptions = field(default_factory=_mystery_gift_host_defaults)
    trust_pia: bool = True
    client_ready_idle_frames: int | None = None
    inter_block_gap_frames: int | None = None
    block_repeat: int | None = None
    ram_script_block_repeat: int | None = None
    end_on_success: bool = False
    idle_timeout_seconds: int | None = None
    attempt_log_dir: str | None = None

    def __post_init__(self):
        if not isinstance(self.profile, TrainerProfile):
            raise ValueError("profile must be a TrainerProfile")
        if not isinstance(self.payload, MysteryGiftPayload):
            raise ValueError("payload must be a MysteryGiftPayload")
        if not isinstance(self.ldn, LdnConfig):
            raise ValueError("ldn must be an LdnConfig")
        if not isinstance(self.role, HostOptions):
            raise ValueError("role must be HostOptions")
        if type(self.trust_pia) is not bool:
            raise ValueError("trust_pia must be a bool")
        if (self.client_ready_idle_frames is not None
                and (type(self.client_ready_idle_frames) is not int
                     or not 0 <= self.client_ready_idle_frames <= 600)):
            raise ValueError("client_ready_idle_frames must be between 0 and 600")
        if (self.inter_block_gap_frames is not None
                and (type(self.inter_block_gap_frames) is not int
                     or not 0 <= self.inter_block_gap_frames <= 600)):
            raise ValueError("inter_block_gap_frames must be between 0 and 600")
        if (self.block_repeat is not None
                and (type(self.block_repeat) is not int
                     or not 1 <= self.block_repeat <= 8)):
            raise ValueError("block_repeat must be between 1 and 8")
        if (self.ram_script_block_repeat is not None
                and (type(self.ram_script_block_repeat) is not int
                     or not 1 <= self.ram_script_block_repeat <= 8)):
            raise ValueError("ram_script_block_repeat must be between 1 and 8")
        if type(self.end_on_success) is not bool:
            raise ValueError("end_on_success must be a bool")
        if (self.idle_timeout_seconds is not None
                and (type(self.idle_timeout_seconds) is not int
                     or not 1 <= self.idle_timeout_seconds <= 24 * 60 * 60)):
            raise ValueError("idle_timeout_seconds must be between 1 and 86400")
        if self.attempt_log_dir is not None and not isinstance(self.attempt_log_dir, str):
            raise ValueError("attempt_log_dir must be a string or None")


def parse_trainer_id(value):
    parts = value.split(":")
    if len(parts) not in (1, 2) or any(not part or not part.isdecimal() for part in parts):
        raise ValueError("ID must be decimal TID or TID:SID")
    values = tuple(int(part, 10) for part in parts)
    if any(number > 0xFFFF for number in values):
        raise ValueError("TID and SID must each be between 0 and 65535")
    return values[0], values[1] if len(values) == 2 else None


def trainer_id_argument(value):
    try:
        return parse_trainer_id(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def add_identity_arguments(parser):
    parser.add_argument("--ot", default=None, help="trainer name; defaults to DEFAULT_TRAINER")
    parser.add_argument("--version", choices=tuple(VERSIONS), default=None,
                        help="game version; defaults to DEFAULT_TRAINER")
    parser.add_argument("--language", choices=tuple(LANGUAGES), default=None,
                        help="trainer language; defaults to DEFAULT_TRAINER")
    parser.add_argument("--id", type=trainer_id_argument, metavar="TID[:SID]", default=None,
                        help="decimal trainer ID, optionally followed by decimal secret ID")


def profile_from_overrides(*, ot=None, version=None, language=None, trainer_id=None,
                           base=DEFAULT_TRAINER):
    changes = {}
    if ot is not None:
        changes["name"] = ot
    if version is not None:
        changes["version"] = version
    if language is not None:
        changes["language"] = language
    if trainer_id is not None:
        tid, sid = trainer_id
        changes["tid"] = tid
        if sid is not None:
            changes["sid"] = sid
    return replace(base, **changes)
