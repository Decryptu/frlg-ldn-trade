"""Mystery Gift client scripts the server pushes, and the link game data read back. Every script must
end in CLI_RETURN or CLI_COPY_RECV: the console runs straight out of its 1024-byte recv buffer and bytes
past the script are stale. A client script's declared size is 8 bytes per command, not the full buffer."""

from dataclasses import dataclass

from . import charmap
from .mystery_gift import (
    GAME_DATA_VALID_VAR, MG_LINKID_CARD, MG_LINKID_CLIENT_SCRIPT,
    MG_LINKID_DYNAMIC_MSG, MG_LINKID_EREADER_TRAINER, MG_LINKID_NEWS, MG_LINKID_RAM_SCRIPT,
    MG_LINKID_STAMP, VERSION_CODE_FIRERED, VERSION_CODE_LEAFGREEN,
)

# [decomp:include/mystery_gift_client.h:18]
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

# [decomp:include/mystery_gift_client.h:45]
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
CLIENT_MAX_MSG_SIZE = 64


def client_script(*commands):
    """A bare instruction id is shorthand for (instr, 0)."""
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


# Boot script [decomp:src/mystery_gift_scripts.c:15]; never sent, but the server's first message must
# be the CLIENT_SCRIPT it sits in CLI_RECV waiting for.
CLIENT_SCRIPT_INIT = client_script(
    (CLI_RECV, MG_LINKID_CLIENT_SCRIPT),
    CLI_COPY_RECV,
)

# sClientScript_SendGameData [decomp:src/mystery_gift_scripts.c:20]
CLIENT_SCRIPT_SEND_GAME_DATA = client_script(
    CLI_LOAD_GAME_DATA,
    CLI_SEND_LOADED,
    (CLI_RECV, MG_LINKID_CLIENT_SCRIPT),
    CLI_COPY_RECV,
)

# sClientScript_SaveCard [decomp:src/mystery_gift_scripts.c:42]
CLIENT_SCRIPT_SAVE_CARD = client_script(
    (CLI_RECV, MG_LINKID_CARD),
    CLI_SAVE_CARD,
    (CLI_RECV, MG_LINKID_RAM_SCRIPT),
    CLI_SAVE_RAM_SCRIPT,
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_CARD_RECEIVED),
)

# sClientScript_SaveNews [decomp:src/mystery_gift_scripts.c:51]. The News path is the only one where
# the console answers a gift with a value: CLI_SAVE_NEWS loads MG_LINKID_RESPONSE with FALSE when it
# saved the news and TRUE when it already held exactly these 444 bytes [mystery_gift_client.c:210],
# and CLI_SEND_LOADED ships that answer. The card path has no equivalent.
CLIENT_SCRIPT_SAVE_NEWS = client_script(
    (CLI_RECV, MG_LINKID_NEWS),
    CLI_SAVE_NEWS,
    CLI_SEND_LOADED,
    (CLI_RECV, MG_LINKID_CLIENT_SCRIPT),
    CLI_COPY_RECV,
)

# sClientScript_HadNews [decomp:src/mystery_gift_scripts.c:59]
CLIENT_SCRIPT_HAD_NEWS = client_script(
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_HAD_NEWS),
)

# sClientScript_NewsReceived [decomp:src/mystery_gift_scripts.c:64]. CLI_MSG_NEWS_RECEIVED is a success
# message, so the console saves by itself and then sets the berry reward for a Friend source
# [GetClientResultMessage, mystery_gift_menu.c:905; WonderNews_SetReward, :1367].
CLIENT_SCRIPT_NEWS_RECEIVED = client_script(
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_NEWS_RECEIVED),
)

# The visiting trainer rides the same card session: CLI_RECV_EREADER_TRAINER memcpys the 188 bytes
# into gSaveBlock2Ptr->battleTower.ereaderTrainer and validates them [decomp:src/mystery_gift_client.c:233].
# CLI_MSG_TRAINER_RECEIVED is a success message, so the console saves on its own afterwards
# [GetClientResultMessage, mystery_gift_menu.c:939; MG_STATE_SAVE_LOAD_GIFT, :1379].
CLIENT_SCRIPT_SAVE_CARD_AND_TRAINER = client_script(
    (CLI_RECV, MG_LINKID_CARD),
    CLI_SAVE_CARD,
    (CLI_RECV, MG_LINKID_RAM_SCRIPT),
    CLI_SAVE_RAM_SCRIPT,
    (CLI_RECV, MG_LINKID_EREADER_TRAINER),
    CLI_RECV_EREADER_TRAINER,
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_TRAINER_RECEIVED),
)

