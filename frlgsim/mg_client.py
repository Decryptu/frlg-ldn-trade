"""Child-side FRLG Mystery Gift client [decomp:src/mystery_gift_client.c]: we receive a Wonder Card from
a console that chose Friend -> send. Same feed_in_frame()/tick() contract as the trade joiner, so it drops
into frlgsim.sim.Sim unchanged; every message in both directions is kept in ``messages``."""

from collections import deque

from . import (barrier as barriermod, block, buffer_script, charmap, ereader_trainer,
               linkplayer, mg_link, mg_script, mystery_event, rfu, wonder_news)
from . import mystery_gift as mg
from .mystery_gift import (MG_LINKID_CLIENT_SCRIPT, MG_LINKID_GAME_DATA, MG_LINKID_GAME_STAT,
                           MG_LINKID_READY_END, MG_LINKID_RESPONSE)

ACTIVITY_WONDER_CARD = 21           # include/constants/union_room.h:46
ACTIVITY_WONDER_NEWS = 22

C_LINK = "C_LINK"
C_GIFT = "C_GIFT"
C_CLOSE = "C_CLOSE"
C_DONE = "C_DONE"

F_RUN, F_RECV, F_SEND, F_WAIT, F_DONE = "run", "recv", "send", "wait", "done"

COUNT_LINK_PLAYER = 17              # ceil(200/12): the fixed 200B LinkPlayer pull
LINK_PLAYER_REQTYPES = (0, 1)       # BLOCK_REQ_SIZE_NONE / _200 [link.c BLOCK_REQ_*]

# The parent's receive slot for a child block re-arms only after its four-VBlank countdown
# [decomp:src/link_rfu_2.c:1220] and after MGL_Receive consumed the previous block.
DEFAULT_INTER_BLOCK_GAP = 12

RAM_SCRIPT_SAVE_SIZE = 1024

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
                         software_version=0, max_stamps=0, card_metadata=b"",
                         questionnaire=(), easy_chat_profile=()):
    """[decomp:src/mystery_gift.c:337]; a 7-character name spills its 0xFF over playerTrainerId[0] natively
    and that is reproduced on purpose."""
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
    # The four words the player typed at the Poke Mart clerk, and their battle profile; both travel
    # in every session and neither is ever read back by the game [decomp:src/mystery_gift.c:361].
    for index, value in enumerate(questionnaire[:4]):
        off = mg_script.GD_OFF_QUESTIONNAIRE + 2 * index
        data[off:off + 2] = (int(value) & 0xFFFF).to_bytes(2, "little")
    for index, value in enumerate(easy_chat_profile[:mg_script.EASY_CHAT_BATTLE_WORDS_COUNT]):
        off = mg_script.GD_OFF_EASY_CHAT + 2 * index
        data[off:off + 2] = (int(value) & 0xFFFF).to_bytes(2, "little")
    tid = (link_player.trainer_id & 0xFFFFFFFF).to_bytes(4, "little")
    data[mg_script.GD_OFF_TRAINER_ID:mg_script.GD_OFF_TRAINER_ID + 4] = tid
    name = charmap.encode(link_player.name)[:7] + b"\xff"
    data[mg_script.GD_OFF_PLAYER_NAME:mg_script.GD_OFF_PLAYER_NAME + len(name)] = name
    data[mg_script.GD_OFF_GAME_CODE:mg_script.GD_OFF_GAME_CODE + 4] = bytes(game_code)[:4].ljust(4, b"\x00")
    data[mg_script.GD_OFF_VERSION] = software_version & 0xFF
    return bytes(data)


