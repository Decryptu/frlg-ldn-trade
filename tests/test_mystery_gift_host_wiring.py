"""Wiring tests for the Mystery Gift host: advertisement, config, session seam.

These cover the parts that only run live, so the failure mode they guard against
is "the console never sees us" or "the trade host broke" rather than a protocol
bug.  The gift conversation itself is covered by tests/test_mystery_gift_flow.py.

Run standalone (no pytest needed):   python tests/test_mystery_gift_host_wiring.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import beacon, charmap, crypto, pia_connect, reliable, transport, wonder_card  # noqa: E402
from frlgsim.host_beacon import (  # noqa: E402
    build_trade_app_data, build_wonder_card_app_data,
)
from frlgsim.host_mg_app import (  # noqa: E402
    MysteryGiftHostApplication, MysteryGiftRunConfig,
)
from frlgsim.host_mystery_gift import HostMysteryGiftEngine  # noqa: E402
from frlgsim.config import (  # noqa: E402
    DEFAULT_TRAINER, HostOptions, LdnConfig, MysteryGiftPayload,
)
from frlgsim.host_session import HostSession  # noqa: E402

SESSION_ID = b"\x7b\xf1"


def _record(app_data):
    return transport._b85_decode(app_data[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]


def _search_word(app_data):
    record = _record(app_data)
    return int.from_bytes(
        record[beacon.SEARCH_WORD_OFFSET:beacon.SEARCH_WORD_OFFSET + 2], "little")


# --- the advertisement --------------------------------------------------------------------------
def test_wonder_card_advertisement_matches_the_proven_friend_control():
    """The JoySpot sweep's ``friend_control`` candidate was listed AND joined by a
    real console; its record was ``...9515...`` (docs/joyspot_discovery_findings.md).
    Anything that changes these bytes changes whether the console can see us."""
    inactive, _active = build_wonder_card_app_data(DEFAULT_TRAINER, SESSION_ID)
    record = _record(inactive)
    assert record.hex() == "2288bfc7cfffffffffff7bf1000000009515000000000000"


def test_advertisement_declares_activity_wonder_card_and_is_joinable():
    inactive, active = build_wonder_card_app_data(DEFAULT_TRAINER, SESSION_ID)
    word = _search_word(inactive)
    assert word & beacon.SEARCH_ACTIVITY_MASK == beacon.ACTIVITY_WONDER_CARD == 21
    # union_room.c:2313 refuses a candidate whose startedActivity bit is set, so
    # the advertisement must stay clear until a console has actually joined.
    assert not word & beacon.SEARCH_STARTED_ACTIVITY
    assert _search_word(active) & beacon.SEARCH_STARTED_ACTIVITY
    # SetHostRfuWonderFlags(FALSE, FALSE) [union_room.c:2052]: a native sender
    # advertises no wonder flags, and the Friend list never reads them.
    assert not word & beacon.SEARCH_HAS_CARD


def test_advertisement_preserves_every_unexplained_captured_byte():
    """Only the activity changes relative to the trade beacon; version, language,
    the unexplained search bit 7 and both unexplained regions are untouched."""
    gift, _ = build_wonder_card_app_data(DEFAULT_TRAINER, SESSION_ID)
    trade, _ = build_trade_app_data(DEFAULT_TRAINER, SESSION_ID)
    assert gift[:beacon.PIA_HDR] == trade[:beacon.PIA_HDR]
    gift_record, trade_record = _record(gift), _record(trade)
    differing = [i for i in range(beacon.RECORD_SIZE)
                 if gift_record[i] != trade_record[i]]
    assert differing == [beacon.SEARCH_WORD_OFFSET]
    high = _search_word(gift) & ~beacon.SEARCH_ACTIVITY_MASK
    assert high == _search_word(trade) & ~beacon.SEARCH_ACTIVITY_MASK
    assert high & beacon.SEARCH_UNKNOWN_BIT7


def test_trade_advertisement_is_unchanged_by_the_gift_host():
    """The trade host is proven on hardware and must stay bit-identical."""
    inactive, _active = build_trade_app_data(DEFAULT_TRAINER, SESSION_ID)
    record = _record(inactive)
    assert record.hex() == "2288bfc7cfffffffffff7bf1000000008415000000000000"
    assert record[beacon.SEARCH_WORD_OFFSET] & beacon.SEARCH_ACTIVITY_MASK \
        == beacon.ACTIVITY_TRADE


# --- run configuration ---------------------------------------------------------------------------
def test_default_config_selects_the_self_contained_celebi_gift():
    config = MysteryGiftRunConfig()
    assert config.payload.gift == wonder_card.GIFT_CELEBI
    assert config.payload.flag_id == 1003
    assert config.role.skip_encryption is True
    assert config.role.accept_decrypted_ccmp is False
    assert config.role.native_nonce_sequence is True
    assert config.role.session_response_first is True
    assert config.payload.receipt_flag == 0x2AA
    # The card keeps the original Celebi presentation while the registry uses
    # the composed delivery setup.
    app = MysteryGiftHostApplication.__new__(MysteryGiftHostApplication)
    app.config = config
    card, script = app._build_payload()
    assert charmap.decode(card[10:50]).startswith("CELEBI GIFT")
    assert int.from_bytes(card[2:4], "little") == wonder_card.SPECIES_CELEBI
    assert int.from_bytes(card[4:8], "little") == 3
    assert charmap.decode(card[250:290]).endswith("MercuryEnigma")
    assert len(script) == 352
    assert script != wonder_card.build_delivery_ram_script(item=None, flag_id=1003)


def test_client_ready_idle_frame_override_reaches_the_engine():
    seen = {}

    class FakeTransport:
        def __init__(self, **kwargs):
            seen["transport"] = kwargs

    run = MysteryGiftRunConfig(
        ldn=LdnConfig(phy="phy7", keys_path=__file__),
        client_ready_idle_frames=45)
    app = MysteryGiftHostApplication(
        run, transport_factory=FakeTransport, log=lambda *_args: None)
    app._build_components()

    engine = app.session.activity
    assert engine.timing.client_ready_idle_frames == 45
    assert engine.timing.inter_block_gap_frames == 12
    assert seen["transport"]["phyname"] == "phy7"


def test_max_participants_matches_the_trade_host():
    """Regression for a live failure: the console joined the LDN network and then
    never sent one Pia frame.

    ``max_participants`` is an LDN/Pia value, not the RFU group size. It sizes the
    Net 0x11 station array at ``max_stations * 22`` bytes and native FRLG always
    emits every configured slot [pia_connect.build_net_conn_request], so setting
    it to the two players a gift actually involves changes the length of the
    packet the console has to parse before it will answer.
    """
    trade_default = HostOptions().max_participants
    assert MysteryGiftRunConfig().role.max_participants == trade_default == 6

    def net_flags(max_stations):
        net = pia_connect.build_net_conn_request(
            2, 0, b"\x00" * 6, 0, ["169.254.1.1", "169.254.1.2"], max_stations=max_stations)
        body = crypto.compress(reliable.build_message(pia_connect.PROTO_NET, net))
        return ((-len(body)) % 16) << 4 | 0x03

    # The station array is the length difference, and it lands in the header's
    # pad nibble, so a wrong value is visible in the clear on the wire.
    assert net_flags(2) != net_flags(6)


def test_config_rejects_a_flag_id_outside_the_receipt_flag_table():
    """flagId maps into sReceivedGiftFlags[20] [mystery_gift.c:30]; outside that
    range the console's card would have no receipt flag to set."""
    for bad in (999, 1020, 0):
        try:
            MysteryGiftPayload(flag_id=bad)
        except ValueError:
            continue
        raise AssertionError(f"flag_id {bad} should be rejected")