# Re-sending to a console that already holds the card: the trainer alone, so the event can be
# repeated without the player tossing anything.
CLIENT_SCRIPT_SAVE_TRAINER = client_script(
    (CLI_RECV, MG_LINKID_EREADER_TRAINER),
    CLI_RECV_EREADER_TRAINER,
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_TRAINER_RECEIVED),
)

# The activation Mystery Event runs only after CLI_SAVE_STAMP; the server has already rejected the
# duplicate/full-card cases, so those exits never touch the reward variables.
CLIENT_SCRIPT_INSTALL_CARD_AND_STAMP = client_script(
    (CLI_RECV, MG_LINKID_CARD),
    CLI_SAVE_CARD,
    (CLI_RECV, MG_LINKID_RAM_SCRIPT),
    CLI_SAVE_RAM_SCRIPT,
    (CLI_RECV, MG_LINKID_STAMP),
    CLI_SAVE_STAMP,
    (CLI_RECV, MG_LINKID_RAM_SCRIPT),
    CLI_RUN_MEVENT_SCRIPT,
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_STAMP_RECEIVED),
)

CLIENT_SCRIPT_SAVE_STAMP = client_script(
    (CLI_RECV, MG_LINKID_STAMP),
    CLI_SAVE_STAMP,
    (CLI_RECV, MG_LINKID_RAM_SCRIPT),
    CLI_RUN_MEVENT_SCRIPT,
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_STAMP_RECEIVED),
)

CLIENT_SCRIPT_HAD_STAMP = client_script(
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_HAD_STAMP),
)

CLIENT_SCRIPT_NO_ROOM_STAMPS = client_script(
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_NO_ROOM_STAMPS),
)

# sClientScript_HadCard [decomp:src/mystery_gift_scripts.c:82]
CLIENT_SCRIPT_HAD_CARD = client_script(
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_HAD_CARD),
)

# sClientScript_AskToss [decomp:src/mystery_gift_scripts.c:69]; the answer comes back as MG_LINKID_RESPONSE.
CLIENT_SCRIPT_ASK_TOSS = client_script(
    CLI_ASK_TOSS,
    CLI_LOAD_TOSS_RESPONSE,
    CLI_SEND_LOADED,
    (CLI_RECV, MG_LINKID_CLIENT_SCRIPT),
    CLI_COPY_RECV,
)

# sClientScript_Canceled [decomp:src/mystery_gift_scripts.c:77] is the News cancel path; the card path
# uses CLIENT_SCRIPT_DYNAMIC_ERROR.
CLIENT_SCRIPT_CANCELED = client_script(
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_COMM_CANCELED),
)

# sClientScript_DynamicError [decomp:src/union_room_message.c:562]: what a player who declines to toss
# their card runs; it receives a 64-byte message to display first.
CLIENT_SCRIPT_DYNAMIC_ERROR = client_script(
    (CLI_RECV, MG_LINKID_DYNAMIC_MSG),
    CLI_COPY_MSG,
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_BUFFER_FAILURE),
)

# sText_CanceledReadingCard [decomp:src/union_room_message.c:560], EOS-terminated.
TEXT_CANCELED_READING_CARD = charmap.encode("Canceled reading the Card.") + b"\xff"

# sClientScript_CantAccept [decomp:src/mystery_gift_scripts.c:27]
CLIENT_SCRIPT_CANT_ACCEPT = client_script(
    CLI_SEND_READY_END,
    (CLI_RETURN, CLI_MSG_CANT_ACCEPT),
)


