"""The card is the 332-byte struct WonderCard [decomp:include/global.h:655] and must pass ValidateWonderCard
[decomp:src/mystery_gift.c:191]. The console wraps the RAM script body and computes its checksum itself; the script
runs with no pointer relocation, so it may only use immediate operands and setvaddress-relative branches."""

from . import charmap
from .mystery_gift import (
    CARD_TYPE_GIFT, SEND_TYPE_DISALLOWED, WONDER_CARD_FLAG_OFFSET, NUM_WONDER_CARD_FLAGS,
    FLAG_WONDER_CARD_UNUSED_1,
)

# struct WonderCard layout [include/global.h:655-669], packed, little-endian.
WONDER_CARD_TEXT_LENGTH = 40
WONDER_CARD_BODY_TEXT_LINES = 4
WONDER_CARD_SIZE = 332              # sizeof(struct WonderCard): 330 data + 2 pad (u32 idNumber align)

# [include/constants/items.h:172:180]
ITEM_LIECHI_BERRY = 168
ITEM_GANLON_BERRY = 169
ITEM_SALAC_BERRY = 170
ITEM_PETAYA_BERRY = 171
ITEM_APICOT_BERRY = 172
ITEM_LANSAT_BERRY = 173
ITEM_STARF_BERRY = 174
ITEM_ENIGMA_BERRY = 175
ITEM_MASTER_BALL = 1
ITEM_NONE = 0

# [include/constants/species.h:328]; iconSpecies only selects the card icon.
SPECIES_CLAYDOL = 319
SPECIES_CELEBI = 251
SPECIES_RAIKOU = 243
SPECIES_ENTEI = 244
SPECIES_SUICUNE = 245

OBJ_EVENT_GFX_KANGASKHAN = 119
OBJ_EVENT_GFX_ENTEI = 141
OBJ_EVENT_GFX_SUICUNE = 142
OBJ_EVENT_GFX_RAIKOU = 143
OBJ_EVENT_GFX_CELEBI = 146
DIR_SOUTH = 1
DIR_WEST = 3

# VAR_STARTER_MON: 0 Bulbasaur, 1 Squirtle, 2 Charmander.
STARTER_BEASTS = {
    0: (SPECIES_SUICUNE, OBJ_EVENT_GFX_SUICUNE),
    1: (SPECIES_ENTEI, OBJ_EVENT_GFX_ENTEI),
    2: (SPECIES_RAIKOU, OBJ_EVENT_GFX_RAIKOU),
}

# [include/constants/moves.h]
MOVE_LEECH_SEED = 73
MOVE_RECOVER = 105
MOVE_HEAL_BELL = 215
MOVE_SAFEGUARD = 219

DEFAULT_GIFT_TITLE = "CELEBI GIFT"
DEFAULT_GIFT_SUBTITLE = "A timeless gift"
DEFAULT_GIFT_BODY = (
    "A special CELEBI is waiting",
    "just for you!",
    "Visit the deliveryman on the",
    "2nd floor to receive CELEBI.",
)
DEFAULT_GIFT_SIGNATURE = " - MercuryEnigma"
DEFAULT_GIFT_ICON_SPECIES = SPECIES_CELEBI
DEFAULT_GIFT_ITEM = None

GIFT_BEAST_CUTSCENE = "beast-cutscene"
GIFT_CELEBI = "celebi"
GIFT_CHOICES = (GIFT_BEAST_CUTSCENE, GIFT_CELEBI)
LEGENDARY_BEAST_LEVEL = 65


# Event-script opcodes [asm/macros/event.inc].
_OP_END = 0x02
_OP_CALLSTD = 0x09
_OP_ADDVAR = 0x17
_OP_SETVAR_OR_COPY = 0x1A
_OP_SETFLAG = 0x29
_OP_DELAY = 0x28
_OP_GETPLAYERXY = 0x42
_OP_FACEPLAYER = 0x5A
_OP_CLOSEMESSAGE = 0x68
_OP_LOCK = 0x6A
_OP_RELEASE = 0x6C
_OP_GIVEMON = 0x79
_OP_SETMONMOVE = 0x7B
_OP_GETPARTYSIZE = 0x43
_OP_COMPARE_VAR_TO_VALUE = 0x21
_OP_CHECKFLAG = 0x2B
_OP_SETVADDRESS = 0xB8
_OP_VGOTO_IF = 0xBB
_OP_VMESSAGE = 0xBD
_OP_WAITMESSAGE = 0x66
_OP_WAITBUTTONPRESS = 0x6D
_OP_CREATEVOBJECT = 0xAA
_OP_SETWILDBATTLE = 0xB6
_OP_DOWILDBATTLE = 0xB7