# --- the HostSession activity seam ------------------------------------------------------------------
def test_session_accepts_a_mystery_gift_engine_in_place_of_a_party():
    card, ram_script = wonder_card.build_default_gift()
    engine = HostMysteryGiftEngine(card, ram_script)
    session = HostSession(engine=engine)
    assert session.activity is engine
    # The trade host and its tests reach the engine through `.trade`.
    assert session.trade is engine
    # The shared stack below the activity is built either way.
    assert session.reliable is not None and session.rfu is not None


def test_session_requires_an_activity():
    try:
        HostSession()
    except ValueError:
        return
    raise AssertionError("HostSession with neither a party nor an engine must fail")


def test_engine_exposes_the_contract_the_host_application_drives():
    card, ram_script = wonder_card.build_default_gift()
    engine = HostMysteryGiftEngine(card, ram_script)
    for name in ("tick", "feed_child_slot", "mark_disconnect_sent"):
        assert callable(getattr(engine, name)), name
    for name in ("disconnect_requested", "done", "state", "close_confirmed"):
        assert hasattr(engine, name), name
    assert engine.disconnect_requested is False and engine.done is False
    # mark_disconnect_sent must not be able to declare success early.
    try:
        engine.mark_disconnect_sent()
    except RuntimeError:
        return
    raise AssertionError("mark_disconnect_sent before the close handshake must fail")


# --- standalone runner ----------------------------------------------------------------------------
def _run():
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
