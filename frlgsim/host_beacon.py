"""FRLG discovery application data and periodic 802.11 beacon injection."""

import argparse
import socket
import struct
import threading
import time

from . import beacon, transport


# Captured from a native FireRed Direct Corner leader; undocumented record fields must stay verbatim.
CAPTURED_TRADE_BEACON = bytes.fromhex(
    "005c160058000000000000000000000000000000000101000000050143686173650000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000686c5a68656c76623476354358455a232323232368642323232323232323"
)

RADIOTAP_HEADER = struct.pack("<BBHI", 0, 0, 8, 0)
BROADCAST = b"\xff" * 6
SUPPORTED_RATES = bytes((0x82, 0x84, 0x8B, 0x96, 0x24, 0x30, 0x48, 0x6C))
RSN_PSK_CCMP = bytes.fromhex(
    "0100" "000fac04" "0100" "000fac04" "0100" "000fac02" "0c00")


def parse_mac(value):
    try:
        result = bytes.fromhex(value.replace(":", ""))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid MAC address: {value}") from exc
    if len(result) != 6:
        raise argparse.ArgumentTypeError(f"invalid MAC address: {value}")
    return result


def read_interface_mac(interface):
    with open(f"/sys/class/net/{interface}/address", encoding="ascii") as stream:
        return parse_mac(stream.read().strip())


def _apply_profile_to_search_word(record, profile):
    offset = beacon.SEARCH_WORD_OFFSET
    word = int.from_bytes(record[offset:offset + 2], "little")
    player = profile.to_link_player()
    word &= ~(beacon.SEARCH_VERSION_MASK | beacon.SEARCH_LANGUAGE_MASK)
    word |= ((player.version << beacon.SEARCH_VERSION_SHIFT)
             & beacon.SEARCH_VERSION_MASK)
    word |= ((player.language << beacon.SEARCH_LANGUAGE_SHIFT)
             & beacon.SEARCH_LANGUAGE_MASK)
    record[offset:offset + 2] = word.to_bytes(2, "little")


def _element(element_id, data):
    if len(data) > 255:
        raise ValueError("information element is too long")
    return bytes((element_id, len(data))) + data


