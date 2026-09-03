"""Clones the byte-exact Direct Corner advertisement and changes only identity, RFU parent id, activity/hasCard
and the group-active bit; unknown bytes are preserved. Record bytes 10..11 are the RFU parent id, not the serial."""

from dataclasses import dataclass
import secrets

from . import beacon, charmap, transport
from .host_beacon import CAPTURED_TRADE_BEACON


JOYSPOT_LOCAL_COMMUNICATION_ID = transport.HostTransport.LOCAL_COMMUNICATION_ID
JOYSPOT_MAX_PARTICIPANTS = 2
JOYSPOT_BASE_SCENE_ID = transport.HostTransport.SCENE_ID
JOYSPOT_BASE_APP_VERSION = transport.HostTransport.APPLICATION_VERSION
JOYSPOT_SERIAL = 0x7F7D

SEARCH_WORD_OFFSET = beacon.SEARCH_WORD_OFFSET
SEARCH_ACTIVITY_MASK = beacon.SEARCH_ACTIVITY_MASK
SEARCH_HAS_CARD = beacon.SEARCH_HAS_CARD
SEARCH_STARTED_ACTIVITY = beacon.SEARCH_STARTED_ACTIVITY
SEARCH_UNKNOWN_BIT7 = beacon.SEARCH_UNKNOWN_BIT7

# Serial writes stay inside the unexplained regions [12:16] and [18:24]: never identity, uname, the parent id
# at [10:12] or the search word at [16:18].
SERIAL_PLACEMENT_OFFSETS = frozenset({12, 13, 14, 18, 19, 20, 21, 22})


@dataclass(frozen=True)
class JoySpotCandidate:
    name: str
    description: str
    stage: str = "1.1"
    scene_id: int = JOYSPOT_BASE_SCENE_ID
    app_version: int = JOYSPOT_BASE_APP_VERSION
    pia_app_version: int = beacon.PIA_APP_COMM_VERSION
    activity: int = beacon.ACTIVITY_WONDER_CARD
    has_card: bool = False
    friend_control: bool = False
    serial_offset: int | None = None
    serial_endian: str = "little"
    search_bit7: bool | None = None

    def __post_init__(self):
        if not self.name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in self.name):
            raise ValueError("candidate name must be a lowercase CLI slug")
        if self.stage not in ("1.1", "1.2"):
            raise ValueError("stage must be 1.1 or 1.2")
        if not 0 <= self.scene_id <= 0xFFFF:
            raise ValueError("scene_id must fit in 16 bits")
        if not 0 <= self.app_version <= 0xFFFF:
            raise ValueError("app_version must fit in 16 bits")
        if not 0 <= self.pia_app_version <= 0xFFFF:
            raise ValueError("pia_app_version must fit in 16 bits")
        if type(self.activity) is not int or not 0 <= self.activity <= 0x7F:
            raise ValueError("activity must fit in seven bits")
        if type(self.has_card) is not bool:
            raise ValueError("has_card must be a bool")
        if type(self.friend_control) is not bool:
            raise ValueError("friend_control must be a bool")
        if self.serial_offset is not None:
            if self.serial_offset not in SERIAL_PLACEMENT_OFFSETS:
                raise ValueError(
                    "serial_offset must leave identity, the RFU parent id, and "
                    f"the search word untouched: {sorted(SERIAL_PLACEMENT_OFFSETS)}")
            if self.serial_endian not in ("little", "big"):
                raise ValueError("serial_endian must be 'little' or 'big'")
        if self.search_bit7 is not None and type(self.search_bit7) is not bool:
            raise ValueError("search_bit7 must be a bool or None")


FRIEND_CONTROL = JoySpotCandidate(
    "friend_control",
    "byte-identical activity-21 Friend positive control (not JoySpot)",
    friend_control=True)

STAGE_1_1_CANDIDATES = (
    JoySpotCandidate(
        "wireless_activity21_no_card",
        "exact proven Friend bytes, tested instead in Wireless Communication"),
    JoySpotCandidate(
        "wireless_activity21_card",
        "activity 21 with provisional packed hasCard bit 14", has_card=True),
    JoySpotCandidate(
        "wireless_activity4_card",
        "captured activity 4 with provisional packed hasCard bit 14",
        activity=beacon.ACTIVITY_TRADE, has_card=True),
    JoySpotCandidate(
        "wireless_activity0_card",
        "searching activity 0 with provisional packed hasCard bit 14",
        activity=0, has_card=True),
)

STAGE_1_2_CANDIDATES = (
    JoySpotCandidate(
        "serial_be_12", "big-endian serial at record[12:14]",
        stage="1.2", has_card=True, serial_offset=12, serial_endian="big"),
    JoySpotCandidate(
        "serial_be_14", "big-endian serial at record[14:16]",
        stage="1.2", has_card=True, serial_offset=14, serial_endian="big"),
    JoySpotCandidate(
        "serial_be_18", "big-endian serial at record[18:20]",
        stage="1.2", has_card=True, serial_offset=18, serial_endian="big"),
    JoySpotCandidate(
        "serial_be_20", "big-endian serial at record[20:22]",
        stage="1.2", has_card=True, serial_offset=20, serial_endian="big"),
    JoySpotCandidate(
        "serial_be_22", "big-endian serial at record[22:24]",
        stage="1.2", has_card=True, serial_offset=22, serial_endian="big"),
    JoySpotCandidate(
        "serial_le_13", "unaligned little-endian serial straddling record[13:15]",
        stage="1.2", has_card=True, serial_offset=13),
    JoySpotCandidate(
        "serial_le_19", "unaligned little-endian serial straddling record[19:21]",
        stage="1.2", has_card=True, serial_offset=19),
    JoySpotCandidate(
        "search_bit7_clear",
        "proven Friend bytes with the never-toggled search-word bit 7 cleared",
        stage="1.2", search_bit7=False),
)

