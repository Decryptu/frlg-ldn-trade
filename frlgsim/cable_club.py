"""The cable-club colosseum entry [src/cable_club.c, src/union_room.c:1903].

Direct Corner -> Colosseum -> Single Battle is the same wireless leader/joiner handshake as the
trade centre, and the whole difference up to the battle is three things:

    1. the advertised activity is ACTIVITY_BATTLE_SINGLE, not ACTIVITY_TRADE
       [sAcceptedActivityIds_SingleBattle, src/data/union_room.h:398]
    2. Task_StartActivity warps the console to MAP_BATTLE_COLOSSEUM_2P instead of MAP_TRADE_CENTER,
       through the SAME CB2_TransitionToCableClub - so the 100-byte trainer-card exchange, and with
       it MysteryGift_TryEnableStatsByFlagId, runs exactly as it does for a trade [union_room.c:1903]
    3. once both players are on their spots, Task_StartWirelessCableClubBattle sends ONE MORE player
       record - the bare 28-byte `struct LinkPlayer`, not the 60-byte LinkPlayerBlock of the entry -
       waits 20 frames and a link standby, and enters CB2_InitBattle [cable_club.c:683]

From CB2_InitBattle on it is byte for byte the Union Room battle: the 31-byte LinkBattlerHeader,
three 200-byte party blocks, the controller loop. `uroom_battle` runs all of it unchanged; only the
0x51 selection block is absent here, because that belongs to CB2_UnionRoomBattle.

Why it is worth hosting: only `CB2_ReturnFromCableClubBattle` increments the Wonder Card's
battlesWon [cable_club.c:792], and the in-room Union Room battle returns through CB2_ReturnToField
and counts nothing. See docs/mystery_gift_untried.md.
"""

from . import linkplayer

# struct LinkPlayer, sent whole by SendBlock(0, &gLocalLinkPlayer, sizeof(gLocalLinkPlayer))
# [cable_club.c:701]. The entry block is this same struct wrapped in two GameFreak magics; here it
# travels bare, so the magics must NOT be added.
LOCAL_SIZE = linkplayer.LINK_PLAYER_SIZE          # 28
# `size / 12 + (size % 12 != 0)` [Rfu_InitBlockSend, link_rfu_2.c:1349].
COUNT_LOCAL = 3

# gLinkType while the colosseum battle runs. Task_StartWirelessCableClubBattle case 7 assigns
# gLinkPlayers[0].linkType = LINKTYPE_BATTLE locally on both sides [cable_club.c:736], and
# TryReceiveLinkBattleData tests that exact value [battle_controllers.c:520] - so the value in the
# record WE send is never the one the battle reads, and the wireless path never compares link types
# at all (GetLinkPlayerDataExchangeStatusTimed is the WIRED cable club's).
LINKTYPE_BATTLE = 0x2211
LINKTYPE_SINGLE_BATTLE = 0x2233


def local_link_player_block(link_player, *, name_pad=0x00):
    """The 28 bytes of case 2. gLinkPlayers[] is overwritten from these blocks, and the trainerId in
    ours is the id the console's card counter records against
    [`gLinkPlayers[GetMultiplayerId() ^ 1].trainerId`, cable_club.c:794] - so a second win needs a
    second --id, IncrementCardStatForNewTrainer counting each id once [mystery_gift.c:630]."""
    return link_player.pack(name_pad=name_pad)


def read_local_link_player(data):
    """-> LinkPlayer. Raises if the block is short; there are no magics to validate here."""
    if len(data) < LOCAL_SIZE:
        raise ValueError(f"cable-club LinkPlayer block is {len(data)} bytes, expected {LOCAL_SIZE}")
    return linkplayer.LinkPlayer.unpack(data[:LOCAL_SIZE])
