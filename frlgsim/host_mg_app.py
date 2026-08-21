"""Application runtime for hosting one FRLG Mystery Gift distribution.

Everything below the activity - LDN, Pia, Reliable, RFU bring-up, the beacon
injector, the join/leave lifecycle - is the trade host's proven code, so this
subclasses :class:`frlgsim.host_app.HostApplication` and replaces only the three
trade-specific seams: what gets built, what gets logged at startup, and what
counts as progress.
"""

from dataclasses import dataclass, field

from . import config as configmod, host_session, ldntrace, wonder_card
from .host_app import HostApplication
from .host_beacon import build_wonder_card_app_data
from .host_mystery_gift import (
    MG_CLOSE, MG_DONE, MG_GIFT, MG_START, HostMysteryGiftEngine,
)
from .host_pia import HostPeerProtocol
from .linkplayer import HOST_NAME_PAD
from .mg_server import SERVER_RESULT_NAMES, SVR_MSG_CARD_SENT


@dataclass(frozen=True)
class MysteryGiftRunConfig:
    """Options for one Wonder Card distribution session."""

    profile: configmod.TrainerProfile = configmod.DEFAULT_TRAINER
    ldn: configmod.LdnConfig = field(default_factory=lambda: configmod.LdnConfig(phy="auto"))
    role: configmod.HostOptions = field(default_factory=lambda: configmod.HostOptions(
        skip_encryption=True, native_nonce_sequence=True, session_response_first=True))
    item: int | None = wonder_card.DEFAULT_GIFT_ITEM
    flag_id: int = 1003
    card_title: str = wonder_card.DEFAULT_GIFT_TITLE
    card_subtitle: str = wonder_card.DEFAULT_GIFT_SUBTITLE
    trust_pia: bool = True
    def __post_init__(self):
        if self.item is not None and (type(self.item) is not int or not 0 < self.item <= 0xFFFF):
            raise ValueError("item must be a positive 16-bit item id or None")
        # Raises with the accepted range if flag_id is outside sReceivedGiftFlags.
        wonder_card.flag_for_flag_id(self.flag_id)
        if not isinstance(self.profile, configmod.TrainerProfile):
            raise ValueError("profile must be a TrainerProfile")
        if not isinstance(self.ldn, configmod.LdnConfig):
            raise ValueError("ldn must be an LdnConfig")
        if not isinstance(self.role, configmod.HostOptions):
            raise ValueError("role must be HostOptions")


class MysteryGiftHostApplication(HostApplication):
    """Host one Wonder Card handout for a single console."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)
        self.card = None
        self.ram_script = None
        self._last_state = None
        self._result_logged = False

    def _build_payload(self):
        """Build the live payload from the shared Wonder Card defaults.

        ``build_default_gift`` is the sole source of the card's body, Celebi
        icon, signature, and hidden ID number. The CLI may add an item or
        override the receipt flag, title, and subtitle.
        """
        return wonder_card.build_default_gift(
            item=self.config.item,
            flag_id=self.config.flag_id,
            title=self.config.card_title,
            subtitle=self.config.card_subtitle)

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
        flag = wonder_card.flag_for_flag_id(self.config.flag_id)
        self.info(f"Host identity: OT={self.profile.name!r}, "
                  f"TID=0x{self.profile.tid:04x}, SID=0x{self.profile.sid:04x}")
        self.info("Host LinkPlayer display identity: "
                  f"name_bytes={wire[8:16].hex()} "
                  f"language={int.from_bytes(wire[26:28], 'little')}")
        self.info(f"RFU parent identity: raw={self.session.rfu.host_session_id.hex()} "
                  f"u16=0x{int.from_bytes(self.session.rfu.host_session_id, 'little'):04x}")
        self.info(f"Gift: {self.config.card_title!r} - Wonder Card flagId "
                  f"{self.config.flag_id} (receipt flag 0x{flag:03x}), "
                  f"item {self.config.item if self.config.item is not None else 'none'}, "
                  f"card {len(self.card)}B + RAM script {len(self.ram_script)}B")
        self.info("Advertising ACTIVITY_WONDER_CARD. On the Switch choose "
                  "Mystery Gift -> Wonder Cards -> Friend.")

    def _log_trade_progress(self):
        """Report Mystery Gift milestones (the base class calls this every tick)."""
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
