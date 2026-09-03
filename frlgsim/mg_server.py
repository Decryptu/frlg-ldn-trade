"""Mystery Gift server script interpreter [decomp:src/mystery_gift_server.c]; we are link player 0.
run() advances until it blocks and publishes ``action`` as ("send", ident, payload, size), ("recv", ident)
or ("done", server_msg_id); the caller acknowledges with on_sent()/on_received()."""

from . import mg_script
from .mystery_gift import (
    MG_LINKID_CARD, MG_LINKID_CLIENT_SCRIPT, MG_LINKID_DYNAMIC_MSG,
    MG_LINKID_GAME_DATA, MG_LINKID_RAM_SCRIPT, MG_LINKID_READY_END,
    MG_LINKID_RESPONSE, MG_LINKID_STAMP,
)
from .wonder_card import WONDER_CARD_SIZE

# [decomp:include/mystery_gift_server.h:17]
SVR_RETURN = "SVR_RETURN"
SVR_SEND = "SVR_SEND"
SVR_RECV = "SVR_RECV"
SVR_GOTO = "SVR_GOTO"
SVR_GOTO_IF_EQ = "SVR_GOTO_IF_EQ"
SVR_COPY_GAME_DATA = "SVR_COPY_GAME_DATA"
SVR_CHECK_GAME_DATA = "SVR_CHECK_GAME_DATA"
SVR_CHECK_EXISTING_CARD = "SVR_CHECK_EXISTING_CARD"
SVR_READ_RESPONSE = "SVR_READ_RESPONSE"
SVR_LOAD_CARD = "SVR_LOAD_CARD"
SVR_LOAD_RAM_SCRIPT = "SVR_LOAD_RAM_SCRIPT"
SVR_LOAD_CLIENT_SCRIPT = "SVR_LOAD_CLIENT_SCRIPT"
SVR_LOAD_MSG = "SVR_LOAD_MSG"
SVR_CHECK_RALLY_CARD = "SVR_CHECK_RALLY_CARD"
SVR_CHECK_EXISTING_STAMPS = "SVR_CHECK_EXISTING_STAMPS"
SVR_LOAD_STAMP = "SVR_LOAD_STAMP"
SVR_LOAD_ACTIVATION = "SVR_LOAD_ACTIVATION"

# [decomp:include/mystery_gift_server.h:56]
SVR_MSG_NOTHING_SENT = 0
SVR_MSG_RECORD_UPLOADED = 1
SVR_MSG_CARD_SENT = 2
SVR_MSG_NEWS_SENT = 3
SVR_MSG_STAMP_SENT = 4
SVR_MSG_HAS_CARD = 5
SVR_MSG_HAS_STAMP = 6
SVR_MSG_HAS_NEWS = 7
SVR_MSG_NO_ROOM_STAMPS = 8
SVR_MSG_CLIENT_CANCELED = 9
SVR_MSG_CANT_SEND_GIFT_1 = 10
SVR_MSG_COMM_ERROR = 11

SERVER_RESULT_NAMES = {
    SVR_MSG_NOTHING_SENT: "nothing sent",
    SVR_MSG_CARD_SENT: "Wonder Card sent",
    SVR_MSG_STAMP_SENT: "stamp sent",
    SVR_MSG_HAS_CARD: "the console already had this card",
    SVR_MSG_HAS_STAMP: "the console already had this stamp",
    SVR_MSG_NO_ROOM_STAMPS: "the console's stamp card is full",
    SVR_MSG_CLIENT_CANCELED: "the player kept their existing card",
    SVR_MSG_CANT_SEND_GIFT_1: "the console's game data was rejected",
    SVR_MSG_COMM_ERROR: "communication error",
}

# Native never sets ramScriptSize [decomp:src/mystery_gift_server.c:275], so the RAM script travels as
# a full 1024-byte message.
FULL_BUFFER = 0


class MysteryGiftServerError(Exception):
    """The console sent something the server script cannot proceed from."""


# sServerScript_CantSend [decomp:src/mystery_gift_scripts.c:98]
_SCRIPT_CANT_SEND = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_CANT_ACCEPT),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_CANT_SEND_GIFT_1),
)

