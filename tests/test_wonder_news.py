#!/usr/bin/env python3
"""The Wonder News half of the Mystery Gift menu.

The console's Mystery Gift screen is two axes - {Wonder Cards, Wonder News} x {Wireless, Friend} - and
until now this project only ever served Cards x Friend. News is a different server script over the
same link: 444 bytes with no flagId, no metadata and no delivery script, and the console answers with
its own verdict on whether it kept them [sServerScript_SendNews, decomp:src/mystery_gift_scripts.c:126].

Two things decide whether a hardware run can work at all, and both are checked here:

* the advertisement's activity byte must be ACTIVITY_WONDER_NEWS (22). The console's Friend listen
  task keeps only candidates whose activity is in the accept list of the link group it is searching
  [sAcceptedActivityIds_WonderNews, src/data/union_room.h:406; IsPartnerActivityAcceptable,
  union_room.c:1590], so a Wonder Card beacon is simply invisible on the News screen.
* the server must read MG_LINKID_RESPONSE after the news and branch on it. TRUE means the console
  already held exactly these bytes and kept them; only FALSE reaches sClientScript_NewsReceived, and
  only that message makes the console save and set the berry reward [mystery_gift_menu.c:1367].

Run standalone (no pytest needed):   python tests/test_wonder_news.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import (  # noqa: E402
    beacon, config as configmod, host_beacon, host_mg_app, host_mystery_gift, mg_client,
    mg_script, mg_server, stamp_rally, transport, wonder_news,
)
from frlgsim import mystery_gift as mg  # noqa: E402
from tests.test_mystery_gift_flow import ConsoleClientModel, _drive  # noqa: E402


def _news(**overrides):
    return wonder_news.PKCAMP_NEWS.build(**overrides)


def _distribution(news=None):
    return stamp_rally.MysteryGiftDistribution(
        None, None, news=_news() if news is None else news)


# --- the struct -----------------------------------------------------------------------------
def test_the_news_struct_is_the_444_byte_layout_the_console_memcpys():
    news = _news()
    assert len(news) == wonder_news.WONDER_NEWS_SIZE == 444
    # u16 id; u8 sendType; u8 bgType; u8 titleText[40]; u8 bodyText[10][40] [global.h:646].
    assert int.from_bytes(news[0:2], "little") == wonder_news.PKCAMP_NEWS.news_id
    assert news[2] == wonder_news.PKCAMP_NEWS.send_type
    assert news[3] == wonder_news.PKCAMP_NEWS.bg_type
    assert 4 + 40 + 10 * 40 == wonder_news.WONDER_NEWS_SIZE
    parsed = wonder_news.parse(news)
    assert parsed["title"] == wonder_news.PKCAMP_NEWS.title
    assert parsed["body"][:len(wonder_news.PKCAMP_NEWS.body)] == wonder_news.PKCAMP_NEWS.body
    # Every 40-byte text field is EOS-terminated and 0xFF-padded, exactly as the card's are; the
    # console reads them with a fixed memcpy and appends its own EOS [mystery_gift_show_news.c:338].
    title = news[4:44]
    assert title[len(parsed["title"])] == 0xFF and set(title[len(parsed["title"]):]) == {0xFF}
    assert set(news[44 + 3 * 40:44 + 4 * 40]) == {0xFF}   # the deliberately blank body line


def test_validate_is_the_console_rule_and_nothing_more():
    """ValidateWonderNews checks only id != 0 [decomp:src/mystery_gift.c:113]."""
    assert wonder_news.validate(_news())
    assert not wonder_news.validate(b"\x00\x00" + _news()[2:])
    assert not wonder_news.validate(_news()[:-1])
    for bad in (0, 0x10000):
        try:
            wonder_news.build_wonder_news(news_id=bad, title="X")
        except ValueError:
            pass
        else:
            raise AssertionError(f"news id {bad} should be rejected")


def test_a_ten_line_news_fills_every_body_slot():
    news = wonder_news.BERRY_NEWS.build()
    body = wonder_news.parse(news)["body"]
    assert len(body) == wonder_news.WONDER_NEWS_BODY_TEXT_LINES == 10
    # A line past index 7 is what arms the console's scroll indicator
    # [decomp:src/mystery_gift_show_news.c:346].
    assert body[wonder_news.WONDER_NEWS_VISIBLE_LINES]


# --- the advertisement ----------------------------------------------------------------------
def test_the_news_beacon_advertises_activity_22_and_the_card_beacon_still_21():
    profile = configmod.DEFAULT_TRAINER
    session_id = bytes((0x34, 0x12))

    def activity_of(app_data):
        record = transport._b85_decode(app_data[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]
        word = int.from_bytes(
            record[beacon.SEARCH_WORD_OFFSET:beacon.SEARCH_WORD_OFFSET + 2], "little")
        return word & beacon.SEARCH_ACTIVITY_MASK

    news_inactive, news_active = host_beacon.build_wonder_news_app_data(profile, session_id)
    card_inactive, _card_active = host_beacon.build_wonder_card_app_data(profile, session_id)
    assert activity_of(news_inactive) == beacon.ACTIVITY_WONDER_NEWS == 22
    assert activity_of(news_active) == beacon.ACTIVITY_WONDER_NEWS
    assert activity_of(card_inactive) == beacon.ACTIVITY_WONDER_CARD == 21
    # The two beacons are the same advertisement apart from that one activity byte, so nothing
    # else about the hardware-proven Wonder Card beacon changes on the News path.
    assert len(news_inactive) == len(card_inactive)
    assert sum(a != b for a, b in zip(news_inactive, card_inactive)) <= 2


def test_the_news_host_application_uses_the_news_beacon_and_the_news_results():
    assert host_mg_app.WonderNewsHostApplication.SUCCESS_RESULTS == (mg_server.SVR_MSG_NEWS_SENT,)
    assert (host_mg_app.MysteryGiftHostApplication.SUCCESS_RESULTS
            == (mg_server.SVR_MSG_CARD_SENT, mg_server.SVR_MSG_STAMP_SENT,
                mg_server.SVR_MSG_GIFT_SENT_1))
    assert "Wonder News" in host_mg_app.WonderNewsHostApplication(
        configmod.MysteryGiftRunConfig(
            payload=configmod.WonderNewsPayload()))._hosting_instructions()


# --- the server script ----------------------------------------------------------------------
def test_the_server_script_is_the_decompiled_news_script():
    """gMysteryGiftServerScript_SendWonderNews minus SVR_COPY_SAVED_NEWS, which reads a save block
    we do not have [decomp:src/mystery_gift_scripts.c:174]."""
    script = mg_server.SCRIPT_SEND_WONDER_NEWS
    assert [command[0] for command in script] == [
        mg_server.SVR_LOAD_CLIENT_SCRIPT, mg_server.SVR_SEND, mg_server.SVR_RECV,
        mg_server.SVR_COPY_GAME_DATA, mg_server.SVR_CHECK_GAME_DATA,
        mg_server.SVR_GOTO_IF_EQ, mg_server.SVR_GOTO,
    ]
    # No SVR_CHECK_EXISTING_CARD and no toss prompt anywhere on the News path: news carries no
    # flagId, so nothing compares it against what the console holds.
    send_news = script[-1][1]
    assert [command[0] for command in send_news] == [
        mg_server.SVR_LOAD_CLIENT_SCRIPT, mg_server.SVR_SEND,
        mg_server.SVR_LOAD_NEWS, mg_server.SVR_SEND,
        mg_server.SVR_RECV, mg_server.SVR_READ_RESPONSE, mg_server.SVR_GOTO_IF_EQ,
        mg_server.SVR_LOAD_CLIENT_SCRIPT, mg_server.SVR_SEND,
        mg_server.SVR_RECV, mg_server.SVR_RETURN,
    ]
    assert send_news[4][1] == mg.MG_LINKID_RESPONSE
    assert send_news[6][1] is True and send_news[6][2] is mg_server._SCRIPT_HAS_NEWS
    assert send_news[-1][1] == mg_server.SVR_MSG_NEWS_SENT


def test_the_client_scripts_are_the_decompiled_ones():
    """sClientScript_SaveNews is the only gift script that answers with a value
    [decomp:src/mystery_gift_scripts.c:51]."""
    assert mg_script.CLIENT_SCRIPT_SAVE_NEWS == mg_script.client_script(
        (mg_script.CLI_RECV, mg.MG_LINKID_NEWS),
        mg_script.CLI_SAVE_NEWS,
        mg_script.CLI_SEND_LOADED,
        (mg_script.CLI_RECV, mg.MG_LINKID_CLIENT_SCRIPT),
        mg_script.CLI_COPY_RECV,
    )
    assert mg_script.CLIENT_SCRIPT_NEWS_RECEIVED == mg_script.client_script(
        mg_script.CLI_SEND_READY_END, (mg_script.CLI_RETURN, mg_script.CLI_MSG_NEWS_RECEIVED))
    assert mg_script.CLIENT_SCRIPT_HAD_NEWS == mg_script.client_script(
        mg_script.CLI_SEND_READY_END, (mg_script.CLI_RETURN, mg_script.CLI_MSG_HAD_NEWS))


def test_the_server_sends_the_news_as_one_444_byte_message():
    server = mg_server.MysteryGiftServer(news=_news())
    assert server.is_news_distribution and server.card is None
    action = server.run()
    assert action[0] == "send" and action[1] == mg.MG_LINKID_CLIENT_SCRIPT
    server.on_sent()
    assert server.run() == ("recv", mg.MG_LINKID_GAME_DATA)


# --- end to end against the console model ---------------------------------------------------
def test_news_reaches_a_console_that_holds_none():
    news = _news()
    console = ConsoleClientModel(flag_id=0)
    engine, _frames = _drive(console, distribution=_distribution(news))

    assert console.result == mg_script.CLI_MSG_NEWS_RECEIVED
    assert engine.result == mg_server.SVR_MSG_NEWS_SENT and engine.gift_sent
    assert engine.state == host_mystery_gift.MG_DONE and engine.done
    assert console.saved_news == news
    # No card, no delivery script and no stamp went anywhere near the wire.
    assert console.saved_card is None and console.saved_ram_script is None
    assert [ident for ident, _payload in console.messages_received] == [
        mg.MG_LINKID_CLIENT_SCRIPT,     # sClientScript_SendGameData
        mg.MG_LINKID_CLIENT_SCRIPT,     # sClientScript_SaveNews
        mg.MG_LINKID_NEWS,
        mg.MG_LINKID_CLIENT_SCRIPT,     # sClientScript_NewsReceived
    ]


def test_a_console_that_already_holds_the_same_news_keeps_it():
    """The console's own verdict, not a player prompt: MG_LINKID_RESPONSE TRUE means it kept what
    it had, and the server must end in SVR_MSG_HAS_NEWS instead of claiming a delivery."""
    news = _news()
    console = ConsoleClientModel(flag_id=0, saved_news=news)
    engine, _frames = _drive(console, distribution=_distribution(news))

    assert console.result == mg_script.CLI_MSG_HAD_NEWS
    assert engine.result == mg_server.SVR_MSG_HAS_NEWS and not engine.gift_sent
    assert console.saved_news == news


def test_one_changed_byte_makes_the_same_news_new_again():
    """IsWonderNewsSameAsSaved is a byte compare of the whole struct [mystery_gift.c:140], so the
    --news-id override is enough to re-send the same text to the same console."""
    held = _news()
    fresh = _news(news_id=wonder_news.PKCAMP_NEWS.news_id + 1)
    assert fresh != held
    console = ConsoleClientModel(flag_id=0, saved_news=held)
    engine, _frames = _drive(console, distribution=_distribution(fresh))

    assert console.result == mg_script.CLI_MSG_NEWS_RECEIVED
    assert engine.result == mg_server.SVR_MSG_NEWS_SENT
    assert console.saved_news == fresh


def test_the_ten_line_news_survives_the_link_unchanged():
    news = wonder_news.BERRY_NEWS.build()
    console = ConsoleClientModel(flag_id=0)
    engine, _frames = _drive(console, distribution=_distribution(news))
    assert engine.result == mg_server.SVR_MSG_NEWS_SENT
    assert console.saved_news == news
    assert wonder_news.parse(console.saved_news)["body"] == wonder_news.parse(news)["body"]


def test_our_own_receive_client_answers_the_same_way_as_the_console_model():
    """bin/frlgmg_client.py's client is a second implementation of the same case; keep them agreeing.

    It is the receive direction's console stand-in, so its CLI_SAVE_NEWS has to reproduce the same
    save-or-keep verdict the real console reaches.
    """
    news = _news()
    client = mg_client.MysteryGiftClientEngine()
    client.recv_buffer[:] = news.ljust(mg.MG_LINK_BUFFER_SIZE, b"\x00")
    client.script = mg_script.client_script(mg_script.CLI_SAVE_NEWS)

    client.cmdidx = 0
    client._run_one()
    assert client.saved_news == news
    assert client._pending_send == (mg.MG_LINKID_RESPONSE, (0).to_bytes(4, "little"), 4)

    # Offered the identical struct a second time it keeps what it has and answers TRUE.
    client.cmdidx = 0
    client._run_one()
    assert client.saved_news == news
    assert client._pending_send == (mg.MG_LINKID_RESPONSE, (1).to_bytes(4, "little"), 4)

    # News with id 0 fails ValidateWonderNews, so nothing is saved - but the answer is still FALSE
    # [mystery_gift_client.c:210 takes the save branch whenever the bytes differ].
    client.recv_buffer[:] = (b"\x00\x00" + news[2:]).ljust(mg.MG_LINK_BUFFER_SIZE, b"\x00")
    client.cmdidx = 0
    client._run_one()
    assert client.saved_news == news
    assert client._pending_send == (mg.MG_LINKID_RESPONSE, (0).to_bytes(4, "little"), 4)


# --- configuration --------------------------------------------------------------------------
def test_news_and_card_payloads_cannot_be_mixed():
    for kwargs in ({"card": b"\x00" * 332}, {"ram_script": b"\x02"}):
        try:
            mg_server.MysteryGiftServer(news=_news(), **kwargs)
        except mg_server.MysteryGiftServerError:
            pass
        else:
            raise AssertionError(f"news + {tuple(kwargs)} should be rejected")
    try:
        mg_server.MysteryGiftServer()
    except mg_server.MysteryGiftServerError:
        pass
    else:
        raise AssertionError("a server with neither a card nor news should be rejected")
    try:
        stamp_rally.MysteryGiftDistribution(b"\x00" * 332, b"\x02", news=_news())
    except ValueError:
        pass
    else:
        raise AssertionError("a distribution with both a card and news should be rejected")


def test_the_news_payload_builds_what_the_registry_describes():
    payload = configmod.WonderNewsPayload()
    assert payload.news == wonder_news.DEFAULT_NEWS
    assert payload.build_news() == _news()
    assert payload.build_distribution().is_news
    assert configmod.WonderNewsPayload(news_id=77).build_news()[0:2] == (77).to_bytes(2, "little")
    for bad in ({"news": "nope"}, {"news_id": 0}, {"news_id": 0x10000}):
        try:
            configmod.WonderNewsPayload(**bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad} should be rejected")


def _run_all():
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"ok  {name}")
    print("wonder news: all checks passed")


if __name__ == "__main__":
    _run_all()
