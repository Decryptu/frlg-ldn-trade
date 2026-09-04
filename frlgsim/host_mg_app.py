"""Application runtime for hosting one FRLG Mystery Gift distribution; subclasses HostApplication
and overrides only the build/startup-log/progress seams."""

from . import (buffer_script, charmap, config as configmod, gift_registry, host_session,
               easychat, ldntrace, mystery_event, mystery_gift_attempts, wonder_news)
from .host_app import HostApplication
from .host_beacon import build_wonder_card_app_data, build_wonder_news_app_data
from .host_mystery_gift import (
    MG_CLOSE, MG_DONE, MG_GIFT, MG_START, HostMysteryGiftEngine,
    MysteryGiftTiming,
)
from .host_pia import HostPeerProtocol
from .linkplayer import HOST_NAME_PAD
from .mg_server import (
    BUFFER_EXPECT_TRAINER_ID, SERVER_RESULT_NAMES, SVR_MSG_CARD_SENT, SVR_MSG_GIFT_SENT_1,
    SVR_MSG_NEWS_SENT, SVR_MSG_STAMP_SENT)

MysteryGiftPayload = configmod.MysteryGiftPayload
MysteryGiftDistribution = configmod.MysteryGiftDistribution
MysteryGiftRunConfig = configmod.MysteryGiftRunConfig
WonderNewsPayload = configmod.WonderNewsPayload