_VAR_0x8000 = 0x8000
_VAR_0x8001 = 0x8001
_VAR_STARTER_MON = 0x4031
_VAR_PLAYER_X = 0x8004
_VAR_PLAYER_Y = 0x8005
_VAR_RESULT = 0x800D
_STD_OBTAIN_ITEM = 0           # gStdScripts index [event_scripts.s:78]
_COMPARE_EQ = 1
_PARTY_SIZE = 6
# ScriptSetMonMoveSlot targets the last party mon only for index > PARTY_SIZE; 6 itself is out of bounds.
_LAST_PARTY_MON_INDEX = _PARTY_SIZE + 1
_RAM_SCRIPT_VIRTUAL_BASE = 0x08000000
# Flags 0x3D8..0x3E7 are cleared by ClearMysteryGiftFlags when a replacement card is saved.
_FLAG_REWARD_RECEIVED = 0x3D9

_TEXT_REWARD_RECEIVED = "{PLAYER} received a CELEBI\nfrom the deliveryman!"
_TEXT_PARTY_FULL = "Oh, your party appears to be full.\nPlease make room and come back!"
_TEXT_REWARD_ALREADY_RECEIVED = "Please look forward to future\nMYSTERY GIFTS!"


def _u16(v):
    return (v & 0xFFFF).to_bytes(2, "little")


def _setorcopyvar(dest, src):
    return bytes([_OP_SETVAR_OR_COPY]) + _u16(dest) + _u16(src)


def _givemon(species, level, item=0):
    return (bytes([_OP_GIVEMON]) + _u16(species) + bytes([level]) + _u16(item)
            + b"\x00" * 9)


def _setmonmove(party_index, slot, move):
    return bytes([_OP_SETMONMOVE, party_index, slot]) + _u16(move)


def _script_text(text):
    out = bytearray()
    lines = text.split("\n")
    for line_index, line in enumerate(lines):
        parts = line.split("{PLAYER}")
        for part_index, part in enumerate(parts):
            out += charmap.encode(part)
            if part_index < len(parts) - 1:
                out += b"\xFD\x01"
        if line_index < len(lines) - 1:
            out += b"\xFE"
    return bytes(out) + b"\xFF"


def flag_for_flag_id(flag_id):
    """sReceivedGiftFlags[flagId - 1000] [decomp:src/mystery_gift.c:255]; valid flagIds are 1000..1019."""
    idx = flag_id - WONDER_CARD_FLAG_OFFSET
    if not (0 <= idx < NUM_WONDER_CARD_FLAGS):
        raise ValueError(f"card flagId {flag_id} out of range [1000, {1000 + NUM_WONDER_CARD_FLAGS})")
    # sReceivedGiftFlags[0..3] = AURORA(0x2A7), MYSTIC(0x2A8), OLD_SEA_MAP(0x2A9), UNUSED_1(0x2AA)
    return FLAG_WONDER_CARD_UNUSED_1 - 3 + idx


