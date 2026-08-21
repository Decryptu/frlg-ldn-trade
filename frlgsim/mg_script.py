"""Client scripts and link game data - what the server pushes, what it reads back.

The console does not decide the Mystery Gift flow; the *server* does. The client
boots with a two-instruction script [mystery_gift_scripts.c:15]::

    {CLI_RECV, MG_LINKID_CLIENT_SCRIPT}
    {CLI_COPY_RECV}

and from then on runs whatever ``struct MysteryGiftClientCmd`` array we send it
[mystery_gift_client.c:87].  This module assembles those arrays and the canned
ones the decomp itself uses, plus the reader for the
``struct MysteryGiftLinkGameData`` the client sends back.

Two details the console enforces:

* a script is executed one command per frame straight out of the 1024-byte recv
  buffer, and ``CopyRecvScript`` copies the *whole* buffer.  Bytes past our
  script are stale data from the previous message, so every script must end in
  a command that stops execution (``CLI_RETURN``) or replaces the script
  (``CLI_COPY_RECV``).  Native relies on the same property.
* the message size for a client script is ``sizeof(the array)``
  [mystery_gift_server.h:52 ``PTR_ARG``], i.e. 8 bytes per command - not the
  full buffer.
"""

from dataclasses import dataclass

from . import charmap
from .mystery_gift import (
    GAME_DATA_VALID_VAR, MG_LINKID_CARD, MG_LINKID_CLIENT_SCRIPT,
    MG_LINKID_DYNAMIC_MSG, MG_LINKID_RAM_SCRIPT, VERSION_CODE_FIRERED,
    VERSION_CODE_LEAFGREEN,
)

# --- client script instruction ids [include/mystery_gift_client.h:18] -------------------------
CLI_NONE = 0
CLI_RETURN = 1
CLI_RECV = 2
CLI_SEND_LOADED = 3
CLI_COPY_RECV = 4
CLI_YES_NO = 5
CLI_COPY_RECV_IF_N = 6
CLI_COPY_RECV_IF = 7
CLI_LOAD_GAME_DATA = 8
CLI_SAVE_NEWS = 9
CLI_SAVE_CARD = 10
CLI_PRINT_MSG = 11
CLI_COPY_MSG = 12
CLI_ASK_TOSS = 13
CLI_LOAD_TOSS_RESPONSE = 14
CLI_RUN_MEVENT_SCRIPT = 15
CLI_SAVE_STAMP = 16
CLI_SAVE_RAM_SCRIPT = 17
CLI_RECV_EREADER_TRAINER = 18
CLI_SEND_STAT = 19
CLI_SEND_READY_END = 20
CLI_RUN_BUFFER_SCRIPT = 21

# --- client result message ids [include/mystery_gift_client.h:45] -----------------------------
CLI_MSG_NOTHING_SENT = 0
CLI_MSG_RECORD_UPLOADED = 1
CLI_MSG_CARD_RECEIVED = 2
CLI_MSG_NEWS_RECEIVED = 3
CLI_MSG_STAMP_RECEIVED = 4
CLI_MSG_HAD_CARD = 5
CLI_MSG_HAD_STAMP = 6
CLI_MSG_HAD_NEWS = 7
CLI_MSG_NO_ROOM_STAMPS = 8
CLI_MSG_COMM_CANCELED = 9
CLI_MSG_CANT_ACCEPT = 10
CLI_MSG_COMM_ERROR = 11
CLI_MSG_TRAINER_RECEIVED = 12
CLI_MSG_BUFFER_SUCCESS = 13
CLI_MSG_BUFFER_FAILURE = 14

CLIENT_CMD_SIZE = 8             # sizeof(struct MysteryGiftClientCmd): u32 instr + u32 parameter
CLIENT_MAX_MSG_SIZE = 64        # CLI_PRINT_MSG / CLI_YES_NO dynamic message


def client_script(*commands):
    """Assemble a ``struct MysteryGiftClientCmd[]`` from ``(instr, param)`` pairs.

    A bare instruction id is accepted as shorthand for ``(instr, 0)``.
    """
    out = bytearray()
    for command in commands:
        if isinstance(command, int):
            instr, param = command, 0
        else:
            instr, param = command
        if not 0 <= instr <= 0xFFFFFFFF or not 0 <= param <= 0xFFFFFFFF:
            raise ValueError("client script fields must fit in u32")
        out += instr.to_bytes(4, "little") + param.to_bytes(4, "little")
    return bytes(out)