class MysteryGiftHostApplication(HostApplication):
    # The server results that mean the console actually kept something.
    SUCCESS_RESULTS = (SVR_MSG_CARD_SENT, SVR_MSG_STAMP_SENT, SVR_MSG_GIFT_SENT_1)
    ACTIVITY_NOUN = "Wonder Card"

    def __init__(self, config, *, distribution=None, **kwargs):
        super().__init__(config, **kwargs)
        self.card = None
        self.ram_script = None
        self.distribution = None
        self._prepared_distribution = distribution
        self._last_state = None
        self._result_logged = False

    def _build_payload(self):
        return self.config.payload.build()

    def _build_distribution(self):
        return (self._prepared_distribution if self._prepared_distribution is not None
                else self.config.payload.build_distribution())

    def _build_components(self):
        phy, keys = self._resolve_phy_and_keys()
        link_player = self.profile.to_link_player()
        self.distribution = self._build_distribution()
        self.card = self.distribution.card
        self.ram_script = self.distribution.ram_script
        timing = None
        overrides = {}
        if self.config.client_ready_idle_frames is not None:
            overrides["client_ready_idle_frames"] = self.config.client_ready_idle_frames
        if self.config.inter_block_gap_frames is not None:
            overrides["inter_block_gap_frames"] = self.config.inter_block_gap_frames
        if self.config.block_repeat is not None:
            overrides["block_repeat"] = self.config.block_repeat
        if self.config.ram_script_block_repeat is not None:
            overrides["ram_script_block_repeat"] = self.config.ram_script_block_repeat
        if overrides:
            timing = MysteryGiftTiming(**overrides)
        engine = HostMysteryGiftEngine(
            distribution=self.distribution, link_player=link_player,
            trust_pia=self.config.trust_pia, timing=timing, log=self.log)
        self.session = host_session.HostSession(engine=engine, log=self.log)
        inactive, active = self._build_app_data()
        self.tracer = (ldntrace.Tracer(self.ldn.capture_path, log=self.log)
                       if self.ldn.capture_path else None)
        self.network = self.transport_factory(
            app_data=inactive, password=self.ldn.password,
            nickname=self.profile.discovery_name, keys_path=keys,
            local_comm_id=self.ldn.local_comm_id,
            scene_id=self.options.scene_id,
            max_participants=self.options.max_participants,
            phyname=phy, channel=self.options.channel,
            skip_encryption=self.options.skip_encryption,
            accept_decrypted_ccmp=self.options.accept_decrypted_ccmp,
            tracer=self.tracer, log=self.log)
        self.peer = HostPeerProtocol(
            self.network, self.profile, self.session, active,
            native_nonce_sequence=self.options.native_nonce_sequence,
            session_response_first=self.options.session_response_first,
            tracer=self.tracer, log=self.log)
        self._last_state = self.session.activity.state
        return link_player

    def _build_app_data(self):
        """Which of the console's menus this host is visible in; the activity byte is the only difference."""
        return build_wonder_card_app_data(
            self.profile, self.session.rfu.host_session_id)

    def _log_identity(self, link_player):
        wire = link_player.pack(name_pad=HOST_NAME_PAD)
        payload = self.config.payload
        self.info(f"Host identity: OT={self.profile.name!r}, "
                  f"TID=0x{self.profile.tid:04x}, SID=0x{self.profile.sid:04x}")
        self.info("Host LinkPlayer display identity: "
                  f"name_bytes={wire[8:16].hex()} "
                  f"language={int.from_bytes(wire[26:28], 'little')}")
        self.info(f"RFU parent identity: raw={self.session.rfu.host_session_id.hex()} "
                  f"u16=0x{int.from_bytes(self.session.rfu.host_session_id, 'little'):04x}")
        details = gift_registry.GIFT_REGISTRY.describe(payload.gift)
        card_title = charmap.decode(self.card[10:50])
        self.info(f"Gift: {payload.gift!r}; {details}; card title {card_title!r}; "
                  f"Wonder Card flagId {payload.flag_id} "
                  f"(receipt flag 0x{payload.receipt_flag:03x}), "
                  f"card {len(self.card)}B + RAM script {len(self.ram_script)}B")
        distribution = getattr(self, "distribution", None)
        if distribution is not None and distribution.has_trainer:
            trainer = distribution.trainer
            self.info(
                "Visiting trainer rides with this card: "
                f"{charmap.decode(trainer[4:12])[:5]!r} (facility class {trainer[1]}), "
                f"{len(trainer)}B -> battleTower.ereaderTrainer; the console battles it in the "
                "house on SEVEN ISLAND")
        if distribution is not None and distribution.has_mevent:
            self.info(
                "A Mystery Event script rides with this card: "
                f"{len(distribution.mevent)}B -> CLI_RUN_MEVENT_SCRIPT; "
                + mystery_event.describe(distribution.mevent))
            self.info("The console runs it at the Mystery Gift menu and answers with the script's "
                      "own status in MG_LINKID_RESPONSE; watch for the "
                      "'Mystery Event script status' line below.")
        if distribution is not None and distribution.is_gated:
            self.info("QUESTIONNAIRE GATE: nothing is sent unless the console is already holding "
                      + easychat.describe_words(distribution.questionnaire))
            self.info("A console that is not gets our refusal message and keeps everything it has. "
                      "Word ids are per-language outside the species and move groups, so the "
                      "phrase must have been read off this console first.")
        if self.config.client_ready_idle_frames is not None:
            self.info("Mystery Gift timing override: "
                      f"client_ready_idle_frames={self.config.client_ready_idle_frames}")
        if self.config.inter_block_gap_frames is not None:
            self.info("Mystery Gift timing override: "
                      f"inter_block_gap_frames={self.config.inter_block_gap_frames}")
        if self.config.block_repeat is not None:
            self.info("Mystery Gift timing override: "
                      f"block_repeat={self.config.block_repeat}")
        self.info("Advertising ACTIVITY_WONDER_CARD. On the Switch choose "
                  "Mystery Gift -> Wonder Cards -> Friend.")

    def _hosting_instructions(self):
        return ("Hosting Mystery Gift. On the Switch choose "
                "Mystery Gift -> Wonder Cards -> Friend.")

    def _rfu_ready_message(self):
        return ("RFU NI handshake complete; parent UNI and Mystery Gift "
                "LinkPlayer startup are active.")

    def _close_grace_message(self):
        return ("The console left LDN after confirming Mystery Gift close; "
                "finishing the host grace period.")

    def _completion_message(self):
        return "Mystery Gift close grace completed; host peer traffic stopped cleanly."

    def _log_activity_progress(self):
        engine = self.session.activity
        state = engine.state
        if state != self._last_state:
            self._last_state = state
            message = {
                MG_START: "LinkPlayer exchange complete; waiting for the console's gift client.",
                MG_GIFT: f"Sending the {self.ACTIVITY_NOUN} conversation.",
                MG_CLOSE: "Gift conversation finished; closing the RFU link.",
                MG_DONE: "Mystery Gift session complete.",
            }.get(state)
            if message:
                self.info(message)
        if engine.result is not None and not self._result_logged:
            self._result_logged = True
            self.info("Result: " + SERVER_RESULT_NAMES.get(
                engine.result, f"code {engine.result}"))

    def _success_message(self, result):
        distribution = getattr(self, "distribution", None)
        if distribution is not None and distribution.is_gated:
            return ("The console was holding the phrase, so the gift went out. A console that was "
                    "not would have read the refusal message and kept everything it has.")
        if distribution is not None and distribution.has_mevent:
            status = self.session.activity.server.mevent_status
            return ("Mystery Event script ran on the console; it answered with status "
                    f"{status}. The console saved by itself, so whatever the script wrote is "
                    "now in the save.")
        if result == SVR_MSG_GIFT_SENT_1:
            return ("Visiting trainer delivered. On the Switch, go to SEVEN ISLAND and talk to "
                    "the old woman in the house in town to battle it; the Wonder Card's own "
                    "message is with the delivery man in any Pokemon Center.")
        noun = "Stamp" if result == SVR_MSG_STAMP_SENT else "Wonder Card"
        return (f"{noun} delivered. On the Switch, talk to the delivery man "
                "on the second floor of any Pokemon Center to receive the gift.")

    def _save_received(self):
        """Nothing to save: the gift travels outward only."""

    def run(self):
        joined = super().run()
        engine = self.session.activity if self.session is not None else None
        self.delivery_succeeded = bool(
            engine is not None and engine.result in self.SUCCESS_RESULTS)
        if self.delivery_succeeded:
            print(self._success_message(engine.result))
        elif engine is not None and engine.result is not None:
            print("Session finished without delivering anything: "
                  + SERVER_RESULT_NAMES.get(engine.result, f"code {engine.result}"))
        if joined and self.config.attempt_log_dir:
            try:
                path, attempt = mystery_gift_attempts.append_attempt(
                    self.config.attempt_log_dir,
                    received_result=self.delivery_succeeded,
                    trainer=(engine.child_link_player if engine is not None else None))
                self.info(f"Attempt ledger: recorded attempt {attempt} in {path}")
            except OSError as exc:
                self.info(f"Attempt ledger write failed: {exc}")
        return joined