def describe_wonder_card(card):
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
    def __init__(self, link_player=None, *, version="firered", language="english",
                 holding_flag_id=0, accept_replacement=True, yes_no_answer=True,
                 game_code=None, software_version=0, trust_pia=False,
                 questionnaire=(), easy_chat_profile=(),
                 inter_block_gap=DEFAULT_INTER_BLOCK_GAP, log=lambda *a: None):
        self.lp = link_player or linkplayer.LinkPlayer(version=linkplayer.VERSION_FIRE_RED)
        self.mpid = 1
        self.log = log
        self.info = getattr(log, "info", log)
        self.trust_pia = trust_pia
        self.inter_block_gap = int(inter_block_gap)
        # sim._ensure_ni reads these for the NI game data
        self.ni_activity = ACTIVITY_WONDER_CARD
        self.ni_started = False
        self._live = False

        version_code = (mg.VERSION_CODE_LEAFGREEN if version == "leafgreen"
                        else mg.VERSION_CODE_FIRERED)
        if game_code is None:
            game_code = GAME_CODES.get((version, language), b"BPRE")
        self.game_data = build_link_game_data(
            self.lp, version_code=version_code, flag_id=holding_flag_id,
            game_code=game_code, software_version=software_version,
            questionnaire=questionnaire, easy_chat_profile=easy_chat_profile)
        self.holding_flag_id = holding_flag_id
        # CLI_ASK_TOSS param is FALSE for YES (toss the old card) and TRUE for NO; the server gifts on FALSE.
        self.toss_param = 0 if accept_replacement else 1
        self.yes_no_param = 1 if yes_no_answer else 0

        self.rx = block.BlockReceiver()
        self.sender = None
        self.barrier = barriermod.BarrierResponder(log=self.log)
        self._player_ids_seen = False

        self._lp_sent = False
        self._lp_requests = 0
        self.host_link_player = None
        self._standby_initiated = False
        self._self_standby_echo = None

        self.state = C_LINK
        self.state_history = [C_LINK]
        self.func = F_RUN
        self.script = mg_script.CLIENT_SCRIPT_INIT
        self.cmdidx = 0
        self.param = 0
        self.recv_buffer = bytearray(mg.MG_LINK_BUFFER_SIZE)
        self.link_recv = mg_link.MysteryGiftLinkReceiver()
        self._host_blocks = deque()
        self._pending_send = None
        self._send_blocks = []
        self._send_gap = 0
        self._message_label = ""
        self.saved_card = None
        self.saved_ram_script = None
        self.saved_stamp = None
        self.saved_news = None
        self.saved_trainer = None
        self.activation_scripts = []
        self.mevent_results = []
        self.party_count = 1
        self.national_dex = False
        self.buffer_scripts = []
        self.dynamic_msg = None
        self.result = None
        self.close_confirmed = False
        self.done = False
        self.error = None
        self.messages = []
        self.trace = []
        self.host_ops = {}
        self._tick = 0
        self._unexpected_blocks = 0
        self._gift_idle = 0

    @property
    def established(self):
        return self._lp_sent and self.host_link_player is not None

    @property
    def in_seat_phase(self):
        # sim.py uses this only to pick the retransmit policy; no held keys are ever emitted.
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
        # The console never broadcasts its own 0x6600 at mpId 0; the only evidence a child-initiated
        # round landed is its reflection of ours.
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
            return
        if self.state == C_LINK and reqtype in LINK_PLAYER_REQTYPES and not self._lp_sent:
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

    def _begin_block(self, data, label):
        # Reset the peer-1 reflection so the fresh INIT waits for THIS block's echo.
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

    def _drain_recv(self):
        while self._host_blocks and self.link_recv.active:
            blk = self._host_blocks.popleft()
            try:
                payload = self.link_recv.feed_block(blk)
            except mg_link.MysteryGiftLinkError as exc:
                # Natively LinkRfu_FatalError; keep the link up so the capture shows what the console does next.
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
            # IsWonderNewsSameAsSaved compares the whole 444-byte struct against what is already
            # saved [decomp:src/mystery_gift.c:140]; the verdict travels back as MG_LINKID_RESPONSE,
            # FALSE when the news was taken and TRUE when the console kept what it had
            # [mystery_gift_client.c:210]. Invalid news is not saved but still answers FALSE.
            news = bytes(self.recv_buffer[:wonder_news.WONDER_NEWS_SIZE])
            same = (self.saved_news is not None
                    and wonder_news.validate(self.saved_news)
                    and self.saved_news == news)
            if not same and wonder_news.validate(news):
                self.saved_news = news
            self._pending_send = (MG_LINKID_RESPONSE,
                                  (1 if same else 0).to_bytes(4, "little"), 4)
            self.info("[mg] Wonder News already held, keeping it" if same
                      else "[mg] WONDER NEWS SAVED: " + wonder_news.describe(news))
        elif instr == mg_script.CLI_RUN_MEVENT_SCRIPT:
            # Client_RunMysteryEventScript runs the bytecode in place out of recvBuffer and leaves
            # ctx->data[2] in client->param [decomp:src/mystery_gift_client.c:257], which is what a
            # following CLI_LOAD_TOSS_RESPONSE ships back.
            script = bytes(self.recv_buffer)
            self.activation_scripts.append(script)
            result = mystery_event.run(script, party_count=self.party_count)
            self.mevent_results.append(result)
            self.param = result.status
            for effect in result.effects:
                if effect[0] == "givenationaldex":
                    self.national_dex = True
                elif effect[0] == "givepokemon":
                    self.party_count += 1
            self.info(f"[mg] MYSTERY EVENT SCRIPT RUN: "
                      f"{mystery_event.describe(script)} -> {result.ran} commands, stopped at "
                      f"{result.stopped_at}, status {result.status}, "
                      f"effects {[effect[0] for effect in result.effects]}")
        elif instr == mg_script.CLI_SAVE_STAMP:
            self.saved_stamp = bytes(self.recv_buffer[:4])
            self.info(f"[mg] stamp saved: {self.saved_stamp.hex()}")
        elif instr == mg_script.CLI_SAVE_RAM_SCRIPT:
            self.saved_ram_script = bytes(self.recv_buffer[:RAM_SCRIPT_SAVE_SIZE])
            self.info(f"[mg] RAM (delivery) SCRIPT SAVED ({len(self.saved_ram_script)} bytes, "
                      f"head {self.saved_ram_script[:8].hex()})")
        elif instr == mg_script.CLI_RECV_EREADER_TRAINER:
            # InitRamScript-style: the console copies the struct and validates it, clearing it on a
            # bad checksum [decomp:src/mystery_gift_client.c:233].
            trainer = bytes(self.recv_buffer[:ereader_trainer.TRAINER_SIZE])
            if ereader_trainer.validate(trainer):
                self.saved_trainer = trainer
                self.info("[mg] VISITING TRAINER SAVED "
                          f"({len(trainer)} bytes, class {trainer[1]}, "
                          f"name {charmap.decode(trainer[4:12])!r})")
            else:
                self.saved_trainer = None
                self.info("[mg] visiting trainer FAILED ValidateEReaderTrainer - console clears it")
        elif instr == mg_script.CLI_RUN_BUFFER_SCRIPT:
            # Client_Run copies the WHOLE receive buffer into gDecompressionBuffer and then calls
            # it every frame until it returns 1 [decomp:src/mystery_gift_client.c:237,276]. We run
            # it for real, on a model of the console's memory map, so the offline harness proves
            # the payload and not just the transport.
            code = bytes(self.recv_buffer)
            self.buffer_scripts.append(code)
            self._run_buffer_script(code)
        else:
            self.info(f"[mg] unknown client instruction {instr} param={param} - ignored")

    def _save_block2_image(self):
        """As much of struct SaveBlock2 [decomp:include/global.h:327] as a payload can read.

        The trainer id here is the real one. The copy that travels in MysteryGiftLinkGameData can
        have its low byte eaten by the player name's terminator [decomp:src/mystery_gift.c:364];
        that divergence is the point of the trainer-id probe, so it must not be modelled away.
        """
        sav2 = bytearray(0x1000)
        name = charmap.encode(self.lp.name)[:7] + b"\xff"
        sav2[buffer_script.SAV2_PLAYER_NAME:buffer_script.SAV2_PLAYER_NAME + len(name)] = name
        sav2[buffer_script.SAV2_PLAYER_TRAINER_ID:buffer_script.SAV2_PLAYER_TRAINER_ID + 4] = (
            (self.lp.trainer_id & 0xFFFFFFFF).to_bytes(4, "little"))
        return bytes(sav2)

    def _run_buffer_script(self, code):
        if not buffer_script.emulation_available():
            self.param = 1
            self.info("[mg] buffer script received, NOT executed (no unicorn): "
                      + buffer_script.describe(code))
            return
        try:
            run = buffer_script.emulate(code, param=self.param or 0,
                                        sav2=self._save_block2_image())
        except buffer_script.BufferScriptError as exc:
            # On the console this is a crash or a hang inside the Mystery Gift menu, with no way
            # back: exactly what the offline harness exists to catch.
            self.error = f"buffer script would not run on the console: {exc}"
            self.info("[mg] BUFFER SCRIPT FAILED: " + str(exc))
            return
        self.param = run.param
        if not run.done:
            self.error = (f"buffer script returned {run.returned}, not "
                          f"{buffer_script.BUFFER_SCRIPT_DONE}: the console would call it again "
                          "next frame, forever")
            self.info("[mg] BUFFER SCRIPT NEVER FINISHES: " + self.error)
            return
        self.info(f"[mg] BUFFER SCRIPT RAN: {buffer_script.describe(code)}, "
                  f"{run.instructions} instructions, returned {run.returned}, "
                  f"left 0x{run.param:08X} in param")

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

    def poll_send_done(self):
        if self.sender is not None and self.sender.state == block.HOLD:
            self.sender.tick(self.rx.peers[1])

    def tick(self):
        self._tick += 1
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
                    pass
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

    def status(self):
        return (f"state={self.state} func={self.func} established={self.established} "
                f"lp_sent={self._lp_sent} host_lp={self.host_link_player is not None} "
                f"barrier={self.barrier.mode}/{self.barrier.local_count} "
                f"sender={(self.sender.state, self.sender.index, self.sender.count) if self.sender else None} "
                f"msgs_in={sum(1 for m in self.messages if m[1] == 'in')} "
                f"msgs_out={sum(1 for m in self.messages if m[1] == 'out')} "
                f"buffered={len(self._host_blocks)} awaiting={self.link_recv.expected_ident} "
                f"card={self.card_received} result={self.result} host_ops={self.host_ops}")
