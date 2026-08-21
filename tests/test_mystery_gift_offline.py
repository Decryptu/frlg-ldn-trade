"""Offline tests for the Mystery Gift distributor work (Milestone-1 foundations + payload).

Everything here is hardware-independent: it checks the byte-exact protocol pieces built so far
against the FRLG decomp facts, with no Switch, no LDN, no root. The hardware-iterated integration
layers (Pia host FSM, NI handshake, ldn.create_network, the engine) are NOT covered here because
they can only be validated against a real console.

Run standalone (no pytest needed):   python tests/test_mystery_gift_offline.py
Or under pytest if installed:         pytest tests/test_mystery_gift_offline.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import block, charmap, gbaframe, rfu, linkplayer, wonder_card, ni, beacon, transport
from frlgsim import mystery_gift as mg


# --- CRC16 (MysteryGiftLink header checksum) -------------------------------------------------
def test_crc16_bitwise_equals_game_table():
    """crc16() must equal the game's table-driven CalcCRC16WithTable [util.c:250] for any data."""
    for sample in (b"", b"\x00", b"GameFreak inc.", bytes(range(256)), b"\xff" * 333,
                   os.urandom(500)):
        assert mg.crc16(sample) == mg._crc16_tabledriven(sample)


def test_crc16_regression_anchors():
    """Fixed values captured from the verified routine (init 0x1121, poly 0x8408, final ~crc)."""
    assert mg.crc16(b"") == 0xEEDE
    assert mg.crc16(b"\x00") == 0xCF65
    assert mg.crc16(b"GameFreak inc.") == 0xC20F
    assert mg.crc16(b"123456789") == 0xBE75


def test_mg_link_constants():
    assert mg.MG_LINKID_CLIENT_SCRIPT == 16 and mg.MG_LINKID_GAME_DATA == 17
    assert mg.MG_LINKID_CARD == 22 and mg.MG_LINKID_RAM_SCRIPT == 25 and mg.MG_LINKID_READY_END == 20
    assert mg.MG_LINK_BUFFER_SIZE == 0x400 and mg.MG_LINK_HEADER_SIZE == 6 and mg.MG_LINK_MAX_CHUNK == 252


# --- Wonder Card + delivery RAM script ----------------------------------------------------------
def test_wonder_card_size_and_validation_fields():
    """332 bytes, and the fields the console's ValidateWonderCard [mystery_gift.c:191] checks."""
    card = wonder_card.build_wonder_card(flag_id=1003, title="ENIGMA BERRY")
    assert len(card) == 332
    assert int.from_bytes(card[0:2], "little") == 1003          # flagId != 0
    assert (card[8] & 0x3) == mg.CARD_TYPE_GIFT                  # type < 3
    assert ((card[8] >> 2) & 0xF) < mg.NUM_WONDER_BGS           # bgType < 8
    assert ((card[8] >> 6) & 0x3) in (0, 1, 2)                  # sendType valid
    assert card[9] <= mg.MAX_STAMP_CARD_STAMPS                  # maxStamps <= 7