# --- the decomp's own client scripts [src/mystery_gift_scripts.c] -----------------------------
# Boot script the client starts with; we never send this one, but the server's
# first message must be the CLIENT_SCRIPT it is sitting in CLI_RECV waiting for.
CLIENT_SCRIPT_INIT = client_script(
    (CLI_RECV, MG_LINKID_CLIENT_SCRIPT),
    CLI_COPY_RECV,
)

# sClientScript_SendGameData [:20] - ask the console who it is, then wait for
# our verdict as another client script.
CLIENT_SCRIPT_SEND_GAME_DATA = client_script(
    CLI_LOAD_GAME_DATA,
    CLI_SEND_LOADED,
    (CLI_RECV, MG_LINKID_CLIENT_SCRIPT),
    CLI_COPY_RECV,
)

# sClientScript_SaveCard [:42] - the gift itself.
CLIENT_SCRIPT_SAVE_CARD = client_script(
    (CLI_RECV, MG_LINKID_CARD),
    CLI_SAVE_CARD,
    (CLI_RECV, MG_LINKID_RAM_SCRIPT),
    CLI_SAVE_RAM_SCRIPT,
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_CARD_RECEIVED),
)

# sClientScript_HadCard [:82] - the console already holds this exact card.
CLIENT_SCRIPT_HAD_CARD = client_script(
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_HAD_CARD),
)

# sClientScript_AskToss [:69] - the console holds a *different* card; offer to
# replace it and send the player's answer back as MG_LINKID_RESPONSE.
CLIENT_SCRIPT_ASK_TOSS = client_script(
    CLI_ASK_TOSS,
    CLI_LOAD_TOSS_RESPONSE,
    CLI_SEND_LOADED,
    (CLI_RECV, MG_LINKID_CLIENT_SCRIPT),
    CLI_COPY_RECV,
)

# sClientScript_Canceled [:77] - the *News* cancel path. Kept for completeness;
# the card path uses CLIENT_SCRIPT_DYNAMIC_ERROR below.
CLIENT_SCRIPT_CANCELED = client_script(
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_COMM_CANCELED),
)

# sClientScript_DynamicError [union_room_message.c:562] - what a player who
# declines to toss their existing *card* actually runs. Unlike the News cancel
# script it first receives a live 64-byte message to display.
CLIENT_SCRIPT_DYNAMIC_ERROR = client_script(
    (CLI_RECV, MG_LINKID_DYNAMIC_MSG),
    CLI_COPY_MSG,
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_BUFFER_FAILURE),
)

# sText_CanceledReadingCard [union_room_message.c:560], the message that script
# displays. Encoded in the game's character set, EOS-terminated.
TEXT_CANCELED_READING_CARD = charmap.encode("Canceled reading the Card.") + b"\xff"

# sClientScript_CantAccept [:27] - the console's game data failed validation.
CLIENT_SCRIPT_CANT_ACCEPT = client_script(
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_CANT_ACCEPT),
)


# --- struct MysteryGiftLinkGameData [include/mystery_gift.h:22] -------------------------------
# Offsets follow GBA natural alignment: u16 fields at 0x04/0x0C are each
# followed by two padding bytes so the next u32 stays 4-aligned.
GAME_DATA_SIZE = 0x60
GD_OFF_UNK_00 = 0x00            # magic, must be GAME_DATA_VALID_VAR
GD_OFF_UNK_04 = 0x04
GD_OFF_UNK_08 = 0x08
GD_OFF_UNK_0C = 0x0C
GD_OFF_UNK_10 = 0x10            # low nibble = VERSION_CODE (1 FireRed, 2 LeafGreen)
GD_OFF_FLAG_ID = 0x14           # 0 = console holds no Wonder Card
GD_OFF_QUESTIONNAIRE = 0x16     # u16[NUM_QUESTIONNAIRE_WORDS]
GD_OFF_CARD_METADATA = 0x1E     # struct WonderCardMetadata (36 bytes)
GD_OFF_MAX_STAMPS = 0x42
GD_OFF_PLAYER_NAME = 0x43       # u8[PLAYER_NAME_LENGTH] = 7, with NO terminator slot
GD_OFF_TRAINER_ID = 0x4A        # u8[TRAINER_ID_LENGTH]
PLAYER_NAME_FIELD_SIZE = 7
GD_OFF_EASY_CHAT = 0x4E         # u16[EASY_CHAT_BATTLE_WORDS_COUNT]
GD_OFF_GAME_CODE = 0x5A         # u8[GAME_CODE_LENGTH]
GD_OFF_VERSION = 0x5E           # RomHeaderSoftwareVersion