# sServerScript_HasCard [decomp:src/mystery_gift_scripts.c:160]
_SCRIPT_HAS_CARD = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_HAD_CARD),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_HAS_CARD),
)

# gServerScript_ClientCanceledCard [decomp:src/union_room_message.c:569]; unlike the News cancel path
# it pushes a live message for the console to display before ending.
_SCRIPT_CLIENT_CANCELED = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_DYNAMIC_ERROR),
    (SVR_SEND,),
    (SVR_LOAD_MSG, mg_script.TEXT_CANCELED_READING_CARD),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_CLIENT_CANCELED),
)

# sServerScript_SendCard [decomp:src/mystery_gift_scripts.c:140]
_SCRIPT_SEND_CARD = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_CARD),
    (SVR_SEND,),
    (SVR_LOAD_CARD,),
    (SVR_SEND,),
    (SVR_LOAD_RAM_SCRIPT,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_CARD_SENT),
)

_SCRIPT_HAS_STAMP = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_HAD_STAMP),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_HAS_STAMP),
)

_SCRIPT_NO_ROOM_STAMPS = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_NO_ROOM_STAMPS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_NO_ROOM_STAMPS),
)

_SCRIPT_SEND_STAMP_ONLY = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_STAMP),
    (SVR_SEND,),
    (SVR_LOAD_STAMP,),
    (SVR_SEND,),
    (SVR_LOAD_ACTIVATION, False),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_STAMP_SENT),
)

_SCRIPT_INSTALL_CARD_AND_STAMP = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_INSTALL_CARD_AND_STAMP),
    (SVR_SEND,),
    (SVR_LOAD_CARD,),
    (SVR_SEND,),
    (SVR_LOAD_RAM_SCRIPT,),
    (SVR_SEND,),
    (SVR_LOAD_STAMP,),
    (SVR_SEND,),
    (SVR_LOAD_ACTIVATION, True),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_STAMP_SENT),
)

_SCRIPT_STAMP_TOSS_PROMPT = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_ASK_TOSS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_RESPONSE,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_INSTALL_CARD_AND_STAMP),
    (SVR_GOTO, _SCRIPT_CLIENT_CANCELED),
)

# MysteryGift_CheckStamps results. Native checks full before duplicate; this host checks duplicate
# first so a collected stamp is reported accurately on a full card.
STAMPS_FULL = 1
STAMP_NEW = 2
STAMP_ALREADY_PRESENT = 3

SCRIPT_SEND_STAMP_EVENT = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SEND_GAME_DATA),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_GAME_DATA),
    (SVR_COPY_GAME_DATA,),
    (SVR_CHECK_GAME_DATA,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_CANT_SEND),
    (SVR_CHECK_RALLY_CARD,),
    (SVR_GOTO_IF_EQ, mg_script.HAS_DIFF_CARD, _SCRIPT_STAMP_TOSS_PROMPT),
    (SVR_GOTO_IF_EQ, mg_script.HAS_NO_CARD, _SCRIPT_INSTALL_CARD_AND_STAMP),
    (SVR_CHECK_EXISTING_STAMPS,),
    (SVR_GOTO_IF_EQ, STAMP_ALREADY_PRESENT, _SCRIPT_HAS_STAMP),
    (SVR_GOTO_IF_EQ, STAMPS_FULL, _SCRIPT_NO_ROOM_STAMPS),
    (SVR_GOTO, _SCRIPT_SEND_STAMP_ONLY),
)

# sServerScript_TossPrompt [decomp:src/mystery_gift_scripts.c:151]
_SCRIPT_TOSS_PROMPT = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_ASK_TOSS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_RESPONSE,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_SEND_CARD),
    (SVR_GOTO, _SCRIPT_CLIENT_CANCELED),
)