# struct MysteryGiftLinkGameData [decomp:include/mystery_gift.h:22]; agbcc aligns the nested
# WonderCardMetadata up to 0x20, so the payload is 0x64 bytes, not the packed 0x60.
GAME_DATA_SIZE = 0x64
GD_OFF_UNK_00 = 0x00            # magic, must be GAME_DATA_VALID_VAR
GD_OFF_UNK_04 = 0x04
GD_OFF_UNK_08 = 0x08
GD_OFF_UNK_0C = 0x0C
GD_OFF_UNK_10 = 0x10            # low nibble = VERSION_CODE (1 FireRed, 2 LeafGreen)
GD_OFF_FLAG_ID = 0x14           # 0 = console holds no Wonder Card
GD_OFF_QUESTIONNAIRE = 0x16     # u16[NUM_QUESTIONNAIRE_WORDS]
GD_OFF_CARD_METADATA = 0x20     # struct WonderCardMetadata (36 bytes)
GD_OFF_METADATA_ICON = GD_OFF_CARD_METADATA + 6
GD_OFF_STAMP_SPECIES = GD_OFF_CARD_METADATA + 8
GD_OFF_STAMP_IDS = GD_OFF_STAMP_SPECIES + 14
GD_OFF_MAX_STAMPS = 0x44
GD_OFF_PLAYER_NAME = 0x45       # u8[PLAYER_NAME_LENGTH] = 7, with NO terminator slot
GD_OFF_TRAINER_ID = 0x4C        # u8[TRAINER_ID_LENGTH]
PLAYER_NAME_FIELD_SIZE = 7
GD_OFF_EASY_CHAT = 0x50         # u16[EASY_CHAT_BATTLE_WORDS_COUNT]
GD_OFF_GAME_CODE = 0x5C         # u8[GAME_CODE_LENGTH]
GD_OFF_VERSION = 0x60           # RomHeaderSoftwareVersion

# [decomp:src/mystery_gift.c:388]
HAS_NO_CARD = 0
HAS_SAME_CARD = 1
HAS_DIFF_CARD = 2

_VERSION_NAMES = {VERSION_CODE_FIRERED: "FireRed", VERSION_CODE_LEAFGREEN: "LeafGreen"}


@dataclass(frozen=True)
class LinkGameData:
    raw: bytes
    magic: int
    unk_04: int
    unk_08: int
    unk_0c: int
    version_code: int
    flag_id: int
    metadata_icon_species: int
    stamp_species: tuple
    stamp_ids: tuple
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
    def stamps(self):
        return tuple((species, stamp_id)
                     for species, stamp_id in zip(self.stamp_species, self.stamp_ids)
                     if species and stamp_id)

    @property
    def trainer_id_is_reliable(self):
        """A full 7-character name's 0xFF terminator overwrites playerTrainerId[0] [decomp:src/mystery_gift.c:364]."""
        return len(self.raw[GD_OFF_PLAYER_NAME:GD_OFF_PLAYER_NAME + PLAYER_NAME_FIELD_SIZE]
                   .rstrip(b"\xff")) < PLAYER_NAME_FIELD_SIZE

    def describe(self):
        trainer = (f"TID {self.trainer_id & 0xFFFF}" if self.trainer_id_is_reliable
                   else "TID unavailable (7-character name)")
        return (f"{self.player_name!r} ({trainer}) on {self.version_name}, "
                + (f"holding card flagId {self.flag_id}" if self.has_card
                   else "holding no Wonder Card"))


def parse_link_game_data(payload):
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
        metadata_icon_species=u16(GD_OFF_METADATA_ICON),
        stamp_species=tuple(u16(GD_OFF_STAMP_SPECIES + 2 * i) for i in range(7)),
        stamp_ids=tuple(u16(GD_OFF_STAMP_IDS + 2 * i) for i in range(7)),
        max_stamps=payload[GD_OFF_MAX_STAMPS],
        player_name=charmap.decode(payload[GD_OFF_PLAYER_NAME:GD_OFF_PLAYER_NAME + 7]),
        trainer_id=u32(GD_OFF_TRAINER_ID),
        questionnaire_words=tuple(
            u16(GD_OFF_QUESTIONNAIRE + 2 * i) for i in range(4)),
        game_code=payload[GD_OFF_GAME_CODE:GD_OFF_GAME_CODE + 4],
        software_version=payload[GD_OFF_VERSION],
    )


def validate_link_game_data(data):
    """Port of MysteryGift_ValidateLinkGameData [decomp:src/mystery_gift.c:373]."""
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
    """Port of MysteryGift_CompareCardFlags [decomp:src/mystery_gift.c:388]."""
    if data.flag_id == 0:
        return HAS_NO_CARD
    if our_flag_id == data.flag_id:
        return HAS_SAME_CARD
    return HAS_DIFF_CARD
