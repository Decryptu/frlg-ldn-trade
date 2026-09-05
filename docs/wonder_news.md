---
title: Wonder News
parent: Mystery Gift
nav_order: 6
---

# Wonder News

The console's Mystery Gift menu is two axes - {Wonder Cards, Wonder News} × {Wireless
Communication, Friend} - and for the whole life of this project the host only ever served Cards ×
Friend. This page is the second column: what Wonder News is, what had to change to serve it, and
what the console does with it afterwards.

Everything here is a decompilation fact unless it is marked otherwise.

## What news is

`struct WonderNews` [`include/global.h:646`] is 444 bytes and, unlike a Wonder Card, carries no
identity at all:

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0x000 | 2 | `id` | the only thing `ValidateWonderNews` checks: it must not be 0 [`mystery_gift.c:113`] |
| 0x002 | 1 | `sendType` | `SEND_TYPE_DISALLOWED` hides the console's own "Send" option [`IsSendingSavedWonderNewsAllowed`, `mystery_gift.c:120`] |
| 0x003 | 1 | `bgType` | not validated; `WonderNews_Init` clamps `>= NUM_WONDER_BGS` to 0 [`mystery_gift_show_news.c:110`] |
| 0x004 | 40 | `titleText` | centred in a 224 px window |
| 0x02C | 400 | `bodyText[10][40]` | eight lines are on screen; a non-empty line past index 7 arms the scroll indicator [`:346`] |

No `flagId`, no `WonderCardMetadata`, no delivery RAM script, no receipt event flag. Nothing on the
News path ever consults `sReceivedGiftFlags`, so none of the Wonder Card flag-id bookkeeping applies
and none of the flag-id traps do either.

What decides whether a console keeps news is `IsWonderNewsSameAsSaved` [`mystery_gift.c:140`]: a
byte-for-byte compare of the whole 444-byte struct against the news already in the save block. One
different byte anywhere makes old news new again - which is what `--news-id` exists for.

## The two things that had to change

Below the server script, this is the Wonder Card host unchanged: the same LDN network, the same RFU
parent, the same `MysteryGiftLink` framing, the same `LinkPlayer` exchange and close.

**1. The advertisement's activity byte.** The console's Friend listen task keeps only candidates
whose advertised activity appears in the accept list of the link group it is searching in
[`IsPartnerActivityAcceptable`, `union_room.c:1590`], and the News list holds exactly one id
[`sAcceptedActivityIds_WonderNews`, `src/data/union_room.h:406`]. So a host advertising
`ACTIVITY_WONDER_CARD` (21) is simply not listed on the News screen and vice versa;
`build_wonder_news_app_data` sets 22 and changes nothing else about the hardware-proven beacon.

The `hasNews` compatibility bit is *not* the gate here. `HasWonderCardOrNewsByLinkGroup`
[`union_room.c:3777`] is reached only from `Task_ListenForWonderDistributor`, the Wireless path,
which is closed to us for other reasons - see [JoySpot discovery](joyspot_discovery_findings.md).
The Friend path never reads it, exactly as the Wonder Card host never needed `hasCard`.

**2. The server script answers to the console.** Every other gift this project sends is one-way: we
push bytes and the console never comments. News is the exception. `sClientScript_SaveNews`
[`mystery_gift_scripts.c:51`] runs `CLI_SAVE_NEWS` and then `CLI_SEND_LOADED`, and `CLI_SAVE_NEWS`
loads a `MG_LINKID_RESPONSE` word with the console's own verdict [`mystery_gift_client.c:210`]:

* `FALSE` - the news differed from what was held, so it was saved.
* `TRUE` - the console already held exactly these 444 bytes and kept them.

`sServerScript_SendNews` [`mystery_gift_scripts.c:126`] branches on that: `TRUE` goes to
`sServerScript_HasNews` and ends in `SVR_MSG_HAS_NEWS`; `FALSE` falls through to
`sClientScript_NewsReceived`, and only that path makes the console save and set its reward. Our
`SCRIPT_SEND_WONDER_NEWS` is that script minus its leading `SVR_COPY_SAVED_NEWS`, which reads a save
block we do not have - the same edit the Wonder Card script needed.

Note what is *not* in the script: no `SVR_CHECK_EXISTING_CARD`, no toss prompt, no `SVR_LOAD_RAM_SCRIPT`.
News cannot displace a card, and a player is never asked to throw anything away to take it.

## What the player gets

Receiving news from a Friend calls `WonderNews_SetReward(WONDER_NEWS_RECV_FRIEND)`
[`mystery_gift_menu.c:1367`], which rolls a random berry between `ITEM_RAZZ_BERRY` and
`ITEM_NOMEL_BERRY` into `WonderNewsMetadata.berry` [`wonder_news.c:21`]. The man in the house in
CERULEAN CITY (`CeruleanCity_House4`) hands it over. Up to five rewards, then the player must walk
500 steps before the counter resets [`MAX_REWARD`, `WonderNews_IncrementStepCounter`].

The four-berry "big" reward is `NEWS_REWARD_RECV_BIG`, which needs `WONDER_NEWS_RECV_WIRELESS` -
that is the Wireless path, and it is closed. A Friend source is always the small reward.

## Running it

    ./scratchpad/run_mg_news.sh wnNN                    # or: run_mg_fast.sh wnNN --news --version firered
    (them) Mystery Gift -> the second menu entry (Wonder News, under Wonder Cards)
           -> the "you have no news, input one?" message -> Friend (Ami)
    (them) pick PkCamp from the list

A console that already holds news goes straight to the news display instead of the input prompt;
press A there and choose **Receive** to reach the same screen.

Re-sending the identical news to the same console is a no-op by design - it answers `TRUE` and the
host reports "the console already had this news". Pass `--news-id N` to change the id and the same
text lands again.

## On hardware (`wn01`, 2026-09-04, first try)

A French FireRed (`PLAYER`, TID 57189) holding Wonder Card flagId 1008 took the news in 18 seconds
with no retries, no stall and no hold:

```
ident 16  sClientScript_SendGameData
ident 17  MysteryGiftLinkGameData - PLAYER, FireRed, holding card flagId 1008
ident 16  sClientScript_SaveNews
ident 23  MG_LINKID_NEWS - 444 bytes in three blocks
ident 19  MG_LINKID_RESPONSE - FALSE: the console saved it
ident 16  sClientScript_NewsReceived
ident 20  READY_END                              -> SVR_MSG_NEWS_SENT
```

The advertisement in the capture carries activity 22 throughout, with the `startedActivity` bit
flipping on when the console joined. The console saved by itself, closed the link normally, and the
Wonder Card it was holding was untouched - news and cards do not displace each other.

Confirmed on the console afterwards: the news renders correctly under Mystery Gift → Wonder News,
and the man in the Cerulean City house handed over a berry. That closes the loop the decompilation
describes, from `WonderNews_SetReward(WONDER_NEWS_RECV_FRIEND)` to the item in the bag.

## Checking it offline first

    ./.venv/bin/python scratchpad/mg_client_harness.py --news                     # the send path
    ./.venv/bin/python scratchpad/mg_client_harness.py --news --held-news pkcamp  # the HasNews path
    ./.venv/bin/python -m pytest tests/test_wonder_news.py -q

`tests/test_mystery_gift_end_to_end.py` also runs a ten-line news through the impaired-radio
full stack: news is one fragment longer than a Wonder Card and, unlike a card, needs an answer back
from the console before the session can end.
