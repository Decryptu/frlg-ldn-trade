"""Runtime for the experimental JoySpot discovery-only hardware probe.

The supported distributor is the Friend-path ``frlgmg_host.py``. This probe is
kept solely to investigate the unresolved Wireless Communication serial mapping.
It intentionally stops at LDN advertisement and association: it does not
instantiate Pia, Reliable, RFU, LinkPlayer, or Mystery Gift state.
"""

from dataclasses import dataclass
import os

from . import ldntrace, transport
from .host_beacon import BeaconInjector
from .host_support import resolve_keys
from .joyspot_discovery import (
    JOYSPOT_LOCAL_COMMUNICATION_ID,
    JOYSPOT_MAX_PARTICIPANTS,
    JOYSPOT_SERIAL,
    JoySpotCandidate,
    build_joyspot_app_data,
    candidate_by_name,
    decode_joyspot_app_data,
    new_parent_session_id,
)


PROBE_POLL_SECONDS = 0.25


@dataclass(frozen=True)
class JoySpotProbeConfig:
    """OS and radio settings for one controlled discovery candidate."""

    candidate: JoySpotCandidate
    phy: str = "auto"
    keys_path: str = "~/.switch/prod.keys"
    password: bytes | None = None
    channel: int = 1
    capture_path: str | None = None
    skip_preflight: bool = False
    skip_encryption: bool = False

    def __post_init__(self):
        if isinstance(self.candidate, str):
            object.__setattr__(self, "candidate", candidate_by_name(self.candidate))
        if not isinstance(self.candidate, JoySpotCandidate):
            raise ValueError("candidate must be a JoySpotCandidate")
        if not isinstance(self.phy, str) or not self.phy:
            raise ValueError("phy must be a non-empty string")
        if not isinstance(self.keys_path, str) or not self.keys_path:
            raise ValueError("keys_path must be a non-empty string")
        if self.password is not None and not isinstance(self.password, bytes):
            raise ValueError("password must be bytes or None")
        if type(self.channel) is not int or not 1 <= self.channel <= 14:
            raise ValueError("channel must be 1..14")
        if self.capture_path is not None and not isinstance(self.capture_path, str):
            raise ValueError("capture_path must be a string or None")