JOYSPOT_CANDIDATES = STAGE_1_1_CANDIDATES + STAGE_1_2_CANDIDATES + (FRIEND_CONTROL,)
JOYSPOT_STAGES = ("1.1", "1.2")

_CANDIDATES_BY_NAME = {candidate.name: candidate for candidate in JOYSPOT_CANDIDATES}


def candidate_by_name(name):
    try:
        return _CANDIDATES_BY_NAME[name]
    except KeyError as exc:
        raise ValueError(f"unknown JoySpot candidate: {name}") from exc


def candidates_for_stage(stage):
    """Always ends with the Friend positive control so a silent sweep is distinguishable from a radio fault."""
    if stage == "all":
        return JOYSPOT_CANDIDATES
    if stage not in JOYSPOT_STAGES:
        raise ValueError(f"unknown JoySpot stage: {stage}")
    return tuple(
        candidate for candidate in JOYSPOT_CANDIDATES
        if candidate.stage == stage and not candidate.friend_control
    ) + (FRIEND_CONTROL,)


def new_parent_session_id():
    return secrets.token_bytes(1) + b"\xf1"


def _record_from_app_data(app_data):
    raw = transport._b85_decode(bytes(app_data)[beacon.PIA_HDR:])
    if len(raw) < beacon.RECORD_SIZE:
        raise ValueError("application data does not contain a 24-byte discovery record")
    return bytearray(raw[:beacon.RECORD_SIZE])


def _replace_pia_name(header, name):
    encoded = name.encode("utf-8")[:64]
    header[0x17:0x1B] = len(encoded).to_bytes(4, "big")
    header[0x1B] = beacon.PIA_NAME_UTF8
    header[0x1C:beacon.PIA_HDR] = b"\x00" * (beacon.PIA_HDR - 0x1C)
    header[0x1C:0x1C + len(encoded)] = encoded


def build_joyspot_app_data(
        profile, host_session_id, candidate="wireless_activity21_no_card"):
    if isinstance(candidate, str):
        candidate = candidate_by_name(candidate)
    if not isinstance(candidate, JoySpotCandidate):
        raise TypeError("candidate must be a JoySpotCandidate or candidate name")

    host_session_id = bytes(host_session_id)
    if len(host_session_id) != 2:
        raise ValueError("host_session_id must contain exactly two bytes")

    source = bytearray(CAPTURED_TRADE_BEACON)
    header = bytearray(source[:beacon.PIA_HDR])
    header[0x03:0x05] = candidate.pia_app_version.to_bytes(2, "big")
    _replace_pia_name(header, profile.session_name)

    record = _record_from_app_data(source)
    record[0:2] = profile.discovery_trainer_id.to_bytes(2, "little")
    record[2:10] = charmap.encode(profile.discovery_name, width=8, pad=0xFF)
    record[10:12] = host_session_id

    search_word = int.from_bytes(
        record[SEARCH_WORD_OFFSET:SEARCH_WORD_OFFSET + 2], "little")
    search_word &= ~(
        SEARCH_ACTIVITY_MASK | SEARCH_HAS_CARD | SEARCH_STARTED_ACTIVITY)
    search_word |= candidate.activity
    if candidate.has_card:
        search_word |= SEARCH_HAS_CARD
    if candidate.search_bit7 is not None:
        if candidate.search_bit7:
            search_word |= SEARCH_UNKNOWN_BIT7
        else:
            search_word &= ~SEARCH_UNKNOWN_BIT7
    record[SEARCH_WORD_OFFSET:SEARCH_WORD_OFFSET + 2] = search_word.to_bytes(2, "little")

    if candidate.serial_offset is not None:
        offset = candidate.serial_offset
        record[offset:offset + 2] = JOYSPOT_SERIAL.to_bytes(2, candidate.serial_endian)

    return bytes(header) + beacon.b85_encode(bytes(record))


@dataclass(frozen=True)
class DecodedJoySpotAdvertisement:
    record: bytes
    trainer_id: int
    name: str
    rfu_session_id: bytes
    search_word: int
    activity: int
    has_card: bool
    started_activity: bool
    search_bit7: bool
    unexplained_low: bytes
    unexplained_high: bytes
    pia_sys_version: int
    pia_app_version: int
    pia_nickname: str


def decode_joyspot_app_data(app_data):
    app_data = bytes(app_data)
    if len(app_data) < beacon.PIA_HDR:
        raise ValueError("application data is shorter than the Pia header")
    record = bytes(_record_from_app_data(app_data))
    search_word = int.from_bytes(
        record[SEARCH_WORD_OFFSET:SEARCH_WORD_OFFSET + 2], "little")
    pia = beacon.decode_pia_header(app_data[:beacon.PIA_HDR])
    return DecodedJoySpotAdvertisement(
        record=record,
        trainer_id=int.from_bytes(record[0:2], "little"),
        name=charmap.decode(record[2:10]),
        rfu_session_id=record[10:12],
        search_word=search_word,
        activity=search_word & SEARCH_ACTIVITY_MASK,
        has_card=bool(search_word & SEARCH_HAS_CARD),
        started_activity=bool(search_word & SEARCH_STARTED_ACTIVITY),
        search_bit7=bool(search_word & SEARCH_UNKNOWN_BIT7),
        unexplained_low=record[12:16],
        unexplained_high=record[18:24],
        pia_sys_version=pia["sys_comm_ver"],
        pia_app_version=pia["app_comm_ver"],
        pia_nickname=pia["nickname"],
    )
