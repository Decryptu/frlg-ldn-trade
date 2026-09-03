"""The Union Room battle [src/union_room_battle.c, src/battle_main.c, src/battle_controllers.c].

The console's side of the entry gate is its own party: HasAtLeastTwoMonsOfLevel30OrLower
[union_room.c:4565] requires two non-egg mons at level 30 or lower before it will offer OR accept
a battle, and it refuses on its own screen with nothing on the air.

Once both sides accept the activity word 0x41, the sequence is:

    1. one 0x20-byte block, [0] = 0x51 accept (or 0x52 to back out) [CB2_UnionRoomBattle case 3]
    2. both must read 0x51, then the REVISION >= 0xA path takes TWO link-task waits with a
       SetLinkStandbyCallback between them [cases 50/51/52] -- the GBA release took one
    3. a 31-byte LinkBattlerHeader: version signature, vs-screen health flags, enigma berry
    4. three 200-byte blocks, the six party slots two at a time [CB2_HandleStartBattle 3/7/11]
    5. the controller loop

We send version signature 0x200 on purpose. LinkBattleComputeBattleTypeFlags [battle_main.c:886]
makes the console elect ITSELF master for any signature below 0x201 that is not 0x100, and only the
master runs `gBattleMainFunc = BeginBattleIntro` [battle_controllers.c:141]. So the console runs the
whole battle -- turn order, damage, RNG -- and we run a controller that answers its commands. See
docs/joiner_protocol_notes.md "The Union Room battle".
"""

from . import battle_link as bl, battle_mon, mon as monmod

ACCEPT_BLOCK_SIZE = 0x20
ACCEPT = 0x51                   # ACTIVITY_ACCEPT | 0x40 [union_room_battle.c:143]
DECLINE = 0x52                  # ACTIVITY_DECLINE | 0x40

HEADER_SIZE = 31                # LinkBattlerHeader: 4 + sizeof(BattleEnigmaBerry) 0x1B, all u8
VERSION_NON_MASTER = 0x200      # below 0x201 and not 0x100: the console makes itself master
VERSION_FIRERED = 0x201         # what the game itself sends (lo=1, hi=2)

PARTY_BLOCK_COUNT = 3

# RFU block counts: `size / 12 + (size % 12 != 0)` [Rfu_InitBlockSend, link_rfu_2.c:1349]. The
# 0x20 selection block and the 31-byte header happen to share a count; they are told apart by
# where we are in the sequence, not by size.
COUNT_ACCEPT = 3
COUNT_HEADER = 3


def accept_block(accepted=True):
    """The 0x20-byte selection block. `memset(gBlockSendBuffer, 0, 0x20)` then one byte, so the
    rest is zero [CB2_UnionRoomBattle case 3]."""
    out = bytearray(ACCEPT_BLOCK_SIZE)
    out[0] = ACCEPT if accepted else DECLINE
    return bytes(out)


def read_accept_block(data):
    """-> True for accept, False for decline. The console closes the link unless both read 0x51."""
    if len(data) < 1:
        raise ValueError("empty selection block")
    if data[0] == ACCEPT:
        return True
    if data[0] == DECLINE:
        return False
    raise ValueError(f"selection block starts 0x{data[0]:02x}, expected 0x51 or 0x52")


def battler_header(version=VERSION_NON_MASTER, vs_screen_flags=0):
    """struct LinkBattlerHeader. vs_screen_flags marks fainted party slots as `3 << i*2`
    [BufferPartyVsScreenHealth_AtStart, battle_main.c:747]; healthy mons are 0. The enigma berry
    tail stays zero: it only matters for a mon holding an Enigma Berry, which ours do not."""
    out = bytearray(HEADER_SIZE)
    out[0] = version & 0xFF
    out[1] = (version >> 8) & 0xFF
    out[2] = vs_screen_flags & 0xFF
    out[3] = (vs_screen_flags >> 8) & 0xFF
    return bytes(out)


def party_blocks(mons):
    """The three 200-byte blocks of state 3/7/11. Exactly the transfer the trade already does, so
    `mon.party_blocks` is reused unchanged. SetUpPartiesAndStartBattle keeps only the two chosen
    mons and zeroes the rest [union_room_battle.c:47], so pass at most two."""
    if len(mons) > 2:
        raise ValueError("a Union Room battle is two mons a side [union_room_battle.c:47]")
    return monmod.party_blocks(monmod.build_player_party(mons))