def build_delivery_ram_script(item=DEFAULT_GIFT_ITEM, flag=None, flag_id=None):
    """Ends with ``end`` (not ``endram``) so the saved script survives: the item is re-given on every
    interaction, Celebi once per card (flag reset when a replacement card is saved)."""
    if flag is None:
        flag = flag_for_flag_id(flag_id) if flag_id is not None else (FLAG_WONDER_CARD_UNUSED_1)
    if item is not None and (type(item) is not int or not 0 < item <= 0xFFFF):
        raise ValueError("item must be a positive 16-bit item id or None")

    out = bytearray(bytes([_OP_LOCK, _OP_FACEPLAYER]))
    if item is not None:
        out += (_setorcopyvar(_VAR_0x8000, item)
                + _setorcopyvar(_VAR_0x8001, 1)
                + bytes([_OP_CALLSTD, _STD_OBTAIN_ITEM])
                + bytes([_OP_SETFLAG]) + _u16(flag))

    # Saved RAM scripts cannot hold absolute pointers; setvaddress + vgoto_if are relative [decomp:src/scrcmd.c:165-206].
    virtual_anchor = len(out)
    out += bytes([_OP_SETVADDRESS]) + _RAM_SCRIPT_VIRTUAL_BASE.to_bytes(4, "little")
    out += bytes([_OP_CHECKFLAG]) + _u16(_FLAG_REWARD_RECEIVED)
    already_branch_pointer = len(out)
    out += bytes([_OP_VGOTO_IF, _COMPARE_EQ]) + b"\x00\x00\x00\x00"
    out += bytes([_OP_GETPARTYSIZE])
    out += bytes([_OP_COMPARE_VAR_TO_VALUE]) + _u16(_VAR_RESULT) + _u16(_PARTY_SIZE)
    full_party_branch_pointer = len(out)
    out += bytes([_OP_VGOTO_IF, _COMPARE_EQ]) + b"\x00\x00\x00\x00"

    out += _givemon(SPECIES_CELEBI, 50)
    for slot, move in enumerate((MOVE_LEECH_SEED, MOVE_RECOVER, MOVE_HEAL_BELL, MOVE_SAFEGUARD)):
        out += _setmonmove(_LAST_PARTY_MON_INDEX, slot, move)
    if item is None:
        out += bytes([_OP_SETFLAG]) + _u16(flag)
    out += bytes([_OP_SETFLAG]) + _u16(_FLAG_REWARD_RECEIVED)

    def append_message_branch(text):
        out.append(_OP_VMESSAGE)
        text_pointer = len(out)
        out.extend(b"\x00\x00\x00\x00")
        out.extend(bytes([_OP_WAITMESSAGE, _OP_WAITBUTTONPRESS, _OP_RELEASE, _OP_END]))
        return text_pointer, text

    received_text_pointer, received_text = append_message_branch(_TEXT_REWARD_RECEIVED)
    already_label = len(out)
    already_text_pointer, already_text = append_message_branch(_TEXT_REWARD_ALREADY_RECEIVED)
    full_party_label = len(out)
    full_party_text_pointer, full_party_text = append_message_branch(_TEXT_PARTY_FULL)

    def virtual_address(offset):
        return _RAM_SCRIPT_VIRTUAL_BASE + (offset - virtual_anchor)

    out[already_branch_pointer + 2:already_branch_pointer + 6] = \
        virtual_address(already_label).to_bytes(4, "little")
    out[full_party_branch_pointer + 2:full_party_branch_pointer + 6] = \
        virtual_address(full_party_label).to_bytes(4, "little")

    for text_pointer, text in ((received_text_pointer, received_text),
                               (already_text_pointer, already_text),
                               (full_party_text_pointer, full_party_text)):
        text_offset = len(out)
        out[text_pointer:text_pointer + 4] = virtual_address(text_offset).to_bytes(4, "little")
        out += _script_text(text)
    return bytes(out)


def _card_text(s):
    return charmap.encode(s or "", width=WONDER_CARD_TEXT_LENGTH, pad=0xFF)


def build_wonder_card(*, flag_id=1003, icon_species=1, id_number=0,
                      card_type=CARD_TYPE_GIFT, bg_type=0, send_type=SEND_TYPE_DISALLOWED,
                      max_stamps=0, title="", subtitle="", body=(), footer1="", footer2=""):
    """ValidateWonderCard needs flagId != 0, type < 3, sendType in {0,1,2}, bgType < 8, maxStamps <= 7;
    body is up to 4 lines of <= 39 chars; id_number 0 displays flag_id % 100."""
    if flag_id == 0:
        raise ValueError("flagId 0 is rejected by ValidateWonderCard")
    if not (0 <= card_type < 3 and 0 <= bg_type < 8 and send_type in (0, 1, 2) and 0 <= max_stamps <= 7):
        raise ValueError("WonderCard field out of the range ValidateWonderCard accepts")
    flag_for_flag_id(flag_id)

    bitfield = (card_type & 0x3) | ((bg_type & 0xF) << 2) | ((send_type & 0x3) << 6)
    display_id = flag_id % 100 if id_number == 0 else id_number
    out = bytearray()
    out += _u16(flag_id)                       # +0
    out += _u16(icon_species)                  # +2
    out += display_id.to_bytes(4, "little")   # +4 idNumber shown on card
    out += bytes([bitfield, max_stamps & 0xFF])            # +8, +9
    out += _card_text(title)                   # +10
    out += _card_text(subtitle)                # +50
    body = list(body)[:WONDER_CARD_BODY_TEXT_LINES]
    for i in range(WONDER_CARD_BODY_TEXT_LINES):           # +90 .. +250
        out += _card_text(body[i] if i < len(body) else "")
    out += _card_text(footer1)                 # +250
    out += _card_text(footer2)                 # +290
    out += b"\x00\x00"                          # +330: 2 pad bytes (u32 alignment of struct)
    assert len(out) == WONDER_CARD_SIZE, len(out)
    return bytes(out)


