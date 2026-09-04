"""Mystery Gift server script interpreter [decomp:src/mystery_gift_server.c]; we are link player 0.
run() advances until it blocks and publishes ``action`` as ("send", ident, payload, size), ("recv", ident)
or ("done", server_msg_id); the caller acknowledges with on_sent()/on_received()."""

from . import (buffer_script, charmap, easychat, ereader_trainer, mg_script,
               mystery_event, wonder_news)
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
SVR_CHECK_QUESTIONNAIRE = "SVR_CHECK_QUESTIONNAIRE"
SVR_GET_CARD_STAT = "SVR_GET_CARD_STAT"
SVR_LOAD_DENIED_MSG = "SVR_LOAD_DENIED_MSG"
SVR_READ_MEVENT_STATUS = "SVR_READ_MEVENT_STATUS"
SVR_LOAD_BUFFER_SCRIPT = "SVR_LOAD_BUFFER_SCRIPT"
SVR_READ_BUFFER_STATUS = "SVR_READ_BUFFER_STATUS"
SVR_LOAD_BUFFER_VERDICT_MSG = "SVR_LOAD_BUFFER_VERDICT_MSG"

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


NUM_QUESTIONNAIRE_WORDS = 4     # [decomp:include/constants/global.h:68]

# What a console that says the wrong phrase reads, through CLIENT_SCRIPT_DYNAMIC_ERROR.
DEFAULT_DENIED_MESSAGE = charmap.encode("That is not the phrase.") + b"\xff"

# buffer_expect: compare what the payload returned against the trainer id the console already told
# us in its MysteryGiftLinkGameData. The two come from different places in the console - our ARM
# code reads gSaveBlock2Ptr directly, the game data was assembled by the ROM - so a match is proof
# the payload ran, ran with the arguments the decomp says it gets, and read the real save.
BUFFER_EXPECT_TRAINER_ID = buffer_script.EXPECT_TRAINER_ID

# What AddTextPrinterToWindow1 draws into: window 1 of sMainWindows, 28 tiles wide and 4 high
# [decomp:src/mystery_gift_menu.c:97,524] - two lines. The ROM's own longest string in it is
# gText_WonderCardReceivedFrom's first line, "A WONDER CARD has been received", 31 characters
# [decomp:src/strings.c:1291]. bs01 proved what happens past that: a 47-character line overflowed
# the window's pixel buffer and wrapped around it, printing "ly. code ran and read yourTRAINER IDc"
# on the console.
MAX_MESSAGE_LINES = 2
MAX_MESSAGE_LINE_CHARS = 31


def _encode_message(text, default):
    """A CLI_COPY_MSG payload, from a str, ready bytes, or the default.

    `\n` becomes 0xFE, the game's line break. charmap.encode DROPS characters it does not know,
    newline included, so encoding a two-line message with it alone silently produces one long line
    - which is exactly what went out in bs01.
    """
    if text is None:
        return default
    if isinstance(text, (bytes, bytearray)):
        encoded = bytes(text)
    else:
        lines = text.split("\n")
        if len(lines) > MAX_MESSAGE_LINES:
            raise MysteryGiftServerError(
                f"the console's message window holds {MAX_MESSAGE_LINES} lines, got {len(lines)}")
        for line in lines:
            if len(line) > MAX_MESSAGE_LINE_CHARS:
                raise MysteryGiftServerError(
                    f"line {line!r} is {len(line)} characters; the window fits about "
                    f"{MAX_MESSAGE_LINE_CHARS} and a longer one wraps around inside it")
        encoded = b"\xFE".join(charmap.encode(line) for line in lines) + b"\xff"
    if len(encoded) > mg_script.CLIENT_MAX_MSG_SIZE:
        raise MysteryGiftServerError(
            f"the message encodes to {len(encoded)} bytes; the console copies only "
            f"{mg_script.CLIENT_MAX_MSG_SIZE}")
    return encoded


# Both printed by the console itself, through CLI_MSG_BUFFER_SUCCESS / _FAILURE.
DEFAULT_BUFFER_SUCCESS_MESSAGE = _encode_message(
    "The code ran and read your\nTRAINER ID correctly.", None)
DEFAULT_BUFFER_FAILURE_MESSAGE = _encode_message(
    "The code ran but read the\nwrong value.", None)


class MysteryGiftServerError(Exception):
    """The console sent something the server script cannot proceed from."""