class WonderNewsHostApplication(MysteryGiftHostApplication):
    """The Wonder News half of the Mystery Gift menu.

    Everything below the server script is the Wonder Card host: the same LDN network, the same RFU
    parent, the same MysteryGiftLink framing. Only two things change - the advertisement's activity
    byte (22, or the console's News screen never lists us) and the server script, which sends 444
    bytes of news and then reads the console's own verdict on whether it kept them.
    """

    SUCCESS_RESULTS = (SVR_MSG_NEWS_SENT,)
    ACTIVITY_NOUN = "Wonder News"

    def _build_app_data(self):
        return build_wonder_news_app_data(
            self.profile, self.session.rfu.host_session_id)

    def _log_identity(self, link_player):
        wire = link_player.pack(name_pad=HOST_NAME_PAD)
        payload = self.config.payload
        news = self.distribution.news
        self.info(f"Host identity: OT={self.profile.name!r}, "
                  f"TID=0x{self.profile.tid:04x}, SID=0x{self.profile.sid:04x}")
        self.info("Host LinkPlayer display identity: "
                  f"name_bytes={wire[8:16].hex()} "
                  f"language={int.from_bytes(wire[26:28], 'little')}")
        self.info(f"RFU parent identity: raw={self.session.rfu.host_session_id.hex()} "
                  f"u16=0x{int.from_bytes(self.session.rfu.host_session_id, 'little'):04x}")
        self.info(f"News: {payload.news!r}; {payload.spec.description}; "
                  + wonder_news.describe(news) + f", {len(news)}B")
        self.info("A console that already holds these exact 444 bytes answers "
                  "MG_LINKID_RESPONSE with TRUE and keeps what it has; pass --news-id to make the "
                  "same text new again.")
        self.info("Advertising ACTIVITY_WONDER_NEWS. On the Switch choose "
                  "Mystery Gift -> Wonder News -> Friend.")

    def _hosting_instructions(self):
        return ("Hosting Wonder News. On the Switch choose "
                "Mystery Gift -> Wonder News -> Friend.")

    def _success_message(self, result):
        return ("Wonder News delivered. On the Switch it is under Mystery Gift -> Wonder News; "
                "the man in the house in CERULEAN CITY hands over a BERRY for it.")