def test_wonder_card_rejects_invalid_like_the_console():
    """Builder rejects the same out-of-range fields SaveWonderCard would reject."""
    for kwargs in ({"flag_id": 0}, {"bg_type": 8}, {"card_type": 3},
                   {"send_type": 3}, {"max_stamps": 8}):
        try:
            wonder_card.build_wonder_card(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {kwargs}")


def test_delivery_ram_script_is_byte_exact():
    """The saved script has exact per-card Celebi control flow and messages."""
    expected_no_item = bytes.fromhex(
            "6a5ab8000000082bd903bb014c00000843210d800600bb0155000008"
            "79fb00320000000000000000000000"
            "7b070049007b070169007b0702d7007b0703db0029aa0229d903"
            "bd5e000008666d6c02bd89000008666d6c02bdb6000008666d6c02"
            "fd0100e6d9d7d9ddead9d800d500bdbfc6bfbcc3fedae6e3e100e8dcd900d8d9e0ddead9e6ede1d5e2abff"
            "cae0d9d5e7d900e0e3e3df00dae3e6ebd5e6d800e8e300dae9e8e9e6d9fec7d3cdcebfccd300c1c3c0cecdabff"
            "c9dcb800ede3e9e600e4d5e6e8ed00d5e4e4d9d5e6e700e8e300d6d900dae9e0e0ad"
            "fecae0d9d5e7d900e1d5dfd900e6e3e3e100d5e2d800d7e3e1d900d6d5d7dfabff")

    assert wonder_card.build_delivery_ram_script(flag_id=1003) == expected_no_item
    # An explicitly requested item keeps the standard giveitem prefix.
    item_script = wonder_card.build_delivery_ram_script(item=173, flag_id=1003)
    assert item_script.startswith(bytes.fromhex("6a5a1a0080ad001a01800100090029aa02"))
    assert len(item_script) == len(expected_no_item) + 12


def test_flag_id_maps_to_receipt_flag():
    assert wonder_card.flag_for_flag_id(1000) == 0x2A7   # FLAG_RECEIVED_AURORA_TICKET
    assert wonder_card.flag_for_flag_id(1003) == 0x2AA   # FLAG_WONDER_CARD_UNUSED_1
    for bad in (999, 1020):
        try:
            wonder_card.flag_for_flag_id(bad)
        except ValueError:
            continue
        raise AssertionError(f"flagId {bad} should be rejected")


def test_default_gift_bundle():
    """The shipped payload is a level-50 Celebi with no item."""
    card, script = wonder_card.build_default_gift()
    assert len(card) == 332 and len(script) == 251
    assert wonder_card.DEFAULT_GIFT_ITEM is None
    assert int.from_bytes(card[2:4], "little") == wonder_card.SPECIES_CELEBI
    # idNumber zero hides the top-right numeric display in WonderCard_Draw.
    assert int.from_bytes(card[4:8], "little") == 0
    assert charmap.decode(card[250:290]).endswith("MercuryEnigma")
    assert script == wonder_card.build_delivery_ram_script(item=None, flag_id=1003)


# --- Parent-side 0x54 framing (sim as leader/parent) -----------------------------------------
def test_parent_uni_echo_table_roundtrips_through_parse_in():
    """wrap_t_parent(parent_uni_slot(70B table)) must parse back into 5 mpId rows via parse_in."""
    row0 = rfu.serialize(rfu.send_player_ids_words())            # parent's own broadcast
    row1 = rfu.serialize([0x8800, 3, 0x81, 0, 0, 0, 0])         # child's reflected block-init
    table = rfu.pack_recv_cmds([row0, row1])
    assert len(table) == 70

    frame = gbaframe.wrap_t_parent(rfu.parent_uni_slot(table, bm_slot=1), ts=0x1234)
    rec = gbaframe.parse_in(frame)
    assert rec["type"] == "T" and rec["ts"] == 0x1234
    assert rec["llsf_state"] == rfu.LCOM_UNI
    slots = dict(rec["slots"])
    assert len(rec["slots"]) == 5
    assert slots[0] == row0 and slots[1] == row1 and slots[2] == b"\x00" * 14
    assert rfu.parse_slot(slots[0])["op"] == rfu.SEND_PLAYER_IDS
    assert rfu.parse_slot(slots[1])["op"] == rfu.SEND_BLOCK_INIT


def test_parent_accept_and_disconnect_frames():
    acc = gbaframe.parse_in(gbaframe.build_accept(b"\xAB\xCD", b"\x79\x67"))
    assert acc["type"] == "A" and acc["connect_id"] == b"\x79\x67"
    dis = gbaframe.parse_in(gbaframe.build_disconnect(b"\x79\x67"))
    assert dis["type"] == 0x44


# --- Parent link-opcode payloads --------------------------------------------------------------
def test_send_player_ids_payload():
    """0x7700: w1=playerCount=2, linkPlayerIdx[0]=1 (child -> mpId 1), rest 0 [link_rfu_2.c:1298]."""
    b = rfu.serialize(rfu.send_player_ids_words())
    assert b[0:2] == b"\x00\x77" and b[2:4] == b"\x02\x00"
    assert b[4:6] == b"\x01\x00" and b[6:8] == b"\x00\x00"


def test_send_block_req_none_payload():
    r = rfu.parse_slot(rfu.serialize(rfu.send_block_req_words()))
    assert r["op"] == rfu.SEND_BLOCK_REQ and r["reqtype"] == rfu.BLOCK_REQ_SIZE_NONE


def test_link_player_block_has_both_magics():
    lp = linkplayer.LinkPlayer(name="EMU", version=linkplayer.VERSION_FIRE_RED, player_id=0)
    blk = linkplayer.build_block(lp)
    assert len(blk) == 60
    parsed, ok = linkplayer.parse_block(blk)
    assert ok and parsed.name == "EMU" and parsed.version == linkplayer.VERSION_FIRE_RED


def test_trade_animation_partner_name_is_terminated_and_identity_aligned():
    """The trade animation's ``{STR_VAR_1}`` is copied directly from
    ``gLinkPlayers[GetMultiplayerId() ^ 1].name`` (trade_scene.c).  Lock the
    exact LinkPlayer name/language offsets and the matching trainer-card name
    so a layout or character-map regression cannot turn the destination name
    in ``"{MON} will be sent to {TRAINER}"`` into unterminated text.
    """
    lp = linkplayer.LinkPlayer(
        name="EMU", trainer_id=0x47ED8822,
        version=linkplayer.VERSION_LEAF_GREEN,
        player_id=0, language=linkplayer.LANGUAGE_ENGLISH,
    )
    packed = lp.pack()
    assert packed[8:16] == bytes.fromhex("bfc7cfff00000000")
    assert packed[26:28] == b"\x02\x00"
    assert packed[8:16].index(charmap.EOS) == 3

    card = linkplayer.build_trainer_card(lp)
    assert card[linkplayer.TC_OFF_PLAYER_NAME:
                linkplayer.TC_OFF_PLAYER_NAME + 8] == packed[8:16]


def test_200_byte_link_player_transfer_cannot_overwrite_name_with_tail_fragment():
    """The RFU NONE request transfers a 60-byte LinkPlayerBlock in a fixed
    200-byte buffer (17 twelve-byte fragments).  Model the Switch receiver's
    offset calculation, including repeated INIT and fragment 16, and prove the
    140-byte tail cannot overlap the display-name field in fragment 2.
    """
    lp = linkplayer.LinkPlayer(name="EMU", player_id=0)
    sent = linkplayer.build_block(lp).ljust(200, b"\x00")
    sender = block.BlockSender(sent, owner=0, trust_pia=True)
    recv = block.RecvBlock()

    # The live 8.3 trace carried four INIT polls before fragments 0..16.
    for _ in range(4):
        recv.on_init(sender.count, 0x80)
    while not sender.done:
        cmd = rfu.parse_slot(rfu.serialize(sender.tick(None)))
        if cmd["op"] == rfu.SEND_BLOCK:
            recv.on_block(cmd["index"], cmd["frag"])

    assert recv.done
    assert recv.data()[:200] == sent
    # gBlockRecvBuffer offset 16*12=192: the final fragment is only padding.
    assert recv.data()[192:204] == b"\x00" * 12
    parsed, ok = linkplayer.parse_block(recv.data())
    assert ok and parsed.name == "EMU"


# --- Parent NI handshake (sender = join status; receiver = ack + reassemble child game data) --
def test_ni_send_sequence_matches_verified_child_sender():
    """The shared _ni_send_sequence must reproduce the byte-verified child NISender frame-for-frame
    (this is what lets ParentNISender reuse it with confidence)."""
    src = ni.build_game_data(5, 0x2288, "EMU")
    sender = ni.NISender(src)
    got = []
    while not sender.done:
        slot = sender.next_slot()
        if slot is None:
            break
        got.append(slot)
    seq = ni._ni_send_sequence(src, data_type=1, payload_size=12)
    rebuilt = [rfu.child_ni_llsf(st, n, ph, 0, sz) + pay for (st, n, ph, sz, pay) in seq]
    assert got == rebuilt
    assert len(got) == 6                              # NI_START + 3xNI + NI_END + NULL


def test_parent_ni_sender_join_status_frames():
    """PARENT NI sender for the 1-byte join status: two NI_STARTs (payloadSize 5 < 7-byte header),
    one NI (the status), NI_END, NULL — byte-exact in 3-byte PARENT LLSF."""
    sender = ni.ParentNISender(status=ni.RFU_STATUS_JOIN_GROUP_OK)
    got = []
    while not sender.done:
        got.append(sender.next_slot())
    hdr = ni._ni_header(0, 5, 1)                      # dataType 0, payloadSize 5, dataSize 1
    expected = [
        rfu.parent_ni_llsf(rfu.LCOM_NI_START, 1, 0, 0, 5, 1) + hdr[0:5],
        rfu.parent_ni_llsf(rfu.LCOM_NI_START, 2, 0, 0, 2, 1) + hdr[5:7],
        rfu.parent_ni_llsf(rfu.LCOM_NI, 1, 0, 0, 1, 1) + bytes([5]),
        rfu.parent_ni_llsf(rfu.LCOM_NI_END, 0, 0, 0, 0, 1),
        rfu.parent_ni_llsf(rfu.LCOM_NULL, 1, 0, 0, 0, 1),
    ]
    assert got == expected


def test_child_acks_of_parent_ni_match_reference_capture():
    """Round-trip: wrap each ParentNISender frame in a HOST 'T', parse_in it, feed the child's
    NIReceiver — the child's recv-ack sequence must equal the reference capture (8006/0007/800a/000e),
    and the child must read the join status 5. Exercises wrap_t_parent + parse_in on NI frames too."""
    sender = ni.ParentNISender()
    recv = ni.NIReceiver()
    acks, ts = [], 1
    while not sender.done:
        rec = gbaframe.parse_in(gbaframe.wrap_t_parent(sender.next_slot(), ts))
        ts += 1
        assert rec["type"] == "T"
        ack = recv.on_host_ni(rec.get("ni"))
        if ack is not None:
            acks.append(ack.hex())
    assert acks == ["8006", "0007", "800a", "000e"]
    assert recv.status == ni.RFU_STATUS_JOIN_GROUP_OK
    assert recv.complete


def test_parent_ni_receiver_acks_and_reassembles_child_game_data():
    """PARENT NI receiver: ack the console-child's game-data NI (mirror state/n/phase, ack=1, sz=0 in
    PARENT LLSF) and reassemble the 26-byte RfuGameData with the child's trainer id + uname."""
    src = ni.build_game_data(5, 0x2288, "EMU")
    child = ni.NISender(src)                          # models the console acting as RFU child
    recv = ni.ParentNIReceiver()
    acks = []
    while not child.done:
        slot = child.next_slot()
        if slot is None:
            break
        ack = recv.on_child_ni(ni.decode_child_ni_slot(slot))
        if ack is not None:
            acks.append(ack)
    assert recv.complete
    assert recv.game_data == src
    assert recv.data_type == 1 and recv.data_size == 26 and recv.payload_size == 12
    assert recv.trainer_id == 0x2288
    assert recv.uname == src[17:26]
    expected_acks = [                                 # NULL is NOT acked -> 5 acks for 6 child frames
        rfu.parent_ni_llsf(rfu.LCOM_NI_START, 1, 0, 1, 0, 1),
        rfu.parent_ni_llsf(rfu.LCOM_NI, 1, 0, 1, 0, 1),
        rfu.parent_ni_llsf(rfu.LCOM_NI, 1, 1, 1, 0, 1),
        rfu.parent_ni_llsf(rfu.LCOM_NI, 1, 2, 1, 0, 1),
        rfu.parent_ni_llsf(rfu.LCOM_NI_END, 0, 0, 1, 0, 1),
    ]
    assert acks == expected_acks


# --- Host beacon encoder (inverse of transport._dump_beacon / _b85_decode) --------------------
def test_b85_encode_inverts_decode():
    """beacon.b85_encode must be the exact inverse of transport._b85_decode for 4-byte groups."""
    for data in (bytes(range(24)), b"\x00\x00\x00\x00", b"\xff" * 24, os.urandom(24)):
        assert transport._b85_decode(beacon.b85_encode(data))[:len(data)] == data


def test_beacon_record_round_trips_through_dump_decoder():
    """build_beacon's RFU record must decode back to the same fields transport._dump_beacon reads
    (trainer id, name, RFU session id, tradeSpecies) — the only fields the decoder proves."""
    app = beacon.build_beacon(trainer_id=0x2288, name="EMU", rfu_session_id=beacon.RFU_SERIAL_GAME,
                              trade_species=277)
    assert len(app) == beacon.PIA_HDR + 30                 # 0x5C header + base85(24B) = 30 chars
    rec = transport._b85_decode(app[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]
    assert int.from_bytes(rec[0:2], "little") == 0x2288
    assert transport._frlg_name(rec[2:10]) == "EMU"
    assert int.from_bytes(rec[10:12], "little") == beacon.RFU_SERIAL_GAME
    assert int.from_bytes(rec[20:24], "little") >> 16 == 277


def test_beacon_has_card_and_activity_bits_present():
    """The game-data word carries the hasCard bit and activity nibble (positions are live-tuned, but
    they must at least be encoded so there is something to calibrate)."""
    gd = beacon.game_data_word(activity=beacon.ACTIVITY_WONDER_CARD, has_card=True)
    assert gd & beacon.HASCARD_BIT                          # gname[0] |= 0x20
    assert (gd >> 8) & 0x7F == beacon.ACTIVITY_WONDER_CARD  # activity in the compat high byte (first cut)


def test_trade_beacon_activity_has_no_wonder_card_bit():
    gd = beacon.game_data_word(activity=beacon.ACTIVITY_TRADE, has_card=False)
    assert (gd >> 8) & 0x7F == beacon.ACTIVITY_TRADE
    assert not gd & beacon.HASCARD_BIT


def test_pia_header_matches_wiki_layout_and_round_trips():
    """Pia 6.16-6.41 header (sysCommVer 21-22, big-endian) per the NintendoClients wiki: size 0x5C at
    0x00, sysCommVer at 0x02, big-endian fields, name at 0x1C; decode is the inverse of build."""
    h = beacon.build_pia_header(sys_comm_ver=21, app_comm_ver=1, nickname="Chase",
                                name_encoding=beacon.PIA_NAME_UTF8)
    assert len(h) == beacon.PIA_HDR == 0x5C
    assert int.from_bytes(h[0x00:0x02], "big") == 0x5C     # big-endian size
    assert h[0x02] == 21                                    # sys comm version
    assert int.from_bytes(h[0x03:0x05], "big") == 1        # app comm version (big-endian)
    assert h[0x15] == 1 and h[0x16] == 1                    # player limit enabled, num players
    assert h[0x1B] == beacon.PIA_NAME_UTF8
    d = beacon.decode_pia_header(h)
    assert d["size"] == 0x5C and d["sys_comm_ver"] == 21 and d["app_comm_ver"] == 1
    assert d["nickname"] == "Chase" and d["name_size"] == 5


def test_build_beacon_uses_real_pia_header_by_default():
    """build_beacon now emits a well-formed Pia header (not zeros); the record still round-trips."""
    app = beacon.build_beacon(trainer_id=0x2288, name="EMU", nickname="Chase")
    assert app[:0x5C] != b"\x00" * 0x5C                     # no longer zero-filled
    assert beacon.decode_pia_header(app[:0x5C])["sys_comm_ver"] == beacon.PIA_SYS_COMM_VERSION
    rec = transport._b85_decode(app[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]
    assert transport._frlg_name(rec[2:10]) == "EMU"


def test_mutate_beacon_preserves_header_changes_record():
    """mutate_beacon keeps a captured Pia header verbatim and only rewrites overridden RFU fields."""
    captured = bytes(range(beacon.PIA_HDR)) + beacon.b85_encode(
        beacon.build_record(trainer_id=0x1111, name="ABC", rfu_session_id=9))
    out = beacon.mutate_beacon(captured, name="EMU", trainer_id=0x2288)
    assert out[:beacon.PIA_HDR] == captured[:beacon.PIA_HDR]     # header untouched
    rec = transport._b85_decode(out[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]
    assert transport._frlg_name(rec[2:10]) == "EMU" and int.from_bytes(rec[0:2], "little") == 0x2288
    assert int.from_bytes(rec[10:12], "little") == 9            # not overridden -> preserved


# --- Hosting preflight (iw-phy AP-mode check) + trace harness ---------------------------------
_IW_MT7601U = """Wiphy phy0
	max # scan SSIDs: 4
	Supported interface modes:
		 * managed
		 * monitor
	software interface modes (can always be added):
		 * monitor
	Supported commands:
		 * new_interface
"""

_IW_MT76X2U = """Wiphy phy1
	Supported interface modes:
		 * managed
		 * AP
		 * monitor
		 * mesh point
	software interface modes (can always be added):
		 * monitor
	valid interface combinations:
		 * #{ managed, AP, mesh point } <= 2, #{ IBSS } <= 1,
"""


def test_preflight_rejects_mt7601u_with_clear_verdict():
    """The MT7601U case: managed+monitor only -> one clear RuntimeError, not ENOTSUP walls."""
    modes, soft = transport._parse_iw_modes(_IW_MT7601U)
    assert modes == ["managed", "monitor"] and soft == ["monitor"]
    try:
        transport.preflight_host("phy0", log=lambda *a: None, _iw_output=_IW_MT7601U)
    except RuntimeError as e:
        assert "no AP mode" in str(e) and "AP-capable adapter" in str(e)
    else:
        raise AssertionError("preflight should reject a phy without AP mode")


def test_preflight_accepts_ap_capable_phy():
    modes, _soft = transport._parse_iw_modes(_IW_MT76X2U)
    assert "AP" in modes
    assert transport.preflight_host("phy1", log=lambda *a: None, _iw_output=_IW_MT76X2U) is True


def test_tracer_writes_jsonl(tmp_path=None):
    """ldntrace.Tracer writes one JSON object per line with rec/kind/ts, and a closing summary."""
    import json
    import tempfile
    from frlgsim import ldntrace
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "trace.jsonl")
        tr = ldntrace.Tracer(path, log=lambda *a: None)
        tr.write("udp_out", dst="169.254.1.255", hex="5c00")
        tr.write("advert", nonce="00000001", hex="7f0022aa")
        tr.close()
        recs = [json.loads(line) for line in open(path)]
    kinds = [r["kind"] for r in recs]
    assert kinds == ["udp_out", "advert", "summary"]
    assert all(r["rec"] == "trace" and "ts" in r for r in recs)
    assert recs[0]["hex"] == "5c00" and recs[2]["counts"]["advert"] == 1


# --- standalone runner (no pytest) ------------------------------------------------------------
def _run():
    tests = sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f))
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as e:                                  # noqa: BLE001 - report and continue
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
