"""Mystery Gift server script interpreter [decomp:src/mystery_gift_server.c]; we are link player 0.
run() advances until it blocks and publishes ``action`` as ("send", ident, payload, size), ("recv", ident)
or ("done", server_msg_id); the caller acknowledges with on_sent()/on_received()."""

from . import ereader_trainer, mg_script, mystery_event, wonder_news
from .mystery_gift import (
    MG_LINKID_CARD, MG_LINKID_CLIENT_SCRIPT, MG_LINKID_DYNAMIC_MSG,
    MG_LINKID_EREADER_TRAINER, MG_LINKID_GAME_DATA, MG_LINKID_NEWS, MG_LINKID_RAM_SCRIPT,
    MG_LINKID_READY_END, MG_LINKID_RESPONSE, MG_LINKID_STAMP,
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
SVR_LOAD_NEWS = "SVR_LOAD_NEWS"
SVR_LOAD_RAM_SCRIPT = "SVR_LOAD_RAM_SCRIPT"
SVR_LOAD_CLIENT_SCRIPT = "SVR_LOAD_CLIENT_SCRIPT"
SVR_LOAD_MSG = "SVR_LOAD_MSG"
SVR_CHECK_RALLY_CARD = "SVR_CHECK_RALLY_CARD"
SVR_CHECK_EXISTING_STAMPS = "SVR_CHECK_EXISTING_STAMPS"
SVR_LOAD_STAMP = "SVR_LOAD_STAMP"
SVR_LOAD_ACTIVATION = "SVR_LOAD_ACTIVATION"
SVR_LOAD_EREADER_TRAINER = "SVR_LOAD_EREADER_TRAINER"
SVR_LOAD_MEVENT = "SVR_LOAD_MEVENT"
SVR_READ_MEVENT_STATUS = "SVR_READ_MEVENT_STATUS"

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
SVR_MSG_GIFT_SENT_1 = 13

SERVER_RESULT_NAMES = {
    SVR_MSG_NOTHING_SENT: "nothing sent",
    SVR_MSG_CARD_SENT: "Wonder Card sent",
    SVR_MSG_NEWS_SENT: "Wonder News sent",
    SVR_MSG_HAS_NEWS: "the console already had this news",
    SVR_MSG_STAMP_SENT: "stamp sent",
    SVR_MSG_HAS_CARD: "the console already had this card",
    SVR_MSG_HAS_STAMP: "the console already had this stamp",
    SVR_MSG_NO_ROOM_STAMPS: "the console's stamp card is full",
    SVR_MSG_CLIENT_CANCELED: "the player kept their existing card",
    SVR_MSG_CANT_SEND_GIFT_1: "the console's game data was rejected",
    SVR_MSG_COMM_ERROR: "communication error",
    SVR_MSG_GIFT_SENT_1: "gift sent",
}

# Native never sets ramScriptSize [decomp:src/mystery_gift_server.c:275], so the RAM script travels as
# a full 1024-byte message.
FULL_BUFFER = 0


# ctx->data[2] as the stock opcodes leave it; anything else came from our own setstatus.
MEVENT_STATUS_NAMES = {
    0: "untouched - no opcode set a status",
    mystery_event.STATUS_FAILED: "failed: setenigmaberry invalid, or a checksum/crc mismatch",
    mystery_event.STATUS_SUCCESS: "success",
    mystery_event.STATUS_INCOMPATIBLE: "incompatible, or givepokemon found a full party",
}


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

# sServerScript_HasNews [decomp:src/mystery_gift_scripts.c:119]
_SCRIPT_HAS_NEWS = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_HAD_NEWS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_HAS_NEWS),
)

# sServerScript_SendNews [decomp:src/mystery_gift_scripts.c:126]. The response is the console's own
# verdict, not a player prompt: TRUE means it kept what it already had, so only FALSE continues to the
# success script. There is no toss prompt and no flagId compare anywhere on the News path.
_SCRIPT_SEND_NEWS = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_NEWS),
    (SVR_SEND,),
    (SVR_LOAD_NEWS,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_RESPONSE,),
    (SVR_GOTO_IF_EQ, True, _SCRIPT_HAS_NEWS),
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_NEWS_RECEIVED),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_NEWS_SENT),
)

# gMysteryGiftServerScript_SendWonderNews [decomp:src/mystery_gift_scripts.c:174] minus its leading
# SVR_COPY_SAVED_NEWS: the news comes from configuration, not from a save block we do not have.
SCRIPT_SEND_WONDER_NEWS = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SEND_GAME_DATA),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_GAME_DATA),
    (SVR_COPY_GAME_DATA,),
    (SVR_CHECK_GAME_DATA,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_CANT_SEND),
    (SVR_GOTO, _SCRIPT_SEND_NEWS),
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

