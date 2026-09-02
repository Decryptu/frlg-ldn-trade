"""CHILD-side FRLG Mystery Gift client - we RECEIVE a Wonder Card from a real console.

This is the mirror image of :mod:`frlgsim.host_mystery_gift`.  There we are the RFU parent
running ``mystery_gift_server.c``; here we are the RFU child running ``mystery_gift_client.c``
[decomp:src/mystery_gift_client.c] against a console that chose
Mystery Gift -> Wonder Cards -> Friend -> *send* (``Task_SendMysteryGift``, union_room.c:2041).

Why it exists: every capture of a real Mystery Gift HOST so far was passive (two consoles, a
monitor vif, ~50% of the air lost to aggregation).  With our own radio in the session we see the
console's whole parent stream at full fidelity - what a real host does in the first three
seconds after the join is exactly the data the 3-second wall investigation never had.

Integration contract is the JOINER's (:class:`frlgsim.trade.TradeEngine`), so it drops into
:class:`frlgsim.sim.Sim` unchanged::

    engine.feed_in_frame(gbaframe.parse_in(host_T))   # each host 'T' (the gRecvCmds table)
    words = engine.tick()                              # once per VBlank, our 7-word gSendCmd

What the child does, in order [decomp citations inline]:

1. ``Task_PlayerExchange`` child branch: answer the parent's one ``SEND_BLOCK_REQ`` with our
   200-byte LinkPlayerBlock, take the parent's LinkPlayer block (count 17, GameFreak magics)
   -> ``gReceivedRemoteLinkPlayers`` [link_rfu_2.c:1813-1900].
2. ``Task_CardOrNewsWithFriend`` case 11: ONE ``SetLinkStandbyCallback`` round (count 0)
   [union_room.c:2391].  Child-initiated, as every standby is on this console (barrier.py).
3. ``MysteryGiftClient_Create`` [mystery_gift_menu.c:1231]: run the two-instruction boot
   script (RECV client script, COPY_RECV) and from then on whatever scripts the server pushes
   [mystery_gift_scripts.c:15; mystery_gift_client.c:87].  One instruction per VBlank.
4. ``CLI_RETURN`` -> ``Rfu_SetCloseLinkCallback`` [mystery_gift_menu.c:1248]: emit
   READY_CLOSE_LINK and wait for the parent's.

Every message in both directions is kept (``messages``) with its VBlank index: this engine is
an instrument first and a card receiver second.
"""

from collections import deque

from . import barrier as barriermod, block, charmap, linkplayer, mg_link, mg_script, rfu
from . import mystery_gift as mg
from .mystery_gift import (MG_LINKID_CLIENT_SCRIPT, MG_LINKID_GAME_DATA, MG_LINKID_GAME_STAT,
                           MG_LINKID_READY_END, MG_LINKID_RESPONSE)

ACTIVITY_WONDER_CARD = 21           # include/constants/union_room.h:46
ACTIVITY_WONDER_NEWS = 22

# engine states
C_LINK = "C_LINK"                   # LinkPlayer exchange + the post-exchange standby
C_GIFT = "C_GIFT"                   # MysteryGiftClient running the server's scripts
C_CLOSE = "C_CLOSE"                 # READY_CLOSE_LINK handshake
C_DONE = "C_DONE"

# client funcs [mystery_gift_client.c FUNC_*]
F_RUN, F_RECV, F_SEND, F_WAIT, F_DONE = "run", "recv", "send", "wait", "done"

COUNT_LINK_PLAYER = 17              # ceil(200/12): the fixed 200B LinkPlayer pull
LINK_PLAYER_REQTYPES = (0, 1)       # BLOCK_REQ_SIZE_NONE / _200 [link.c BLOCK_REQ_*]

# Idle VBlanks between two consecutive blocks of ONE outgoing message. The parent's receive
# slot for a CHILD block only re-arms after its four-VBlank numBlocksReceived countdown
# [link_rfu_2.c:1220] AND after MGL_Receive consumed the previous block, and the console's
# server task consumes one block per frame at best. The host engine gives the console 12; a
# console parent is at least as slow as we are, so we give it the same.
DEFAULT_INTER_BLOCK_GAP = 12

