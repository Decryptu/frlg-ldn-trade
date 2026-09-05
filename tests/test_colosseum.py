"""The cable-club colosseum host: the advertisement, the extra LinkPlayer record, the battle.

Every assertion here is a decomp fact; see frlgsim/cable_club.py and
docs/mystery_gift_untried.md. NOTHING here is hardware-proven yet: no run has advertised
ACTIVITY_BATTLE_SINGLE.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import beacon, cable_club, linkplayer, transport, trade  # noqa: E402
from frlgsim import uroom_battle as ub  # noqa: E402
from frlgsim.config import DEFAULT_TRAINER  # noqa: E402
from frlgsim.host_beacon import build_colosseum_app_data, build_trade_app_data  # noqa: E402
from frlgsim.host_trade import (  # noqa: E402
    H_CC_BATTLE_ENTRY, H_UROOM_BATTLE_LINK, HostTradeEngine,
)

SESSION_ID = b"\x7b\xf1"


def _mon():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scratchpad", "TREECKO.pk3")
    if not os.path.exists(path):
        pytest.skip("scratchpad/TREECKO.pk3 is not in this checkout")
    from frlgsim import mon as monmod
    return monmod.Mon.from_file(path)


def _search_word(app_data):
    record = transport._b85_decode(app_data[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]
    return int.from_bytes(
        record[beacon.SEARCH_WORD_OFFSET:beacon.SEARCH_WORD_OFFSET + 2], "little")


# --- the advertisement ------------------------------------------------------------------------

def test_the_activity_constant_matches_the_decomp():
    """sAcceptedActivityIds_SingleBattle[] = {ACTIVITY_BATTLE_SINGLE, 0xFF}
    [src/data/union_room.h:398], and ACTIVITY_BATTLE_SINGLE is 1
    [include/constants/union_room.h:22]."""
    assert beacon.ACTIVITY_BATTLE_SINGLE == 1


def test_the_colosseum_beacon_advertises_the_single_battle_activity():
    inactive, _active = build_colosseum_app_data(DEFAULT_TRAINER, SESSION_ID)
    activity = _search_word(inactive) & beacon.SEARCH_ACTIVITY_MASK
    assert activity == beacon.ACTIVITY_BATTLE_SINGLE


def test_the_trade_beacon_is_invisible_on_the_colosseum_screen():
    """The console searching with LINK_GROUP_SINGLE_BATTLE keeps a candidate only if
    IsPartnerActivityAcceptable matches its one-entry accept list [union_room.c:1590]."""
    trade_word = _search_word(build_trade_app_data(DEFAULT_TRAINER, SESSION_ID)[0])
    assert trade_word & beacon.SEARCH_ACTIVITY_MASK == beacon.ACTIVITY_TRADE
    assert beacon.ACTIVITY_TRADE != beacon.ACTIVITY_BATTLE_SINGLE


# --- the extra 28-byte LinkPlayer record ------------------------------------------------------

def test_the_cable_club_record_is_the_bare_struct_without_the_magics():
    """SendBlock(0, &gLocalLinkPlayer, sizeof(gLocalLinkPlayer)) [cable_club.c:701] sends the
    struct itself; the 60-byte LinkPlayerBlock of the entry wraps it in two GameFreak magics."""
    lp = DEFAULT_TRAINER.to_link_player()
    blk = cable_club.local_link_player_block(lp)
    assert len(blk) == cable_club.LOCAL_SIZE == 28
    assert b"GameFreak" not in blk
    assert cable_club.read_local_link_player(blk).trainer_id == lp.trainer_id


def test_the_block_count_is_the_rfu_fragment_count():
    """`size / 12 + (size % 12 != 0)` [Rfu_InitBlockSend, link_rfu_2.c:1349]."""
    assert cable_club.COUNT_LOCAL == 28 // 12 + 1 == 3


def test_a_short_record_is_rejected_rather_than_read_short():
    with pytest.raises(ValueError):
        cable_club.read_local_link_player(bytes(20))


# --- the engine -------------------------------------------------------------------------------

def _engine(party=None, **kw):
    kw.setdefault("colosseum", True)
    h = HostTradeEngine(party or [_mon()], trade_slot=0, **kw)
    h._words.clear()
    h._blocks.clear()
    return h


def _sent(h):
    return [data for data, _ in h._blocks]


def test_the_colosseum_cannot_be_hosted_from_the_union_room():
    with pytest.raises(ValueError):
        HostTradeEngine([_mon()], trade_slot=0, colosseum=True, union_room=True)


def test_the_card_standby_arms_the_battle_entry_without_waiting_for_a_seat():
    """cc1: the console fades to black on its spot and parks in Task_StartWirelessCableClubBattle
    case 3 waiting for our record. The trade centre's post-seat standby rounds never come, so
    gating on them deadlocked both sides."""
    from frlgsim.host_trade import H_ENTRY_CARD
    h = _engine()
    h._set_state(H_ENTRY_CARD)
    h._expected = "warp1"
    h._on_child_standby(1)
    assert h.state == H_CC_BATTLE_ENTRY and h._expected == "cc_link_player"
    assert h._held_label == "COLOSSEUM_SPOT"


def test_the_trade_host_still_takes_its_seat_at_that_standby():
    from frlgsim.host_trade import H_ENTRY_CARD, H_ENTRY_SEAT
    h = _engine(colosseum=False)
    h._set_state(H_ENTRY_CARD)
    h._expected = "warp1"
    h._on_child_standby(1)
    assert h.state == H_ENTRY_SEAT and h._expected == "warp2"


def test_the_seat_opens_the_battle_entry_instead_of_the_trade_menu():
    h = _engine()
    h._begin_seated_activity()
    assert h.state == H_CC_BATTLE_ENTRY and h._expected == "cc_link_player"
    assert _sent(h) == []


def test_the_trade_host_still_opens_its_party_exchange_there():
    from frlgsim.host_trade import H_PARTY
    h = _engine(colosseum=False)
    h._begin_seated_activity()
    assert h.state == H_PARTY


def test_the_whole_entry_runs_block_for_block():
    """cc_link_player -> the 31-byte header -> three 200-byte party blocks -> the controller."""
    h = _engine()
    h._begin_seated_activity()

    theirs = DEFAULT_TRAINER.to_link_player()
    theirs.trainer_id = 0xE5BBDF65
    h._after_child_block(cable_club.COUNT_LOCAL, cable_club.local_link_player_block(theirs))
    assert _sent(h) == [cable_club.local_link_player_block(h.lp, name_pad=0xFF)]
    assert h._expected == "battle_header"
    assert h.child_link_player.trainer_id == 0xE5BBDF65

    h._blocks.clear()
    h._after_child_block(ub.COUNT_HEADER, ub.battler_header(ub.VERSION_FIRERED))
    assert _sent(h) == [ub.battler_header(party_count=1)]
    assert h._expected == "battle_party:0"

    for i in range(3):
        h._blocks.clear()
        h._after_child_block(trade.COUNT_PARTY, bytes(200))
    assert h.state == H_UROOM_BATTLE_LINK and h._expected == "battle_link"
    assert h.battle is not None and len(h.battle.mons) == 1


def test_the_whole_party_fights_not_just_two():
    """There is no selection step: Task_StartActivity sends the party as it stands
    [union_room.c:1903], unlike SetUpPartiesAndStartBattle in the room."""
    party = [_mon() for _ in range(4)]
    h = _engine(party=party)
    h._begin_seated_activity()
    h._after_child_block(cable_club.COUNT_LOCAL,
                         cable_club.local_link_player_block(DEFAULT_TRAINER.to_link_player()))
    h._blocks.clear()
    h._after_child_block(ub.COUNT_HEADER, ub.battler_header(ub.VERSION_FIRERED))
    assert _sent(h) == [ub.battler_header(party_count=4)]
    expected = ub.party_blocks(party, limit=6)
    for i in range(3):
        h._blocks.clear()
        h._after_child_block(trade.COUNT_PARTY, bytes(200))
        assert _sent(h) == [expected[i]]
    assert len(h.battle.mons) == 4


def test_the_union_room_battle_still_refuses_more_than_two():
    with pytest.raises(ValueError):
        ub.party_blocks([_mon()] * 3)


def test_our_trainer_id_is_the_one_the_counter_records():
    """MysteryGift_TryIncrementStat(CARD_STAT_BATTLES_WON, gLinkPlayers[id ^ 1].trainerId)
    [cable_club.c:794], and IncrementCardStatForNewTrainer counts an id once
    [mystery_gift.c:630] - so three wins need three --id values, carried by this block."""
    from frlgsim import config as configmod
    profile = configmod.profile_from_overrides(trainer_id=(1234, 4321))
    h = HostTradeEngine([_mon()], trade_slot=0, colosseum=True, profile=profile)
    blk = cable_club.local_link_player_block(h.lp)
    assert cable_club.read_local_link_player(blk).trainer_id == (4321 << 16) | 1234


def test_a_forfeit_is_still_a_win_for_the_console():
    """HandleAction_Run sets B_OUTCOME_WON on the other side and ORs B_OUTCOME_LINK_BATTLE_RAN
    [battle_main.c:4300], but HandleEndTurn_BattleWon clears that bit before
    CB2_ReturnFromCableClubBattle switches on the outcome [battle_main.c:3734], so the plain
    B_OUTCOME_WON case is what runs. Our default forfeit therefore still moves battlesWon."""
    from frlgsim import battle_link as bl
    h = _engine()
    h._begin_seated_activity()
    h._after_child_block(cable_club.COUNT_LOCAL,
                         cable_club.local_link_player_block(DEFAULT_TRAINER.to_link_player()))
    h._after_child_block(ub.COUNT_HEADER, ub.battler_header(ub.VERSION_FIRERED))
    for _ in range(3):
        h._after_child_block(trade.COUNT_PARTY, bytes(200))
    assert h.battle.forfeit is True
    out = h.battle.feed(bl.build(bl.BUFFER_A, bl.OUR_BATTLER, bytes([bl.CHOOSEACTION, 0, 0, 0])))
    reply = bl.parse(out[0])
    assert reply["payload"][:2] == bytes([bl.TWORETURNVALUES, bl.B_ACTION_RUN])


# --- the host application and the CLI ---------------------------------------------------------

def _advertised_activity(**options):
    """Drive the real HostApplication._build_components and read what it puts on the air."""
    import tempfile
    from frlgsim import config as configmod, mevent_pokemon
    from frlgsim.host_app import HostApplication

    seen = {}

    class FakeTransport:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "PARTY1.pk3")
    with open(path, "wb") as handle:
        handle.write(mevent_pokemon.build_party_mon(129, 5, nickname="CARPY").party_bytes())
    run = configmod.TradeRunConfig(
        DEFAULT_TRAINER,
        configmod.TradePlan(party_paths=(path,), trade_slot=0, offered_slots=(0,),
                            trust_pia=True),
        configmod.LdnConfig(phy="phy7", keys_path=__file__),
        configmod.HostOptions(**options))
    app = HostApplication(run, transport_factory=FakeTransport, log=lambda *_a: None,
                          injector_factory=lambda **unused: None)
    app._build_components()
    return seen["app_data"], app


def test_the_host_app_advertises_the_battle_activity_only_with_the_option():
    app_data, app = _advertised_activity(colosseum=True)
    assert _search_word(app_data) & beacon.SEARCH_ACTIVITY_MASK == beacon.ACTIVITY_BATTLE_SINGLE
    assert app.session.activity.colosseum is True
    app_data, app = _advertised_activity()
    assert _search_word(app_data) & beacon.SEARCH_ACTIVITY_MASK == beacon.ACTIVITY_TRADE
    assert app.session.activity.colosseum is False


def test_the_cli_flag_reaches_the_options_and_keeps_the_slot_valid():
    """--colosseum offers nothing, so the trade slot only has to index the party; the default
    --slot 1 must not fail a one-mon battle party."""
    import frlgtrade_host
    parser = frlgtrade_host.build_parser(
        __import__("frlgsim.config", fromlist=["config"]).HostFileConfig())
    args = parser.parse_args(["--colosseum", "--card-flag-id", "1005", "CARPY.pk3"])
    run = frlgtrade_host.build_run_config(parser, args)
    assert run.role.colosseum is True
    assert run.profile.card_flag_id == 1005
    assert run.plan.trade_slot == 0 and run.plan.offered_slots == (0,)


def test_the_colosseum_and_the_union_room_are_refused_together_at_the_cli():
    import frlgtrade_host
    parser = frlgtrade_host.build_parser(
        __import__("frlgsim.config", fromlist=["config"]).HostFileConfig())
    args = parser.parse_args(["--colosseum", "--union-room", "CARPY.pk3"])
    with pytest.raises(SystemExit):
        frlgtrade_host.build_run_config(parser, args)


def test_the_seat_route_keeps_the_ready_key_and_drops_the_trade_centre_walk():
    """Only READY gates GetCableClubPartnersReady [overworld.c:2989]; the walk in
    ENTRY_LEFT_CHAIR_ROUTE is the TRADE CENTRE's map and would be wrong here."""
    from frlgsim.host_trade import (
        COLOSSEUM_SPOT_ROUTE, ENTRY_LEFT_CHAIR_ROUTE, LINK_KEY_EMPTY, LINK_KEY_READY,
    )
    keys = {key for key, _held in COLOSSEUM_SPOT_ROUTE}
    assert keys == {LINK_KEY_EMPTY, LINK_KEY_READY}
    assert sum(held for key, held in COLOSSEUM_SPOT_ROUTE if key == LINK_KEY_READY) == 1
    # the settling idle before it is the native leader's, unchanged
    assert COLOSSEUM_SPOT_ROUTE[0] == ENTRY_LEFT_CHAIR_ROUTE[0]