# The visiting trainer. No native script sends one over the wireless link -- the Wonder Card that
# advertised it did [MysteryEventScript_VisitingTrainer, data/mystery_event_msg.s:113] and the
# trainer itself arrived in a later session -- so these are ours, built from the same opcodes.
_SCRIPT_SEND_CARD_AND_TRAINER = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_CARD_AND_TRAINER),
    (SVR_SEND,),
    (SVR_LOAD_CARD,),
    (SVR_SEND,),
    (SVR_LOAD_RAM_SCRIPT,),
    (SVR_SEND,),
    (SVR_LOAD_EREADER_TRAINER,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_GIFT_SENT_1),
)

# HAS_SAME_CARD: the console keeps the card it already holds and just takes the trainer again, so a
# rematch costs nothing and no card is tossed.
_SCRIPT_SEND_TRAINER_ONLY = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_TRAINER),
    (SVR_SEND,),
    (SVR_LOAD_EREADER_TRAINER,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_GIFT_SENT_1),
)

_SCRIPT_TOSS_PROMPT_TRAINER = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_ASK_TOSS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_RESPONSE,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_SEND_CARD_AND_TRAINER),
    (SVR_GOTO, _SCRIPT_CLIENT_CANCELED),
)

SCRIPT_SEND_VISITING_TRAINER = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SEND_GAME_DATA),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_GAME_DATA),
    (SVR_COPY_GAME_DATA,),
    (SVR_CHECK_GAME_DATA,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_CANT_SEND),
    (SVR_CHECK_EXISTING_CARD,),
    (SVR_GOTO_IF_EQ, mg_script.HAS_DIFF_CARD, _SCRIPT_TOSS_PROMPT_TRAINER),
    (SVR_GOTO_IF_EQ, mg_script.HAS_NO_CARD, _SCRIPT_SEND_CARD_AND_TRAINER),
    (SVR_GOTO, _SCRIPT_SEND_TRAINER_ONLY),
)

# The Mystery Event VM. No native script reaches it over the wireless link -- the stamp rally's
# activation script is the only CLI_RUN_MEVENT_SCRIPT in the game -- so these are ours. The tail
# after the mevent send reads MG_LINKID_RESPONSE, which carries the script's own status back.
_SCRIPT_MEVENT_TAIL = (
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_MEVENT_STATUS,),
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_MEVENT_DONE),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_CARD_SENT),
)

_SCRIPT_SEND_CARD_AND_MEVENT = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_CARD_AND_MEVENT),
    (SVR_SEND,),
    (SVR_LOAD_CARD,),
    (SVR_SEND,),
    (SVR_LOAD_RAM_SCRIPT,),
    (SVR_SEND,),
    (SVR_LOAD_MEVENT,),
    (SVR_SEND,),
    (SVR_GOTO, _SCRIPT_MEVENT_TAIL),
)

# HAS_SAME_CARD: the console keeps the card it holds and only runs the event, so re-running an
# event costs nothing and prompts for nothing.
_SCRIPT_SEND_MEVENT_ONLY = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_RUN_MEVENT),
    (SVR_SEND,),
    (SVR_LOAD_MEVENT,),
    (SVR_SEND,),
    (SVR_GOTO, _SCRIPT_MEVENT_TAIL),
)

_SCRIPT_TOSS_PROMPT_MEVENT = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_ASK_TOSS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_RESPONSE,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_SEND_CARD_AND_MEVENT),
    (SVR_GOTO, _SCRIPT_CLIENT_CANCELED),
)

