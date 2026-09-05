"""Mystery Gift CLIENT (frlgsim.mg_client) driven against our own Mystery Gift HOST.

Row-level, no radio, no Pia: one parent row and one child row per tick, the parent echoing
the child's previous row in gRecvCmds row 1 (the reflection the child's BlockSender acks on).
The host engine is the one proven on retail hardware, so a client that completes here speaks
the same block/message protocol a console does.
"""

from frlgsim import host_mystery_gift, linkplayer, mg_client, mg_script, rfu, wonder_card
from frlgsim import mystery_gift as mg


def _drive(client, *, holding=None, flag_id=1005, ticks=6000):
    card, ram_script = wonder_card.build_legendary_beast_cutscene_gift(flag_id=flag_id)
    host = host_mystery_gift.HostMysteryGiftEngine(
        card, ram_script,
        link_player=linkplayer.LinkPlayer(name="EMU", version=linkplayer.VERSION_FIRE_RED),
        timing=host_mystery_gift.MysteryGiftTiming(client_ready_idle_frames=10))
    slot = rfu.SlotBuilder()
    child_slot = rfu.idle_slot()
    for t in range(ticks):
        parent_cmd = rfu.serialize(host.tick())
        table = rfu.pack_recv_cmds([parent_cmd, child_slot])
        rec = {"type": "T", "ts": t, "slot_len": 73, "llsf_state": 4,
               "slots": [(m, table[m * 14:(m + 1) * 14]) for m in range(2)], "payload": table}
        rec["positional"] = rec["slots"]
        client.feed_in_frame(rec)
        child_slot = slot.build(client.tick() or [0] * 7)
        host.feed_child_slot(child_slot)
        if host.disconnect_requested:
            host.mark_disconnect_sent()
            return host, t
    raise AssertionError(f"flow did not finish: host={host.state} client={client.status()}")


def _client(**kw):
    return mg_client.MysteryGiftClientEngine(
        linkplayer.LinkPlayer(name="PkCamp", version=linkplayer.VERSION_FIRE_RED), **kw)


def test_client_receives_card_and_ram_script_and_closes():
    client = _client()
    host, ticks = _drive(client)
    assert client.established
    assert client.result == mg_script.CLI_MSG_CARD_RECEIVED
    assert host.gift_sent
    assert len(client.saved_card) == 332
    assert int.from_bytes(client.saved_card[0:2], "little") == 1005
    assert client.saved_ram_script is not None and len(client.saved_ram_script) == 1024
    assert client.close_confirmed and client.done
    idents = [(d, ident) for _t, d, ident, _s, _p in client.messages]
    assert idents == [("in", mg.MG_LINKID_CLIENT_SCRIPT), ("out", mg.MG_LINKID_GAME_DATA),
                      ("in", mg.MG_LINKID_CLIENT_SCRIPT), ("in", mg.MG_LINKID_CARD),
                      ("in", mg.MG_LINKID_RAM_SCRIPT), ("out", mg.MG_LINKID_READY_END)]
    assert ticks < 1500


def test_client_holding_the_same_card_is_told_had_card():
    client = _client(holding_flag_id=1005)
    host, _ = _drive(client)
    assert client.result == mg_script.CLI_MSG_HAD_CARD
    assert client.saved_card is None and not host.gift_sent


def test_client_holding_a_different_card_accepts_the_replacement():
    client = _client(holding_flag_id=1001)
    host, _ = _drive(client)
    assert client.result == mg_script.CLI_MSG_CARD_RECEIVED
    assert host.gift_sent and client.saved_card is not None
    responses = [p for _t, d, i, _s, p in client.messages if d == "out" and i == mg.MG_LINKID_RESPONSE]
    assert responses == [(0).to_bytes(4, "little")]      # FALSE = toss the old card


def test_client_keeping_its_card_gets_the_canceled_message():
    client = _client(holding_flag_id=1001, accept_replacement=False)
    host, _ = _drive(client)
    assert client.result == mg_script.CLI_MSG_BUFFER_FAILURE
    assert client.saved_card is None and not host.gift_sent
    assert client.dynamic_msg is not None
    assert client.dynamic_msg.startswith(mg_script.TEXT_CANCELED_READING_CARD[:10])


def test_link_game_data_matches_what_the_console_validates():
    data = mg_client.build_link_game_data(
        linkplayer.LinkPlayer(name="PkCamp", trainer_id=0x47ED8822),
        version_code=mg.VERSION_CODE_FIRERED, flag_id=1017, game_code=b"BPRF")
    parsed = mg_script.parse_link_game_data(data)
    assert mg_script.validate_link_game_data(parsed)
    assert parsed.flag_id == 1017 and parsed.player_name == "PkCamp"
    assert parsed.trainer_id == 0x47ED8822 and parsed.game_code == b"BPRF"
    assert parsed.version_name == "FireRed"


def test_client_advertises_the_wonder_card_activity():
    client = _client()
    assert client.ni_activity == 21 and client.ni_started is False
    assert client.in_seat_phase and not client.host_in_seat