RAM_SCRIPT_SAVE_SIZE = 1024         # keep the whole ident-25 buffer, not just script[995]

GAME_CODES = {                      # RomHeaderGameCode: BPR=FireRed BPG=LeafGreen + region byte
    ("firered", "english"): b"BPRE", ("leafgreen", "english"): b"BPGE",
    ("firered", "french"): b"BPRF", ("leafgreen", "french"): b"BPGF",
    ("firered", "italian"): b"BPRI", ("leafgreen", "italian"): b"BPGI",
    ("firered", "german"): b"BPRD", ("leafgreen", "german"): b"BPGD",
    ("firered", "spanish"): b"BPRS", ("leafgreen", "spanish"): b"BPGS",
}

CLI_NAMES = {v: k for k, v in vars(mg_script).items() if k.startswith("CLI_") and
             not k.startswith("CLI_MSG_") and isinstance(v, int)}
CLI_MSG_NAMES = {v: k for k, v in vars(mg_script).items() if k.startswith("CLI_MSG_")}
IDENT_NAMES = {v: k for k, v in vars(mg).items() if k.startswith("MG_LINKID_")}


def build_link_game_data(link_player, *, version_code, flag_id=0, game_code=b"BPRE",
                         software_version=0, max_stamps=0, card_metadata=b""):
    """``MysteryGift_LoadLinkGameData`` [mystery_gift.c:337] from our profile.

    The struct is CpuFill32'd to zero first, so every unset field is 0x00. ``playerName`` is a
    StringCopy into a 7-byte field with no terminator slot - a 7-character name spills its 0xFF
    over ``playerTrainerId[0]`` natively (see :class:`mg_script.LinkGameData`); we reproduce
    that faithfully rather than "fix" it, because it is what a console sends.
    """
    data = bytearray(mg_script.GAME_DATA_SIZE)
    data[0x00:0x04] = mg.GAME_DATA_VALID_VAR.to_bytes(4, "little")
    data[0x04:0x06] = (1).to_bytes(2, "little")
    data[0x08:0x0C] = (1).to_bytes(4, "little")
    data[0x0C:0x0E] = (1).to_bytes(2, "little")
    data[0x10:0x14] = (version_code & 0xFFFFFFFF).to_bytes(4, "little")
    data[mg_script.GD_OFF_FLAG_ID:mg_script.GD_OFF_FLAG_ID + 2] = (flag_id & 0xFFFF).to_bytes(2, "little")
    if card_metadata:
        meta = bytes(card_metadata)[:36]
        data[mg_script.GD_OFF_CARD_METADATA:mg_script.GD_OFF_CARD_METADATA + len(meta)] = meta
    data[mg_script.GD_OFF_MAX_STAMPS] = max_stamps & 0xFF
    tid = (link_player.trainer_id & 0xFFFFFFFF).to_bytes(4, "little")
    data[mg_script.GD_OFF_TRAINER_ID:mg_script.GD_OFF_TRAINER_ID + 4] = tid
    name = charmap.encode(link_player.name)[:7] + b"\xff"      # StringCopy: text + EOS
    data[mg_script.GD_OFF_PLAYER_NAME:mg_script.GD_OFF_PLAYER_NAME + len(name)] = name
    data[mg_script.GD_OFF_GAME_CODE:mg_script.GD_OFF_GAME_CODE + 4] = bytes(game_code)[:4].ljust(4, b"\x00")
    data[mg_script.GD_OFF_VERSION] = software_version & 0xFF
    return bytes(data)


def describe_wonder_card(card):
    """Human-readable summary of a 332-byte ``struct WonderCard`` [include/global.h:655]."""
    card = bytes(card)
    if len(card) < mg_script.GD_OFF_CARD_METADATA:
        return f"{len(card)}-byte card (short)"
    flag_id = int.from_bytes(card[0:2], "little")
    icon = int.from_bytes(card[2:4], "little")
    id_number = int.from_bytes(card[4:8], "little")
    bits = card[8]
    card_type, bg, send = bits & 3, (bits >> 2) & 0xF, (bits >> 6) & 3
    max_stamps = card[9]

    def text(off):
        return charmap.decode(card[off:off + 40])

    lines = [text(90 + 40 * i) for i in range(4)]
    return (f"flagId={flag_id} icon={icon} id={id_number} type={card_type} bg={bg} "
            f"sendType={send} maxStamps={max_stamps} title={text(10)!r} subtitle={text(50)!r} "
            f"body={lines!r} footer={[text(250), text(290)]!r}")