SCRIPT_SEND_MYSTERY_EVENT = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SEND_GAME_DATA),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_GAME_DATA),
    (SVR_COPY_GAME_DATA,),
    (SVR_CHECK_GAME_DATA,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_CANT_SEND),
    (SVR_CHECK_EXISTING_CARD,),
    (SVR_GOTO_IF_EQ, mg_script.HAS_DIFF_CARD, _SCRIPT_TOSS_PROMPT_MEVENT),
    (SVR_GOTO_IF_EQ, mg_script.HAS_NO_CARD, _SCRIPT_SEND_CARD_AND_MEVENT),
    (SVR_GOTO, _SCRIPT_SEND_MEVENT_ONLY),
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

    def __init__(self, card=None, ram_script=None, *, news=None, stamp=None,
                 activation_script=None, install_activation_script=None, trainer=None,
                 mevent=None, script=None, log=lambda *a: None):
        self.news = None if news is None else bytes(news)
        if self.news is not None:
            # Wonder News is a session of its own: no card, no flagId, no delivery script.
            if card is not None or ram_script is not None:
                raise MysteryGiftServerError(
                    "a Wonder News session carries no Wonder Card and no RAM script")
            if len(self.news) != wonder_news.WONDER_NEWS_SIZE:
                raise MysteryGiftServerError(
                    f"Wonder News must be exactly {wonder_news.WONDER_NEWS_SIZE} bytes, "
                    f"got {len(self.news)}")
            if not wonder_news.validate(self.news):
                raise MysteryGiftServerError(
                    "news id 0 fails ValidateWonderNews; the console would keep nothing")
        elif card is None or ram_script is None:
            raise MysteryGiftServerError(
                "a Mystery Gift session needs either a Wonder Card and RAM script, or news")
        self.card = None if card is None else bytes(card)
        self.ram_script = None if ram_script is None else bytes(ram_script)
        if self.news is None:
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
        self.trainer = None if trainer is None else bytes(trainer)
        if self.trainer is not None:
            if len(self.trainer) != ereader_trainer.TRAINER_SIZE:
                raise MysteryGiftServerError(
                    f"a visiting trainer is {ereader_trainer.TRAINER_SIZE} bytes, "
                    f"got {len(self.trainer)}")
            if not ereader_trainer.validate(self.trainer):
                raise MysteryGiftServerError(
                    "the visiting trainer fails ValidateEReaderTrainer; the console would "
                    "silently clear it")
            if self.stamp is not None:
                raise MysteryGiftServerError(
                    "a stamp rally and a visiting trainer cannot share one session")
        if self.news is not None and (self.stamp is not None or self.trainer is not None):
            raise MysteryGiftServerError(
                "Wonder News cannot share a session with a stamp rally or a visiting trainer")
        self.mevent = None if mevent is None else bytes(mevent)
        if self.mevent is not None:
            if len(self.mevent) > mystery_event.MAX_SCRIPT_SIZE:
                raise MysteryGiftServerError(
                    f"Mystery Event script is {len(self.mevent)} bytes; the console's receive "
                    f"buffer is {mystery_event.MAX_SCRIPT_SIZE}")
            if not mystery_event.decode(self.mevent):
                raise MysteryGiftServerError("Mystery Event script is empty")
            if mystery_event.decode(self.mevent)[-1][0] not in mystery_event.TERMINAL_OPCODES:
                raise MysteryGiftServerError(
                    "Mystery Event script has no terminal command; the console would carry on "
                    "decoding the rest of its receive buffer")
            if self.news is not None or self.stamp is not None or self.trainer is not None:
                raise MysteryGiftServerError(
                    "a Mystery Event script cannot share a session with news, a stamp rally or a "
                    "visiting trainer")
        self.is_mevent_distribution = self.mevent is not None
        self.mevent_status = None
        self.is_stamp_distribution = self.stamp is not None
        self.is_trainer_distribution = self.trainer is not None
        self.is_news_distribution = self.news is not None
        self.log = log
        self.info = getattr(log, "info", log)
        if script is not None:
            self.script = script
        elif self.is_news_distribution:
            self.script = SCRIPT_SEND_WONDER_NEWS
        elif self.is_stamp_distribution:
            self.script = SCRIPT_SEND_STAMP_EVENT
        elif self.is_trainer_distribution:
            self.script = SCRIPT_SEND_VISITING_TRAINER
        elif self.is_mevent_distribution:
            self.script = SCRIPT_SEND_MYSTERY_EVENT
        else:
            self.script = SCRIPT_SEND_WONDER_CARD
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
        if self.card is None:
            raise MysteryGiftServerError("this session carries no Wonder Card")
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

    def _do_svr_load_news(self):
        self._loaded = (MG_LINKID_NEWS, self.news, len(self.news))

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

    def _do_svr_load_ereader_trainer(self):
        self._loaded = (MG_LINKID_EREADER_TRAINER, self.trainer, len(self.trainer))

    def _do_svr_load_mevent(self):
        self._loaded = (MG_LINKID_RAM_SCRIPT, self.mevent, len(self.mevent))
        self.info("Mystery Event script: " + mystery_event.describe(self.mevent))

    def _do_svr_read_mevent_status(self):
        # ctx->data[2] as MEventScript_Run left it, relayed by CLI_LOAD_TOSS_RESPONSE.
        self.mevent_status = int.from_bytes(self._received[:4], "little")
        self.param = self.mevent_status
        self.trace.append(("mevent_status", self.mevent_status))
        self.info(f"Mystery Event script status: {self.mevent_status} "
                  f"({MEVENT_STATUS_NAMES.get(self.mevent_status, 'set by our own setstatus')})")

    def _do_svr_load_msg(self, text):
        self._loaded = (MG_LINKID_DYNAMIC_MSG, text, len(text))