# sServerScript_CantSend [decomp:src/mystery_gift_scripts.c:98]
_SCRIPT_CANT_SEND = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_CANT_ACCEPT),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_CANT_SEND_GIFT_1),
)

# Every distribution opens the same way [decomp:src/mystery_gift_scripts.c:174,:185]: push the
# client script that uploads the console's MysteryGiftLinkGameData, take it, and refuse the session
# if it fails MysteryGift_ValidateLinkGameData. Named once so a gate can be spliced after it.
_GAME_DATA_PREFIX = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SEND_GAME_DATA),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_GAME_DATA),
    (SVR_COPY_GAME_DATA,),
    (SVR_CHECK_GAME_DATA,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_CANT_SEND),
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
    *_GAME_DATA_PREFIX,
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
    *_GAME_DATA_PREFIX,
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
    *_GAME_DATA_PREFIX,
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
    *_GAME_DATA_PREFIX,
    (SVR_CHECK_EXISTING_CARD,),
    (SVR_GOTO_IF_EQ, mg_script.HAS_DIFF_CARD, _SCRIPT_TOSS_PROMPT_MEVENT),
    (SVR_GOTO_IF_EQ, mg_script.HAS_NO_CARD, _SCRIPT_SEND_CARD_AND_MEVENT),
    (SVR_GOTO, _SCRIPT_SEND_MEVENT_ONLY),
)


# --- Native code: CLI_RUN_BUFFER_SCRIPT ------------------------------------------------------------
# No Wonder Card, no toss prompt and no branch on what the console already holds: the payload is not
# a gift, so this runs the same way whatever card the console is carrying, and it never saves unless
# the verdict is success. The verdict itself is decided here, from the value the payload left in
# client->param, and the console is told which one it was in a message we compose.
_SCRIPT_BUFFER_SUCCESS = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_BUFFER_SUCCESS),
    (SVR_SEND,),
    (SVR_LOAD_BUFFER_VERDICT_MSG,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_GIFT_SENT_1),
)

# CLIENT_SCRIPT_DYNAMIC_ERROR is the ROM's CLI_MSG_BUFFER_FAILURE exit, proven on hardware by the
# questionnaire refusal (mev04): our message prints and the console returns to the menu, no save.
_SCRIPT_BUFFER_FAILURE = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_DYNAMIC_ERROR),
    (SVR_SEND,),
    (SVR_LOAD_BUFFER_VERDICT_MSG,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_NOTHING_SENT),
)

SCRIPT_RUN_BUFFER_SCRIPT = (
    *_GAME_DATA_PREFIX,
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_RUN_BUFFER),
    (SVR_SEND,),
    (SVR_LOAD_BUFFER_SCRIPT,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_BUFFER_STATUS,),
    (SVR_GOTO_IF_EQ, True, _SCRIPT_BUFFER_SUCCESS),
    (SVR_GOTO, _SCRIPT_BUFFER_FAILURE),
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
    *_GAME_DATA_PREFIX,
    (SVR_CHECK_EXISTING_CARD,),
    (SVR_GOTO_IF_EQ, mg_script.HAS_DIFF_CARD, _SCRIPT_TOSS_PROMPT),
    (SVR_GOTO_IF_EQ, mg_script.HAS_NO_CARD, _SCRIPT_SEND_CARD),
    (SVR_GOTO, _SCRIPT_HAS_CARD),
)


# --- The questionnaire gate ----------------------------------------------------------------------
# SVR_CHECK_QUESTIONNAIRE compares all four Easy Chat words the player typed at the Poke Mart clerk
# against a phrase we choose, exactly [MysteryGift_DoesQuestionnaireMatch, decomp:src/mystery_gift.c:422].
# No native server script ever uses it, so this whole flow is ours: a password on a gift. The official
# Visiting Trainer card is the only known use of the idea, with "GIVE ME AWESOME TRAINER".
#
# TRAP: the four words are IDS, and an id is a slot in a per-language table. What a FRENCH player
# types produces French ids, which the English decomp cannot tell us - so the phrase has to be read
# off a real console first. The host logs it from every session [easychat_french.py].
_SCRIPT_QUESTIONNAIRE_DENIED = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_DYNAMIC_ERROR),
    (SVR_SEND,),
    (SVR_LOAD_DENIED_MSG,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_NOTHING_SENT),
)