def build_wifi_beacon(bssid, channel, sequence, ssid_length=32, dtim_period=3):
    header = struct.pack(
        "<HH6s6s6sH", 0x0080, 0, BROADCAST, bssid, bssid,
        (sequence & 0xFFF) << 4)
    timestamp = (time.monotonic_ns() // 1_000) & 0xFFFFFFFFFFFFFFFF
    fixed = struct.pack("<QHH", timestamp, 100, 0x0511)
    elements = b"".join((
        _element(0, b"\x00" * ssid_length),
        _element(1, SUPPORTED_RATES),
        _element(3, bytes((channel,))),
        _element(5, bytes((0, dtim_period, 0, 0))),
        _element(48, RSN_PSK_CCMP),
    ))
    return RADIOTAP_HEADER + header + fixed + elements


def build_trade_app_data(profile, host_session_id):
    app_data = bytearray(beacon.mutate_beacon(
        CAPTURED_TRADE_BEACON, name=profile.discovery_name,
        trainer_id=profile.discovery_trainer_id))
    pia_name = profile.session_name.encode("utf-8")[:64]
    app_data[0x17:0x1B] = len(pia_name).to_bytes(4, "big")
    app_data[0x1B] = beacon.PIA_NAME_UTF8
    app_data[0x1C:beacon.PIA_HDR] = b"\x00" * 64
    app_data[0x1C:0x1C + len(pia_name)] = pia_name

    record = bytearray(transport._b85_decode(
        app_data[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]).ljust(
            beacon.RECORD_SIZE, b"\x00")
    record[10:12] = bytes(host_session_id)[:2].ljust(2, b"\x00")
    _apply_profile_to_search_word(record, profile)
    inactive = bytes(app_data[:beacon.PIA_HDR]) + beacon.b85_encode(bytes(record))
    return inactive, activate_trade_app_data(inactive, host_session_id)


def _build_activity_app_data(profile, host_session_id, activity, trade_board=None):
    """The advertisement every "we are a FRLG host doing X" beacon shares; only `activity` differs.

    The console's listen task keeps a candidate only if IsPartnerActivityAcceptable matches the
    activity against the accept list of the link group it is searching in
    [src/data/union_room.h:398-453; union_room.c:1590], so this byte alone decides which of the
    console's menus we are visible in.
    """
    app_data = bytearray(beacon.mutate_beacon(
        CAPTURED_TRADE_BEACON, name=profile.discovery_name,
        trainer_id=profile.discovery_trainer_id))
    pia_name = profile.session_name.encode("utf-8")[:64]
    app_data[0x17:0x1B] = len(pia_name).to_bytes(4, "big")
    app_data[0x1B] = beacon.PIA_NAME_UTF8
    app_data[0x1C:beacon.PIA_HDR] = b"\x00" * 64
    app_data[0x1C:0x1C + len(pia_name)] = pia_name

    record = bytearray(transport._b85_decode(
        app_data[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]).ljust(
            beacon.RECORD_SIZE, b"\x00")
    record[10:12] = bytes(host_session_id)[:2].ljust(2, b"\x00")
    _apply_profile_to_search_word(record, profile)
    offset = beacon.SEARCH_WORD_OFFSET
    search_word = int.from_bytes(record[offset:offset + 2], "little")
    search_word &= ~(beacon.SEARCH_ACTIVITY_MASK | beacon.SEARCH_HAS_CARD
                     | beacon.SEARCH_STARTED_ACTIVITY)
    search_word |= activity & beacon.SEARCH_ACTIVITY_MASK
    record[offset:offset + 2] = search_word.to_bytes(2, "little")
    if trade_board is not None:
        # (species, level, wanted_type): what the console's trading board lists us with
        # [union_room.c:3400]. IsPartnerActivityIncompatible compares all three at connect time
        # [link_rfu_2.c:2949], so they must not change while we host.
        record = bytearray(beacon.set_trade_board(record, *trade_board))

    inactive = bytes(app_data[:beacon.PIA_HDR]) + beacon.b85_encode(bytes(record))
    return inactive, activate_trade_app_data(inactive, host_session_id)


def build_union_room_app_data(profile, host_session_id, activity=None, trade_board=None):
    """Advertisement for the Union Room (the middle NPC on Pokemon Center 2F).

    The trade and Wonder Card beacons are invisible there: IsPartnerActivityAcceptable drops every
    activity but the ones the room's accept lists carry [src/data/union_room.h:398-453]. The default
    is the bare IN_UNION_ROOM a console standing in the room accepts and connects to (u03).
    """
    if activity is None:
        # IN_UNION_ROOM | ACTIVITY_NONE: IsPartnerActivityIncompatible [link_rfu_2.c:2933] requires
        # partner->activity == IN_UNION_ROOM exactly, so the trade intent must NOT be advertised.
        activity = beacon.IN_UNION_ROOM
    return _build_activity_app_data(profile, host_session_id, activity,
                                    trade_board=trade_board)


def build_wonder_card_app_data(profile, host_session_id):
    """Mystery Gift -> Wonder Cards -> Friend (sAcceptedActivityIds_WonderCard)."""
    return _build_activity_app_data(profile, host_session_id,
                                    beacon.ACTIVITY_WONDER_CARD)


def build_wonder_news_app_data(profile, host_session_id):
    """Mystery Gift -> Wonder News -> Friend.

    The Friend listen task filters on exactly ACTIVITY_WONDER_NEWS
    [sAcceptedActivityIds_WonderNews, src/data/union_room.h:406], so a Wonder Card beacon is
    invisible on this screen and vice versa. The compatibility hasNews bit is NOT consulted here:
    HasWonderCardOrNewsByLinkGroup [union_room.c:3777] is only reached from
    Task_ListenForWonderDistributor, the Wireless path.
    """
    return _build_activity_app_data(profile, host_session_id,
                                    beacon.ACTIVITY_WONDER_NEWS)


def activate_trade_app_data(app_data, host_session_id):
    app_data = bytearray(app_data)
    active_header = bytearray(app_data[:beacon.PIA_HDR])
    if len(active_header) > 0x16:
        active_header[0x16] = 2
    record = bytearray(transport._b85_decode(
        app_data[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]).ljust(
            beacon.RECORD_SIZE, b"\x00")
    record[10:12] = bytes(host_session_id)[:2].ljust(2, b"\x00")
    record[17] |= 0x80
    return bytes(active_header) + beacon.b85_encode(bytes(record))


class BeaconInjector:
    """Some Wi-Fi drivers never beacon the AP themselves; this thread injects 802.11 beacons from userspace."""

    def __init__(self, monitor="ldn-mon", ap="ldn", channel=1,
                 ssid_length=32, dtim_period=3, log=print):
        self.monitor = monitor
        self.ap = ap
        self.channel = channel
        self.ssid_length = ssid_length
        self.dtim_period = dtim_period
        self.log = log
        self.sent = 0
        self.error = None
        self._stop = threading.Event()
        self._started = threading.Event()
        self._thread = None

    def start(self, timeout=5):
        self._thread = threading.Thread(
            target=self._run, name="ldn-beacon-injector", daemon=True)
        self._thread.start()
        if not self._started.wait(timeout):
            raise RuntimeError("802.11 beacon injector did not start")
        if self.error is not None:
            raise RuntimeError(f"802.11 beacon injector failed: {self.error}")
        return self

    def _run(self):
        tx = None
        try:
            bssid = read_interface_mac(self.ap)
            tx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
            tx.bind((self.monitor, 0))
            self.log(f"[host] injecting periodic 802.11 beacons on {self.monitor}: "
                     f"bssid={bssid.hex(':')} channel={self.channel} interval=100 TU")
            self._started.set()
            sequence = 0
            deadline = time.monotonic()
            while not self._stop.is_set():
                tx.send(build_wifi_beacon(
                    bssid, self.channel, sequence, self.ssid_length, self.dtim_period))
                sequence = (sequence + 1) & 0xFFF
                self.sent += 1
                deadline += 0.1024
                self._stop.wait(max(0.0, deadline - time.monotonic()))
        except BaseException as exc:
            self.error = exc
            self._started.set()
        finally:
            if tx is not None:
                tx.close()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.log(f"[host] stopped 802.11 beacon injection after {self.sent} beacon(s)")