class BattleController:
    """Our half of the link battle, as the NON-master.

    Feed it every inbound link buffer block; it returns the blocks to send back, in order. The one
    rule that matters is that EVERY BUFFER_A command must be acked, for BOTH battlers, or the master
    waits on gBattleControllerExecFlags forever [battle_util.c:185-201]. Only the seven commands in
    battle_link.NEEDS_REPLY also want a BUFFER_B reply, and only for our own battler.
    """

    def __init__(self, mons, *, multiplayer_id=0, forfeit=True, log=None):
        self.mons = list(mons)
        self.multiplayer_id = multiplayer_id
        self.forfeit = forfeit
        self.log = log
        self.our_battler = bl.OUR_BATTLER
        self.active_index = 0       # gBattlerPartyIndexes[our battler]; slot 0 at battle start
        self.commands = []          # (battler, cmd) in arrival order, for the run classifier
        self.outcome = None         # set by ENDLINKBATTLE
        self.done = False

    def _info(self, msg):
        if self.log is not None:
            self.log(msg)

    def _mon_data(self, request_id, mon_to_check):
        """PlayerHandleGetMonData [battle_controller_player.c:1495]: mon_to_check 0 means the active
        mon, anything else is a party bitmask and the answers are concatenated."""
        if request_id != bl.REQUEST_ALL_BATTLE:
            raise ValueError(f"GETMONDATA request {request_id} is not implemented; only "
                             f"REQUEST_ALL_BATTLE ({bl.REQUEST_ALL_BATTLE}) is sent at battle start")
        if mon_to_check == 0:
            indexes = [self.active_index]
        else:
            indexes = [i for i in range(6) if mon_to_check & (1 << i)]
        out = bytearray()
        for i in indexes:
            if i < len(self.mons):
                out += battle_mon.from_mon(self.mons[i])
            else:
                out += bytes(battle_mon.SIZE)
        return bytes(out)

    def feed(self, block):
        """One inbound link buffer block -> the blocks we must send, in order."""
        rec = bl.parse(block)
        if rec["buffer_id"] != bl.BUFFER_A:
            # A reply or an ack from the console. Nothing is owed for either.
            return []
        battler, cmd = rec["active_battler"], rec["cmd"]
        self.commands.append((battler, cmd))
        out = []
        if battler == self.our_battler and cmd in bl.NEEDS_REPLY:
            reply = self._reply(rec)
            if reply is not None:
                out.append(reply)
        if cmd == bl.ENDLINKBATTLE:
            self.outcome = rec["payload"][1] if len(rec["payload"]) > 1 else None
            self.done = True
            self._info(f"Union Room battle: the console ended it, outcome {self.outcome}.")
        out.append(bl.ack(battler, self.multiplayer_id))
        return out

    def _reply(self, rec):
        battler, cmd, payload = rec["active_battler"], rec["cmd"], rec["payload"]
        if cmd == bl.GETMONDATA:
            data = self._mon_data(payload[1], payload[2])
            self._info(f"Union Room battle: sending our mon: {battle_mon.describe(data)}")
            return bl.data_transfer(battler, data)
        if cmd == bl.CHOOSEACTION:
            if self.forfeit:
                self._info("Union Room battle: choosing RUN, which forfeits a link battle.")
                return bl.two_return_values(battler, bl.B_ACTION_RUN, 0)
            return bl.two_return_values(battler, bl.B_ACTION_USE_MOVE, 0)
        if cmd == bl.CHOOSEMOVE:
            # move slot 0 at the opposing battler [battle_controller_player.c:342].
            return bl.two_return_values(battler, bl.RET_CHOSEN_MOVE, 0 | (bl.MASTER_BATTLER << 8))
        if cmd == bl.CHOOSEPOKEMON:
            return bl.chosen_mon_return_value(battler, self.active_index)
        if cmd == bl.OPENBAG:
            return bl.one_return_value(battler, 0)      # ITEM_NONE: we carry no bag
        if cmd == bl.EXPUPDATE:
            return bl.two_return_values(battler, 0, 0)  # not levelled up
        return None