def gate_on_questionnaire(script):
    """Splice a questionnaire check between the game-data prefix and whatever the script does next."""
    if tuple(script[:len(_GAME_DATA_PREFIX)]) != _GAME_DATA_PREFIX:
        raise MysteryGiftServerError(
            "only a script that opens with the standard game-data prefix can be gated")
    return (_GAME_DATA_PREFIX
            + ((SVR_CHECK_QUESTIONNAIRE,),
               (SVR_GOTO_IF_EQ, False, _SCRIPT_QUESTIONNAIRE_DENIED))
            + tuple(script[len(_GAME_DATA_PREFIX):]))


class MysteryGiftServer:
    # The console saves only sizeof(RamScriptData.script) bytes of the 1024-byte message
    # [decomp:src/script.c:578]; a longer delivery script is truncated mid-bytecode.
    MAX_RAM_SCRIPT_SIZE = 995

    def __init__(self, card=None, ram_script=None, *, news=None, stamp=None,
                 activation_script=None, install_activation_script=None, trainer=None,
                 mevent=None, buffer_code=None, buffer_expect=None,
                 buffer_success_message=None, buffer_failure_message=None,
                 questionnaire=None, denied_message=None,
                 script=None, log=lambda *a: None):
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
        elif buffer_code is None and (card is None or ram_script is None):
            raise MysteryGiftServerError(
                "a Mystery Gift session needs a Wonder Card and RAM script, or news, or a "
                "buffer script")
        self.card = None if card is None else bytes(card)
        self.ram_script = None if ram_script is None else bytes(ram_script)
        if self.news is None and buffer_code is None:
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
        # A CLI_RUN_BUFFER_SCRIPT payload: native ARM the console runs out of
        # gDecompressionBuffer [buffer_script.py]. It is not a gift, so it shares a session with
        # nothing else - the client script that runs it neither sends nor saves a card.
        self.buffer_code = None if buffer_code is None else bytes(buffer_code)
        if self.buffer_code is not None:
            buffer_script.validate(self.buffer_code)
            if any(other is not None for other in
                   (self.card, self.news, self.stamp, self.trainer, self.mevent)):
                raise MysteryGiftServerError(
                    "a buffer script runs on its own: no card, news, stamp rally, visiting "
                    "trainer or Mystery Event script in the same session")
        self.buffer_expect = buffer_expect
        if not (buffer_expect is None or buffer_expect == BUFFER_EXPECT_TRAINER_ID
                or isinstance(buffer_expect, int)):
            raise MysteryGiftServerError(
                f"buffer_expect is a u32, {BUFFER_EXPECT_TRAINER_ID!r} or None, "
                f"got {buffer_expect!r}")
        self.buffer_success_message = _encode_message(
            buffer_success_message, DEFAULT_BUFFER_SUCCESS_MESSAGE)
        self.buffer_failure_message = _encode_message(
            buffer_failure_message, DEFAULT_BUFFER_FAILURE_MESSAGE)
        self.questionnaire = None if questionnaire is None else tuple(
            int(word) & 0xFFFF for word in questionnaire)
        if self.questionnaire is not None and len(self.questionnaire) != NUM_QUESTIONNAIRE_WORDS:
            raise MysteryGiftServerError(
                f"a questionnaire phrase is exactly {NUM_QUESTIONNAIRE_WORDS} Easy Chat words, "
                f"got {len(self.questionnaire)}")
        # Same window, same trap: a refusal message wraps around inside it just as bs01's did.
        self.denied_message = _encode_message(denied_message, DEFAULT_DENIED_MESSAGE)
        self.questionnaire_matched = None
        self.is_mevent_distribution = self.mevent is not None
        self.mevent_status = None
        self.is_buffer_distribution = self.buffer_code is not None
        self.buffer_status = None
        self.buffer_matched = None
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
        elif self.is_buffer_distribution:
            self.script = SCRIPT_RUN_BUFFER_SCRIPT
        else:
            self.script = SCRIPT_SEND_WONDER_CARD
        if self.questionnaire is not None and script is None:
            self.script = gate_on_questionnaire(self.script)
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
        for line in self.game_data.describe_extras():
            # Free every session: the console volunteers all of this and nothing in the game ever
            # reads it back. On a French console the word ids are the only ground truth for what a
            # slot actually prints [easychat_french.py].
            self.info(line)

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

    def _do_svr_check_questionnaire(self):
        """Port of MysteryGift_DoesQuestionnaireMatch [decomp:src/mystery_gift.c:422]: all four
        word ids, exactly, in order."""
        typed = tuple(self.game_data.questionnaire_words)
        self.param = typed == self.questionnaire
        self.trace.append(("questionnaire", self.param))
        self.questionnaire_matched = bool(self.param)
        self.info("Questionnaire gate: console typed "
                  + easychat.describe_words(typed) + "; we require "
                  + easychat.describe_words(self.questionnaire)
                  + (" -> MATCH" if self.param else " -> no match, declining the gift"))

    def _do_svr_get_card_stat(self, stat):
        """MysteryGift_GetCardStatFromLinkData [decomp:src/mystery_gift_server.c:200]: a counter the
        console keeps for the card it holds. Never used by a native send script."""
        self.param = mg_script.card_stat(self.game_data, stat)
        self.trace.append(("card_stat", stat, self.param))
        self.info(f"Wonder Card stat {mg_script.CARD_STAT_NAMES.get(stat, stat)}: {self.param}")

    def _do_svr_load_denied_msg(self):
        self._loaded = (MG_LINKID_DYNAMIC_MSG, self.denied_message, len(self.denied_message))

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

    def _do_svr_load_buffer_script(self):
        self._loaded = (MG_LINKID_RAM_SCRIPT, self.buffer_code, len(self.buffer_code))
        self.info("buffer script (native ARM code): "
                  + buffer_script.describe(self.buffer_code))

    def _do_svr_read_buffer_status(self):
        """Read what the payload left in client->param and decide the verdict.

        The status is whatever our own code chose to write, so only the expectation makes it
        evidence. With buffer_expect=None any answer counts as success: the console reached
        CLI_LOAD_TOSS_RESPONSE at all, which already means the payload returned 1.
        """
        self.buffer_status = int.from_bytes(self._received[:4], "little")
        expected, mask, why = self._expected_buffer_status()
        if expected is None:
            self.buffer_matched = True
            self.info(f"Buffer script status: 0x{self.buffer_status:08X} "
                      f"({self.buffer_status}) - the payload returned 1 and answered")
        else:
            self.buffer_matched = (self.buffer_status & mask) == (expected & mask)
            verdict = "MATCHES" if self.buffer_matched else "DOES NOT MATCH"
            self.info(f"Buffer script status: 0x{self.buffer_status:08X} {verdict} "
                      f"0x{expected:08X} ({why})")
            if self.buffer_expect == BUFFER_EXPECT_TRAINER_ID and self.buffer_matched:
                # playerTrainerId is one u32: the public id the trainer card shows is the low
                # half, the SECRET ID the high half. The secret id is not printed anywhere in the
                # game and does not travel in any link message, so reading it out of the save is
                # the only way to have it - and it is half of the gen 3 shiny check,
                # (TID ^ SID ^ PID_high ^ PID_low) < 8.
                self.info(f"  -> TID (public) {self.buffer_status & 0xFFFF}, "
                          f"SID (SECRET) {self.buffer_status >> 16}")
        self.param = self.buffer_matched
        self.trace.append(("buffer_status", self.buffer_status, self.buffer_matched))

    def _expected_buffer_status(self):
        """(expected, comparison mask, what the expectation is) for the configured oracle."""
        if self.buffer_expect is None:
            return None, 0xFFFFFFFF, "no expectation"
        if self.buffer_expect != BUFFER_EXPECT_TRAINER_ID:
            return int(self.buffer_expect) & 0xFFFFFFFF, 0xFFFFFFFF, "the value we asked for"
        if self.game_data is None:
            raise MysteryGiftServerError(
                "buffer_expect=trainer-id needs the console's game data, which this script "
                "never read")
        expected = self.game_data.trainer_id & 0xFFFFFFFF
        if self.game_data.trainer_id_is_reliable:
            return expected, 0xFFFFFFFF, "the trainer id from the console's own game data"
        # StringCopy's terminator ate playerTrainerId[0] on the way into the game data
        # [decomp:src/mystery_gift.c:364], so only the top three bytes are comparable. Our ARM
        # code read the save directly and is the one telling the truth here.
        return expected, 0xFFFFFF00, ("the trainer id from the game data, low byte excluded: "
                                      "a 7-character player name overwrote it")

    def _do_svr_load_buffer_verdict_msg(self):
        text = (self.buffer_success_message if self.buffer_matched
                else self.buffer_failure_message)
        self._loaded = (MG_LINKID_DYNAMIC_MSG, text, len(text))

    def _do_svr_load_msg(self, text):
        self._loaded = (MG_LINKID_DYNAMIC_MSG, text, len(text))