def build_berry_gift(item=DEFAULT_GIFT_ITEM, title=DEFAULT_GIFT_TITLE,
                     subtitle=DEFAULT_GIFT_SUBTITLE, body=DEFAULT_GIFT_BODY,
                     flag_id=1003):
    card = build_wonder_card(
        flag_id=flag_id, icon_species=DEFAULT_GIFT_ICON_SPECIES,
        title=title, subtitle=subtitle, body=body,
        footer1=DEFAULT_GIFT_SIGNATURE)
    script = build_delivery_ram_script(item=item, flag_id=flag_id)
    return card, script


def build_default_gift(**overrides):
    return build_berry_gift(**overrides)


_CUTSCENE_MESSAGE_TOKENS = {
    "PLAYER": b"\xFD\x01",
    "NL": b"\xFE",
    "P": b"\xFB",
    "SCROLL": b"\xFA",
}


def _encode_cutscene_message(text):
    out = bytearray()
    index = 0
    while index < len(text):
        if text[index] == "{":
            end = text.index("}", index)
            token = text[index + 1:end]
            if token not in _CUTSCENE_MESSAGE_TOKENS:
                raise ValueError(f"unknown message token {{{token}}}")
            out += _CUTSCENE_MESSAGE_TOKENS[token]
            index = end + 1
        else:
            out += charmap.encode(text[index])
            index += 1
    return bytes(out) + b"\xFF"


def build_legendary_beast_cutscene_script(
        level=LEGENDARY_BEAST_LEVEL, delay_frames=30):
    if type(level) is not int or not 1 <= level <= 100:
        raise ValueError("level must be between 1 and 100")
    if type(delay_frames) is not int or not 0 <= delay_frames <= 0xFFFF:
        raise ValueError("delay_frames must fit in 16 bits")

    messages = (
        _encode_cutscene_message(
            "Thank you for using the{NL}MYSTERY GIFT system."),
        _encode_cutscene_message(
            "You must be {PLAYER}!{P}There is something here{NL}for you."),
        _encode_cutscene_message(
            "What is that? It looks{NL}like a Legendary Beast!{P}Here, take this."),
    )

    def give_item(item):
        return (_setorcopyvar(_VAR_0x8000, item)
                + _setorcopyvar(_VAR_0x8001, 1)
                + bytes([_OP_CALLSTD, _STD_OBTAIN_ITEM]))

    code = bytearray()
    message_fixups = []
    branch_fixups = []
    labels = {}

    def vmessage(message_index):
        code.append(_OP_VMESSAGE)
        message_fixups.append((len(code), message_index))
        code.extend(b"\x00\x00\x00\x00")
        code.extend(bytes([
            _OP_WAITMESSAGE, _OP_WAITBUTTONPRESS, _OP_CLOSEMESSAGE]))

    def vgoto_if_starter(value, label):
        code.extend(
            bytes([_OP_COMPARE_VAR_TO_VALUE])
            + _u16(_VAR_STARTER_MON) + _u16(value)
            + bytes([_OP_VGOTO_IF, _COMPARE_EQ]))
        branch_fixups.append((len(code), label))
        code.extend(b"\x00\x00\x00\x00")

    def beast_block(species, graphics):
        code.extend(
            bytes([_OP_CREATEVOBJECT, graphics & 0xFF, 0])
            + _u16(_VAR_PLAYER_X) + _u16(_VAR_PLAYER_Y)
            + bytes([3, DIR_WEST]))
        code.extend(bytes([_OP_DELAY]) + _u16(delay_frames))
        vmessage(2)
        code.extend(give_item(ITEM_MASTER_BALL))
        code.append(_OP_RELEASE)
        code.extend(
            bytes([_OP_SETWILDBATTLE]) + _u16(species)
            + bytes([level]) + _u16(ITEM_NONE)
            + bytes([_OP_DOWILDBATTLE, _OP_END]))

    code += bytes([_OP_SETVADDRESS]) + b"\x00\x00\x00\x00"
    code += bytes([_OP_LOCK, _OP_FACEPLAYER])
    vmessage(0)
    vmessage(1)
    code += give_item(ITEM_LANSAT_BERRY)
    code += give_item(ITEM_LIECHI_BERRY)
    code += bytes([_OP_GETPLAYERXY]) + _u16(_VAR_PLAYER_X) + _u16(_VAR_PLAYER_Y)
    code += bytes([_OP_ADDVAR]) + _u16(_VAR_PLAYER_X) + _u16(1)

    vgoto_if_starter(0, "suicune")
    vgoto_if_starter(1, "entei")
    beast_block(*STARTER_BEASTS[2])
    labels["suicune"] = len(code)
    beast_block(*STARTER_BEASTS[0])
    labels["entei"] = len(code)
    beast_block(*STARTER_BEASTS[1])

    code_size = len(code)
    message_offsets = []
    offset = code_size
    for message in messages:
        message_offsets.append(offset)
        offset += len(message)
    for position, message_index in message_fixups:
        code[position:position + 4] = message_offsets[message_index].to_bytes(4, "little")
    for position, label in branch_fixups:
        code[position:position + 4] = labels[label].to_bytes(4, "little")
    return bytes(code) + b"".join(messages)