def test_the_engine_plays_the_colosseum_route_at_the_seat():
    from frlgsim.host_trade import COLOSSEUM_SPOT_ROUTE, ENTRY_LEFT_CHAIR_ROUTE
    h = _engine()
    h._start_entry_route()
    assert h._held_label == "COLOSSEUM_SPOT"
    assert len(h._held_plan) == sum(held for _key, held in COLOSSEUM_SPOT_ROUTE)
    h = _engine(colosseum=False)
    h._start_entry_route()
    assert h._held_label == "ENTRY_LEFT_CHAIR"
    assert len(h._held_plan) == sum(held for _key, held in ENTRY_LEFT_CHAIR_ROUTE)


def test_the_console_leaving_the_colosseum_is_answered_with_our_own_exit_key():
    """cc2/cc3: the console's door script waits for every player to reach
    PLAYER_LINK_STATE_EXITING_ROOM [overworld.c:2977]; unanswered, it sits on "veuillez patienter"
    until the link errors."""
    from frlgsim.host_trade import H_EXIT, H_UROOM_BATTLE_LINK, LINK_KEY_EXIT_ROOM
    h = _engine()
    h._set_state(H_UROOM_BATTLE_LINK)
    h._child_send_held_keys({"keycode": LINK_KEY_EXIT_ROOM})
    assert h.state == H_EXIT
    assert h._held_label == "EXIT_ROOM_KEY"
    assert h._child_exit_seen is True