# MysteryGift_CompareCardFlags [src/mystery_gift.c:388]
HAS_NO_CARD = 0
HAS_SAME_CARD = 1
HAS_DIFF_CARD = 2

_VERSION_NAMES = {VERSION_CODE_FIRERED: "FireRed", VERSION_CODE_LEAFGREEN: "LeafGreen"}


@dataclass(frozen=True)
class LinkGameData:
    """The decoded ``MysteryGiftLinkGameData`` the console sends us."""

    raw: bytes
    magic: int
    unk_04: int
    unk_08: int
    unk_0c: int
    version_code: int
    flag_id: int
    max_stamps: int
    player_name: str
    trainer_id: int
    questionnaire_words: tuple
    game_code: bytes
    software_version: int

    @property
    def version_name(self):
        return _VERSION_NAMES.get(self.version_code & 0x0F, f"version {self.version_code}")

    @property
    def has_card(self):
        return self.flag_id != 0

    @property
    def trainer_id_is_reliable(self):
        """False when the console's name filled the field and clobbered the id.

        ``MysteryGift_LoadLinkGameData`` copies the trainer id first and *then*
        ``StringCopy``s the name [mystery_gift.c:364-365] into a 7-byte field with
        no room for a terminator, so a full-length 7-character name writes its
        0xFF one byte past, over ``playerTrainerId[0]``. Display only - nothing
        the server decides depends on the trainer id.
        """
        return len(self.raw[GD_OFF_PLAYER_NAME:GD_OFF_PLAYER_NAME + PLAYER_NAME_FIELD_SIZE]
                   .rstrip(b"\xff")) < PLAYER_NAME_FIELD_SIZE

    def describe(self):
        trainer = (f"TID {self.trainer_id & 0xFFFF}" if self.trainer_id_is_reliable
                   else "TID unavailable (7-character name)")
        return (f"{self.player_name!r} ({trainer}) on {self.version_name}, "
                + (f"holding card flagId {self.flag_id}" if self.has_card
                   else "holding no Wonder Card"))


def parse_link_game_data(payload):
    """Decode the fields the server acts on. Short payloads raise ``ValueError``."""
    payload = bytes(payload)
    if len(payload) < GAME_DATA_SIZE:
        raise ValueError(
            f"link game data is {len(payload)} bytes, expected {GAME_DATA_SIZE}")

    def u16(off):
        return int.from_bytes(payload[off:off + 2], "little")

    def u32(off):
        return int.from_bytes(payload[off:off + 4], "little")

    return LinkGameData(
        raw=payload[:GAME_DATA_SIZE],
        magic=u32(GD_OFF_UNK_00),
        unk_04=u16(GD_OFF_UNK_04),
        unk_08=u32(GD_OFF_UNK_08),
        unk_0c=u16(GD_OFF_UNK_0C),
        version_code=u32(GD_OFF_UNK_10),
        flag_id=u16(GD_OFF_FLAG_ID),
        max_stamps=payload[GD_OFF_MAX_STAMPS],
        player_name=charmap.decode(payload[GD_OFF_PLAYER_NAME:GD_OFF_PLAYER_NAME + 7]),
        trainer_id=u32(GD_OFF_TRAINER_ID),
        questionnaire_words=tuple(
            u16(GD_OFF_QUESTIONNAIRE + 2 * i) for i in range(4)),
        game_code=payload[GD_OFF_GAME_CODE:GD_OFF_GAME_CODE + 4],
        software_version=payload[GD_OFF_VERSION],
    )


def validate_link_game_data(data):
    """Port of ``MysteryGift_ValidateLinkGameData`` [src/mystery_gift.c:373]."""
    if data.magic != GAME_DATA_VALID_VAR:
        return False
    if not data.unk_04 & 1:
        return False
    if not data.unk_08 & 1:
        return False
    if not data.unk_0c & 1:
        return False
    if not data.version_code & 0x0F:
        return False
    return True


def compare_card_flags(our_flag_id, data):
    """Port of ``MysteryGift_CompareCardFlags`` [src/mystery_gift.c:388]."""
    if data.flag_id == 0:
        return HAS_NO_CARD
    if our_flag_id == data.flag_id:
        return HAS_SAME_CARD
    return HAS_DIFF_CARD