# gMysteryGiftServerScript_SendWonderCard [decomp:src/mystery_gift_scripts.c:185] minus its two leading
# SVR_COPY_SAVED_* (card/script come from configuration; DisableWonderCardSending is deliberately not applied).
SCRIPT_SEND_WONDER_CARD = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SEND_GAME_DATA),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_GAME_DATA),
    (SVR_COPY_GAME_DATA,),
    (SVR_CHECK_GAME_DATA,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_CANT_SEND),
    (SVR_CHECK_EXISTING_CARD,),
    (SVR_GOTO_IF_EQ, mg_script.HAS_DIFF_CARD, _SCRIPT_TOSS_PROMPT),
    (SVR_GOTO_IF_EQ, mg_script.HAS_NO_CARD, _SCRIPT_SEND_CARD),
    (SVR_GOTO, _SCRIPT_HAS_CARD),
)


class MysteryGiftServer:
    # The console saves only sizeof(RamScriptData.script) bytes of the 1024-byte message
    # [decomp:src/script.c:578]; a longer delivery script is truncated mid-bytecode.
    MAX_RAM_SCRIPT_SIZE = 995

    def __init__(self, card, ram_script, *, stamp=None, activation_script=None,
                 install_activation_script=None, script=None, log=lambda *a: None):
        self.card = bytes(card)
        self.ram_script = bytes(ram_script)
        if len(self.ram_script) > self.MAX_RAM_SCRIPT_SIZE:
            raise MysteryGiftServerError(
                f"delivery RAM script is {len(self.ram_script)} bytes; the console "
                f"only saves the first {self.MAX_RAM_SCRIPT_SIZE}")
        if len(self.card) != WONDER_CARD_SIZE:
            raise MysteryGiftServerError(
                f"Wonder Card must be exactly {WONDER_CARD_SIZE} bytes, got {len(self.card)}")
        self.stamp = None if stamp is None else bytes(stamp)
        self.activation_script = (None if activation_script is None
                                  else bytes(activation_script))
        self.install_activation_script = (
            None if install_activation_script is None
            else bytes(install_activation_script))
        extras = (self.stamp, self.activation_script, self.install_activation_script)
        if any(value is not None for value in extras):
            if any(value is None for value in extras):
                raise MysteryGiftServerError(
                    "stamp flow requires a stamp and both activation scripts")
            if len(self.stamp) != 4:
                raise MysteryGiftServerError("stamp must be exactly four bytes")
        self.is_stamp_distribution = self.stamp is not None
        self.log = log
        self.info = getattr(log, "info", log)
        self.script = (SCRIPT_SEND_STAMP_EVENT if script is None and self.is_stamp_distribution
                       else SCRIPT_SEND_WONDER_CARD if script is None else script)
        self.cmdidx = 0
        self.param = None
        self.action = None
        self.result = None
        self.game_data = None
        self.messages_sent = 0
        self.messages_received = 0
        self.trace = []

        self._loaded = None
        self._received = b""

    @property
    def done(self):
        return self.action is not None and self.action[0] == "done"

    @property
    def card_flag_id(self):
        return int.from_bytes(self.card[0:2], "little")

    def run(self):
        while self.action is None:
            self._step()
        return self.action

    def on_sent(self):
        if self.action is None or self.action[0] != "send":
            raise MysteryGiftServerError("on_sent called with no send in flight")
        self.messages_sent += 1
        self.action = None
        self._loaded = None

    def on_received(self, ident, payload):
        if self.action is None or self.action[0] != "recv":
            raise MysteryGiftServerError("on_received called with no recv in flight")
        expected = self.action[1]
        if ident != expected:
            raise MysteryGiftServerError(
                f"expected ident {expected}, console sent {ident}")
        self.messages_received += 1
        self._received = bytes(payload)
        self.action = None

    def _step(self):
        if self.cmdidx >= len(self.script):
            raise MysteryGiftServerError("server script ran off the end without SVR_RETURN")
        command = self.script[self.cmdidx]
        self.cmdidx += 1
        instr, args = command[0], command[1:]
        handler = getattr(self, "_do_" + instr.lower(), None)
        if handler is None:
            raise MysteryGiftServerError(f"unimplemented server opcode {instr}")
        self.trace.append(instr)
        handler(*args)

    def _goto(self, script):
        self.script = script
        self.cmdidx = 0

    def _do_svr_return(self, message_id):
        self.result = message_id
        self.action = ("done", message_id)
        self.info("Mystery Gift server finished: "
                  + SERVER_RESULT_NAMES.get(message_id, f"result {message_id}"))

    def _do_svr_send(self):
        if self._loaded is None:
            raise MysteryGiftServerError("SVR_SEND with no message loaded")
        self.action = ("send",) + self._loaded

    def _do_svr_recv(self, ident):
        self.action = ("recv", ident)

    def _do_svr_goto(self, script):
        self._goto(script)

    def _do_svr_goto_if_eq(self, value, script):
        if self.param == value:
            self._goto(script)

    def _do_svr_copy_game_data(self):
        self.game_data = mg_script.parse_link_game_data(self._received)
        self.info("Console identified itself: " + self.game_data.describe())

    def _do_svr_check_game_data(self):
        self.param = mg_script.validate_link_game_data(self.game_data)
        if not self.param:
            self.info("Console game data failed MysteryGift_ValidateLinkGameData; "
                      "declining to send the card.")

    def _do_svr_check_existing_card(self):
        self.param = mg_script.compare_card_flags(self.card_flag_id, self.game_data)
        self.trace.append(("existing_card", self.param))

    def _do_svr_check_rally_card(self):
        expected_icon = int.from_bytes(self.card[2:4], "little")
        if not self.game_data.has_card:
            self.param = mg_script.HAS_NO_CARD
        elif (self.game_data.flag_id == self.card_flag_id
              and self.game_data.max_stamps == self.card[9]
              and self.game_data.metadata_icon_species
              == expected_icon):
            self.param = mg_script.HAS_SAME_CARD
        else:
            self.param = mg_script.HAS_DIFF_CARD
        self.trace.append(("rally_card", self.param))
        result = {
            mg_script.HAS_NO_CARD: "no card",
            mg_script.HAS_SAME_CARD: "matching rally",
            mg_script.HAS_DIFF_CARD: "different card",
        }[self.param]
        self.info(
            "Rally card check: console "
            f"flagId={self.game_data.flag_id}, maxStamps={self.game_data.max_stamps}, "
            f"metadataIcon={self.game_data.metadata_icon_species}, "
            f"stamps={self.game_data.stamps}; expected flagId={self.card_flag_id}, "
            f"maxStamps={self.card[9]}, metadataIcon={expected_icon} -> {result}.")

    def _do_svr_check_existing_stamps(self):
        species = int.from_bytes(self.stamp[0:2], "little")
        stamp_id = int.from_bytes(self.stamp[2:4], "little")
        slots = range(min(self.game_data.max_stamps, len(self.game_data.stamp_ids)))
        if any(self.game_data.stamp_species[i] == species
               or self.game_data.stamp_ids[i] == stamp_id for i in slots):
            self.param = STAMP_ALREADY_PRESENT
        elif not any(self.game_data.stamp_species[i] == 0
                     and self.game_data.stamp_ids[i] == 0 for i in slots):
            self.param = STAMPS_FULL
        else:
            self.param = STAMP_NEW
        self.trace.append(("existing_stamps", self.param))

    def _do_svr_read_response(self):
        # The raw u32, not a bool [decomp:src/mystery_gift_server.c:193]; TRUE means the player KEPT
        # the old card, so FALSE is the branch that gifts.
        self.param = int.from_bytes(self._received[:4], "little")

    def _do_svr_load_client_script(self, script):
        self._loaded = (MG_LINKID_CLIENT_SCRIPT, script, len(script))

    def _do_svr_load_card(self):
        self._loaded = (MG_LINKID_CARD, self.card, len(self.card))

    def _do_svr_load_ram_script(self):
        self._loaded = (MG_LINKID_RAM_SCRIPT, self.ram_script, FULL_BUFFER)

    def _do_svr_load_stamp(self):
        self._loaded = (MG_LINKID_STAMP, self.stamp, len(self.stamp))

    def _do_svr_load_activation(self, install):
        payload = (self.install_activation_script if install
                   else self.activation_script)
        self._loaded = (MG_LINKID_RAM_SCRIPT, payload, len(payload))

    def _do_svr_load_msg(self, text):
        self._loaded = (MG_LINKID_DYNAMIC_MSG, text, len(text))
