"""Mystery Gift server script engine [src/mystery_gift_server.c].

We are the server: link player 0, RFU parent.  The console is the client and
executes only what we hand it, so this engine owns the whole conversation.

The engine is a small interpreter over the same ``SVR_*`` opcodes the decomp
uses, so a flow written here can be read side by side with
``src/mystery_gift_scripts.c``.  :data:`SCRIPT_SEND_WONDER_CARD` is a faithful
transcription of ``gMysteryGiftServerScript_SendWonderCard``
[mystery_gift_scripts.c:185] including its three-way existing-card branch.

Transport independence: the interpreter never touches blocks or RFU.  It runs
until it blocks on an action and publishes it as :attr:`action`::

    ("send", ident, payload, size)   put this message on the wire
    ("recv", ident)                  wait for this message from the console
    ("done", server_msg_id)          the flow finished

The caller acknowledges with :meth:`on_sent` / :meth:`on_received`.  This is the
same shape as the native ``FUNC_SEND`` / ``FUNC_RECV`` / ``FUNC_RUN`` loop, one
command per step.
"""

from . import mg_script
from .mystery_gift import (
    MG_LINKID_CARD, MG_LINKID_CLIENT_SCRIPT, MG_LINKID_DYNAMIC_MSG,
    MG_LINKID_GAME_DATA, MG_LINKID_RAM_SCRIPT, MG_LINKID_READY_END,
    MG_LINKID_RESPONSE,
)
from .wonder_card import WONDER_CARD_SIZE

# --- server script instruction ids [include/mystery_gift_server.h:17] -------------------------
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

# --- server result message ids [include/mystery_gift_server.h:56] -----------------------------
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
    SVR_MSG_HAS_CARD: "the console already had this card",
    SVR_MSG_CLIENT_CANCELED: "the player kept their existing card",
    SVR_MSG_CANT_SEND_GIFT_1: "the console's game data was rejected",
    SVR_MSG_COMM_ERROR: "communication error",
}

# The RAM script and READY_END both travel as full 1024-byte buffer messages:
# SVR_COPY_SAVED_RAM_SCRIPT sets svr->ramScript but never svr->ramScriptSize
# [mystery_gift_server.c:275], so InitSend receives size 0 and expands it.
FULL_BUFFER = 0


class MysteryGiftServerError(Exception):
    """The console sent something the server script cannot proceed from."""


# --- server scripts, transcribed from src/mystery_gift_scripts.c ------------------------------
# sServerScript_CantSend [:98]
_SCRIPT_CANT_SEND = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_CANT_ACCEPT),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_CANT_SEND_GIFT_1),
)

# sServerScript_HasCard [:160]
_SCRIPT_HAS_CARD = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_HAD_CARD),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_HAS_CARD),
)

# gServerScript_ClientCanceledCard [union_room_message.c:569] - the player
# declined to toss their old card. Note this one lives in union_room_message.c,
# not mystery_gift_scripts.c, and unlike the News cancel path it pushes a live
# message for the console to display before ending.
_SCRIPT_CLIENT_CANCELED = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_DYNAMIC_ERROR),
    (SVR_SEND,),
    (SVR_LOAD_MSG, mg_script.TEXT_CANCELED_READING_CARD),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_CLIENT_CANCELED),
)

# sServerScript_SendCard [:140] - the gift proper.
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

# sServerScript_TossPrompt [:151] - console holds a different card.
_SCRIPT_TOSS_PROMPT = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_ASK_TOSS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_RESPONSE,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_SEND_CARD),      # tossed the old card
    (SVR_GOTO, _SCRIPT_CLIENT_CANCELED),             # kept the old card
)

# gMysteryGiftServerScript_SendWonderCard [mystery_gift_scripts.c:185].
#
# The two leading SVR_COPY_SAVED_* commands are omitted: they load the *sender's
# own saved* card and RAM script, which a distributor supplies from configuration
# instead. One side effect goes with them - SVR_COPY_SAVED_CARD also runs
# DisableWonderCardSending [mystery_gift_server.c:269], downgrading a
# SEND_TYPE_ALLOWED card to SEND_TYPE_DISALLOWED so a player cannot keep passing
# on a card they were given. That is a rule about re-sharing a *received* card,
# not about what a distributor may hand out, so the configured sendType is left
# alone here and is deliberate. (The shipped card is DISALLOWED regardless.)
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
    (SVR_GOTO, _SCRIPT_HAS_CARD),                    # HAS_SAME_CARD
)


