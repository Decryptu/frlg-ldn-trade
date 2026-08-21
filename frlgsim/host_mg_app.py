"""Application runtime for hosting one FRLG Mystery Gift distribution.

Everything below the activity - LDN, Pia, Reliable, RFU bring-up, the beacon
injector, the join/leave lifecycle - is the trade host's proven code, so this
subclasses :class:`frlgsim.host_app.HostApplication` and replaces only the three
trade-specific seams: what gets built, what gets logged at startup, and what
counts as progress.
"""

from . import charmap, config as configmod, host_session, ldntrace, wonder_card
from .host_app import HostApplication
from .host_beacon import build_wonder_card_app_data
from .host_mystery_gift import (
    MG_CLOSE, MG_DONE, MG_GIFT, MG_START, HostMysteryGiftEngine,
)
from .host_pia import HostPeerProtocol
from .linkplayer import HOST_NAME_PAD
from .mg_server import SERVER_RESULT_NAMES, SVR_MSG_CARD_SENT

# Retain the original import location while keeping the models centralized.
MysteryGiftPayload = configmod.MysteryGiftPayload
MysteryGiftRunConfig = configmod.MysteryGiftRunConfig


class MysteryGiftHostApplication(HostApplication):
    """Host one Wonder Card handout for a single console."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)
        self.card = None
        self.ram_script = None
        self._last_state = None
        self._result_logged = False

    def _build_payload(self):
        """Build the selected payload through the shared immutable config."""
        return self.config.payload.build()

    def _build_components(self):
        phy, keys = self._resolve_phy_and_keys()
        link_player = self.profile.to_link_player()
        self.card, self.ram_script = self._build_payload()
        engine = HostMysteryGiftEngine(
            self.card, self.ram_script, link_player=link_player,
            trust_pia=self.config.trust_pia, log=self.log)
        self.session = host_session.HostSession(engine=engine, log=self.log)
        inactive, active = build_wonder_card_app_data(
            self.profile, self.session.rfu.host_session_id)
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
            tracer=self.tracer, log=self.log)
        self.peer = HostPeerProtocol(
            self.network, self.profile, self.session, active,
            native_nonce_sequence=self.options.native_nonce_sequence,
            session_response_first=self.options.session_response_first,
            log=self.log)
        self._last_state = self.session.activity.state
        return link_player

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
        if payload.gift == wonder_card.GIFT_BEAST_CUTSCENE:
            details = (f"level {wonder_card.LEGENDARY_BEAST_LEVEL}; "
                       "Lansat Berry, Liechi Berry, and Master Ball")
        else:
            details = "level-50 Celebi; no item"
        card_title = charmap.decode(self.card[10:50])
        self.info(f"Gift: {payload.gift!r}; {details}; card title {card_title!r}; "
                  f"Wonder Card flagId {payload.flag_id} "
                  f"(receipt flag 0x{payload.receipt_flag:03x}), "
                  f"card {len(self.card)}B + RAM script {len(self.ram_script)}B")
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
        """Report Mystery Gift milestones through the activity-neutral runtime hook."""
        engine = self.session.activity
        state = engine.state
        if state != self._last_state:
            self._last_state = state
            message = {
                MG_START: "LinkPlayer exchange complete; waiting for the console's gift client.",
                MG_GIFT: "Sending the Wonder Card conversation.",
                MG_CLOSE: "Gift conversation finished; closing the RFU link.",
                MG_DONE: "Mystery Gift session complete.",
            }.get(state)
            if message:
                self.info(message)
        if engine.result is not None and not self._result_logged:
            self._result_logged = True
            self.info("Result: " + SERVER_RESULT_NAMES.get(
                engine.result, f"code {engine.result}"))

    def _save_received(self):
        """Nothing to save: the gift travels outward only."""

    def run(self):
        joined = super().run()
        engine = self.session.activity if self.session is not None else None
        if engine is not None and engine.result == SVR_MSG_CARD_SENT:
            print("Wonder Card delivered. On the Switch, talk to the delivery man "
                  "on the second floor of any Pokemon Center to receive the gift.")
        elif engine is not None and engine.result is not None:
            print("Session finished without delivering a card: "
                  + SERVER_RESULT_NAMES.get(engine.result, f"code {engine.result}"))
        return joined