class MysteryGiftClientEngine:
    """Transport-independent FRLG Mystery Gift CLIENT (RFU child, mpId 1)."""

    def __init__(self, link_player=None, *, version="firered", language="english",
                 holding_flag_id=0, accept_replacement=True, yes_no_answer=True,
                 game_code=None, software_version=0, trust_pia=False,
                 inter_block_gap=DEFAULT_INTER_BLOCK_GAP, log=lambda *a: None):
        self.lp = link_player or linkplayer.LinkPlayer(version=linkplayer.VERSION_FIRE_RED)
        self.mpid = 1
        self.log = log
        self.info = getattr(log, "info", log)
        self.trust_pia = trust_pia
        self.inter_block_gap = int(inter_block_gap)
        # what the sim advertises in its NI game data (sim._ensure_ni reads these)
        self.ni_activity = ACTIVITY_WONDER_CARD
        self.ni_started = False         # SetHostRfuGameData(activity, 0, FALSE) [union_room.c:2255]
        self._live = False              # set by the live sim; unused here, kept for the contract

        version_code = (mg.VERSION_CODE_LEAFGREEN if version == "leafgreen"
                        else mg.VERSION_CODE_FIRERED)
        if game_code is None:
            game_code = GAME_CODES.get((version, language), b"BPRE")
        self.game_data = build_link_game_data(
            self.lp, version_code=version_code, flag_id=holding_flag_id,
            game_code=game_code, software_version=software_version)
        self.holding_flag_id = holding_flag_id
        # CLI_ASK_TOSS: the menu sets param FALSE for YES (toss the old card) and TRUE for NO
        # [mystery_gift_menu.c MG_STATE_CLIENT_ASK_TOSS]; the server sends the card on FALSE.
        self.toss_param = 0 if accept_replacement else 1
        self.yes_no_param = 1 if yes_no_answer else 0

        # RFU layer
        self.rx = block.BlockReceiver()
        self.sender = None
        self.barrier = barriermod.BarrierResponder(log=self.log)
        self._player_ids_seen = False

        # LinkPlayer exchange
        self._lp_sent = False
        self._lp_requests = 0
        self.host_link_player = None
        self._standby_initiated = False
        self._self_standby_echo = None   # highest 0x6600 count the host reflected back at us

        # MysteryGiftClient [mystery_gift_client.c]
        self.state = C_LINK
        self.state_history = [C_LINK]
        self.func = F_RUN
        self.script = mg_script.CLIENT_SCRIPT_INIT
        self.cmdidx = 0
        self.param = 0
        self.recv_buffer = bytearray(mg.MG_LINK_BUFFER_SIZE)
        self.link_recv = mg_link.MysteryGiftLinkReceiver()
        self._host_blocks = deque()      # completed parent blocks not yet consumed by MGL_Receive
        self._pending_send = None        # (ident, payload, size) staged by a LOAD_* instruction
        self._send_blocks = []           # remaining blocks of the message going out
        self._send_gap = 0
        self._message_label = ""
        self.saved_card = None
        self.saved_ram_script = None
        self.saved_stamp = None
        self.saved_news = None
        self.activation_scripts = []
        self.buffer_scripts = []
        self.dynamic_msg = None
        self.result = None               # CLI_RETURN parameter (CLI_MSG_*)
        self.close_confirmed = False
        self.done = False
        self.error = None
        # instrumentation: (tick, direction, ident, size, payload) and free-form events
        self.messages = []
        self.trace = []
        self.host_ops = {}
        self._tick = 0
        self._unexpected_blocks = 0
        self._gift_idle = 0

    # --- contract properties ------------------------------------------------------------------
    @property
    def established(self):
        """gReceivedRemoteLinkPlayers: both LinkPlayer blocks exchanged [link_rfu_2.c:1879]."""
        return self._lp_sent and self.host_link_player is not None

    @property
    def in_seat_phase(self):
        # sim.py uses this only to pick the retransmit policy (whole-window before the block
        # phase, gap-targeted inside it). No held keys are ever emitted: host_in_seat stays False.
        return not self.established

    host_in_seat = False
    held_keys_active = False

    @property
    def card_received(self):
        return self.saved_card is not None

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.state_history.append(state)
            self.trace.append((self._tick, "state", state))
            self.log(f"mg client: -> {state}")

    # --- receive ------------------------------------------------------------------------------
    def feed_in_frame(self, unwrapped):
        completed, reqs = self.rx.feed_frame(unwrapped)
        if unwrapped is None:
            return
        for mpid, slot in unwrapped.get("positional", []):
            r = rfu.parse_slot(slot)
            if not r:
                continue
            if mpid != self.mpid:
                self.host_ops[r["name"]] = self.host_ops.get(r["name"], 0) + 1
                if r["op"] == rfu.SEND_PLAYER_IDS and not self._player_ids_seen:
                    self._player_ids_seen = True
                    count = int.from_bytes(slot[2:4], "little")
                    id0 = int.from_bytes(slot[4:6], "little")
                    self.trace.append((self._tick, "player_ids", count, id0))
                    self.info(f"Console assigned player slots: count={count} ids[0]={id0} "
                              f"(our mpId={self.mpid}).")
            elif r["op"] == rfu.READY_EXIT_STANDBY:
                c = r.get("count")
                if c is not None and (self._self_standby_echo is None or c > self._self_standby_echo):
                    self._self_standby_echo = c
                    self.log(f"mg client: host reflected our READY_EXIT_STANDBY count={c}")
            elif r["op"] == rfu.READY_CLOSE_LINK and self.state == C_CLOSE:
                self._confirm_close("reflection")
        host_slot = self._host_barrier_in_frame(unwrapped)
        saw = host_slot is not None
        if saw:
            self.barrier.on_in_slot(host_slot)
            if host_slot["op"] == rfu.READY_CLOSE_LINK:
                self._confirm_close("host 0x5F00")
        self.barrier.observe_frame(saw)
        # The console never broadcasts its own 0x6600 at mpId 0 on hardware (j45-j58); the only
        # evidence a child-initiated round landed is its reflection of ours. Complete on that.
        if (self.barrier.mode == barriermod.STANDBY and self.barrier.initiated
                and self._self_standby_echo is not None
                and self._self_standby_echo >= self.barrier.local_count):
            self.barrier.on_in_slot({"op": rfu.READY_EXIT_STANDBY, "count": self.barrier.local_count})
        for reqtype in reqs:
            self._on_req(reqtype)
        for mpid, count, data in completed:
            if mpid == 0:
                self._on_host_block(count, data)

    def _host_barrier_in_frame(self, unwrapped):
        for mpid, slot in unwrapped.get("positional", []):
            if mpid == self.mpid:
                continue
            d = rfu.parse_slot(slot)
            if d is not None and d["op"] in (rfu.READY_EXIT_STANDBY, rfu.READY_CLOSE_LINK):
                return d
        return None

    def _on_req(self, reqtype):
        self.trace.append((self._tick, "req", reqtype))
        if self.sender is not None and not self.sender.done:
            return                          # the parent re-pulls every frame until it lands
        if self.state == C_LINK and reqtype in LINK_PLAYER_REQTYPES and not self._lp_sent:
            # Task_PlayerExchange child case: both sides Rfu_InitBlockSend their LinkPlayerBlock in
            # the fixed 200-byte buffer [link_rfu_2.c:1172, 232].
            self._lp_requests += 1
            self._lp_sent = True
            self._begin_block(linkplayer.build_block(self.lp).ljust(200, b"\x00"), "link_player")
            self.info("Console requested our LinkPlayer block; sending it.")
            return
        self.log(f"mg client: ignoring SEND_BLOCK_REQ type={reqtype} in {self.state}")

    def _on_host_block(self, count, data):
        if self.host_link_player is None and count == COUNT_LINK_PLAYER:
            lp, ok = linkplayer.parse_block(data)
            if ok:
                self.host_link_player = lp
                self.trace.append((self._tick, "host_link_player", lp.name, lp.version))
                self.info(f"Console identified as {lp.name!r} (version 0x{lp.version:04x}, "
                          f"language {lp.language}); LinkPlayer exchange complete.")
                return
        if self.state in (C_LINK, C_GIFT):
            self._host_blocks.append(bytes(data))
            self.trace.append((self._tick, "host_block", count, len(self._host_blocks)))
            return
        self._unexpected_blocks += 1
        self.trace.append((self._tick, "unexpected_host_block", count, self.state))

    def _confirm_close(self, how):
        if not self.close_confirmed:
            self.close_confirmed = True
            self.trace.append((self._tick, "close_confirmed", how))
            self.info(f"Console acknowledged the link close ({how}).")

    # --- send ---------------------------------------------------------------------------------
    def _begin_block(self, data, label):
        # Reset the peer-1 reflection so the fresh INIT waits for THIS block's echo (trade.py).
        self.rx.peers[1] = block.RecvBlock()
        self.sender = block.BlockSender(data, owner=self.mpid, trust_pia=self.trust_pia,
                                        stream_gap=0)
        self.trace.append((self._tick, "send_block", label, len(data)))

    def _begin_message(self, ident, payload, size):
        blocks = mg_link.build_message(ident, payload, size)
        self._send_blocks = list(blocks)
        self._message_label = f"ident{ident}"
        self.func = F_SEND
        declared = mg_link.parse_header(blocks[0])[2]
        self.messages.append((self._tick, "out", ident, declared, bytes(payload)))
        self.info(f"[mg] sending {IDENT_NAMES.get(ident, ident)} ({ident}) as {len(blocks)} block(s)")

    # --- MysteryGiftLink receive [mystery_gift_link.c MGL_Receive] -----------------------------
    def _drain_recv(self):
        """Feed buffered parent blocks to the message receiver. True once a message completed."""
        while self._host_blocks and self.link_recv.active:
            blk = self._host_blocks.popleft()
            try:
                payload = self.link_recv.feed_block(blk)
            except mg_link.MysteryGiftLinkError as exc:
                # LinkRfu_FatalError territory natively; we record it and keep the link up so
                # the capture shows what the console does next.
                self.error = str(exc)
                self.trace.append((self._tick, "link_error", str(exc)))
                self.info(f"[mg] MysteryGiftLink error: {exc} (native would LinkRfu_FatalError)")
                self.link_recv.expect(self.link_recv.expected_ident)
                continue
            if payload is None:
                continue
            ident = self.link_recv.ident
            self.recv_buffer[:] = bytes(payload).ljust(mg.MG_LINK_BUFFER_SIZE, b"\x00")[:mg.MG_LINK_BUFFER_SIZE]
            self.messages.append((self._tick, "in", ident, len(payload), bytes(payload)))
            self.trace.append((self._tick, "recv_message", ident, len(payload)))
            self.info(f"[mg] received {IDENT_NAMES.get(ident, ident)} ({ident}, {len(payload)} bytes)")
            return True
        return False

    # --- client script interpreter [mystery_gift_client.c Client_Run] ------------------------
    def _run_one(self):
        off = self.cmdidx * mg_script.CLIENT_CMD_SIZE
        if off + mg_script.CLIENT_CMD_SIZE > len(self.script):
            instr, param = mg_script.CLI_NONE, 0
        else:
            instr = int.from_bytes(self.script[off:off + 4], "little")
            param = int.from_bytes(self.script[off + 4:off + 8], "little")
        self.cmdidx += 1
        if instr != mg_script.CLI_NONE:
            self.trace.append((self._tick, "cli", instr, param))
            self.log(f"mg client: {CLI_NAMES.get(instr, instr)} param={param}")
        if instr == mg_script.CLI_NONE:
            return
        if instr == mg_script.CLI_RETURN:
            self.param = param
            self.result = param
            self.func = F_DONE
            self.info(f"[mg] client script returned {CLI_MSG_NAMES.get(param, param)} ({param}).")
        elif instr == mg_script.CLI_RECV:
            self.link_recv.expect(param)
            self.func = F_RECV
            self.log(f"mg client: awaiting {IDENT_NAMES.get(param, param)}")
        elif instr == mg_script.CLI_SEND_LOADED:
            if self._pending_send is None:
                self.info("[mg] CLI_SEND_LOADED with nothing loaded; sending an empty buffer")
                self._pending_send = (MG_LINKID_RESPONSE, b"", mg.MG_LINK_BUFFER_SIZE)
            self._begin_message(*self._pending_send)
        elif instr == mg_script.CLI_SEND_READY_END:
            self._begin_message(MG_LINKID_READY_END, b"", 0)
        elif instr == mg_script.CLI_SEND_STAT:
            self._begin_message(MG_LINKID_GAME_STAT, (0).to_bytes(4, "little"), 4)
        elif instr == mg_script.CLI_COPY_RECV_IF_N:
            if not self.param:
                self._copy_recv_script()
        elif instr == mg_script.CLI_COPY_RECV_IF:
            if self.param:
                self._copy_recv_script()
        elif instr == mg_script.CLI_COPY_RECV:
            self._copy_recv_script()
        elif instr in (mg_script.CLI_YES_NO, mg_script.CLI_PRINT_MSG, mg_script.CLI_COPY_MSG):
            self.dynamic_msg = bytes(self.recv_buffer[:mg_script.CLIENT_MAX_MSG_SIZE])
            text = charmap.decode(self.dynamic_msg)
            self.info(f"[mg] console message: {text!r}")
            if instr == mg_script.CLI_YES_NO:
                self.param = self.yes_no_param
                self.info(f"[mg] yes/no prompt -> answering {'YES' if self.param else 'NO'}")
            # MG_STATE_CLIENT_* menu states answer/dismiss immediately via AdvanceState
            self.func = F_RUN
        elif instr == mg_script.CLI_ASK_TOSS:
            self.param = self.toss_param
            self.info(f"[mg] replace-card prompt -> {'YES (toss the old card)' if self.param == 0 else 'NO (keep it)'}")
            self.func = F_RUN
        elif instr == mg_script.CLI_LOAD_GAME_DATA:
            self._pending_send = (MG_LINKID_GAME_DATA, self.game_data, len(self.game_data))
        elif instr == mg_script.CLI_LOAD_TOSS_RESPONSE:
            self._pending_send = (MG_LINKID_RESPONSE, (self.param & 0xFFFFFFFF).to_bytes(4, "little"), 4)
        elif instr == mg_script.CLI_SAVE_CARD:
            self.saved_card = bytes(self.recv_buffer[:332])
            self.info(f"[mg] WONDER CARD SAVED: {describe_wonder_card(self.saved_card)}")
        elif instr == mg_script.CLI_SAVE_NEWS:
            self.saved_news = bytes(self.recv_buffer[:444])
            self._pending_send = (MG_LINKID_RESPONSE, (0).to_bytes(4, "little"), 4)
            self.info("[mg] Wonder News saved")
        elif instr == mg_script.CLI_RUN_MEVENT_SCRIPT:
            self.activation_scripts.append(bytes(self.recv_buffer))
            self.info("[mg] mystery-event script received (recorded, not executed)")
        elif instr == mg_script.CLI_SAVE_STAMP:
            self.saved_stamp = bytes(self.recv_buffer[:4])
            self.info(f"[mg] stamp saved: {self.saved_stamp.hex()}")
        elif instr == mg_script.CLI_SAVE_RAM_SCRIPT:
            self.saved_ram_script = bytes(self.recv_buffer[:RAM_SCRIPT_SAVE_SIZE])
            self.info(f"[mg] RAM (delivery) SCRIPT SAVED ({len(self.saved_ram_script)} bytes, "
                      f"head {self.saved_ram_script[:8].hex()})")
        elif instr == mg_script.CLI_RECV_EREADER_TRAINER:
            self.info("[mg] e-Reader trainer received (recorded)")
        elif instr == mg_script.CLI_RUN_BUFFER_SCRIPT:
            self.buffer_scripts.append(bytes(self.recv_buffer))
            self.param = 1
            self.info("[mg] buffer (native code) script received - recorded, NOT executed; reporting success")
        else:
            self.info(f"[mg] unknown client instruction {instr} param={param} - ignored")

    def _copy_recv_script(self):
        self.script = bytes(self.recv_buffer)
        self.cmdidx = 0
        n = 0
        for i in range(0, len(self.script), 8):
            ins = int.from_bytes(self.script[i:i + 4], "little")
            n += 1
            if ins in (mg_script.CLI_RETURN, mg_script.CLI_COPY_RECV) or ins > 21:
                break
        self.trace.append((self._tick, "copy_recv_script", n))

    # --- per VBlank ---------------------------------------------------------------------------
    def poll_send_done(self):
        """Window-gated: keep an in-flight HOLD advancing on the host's reflection (trade.py)."""
        if self.sender is not None and self.sender.state == block.HOLD:
            self.sender.tick(self.rx.peers[1])

    def tick(self):
        self._tick += 1
        # 1. a block on the wire always finishes first
        if self.sender is not None:
            host_rx = self.rx.peers[0]
            peer_sending = bool(host_rx.receiving and not host_rx.done)
            words = self.sender.tick(self.rx.peers[1], peer_sending=peer_sending)
            if self.sender.done:
                self.sender = None
                self._send_gap = self.inter_block_gap
                if self.state == C_LINK:
                    self.trace.append((self._tick, "link_player_sent",))
                    self.info("Our LinkPlayer block is complete on the wire.")
            if (words[0] & 0xFFFF) != 0 or self.sender is not None and self.sender.state != block.HOLD:
                return words
        # 2. link phase: the one post-exchange standby [union_room.c:2391]
        if self.state == C_LINK:
            if self.established and not self._standby_initiated:
                self._standby_initiated = True
                self.barrier.initiate(barriermod.STANDBY)
                self.trace.append((self._tick, "standby_initiated", self.barrier.local_count))
                self.info("Link established; standing by (count 0) then starting the Mystery Gift client.")
            if self._standby_initiated and not self.barrier.active:
                self._set_state(C_GIFT)
                self.info("Mystery Gift client started; waiting for the console's client script.")
        if self.barrier.active and self.barrier.mode == barriermod.STANDBY:
            return self.barrier.want_emit() or [0] * 7
        # 3. the client [MysteryGiftClient_Run, one FUNC per frame]
        if self.state == C_GIFT:
            if self.func == F_RUN:
                self._run_one()
            elif self.func == F_RECV:
                if self._drain_recv():
                    self.func = F_RUN
                else:
                    self._gift_idle += 1
            elif self.func == F_SEND:
                if self._send_gap > 0:
                    self._send_gap -= 1
                elif self.sender is not None:
                    pass                    # the previous block is still on the wire (HOLD)
                elif self._send_blocks:
                    self._begin_block(self._send_blocks.pop(0), self._message_label)
                    return self.tick_sender_first_words()
                else:
                    self.func = F_RUN
            if self.func == F_DONE:
                self._set_state(C_CLOSE)
                self.done = True
                self.barrier.initiate(barriermod.CLOSE)
                self.info("Client finished; sending READY_CLOSE_LINK [mystery_gift_menu.c:1248].")
        if self.state == C_CLOSE:
            return self.barrier.want_emit() or [0] * 7
        return [0] * 7

    def tick_sender_first_words(self):
        host_rx = self.rx.peers[0]
        peer_sending = bool(host_rx.receiving and not host_rx.done)
        return self.sender.tick(self.rx.peers[1], peer_sending=peer_sending)

    # --- reporting ----------------------------------------------------------------------------
    def status(self):
        return (f"state={self.state} func={self.func} established={self.established} "
                f"lp_sent={self._lp_sent} host_lp={self.host_link_player is not None} "
                f"barrier={self.barrier.mode}/{self.barrier.local_count} "
                f"sender={(self.sender.state, self.sender.index, self.sender.count) if self.sender else None} "
                f"msgs_in={sum(1 for m in self.messages if m[1] == 'in')} "
                f"msgs_out={sum(1 for m in self.messages if m[1] == 'out')} "
                f"buffered={len(self._host_blocks)} awaiting={self.link_recv.expected_ident} "
                f"card={self.card_received} result={self.result} host_ops={self.host_ops}")