class MysteryGiftServer:
    """Run one gift conversation against a single console.

    ``card`` is the 332-byte ``struct WonderCard``; ``ram_script`` is the raw
    delivery bytecode (the console wraps and checksums it itself).  Both come
    from :mod:`frlgsim.wonder_card`.
    """

    # CLI_SAVE_RAM_SCRIPT calls InitRamScript_NoObjectEvent [mystery_gift_client.c:234],
    # which clamps to sizeof(RamScriptData.script) [script.c:578]. The message on
    # the wire is 1024 bytes, but only this much of it ever reaches the save, so a
    # longer delivery script would be truncated mid-bytecode on the console.
    MAX_RAM_SCRIPT_SIZE = 995

    def __init__(self, card, ram_script, *, script=SCRIPT_SEND_WONDER_CARD,
                 log=lambda *a: None):
        self.card = bytes(card)
        self.ram_script = bytes(ram_script)
        if len(self.ram_script) > self.MAX_RAM_SCRIPT_SIZE:
            raise MysteryGiftServerError(
                f"delivery RAM script is {len(self.ram_script)} bytes; the console "
                f"only saves the first {self.MAX_RAM_SCRIPT_SIZE}")
        if len(self.card) != WONDER_CARD_SIZE:
            raise MysteryGiftServerError(
                f"Wonder Card must be exactly {WONDER_CARD_SIZE} bytes, got {len(self.card)}")
        self.log = log
        self.info = getattr(log, "info", log)
        self.script = script
        self.cmdidx = 0
        self.param = None
        self.action = None
        self.result = None
        self.game_data = None
        self.messages_sent = 0
        self.messages_received = 0
        self.trace = []

        self._loaded = None          # (ident, payload, size) staged by an SVR_LOAD_*
        self._received = b""         # the console's last message (svr->recvBuffer)

    @property
    def done(self):
        return self.action is not None and self.action[0] == "done"

    @property
    def card_flag_id(self):
        """The card's ``flagId``, which SVR_CHECK_EXISTING_CARD compares."""
        return int.from_bytes(self.card[0:2], "little")

    # --- transport interface ------------------------------------------------------------------
    def run(self):
        """Advance the script until it blocks, and return the pending action."""
        while self.action is None:
            self._step()
        return self.action

    def on_sent(self):
        """Acknowledge that the pending ``send`` action reached the console."""
        if self.action is None or self.action[0] != "send":
            raise MysteryGiftServerError("on_sent called with no send in flight")
        self.messages_sent += 1
        self.action = None
        self._loaded = None

    def on_received(self, ident, payload):
        """Deliver the message the pending ``recv`` action was waiting for."""
        if self.action is None or self.action[0] != "recv":
            raise MysteryGiftServerError("on_received called with no recv in flight")
        expected = self.action[1]
        if ident != expected:
            raise MysteryGiftServerError(
                f"expected ident {expected}, console sent {ident}")
        self.messages_received += 1
        self._received = bytes(payload)
        self.action = None

    # --- interpreter --------------------------------------------------------------------------
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

    def _do_svr_read_response(self):
        # svr->param = *(u32 *)svr->recvBuffer [mystery_gift_server.c:193] - the
        # raw word, not a coerced bool. CLI_LOAD_TOSS_RESPONSE sends TRUE when
        # the player KEPT their old card, so FALSE is the branch that gifts.
        self.param = int.from_bytes(self._received[:4], "little")

    def _do_svr_load_client_script(self, script):
        self._loaded = (MG_LINKID_CLIENT_SCRIPT, script, len(script))

    def _do_svr_load_card(self):
        self._loaded = (MG_LINKID_CARD, self.card, len(self.card))

    def _do_svr_load_ram_script(self):
        self._loaded = (MG_LINKID_RAM_SCRIPT, self.ram_script, FULL_BUFFER)

    def _do_svr_load_msg(self, text):
        self._loaded = (MG_LINKID_DYNAMIC_MSG, text, len(text))