def build_legendary_beast_cutscene_gift(
        level=LEGENDARY_BEAST_LEVEL, flag_id=1003):
    flag_for_flag_id(flag_id)
    card = build_wonder_card(
        flag_id=flag_id,
        icon_species=SPECIES_CLAYDOL,
        title="LEGENDARY BEAST",
        subtitle="A shocking encounter!",
        body=("Meet the delivery man for", "berries and a beastly battle!"),
        footer1="frlg-ldn-trade",
    )
    return card, build_legendary_beast_cutscene_script(level=level)


def build_gift(gift, *, flag_id=1003):
    if gift == GIFT_BEAST_CUTSCENE:
        return build_legendary_beast_cutscene_gift(flag_id=flag_id)
    if gift == GIFT_CELEBI:
        return build_default_gift(flag_id=flag_id)
    raise ValueError(f"unknown gift: {gift}")


build_raikou_cutscene_script = build_legendary_beast_cutscene_script
build_raikou_cutscene_gift = build_legendary_beast_cutscene_gift


def _selftest():
    card, script = build_default_gift()
    assert len(card) == WONDER_CARD_SIZE, len(card)
    assert int.from_bytes(card[0:2], "little") == 1003
    bitfield = card[8]
    assert (bitfield & 0x3) == CARD_TYPE_GIFT
    assert ((bitfield >> 2) & 0xF) < 8
    assert ((bitfield >> 6) & 0x3) == SEND_TYPE_DISALLOWED
    assert card[9] == 0
    expected = bytes.fromhex(
        "6a5ab8000000082bd903bb014c00000843210d800600bb0155000008"
        "79fb00320000000000000000000000"
        "7b070049007b070169007b0702d7007b0703db0029aa0229d903"
        "bd5e000008666d6c02bd89000008666d6c02bdb6000008666d6c02"
        "fd0100e6d9d7d9ddead9d800d500bdbfc6bfbcc3fedae6e3e100e8dcd900d8d9e0ddead9e6ede1d5e2abff"
        "cae0d9d5e7d900e0e3e3df00dae3e6ebd5e6d800e8e300dae9e8e9e6d9fec7d3cdcebfccd300c1c3c0cecdabff"
        "c9dcb800ede3e9e600e4d5e6e8ed00d5e4e4d9d5e6e700e8e300d6d900dae9e0e0ad"
        "fecae0d9d5e7d900e1d5dfd900e6e3e3e100d5e2d800d7e3e1d900d6d5d7dfabff")
    assert script == expected, script.hex()
    assert flag_for_flag_id(1003) == 0x2AA
    assert flag_for_flag_id(1000) == 0x2A7
    print("wonder_card self-test OK (card=%d B, ram_script=%d B)" % (len(card), len(script)))


if __name__ == "__main__":
    _selftest()