class JoySpotProbeApplication:
    """Own one research advertisement until interruption or a sweep decision."""

    def __init__(self, config, profile, *, log=print,
                 transport_factory=transport.HostTransport,
                 injector_factory=BeaconInjector,
                 tracer_factory=ldntrace.Tracer,
                 parent_id_factory=new_parent_session_id):
        self.config = config
        self.profile = profile
        self.log = log
        self.info = getattr(log, "info", log)
        self.transport_factory = transport_factory
        self.injector_factory = injector_factory
        self.tracer_factory = tracer_factory
        self.parent_id_factory = parent_id_factory
        self.network = None
        self.injector = None
        self.tracer = None
        self.app_data = None
        self.parent_session_id = None
        self.ignored_datagrams = 0
        self.joined_once = False

    def _resolve_phy_and_keys(self):
        phy = self.config.phy
        if phy == "auto":
            phy = transport.find_ap_phy(log=self.log)
            if phy is None:
                raise SystemExit(
                    "no AP-capable phy found; present phys: "
                    f"{', '.join(transport.list_phys()) or 'none'}")
        keys = resolve_keys(self.config.keys_path)
        if not os.path.exists(keys):
            raise SystemExit(
                f"prod.keys not found at {keys!r}; pass --keys with an absolute path")
        return phy, keys

    def _build_components(self):
        phy, keys = self._resolve_phy_and_keys()
        candidate = self.config.candidate
        self.parent_session_id = bytes(self.parent_id_factory())
        self.app_data = build_joyspot_app_data(
            self.profile, self.parent_session_id, candidate)
        self.tracer = (self.tracer_factory(self.config.capture_path, log=self.log)
                       if self.config.capture_path else None)
        self.network = self.transport_factory(
            app_data=self.app_data,
            password=self.config.password,
            nickname=self.profile.discovery_name,
            keys_path=keys,
            local_comm_id=JOYSPOT_LOCAL_COMMUNICATION_ID,
            scene_id=candidate.scene_id,
            app_version=candidate.app_version,
            max_participants=JOYSPOT_MAX_PARTICIPANTS,
            phyname=phy,
            channel=self.config.channel,
            skip_encryption=self.config.skip_encryption,
            tracer=self.tracer,
            log=self.log,
        )

    def _log_candidate(self):
        candidate = self.config.candidate
        decoded = decode_joyspot_app_data(self.app_data)
        self.info(f"JoySpot Stage {candidate.stage} candidate: {candidate.name}")
        self.info(f"Candidate purpose: {candidate.description}")
        self.info(
            "LDN identity: "
            f"comm_id=0x{JOYSPOT_LOCAL_COMMUNICATION_ID:016x} "
            f"scene={candidate.scene_id} app_version={candidate.app_version} "
            f"participants={JOYSPOT_MAX_PARTICIPANTS}")
        self.info(
            "Pia/discovery identity: "
            f"sysCommVer={decoded.pia_sys_version} "
            f"appCommVer={decoded.pia_app_version} "
            f"trainer={decoded.name!r} TID=0x{decoded.trainer_id:04x}")
        self.info(
            "RFU parent/search hypothesis: "
            f"parent_raw={decoded.rfu_session_id.hex()} "
            f"search_word=0x{decoded.search_word:04x} "
            f"activity={decoded.activity} "
            f"hasCardHypothesis={int(decoded.has_card)} "
            f"bit7={int(decoded.search_bit7)} "
            f"startedActivity={int(decoded.started_activity)}")
        if candidate.serial_offset is not None:
            self.info(
                f"Serial placement: 0x{JOYSPOT_SERIAL:04x} {candidate.serial_endian}-endian "
                f"at record[{candidate.serial_offset}:{candidate.serial_offset + 2}]")
        self.info(
            "Unexplained record regions: "
            f"[12:16]={decoded.unexplained_low.hex()} "
            f"[18:24]={decoded.unexplained_high.hex()}")
        self.info(f"Decoded 24-byte record: {decoded.record.hex()}")
        self.log(f"[joyspot] application_data ({len(self.app_data)}B): {self.app_data.hex()}")

    def _observe_join(self):
        joined = (bool(self.network.participants)
                  or getattr(self.network, "join_events", 0) > 0)
        if joined and not self.joined_once:
            self.joined_once = True
            self.info(
                "Stage 1 strong signal: a console joined this candidate. "
                "No higher protocol is running, so the game may time out normally.")

    def _drain_ignored_traffic(self):
        # Drain the TAP receive queue without parsing or answering Pia.
        # Otherwise the readable socket stays hot after a join and the
        # discovery-only loop spins until the game's expected timeout.
        for _datagram, _source in self.network.recv():
            self.ignored_datagrams += 1
            if self.ignored_datagrams == 1:
                self.info(
                    "Received post-join traffic and intentionally ignored it "
                    "at the Stage 1 discovery boundary.")

    def run(self, *, decision_prompt=None):
        """Run one candidate and return whether a console joined its LDN network.

        With no prompt, advertise until Ctrl-C (the original one-candidate
        workflow).  A sweep supplies a zero-argument prompt callback; it runs
        only after the AP and beacon injector are live, and returning from it
        ends this candidate cleanly.
        """
        self.joined_once = False
        try:
            self._build_components()
            self._log_candidate()
            self.network.start(preflight=not self.config.skip_preflight)
            self.injector = self.injector_factory(
                channel=self.config.channel, log=self.log)
            self.injector.start()
            menu = ("Friend" if self.config.candidate.friend_control
                    else "Wireless Communication")
            self.info(
                "Advertising only: no Pia/RFU/Mystery Gift responses will be sent. "
                "On the Switch choose Mystery Gift -> Wonder Cards -> " + menu + ".")
            if decision_prompt is None:
                self.info(
                    "Leave this candidate running for at least 10 seconds; "
                    "press Ctrl-C afterward.")
            else:
                self.info(
                    "This candidate is live while the terminal waits for your Y/N answer.")

            if decision_prompt is not None:
                decision_prompt()
                if self.injector.error is not None:
                    raise RuntimeError(
                        f"802.11 beacon injector stopped: {self.injector.error}")
                self._observe_join()
                self._drain_ignored_traffic()
                return self.joined_once

            while True:
                if self.injector.error is not None:
                    raise RuntimeError(
                        f"802.11 beacon injector stopped: {self.injector.error}")
                self._observe_join()
                self._drain_ignored_traffic()
                self.network.wait_readable(PROBE_POLL_SECONDS)
        except KeyboardInterrupt:
            self.info("JoySpot probe interrupted; shutting down the candidate cleanly.")
            if decision_prompt is not None:
                raise
        finally:
            if self.injector is not None:
                self.injector.stop()
            if self.network is not None:
                self.network.stop()
            if self.tracer is not None:
                self.tracer.close()
                self.info(
                    f"Probe trace written: {self.config.capture_path} "
                    f"(counts: {self.tracer.counts})")
        return self.joined_once