class BufferScriptHostApplication(MysteryGiftHostApplication):
    """CLI_RUN_BUFFER_SCRIPT: the console executes native ARM code we hand it.

    The last unopened door in the Mystery Gift client, and the only one that is not a gift: no
    Wonder Card, no flagId, nothing written to the save unless the payload writes it. The console
    reaches it from the ordinary Wonder Cards -> Friend screen, so the advertisement, the RFU
    parent and the link framing are all the Wonder Card host's; only the server script differs.
    """

    SUCCESS_RESULTS = (SVR_MSG_GIFT_SENT_1,)
    ACTIVITY_NOUN = "buffer script"

    def _log_identity(self, link_player):
        wire = link_player.pack(name_pad=HOST_NAME_PAD)
        payload = self.config.payload
        code = self.distribution.buffer_code
        self.info(f"Host identity: OT={self.profile.name!r}, "
                  f"TID=0x{self.profile.tid:04x}, SID=0x{self.profile.sid:04x}")
        self.info("Host LinkPlayer display identity: "
                  f"name_bytes={wire[8:16].hex()} "
                  f"language={int.from_bytes(wire[26:28], 'little')}")
        self.info(f"RFU parent identity: raw={self.session.rfu.host_session_id.hex()} "
                  f"u16=0x{int.from_bytes(self.session.rfu.host_session_id, 'little'):04x}")
        self.info(f"Buffer script: {payload.script!r}; {payload.spec.description}; "
                  f"{len(code)}B of ARM, {code.hex()}")
        self.info("The console copies it into gDecompressionBuffer and CALLS IT as "
                  "func(&param, gSaveBlock2Ptr, gSaveBlock1Ptr) "
                  "[decomp:src/mystery_gift_client.c:276]. No Wonder Card is sent and none is "
                  "replaced, so a console holding any card takes this path unprompted.")
        if payload.script == buffer_script.MEMORY_SCAN:
            asked = buffer_script.scan_parameters(code)
            frames = buffer_script.scan_call_count(
                asked["start"], asked["end"], asked["blocks"])
            self.info(
                f"Searching 0x{asked['start']:08X}..0x{asked['end']:08X} for "
                f"0x{asked['needle']:08X}, {asked['blocks']} blocks of "
                f"{buffer_script.SCAN_BLOCK_BYTES} bytes a frame. The payload returns 0 to be "
                "called again next frame [mystery_gift_client.c:277], so this takes about "
                f"{frames} frames, {frames / 60:.1f} s, with the link held open throughout; the "
                f"watchdog ends it after {asked['max_calls']}. The evidence line is 'scan:'.")
        if payload.script == buffer_script.STRING_GATHER:
            asked = buffer_script.gather_parameters(code)
            self.info(
                f"Following {asked['count']} pointer(s) from 0x{asked['src']:08X}, "
                f"{asked['stride']} bytes apart, and sending back the STRINGS themselves rather "
                f"than a window around them - up to {asked['budget']} bytes of them, whole "
                "strings only. A string longer than "
                f"{asked['maxlen']} bytes means the pointer was not one. The evidence line is "
                "'gather:'.")
        if payload.script == buffer_script.CREATE_MON:
            asked = buffer_script.create_mon_parameters(code)
            self.info(
                (f"CALLING 0x{asked['function']:08X} with EIGHT arguments - four in r0..r3 and "
                 "FOUR ON THE STACK, which no payload here has passed before - to build species "
                 f"{asked['species']} at level {asked['level']}"
                 if asked["function"] else
                 "Calling nothing: this checks the send path and the answer's shape with the ROM "
                 "left out of it")
                + (f", IVs all {asked['fixed_iv']}"
                   if asked["fixed_iv"] < buffer_script.USE_RANDOM_IVS else ", IVs rolled")
                + (f", personality 0x{asked['fixed_personality']:08X}"
                   if asked["has_fixed_personality"] else ", personality rolled")
                + ". The 100 bytes are built INSIDE OUR OWN IMAGE"
                + (f" and then copied to 0x{asked['destination']:08X}, which WRITES THE CONSOLE'S "
                   "LIVE MEMORY" if asked["destination"] else
                   ", so nothing on the console is written")
                + ". The evidence line is 'create-mon:'.")
        if payload.script == buffer_script.RNG_TRACE:
            asked = buffer_script.trace_parameters(code)
            self.info(
                f"Sampling 0x{asked['address']:08X} once a frame, {asked['samples']} times "
                f"(~{asked['samples'] / 60:.1f} s), "
                + (f"CALLING 0x{asked['function']:08X} between the two reads of each sample - the "
                   "LCG recurrence between them is the proof that the address is gRngValue and "
                   "that our ARM code called the console's THUMB ROM and came back"
                   if asked["function"] else "calling nothing")
                + ". The evidence line is 'rng-trace:'.")
        expect = payload.expect
        self.info("The evidence line is 'Buffer script status:'. Expecting "
                  + ("the trainer id the console's own game data carried"
                     if expect == BUFFER_EXPECT_TRAINER_ID else
                     "any answer at all" if expect is None else f"0x{int(expect):08X}"))
        self.info("Advertising ACTIVITY_WONDER_CARDS. On the Switch choose "
                  "Mystery Gift -> Wonder Cards -> Friend.")

    def _hosting_instructions(self):
        return ("Hosting a buffer script. On the Switch choose "
                "Mystery Gift -> Wonder Cards -> Friend.")

    def run(self):
        joined = super().run()
        self._write_dump()
        return joined

    def _write_dump(self):
        engine = self.session.activity if self.session is not None else None
        dump = getattr(getattr(engine, "server", None), "buffer_dump", None)
        if not dump:
            return
        path = getattr(self.config.payload, "dump_file", None)
        if path is None:
            return
        try:
            with open(path, "wb") as handle:
                handle.write(dump)
        except OSError as exc:
            self.info(f"could not write the dump to {path}: {exc}")
            return
        print(f"wrote {len(dump)} bytes of console memory to {path}")

    def _success_message(self, result):
        engine = self.session.activity if self.session is not None else None
        status = getattr(getattr(engine, "server", None), "buffer_status", None)
        return ("NATIVE CODE RAN ON THE CONSOLE. It returned "
                + (f"0x{status:08X}" if status is not None else "an answer")
                + ", which matched. The console printed our message and saved.")
