"""Wonder Card + delivery RAM-script authoring (the Mystery Gift payload).

Two byte-exact builders for the gift we hand the console:

  build_wonder_card(...)  -> 332-byte `struct WonderCard` [include/global.h:655], the object the
                             console saves and shows in the Mystery Gift menu. Must pass
                             ValidateWonderCard [src/mystery_gift.c:191] or SaveWonderCard rejects it.

  build_delivery_ram_script(item, flag)
                          -> raw FRLG event-script bytecode run by the in-game deliveryman
                             ("Mystery Gift Man", CableClub_EventScript_MysteryGiftMan) via
                             scrcmd 0xCF `trywondercardscript` [src/scrcmd.c:275]. It gives the
                             player an optional item with the standard fanfare + message, then a
                             level-50 Celebi with its configured moves and sets the card's receipt
                             flag, then
                             `end` (keeps the RAM script available for later deliveryman
                             interactions).

The console wraps our RAM-script bytes in `struct RamScriptData` and computes the checksum itself
(CLI_SAVE_RAM_SCRIPT -> InitRamScript_NoObjectEvent, mystery_gift_client.c:230); we only supply the
script body. IMPORTANT: the script must NOT contain pointers into itself (the RAM script is run as a
normal event script with no pointer relocation), so we use only immediate-operand commands. `giveitem`
is safe because it resolves its message through `callstd` (a ROM standard-script INDEX, not a pointer).
"""

from . import charmap
from .mystery_gift import (
    CARD_TYPE_GIFT, SEND_TYPE_DISALLOWED, WONDER_CARD_FLAG_OFFSET, NUM_WONDER_CARD_FLAGS,
    FLAG_WONDER_CARD_UNUSED_1,
)

# --- struct WonderCard layout [include/global.h:655-669], packed, little-endian ---------------
WONDER_CARD_TEXT_LENGTH = 40        # per text field
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
ITEM_ENIGMA_BERRY = 175          # LAST_BERRY_INDEX

# [include/constants/species.h:328]. ``iconSpecies`` controls the Pokémon icon
# shown on a Wonder Card; it does not affect the delivered item.
SPECIES_CLAYDOL = 319
SPECIES_CELEBI = 251

# [include/constants/moves.h]. The delivery script overwrites Celebi's four
# move slots in this exact order after ``givemon`` adds it to the party.
MOVE_LEECH_SEED = 73
MOVE_RECOVER = 105
MOVE_HEAL_BELL = 215
MOVE_SAFEGUARD = 219

# What the distributor hands out unless told otherwise.
#
# A plain `giveitem ITEM_ENIGMA_BERRY` is a normal, usable berry: GetBerryInfo
# [src/berry.c:996] only substitutes the save's custom berry when
# IsEnigmaBerryValid() passes, and otherwise falls back to the built-in "ENIGMA"
# entry in gBerries [src/berry.c:850]. Handing over a *custom* Enigma Berry (its
# own name, flavours and effect) is a different mechanism entirely - the
# mystery-event `setenigmaberry` command reached through CLI_RUN_MEVENT_SCRIPT -
# and is not what this delivery script does.
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
# The Celebi card has no item by default. Pass an item ID explicitly to include
# a repeatable ``giveitem`` reward in addition to Celebi.
DEFAULT_GIFT_ITEM = None


# --- event-script opcodes used by the delivery script [asm/macros/event.inc] ------------------
_OP_END = 0x02
_OP_CALLSTD = 0x09              # callstd <function:u8>
_OP_SETVAR_OR_COPY = 0x1A      # setorcopyvar <dest:u16> <src:u16>
_OP_SETFLAG = 0x29             # setflag <flag:u16>
_OP_FACEPLAYER = 0x5A
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

_VAR_0x8000 = 0x8000           # giveitem: item id
_VAR_0x8001 = 0x8001           # giveitem: amount
_VAR_RESULT = 0x800D            # getpartysize / givemon result
_STD_OBTAIN_ITEM = 0           # gStdScripts index [event_scripts.s:78] - "obtained the {ITEM}!" + fanfare
_COMPARE_EQ = 1
_PARTY_SIZE = 6
# ScriptSetMonMoveSlot uses the last party mon only when index > PARTY_SIZE;
# 6 itself is an out-of-bounds index in vanilla FRLG.
_LAST_PARTY_MON_INDEX = _PARTY_SIZE + 1
_RAM_SCRIPT_VIRTUAL_BASE = 0x08000000
# Unlike the Wonder Card's receipt flag, these flags are explicitly scoped to
# the saved card: SaveWonderCard -> ClearSavedWonderCardAndRelated ->
# ClearMysteryGiftFlags clears 0x3D8..0x3E7 before storing a replacement card.
# Keep DONE (0x3D8) available for scripts that use its conventional meaning.
_FLAG_REWARD_RECEIVED = 0x3D9  # FLAG_MYSTERY_GIFT_1

_TEXT_REWARD_RECEIVED = "{PLAYER} received a CELEBI\nfrom the deliveryman!"
_TEXT_PARTY_FULL = "Oh, your party appears to be full.\nPlease make room and come back!"
_TEXT_REWARD_ALREADY_RECEIVED = "Please look forward to future\nMYSTERY GIFTS!"


def _u16(v):
    return (v & 0xFFFF).to_bytes(2, "little")


def _setorcopyvar(dest, src):
    return bytes([_OP_SETVAR_OR_COPY]) + _u16(dest) + _u16(src)


def _givemon(species, level, item=0):
    """Encode `givemon species, level, item` with its three unused zero fields."""
    return (bytes([_OP_GIVEMON]) + _u16(species) + bytes([level]) + _u16(item)
            + b"\x00" * 9)


def _setmonmove(party_index, slot, move):
    return bytes([_OP_SETMONMOVE, party_index, slot]) + _u16(move)


def _script_text(text):
    """Encode a saved-script dialogue string with ``{PLAYER}`` expansion.

    ``charmap.encode`` intentionally only handles printable characters, while
    event scripts also need control bytes for the player-name placeholder,
    newlines, and the string terminator.
    """
    out = bytearray()
    lines = text.split("\n")
    for line_index, line in enumerate(lines):
        parts = line.split("{PLAYER}")
        for part_index, part in enumerate(parts):
            out += charmap.encode(part)
            if part_index < len(parts) - 1:
                out += b"\xFD\x01"  # {PLAYER}
        if line_index < len(lines) - 1:
            out += b"\xFE"          # CHAR_NEWLINE
    return bytes(out) + b"\xFF"      # EOS


def flag_for_flag_id(flag_id):
    """The receipt event flag a card flagId maps to (sReceivedGiftFlags[flagId-1000],
    mystery_gift.c:255). Only flagIds in [1000, 1000+20) are valid."""
    idx = flag_id - WONDER_CARD_FLAG_OFFSET
    if not (0 <= idx < NUM_WONDER_CARD_FLAGS):
        raise ValueError(f"card flagId {flag_id} out of range [1000, {1000 + NUM_WONDER_CARD_FLAGS})")
    # sReceivedGiftFlags[0..3] = AURORA(0x2A7), MYSTIC(0x2A8), OLD_SEA_MAP(0x2A9), UNUSED_1(0x2AA), ...
    return FLAG_WONDER_CARD_UNUSED_1 - 3 + idx


def build_delivery_ram_script(item=DEFAULT_GIFT_ITEM, flag=None, flag_id=None):
    """Build the deliveryman script for an optional item and Celebi reward.

    An explicitly supplied ``item`` is given on every interaction. A level-50
    Celebi with Leech Seed, Recover, Heal Bell, and Safeguard is given exactly
    once per Wonder Card. ``givemon`` gives Celebi the receiving player's OT
    and trainer ID. A dedicated Mystery Gift flag records the handout and is
    reset when a replacement Wonder Card is saved. ``setmonmove`` can modify
    only a party Pokémon, so a relocatable ``vgoto_if`` also skips the Celebi
    section when the party is already full; this avoids changing the moves of
    the player's existing last party member when ``givemon`` would use the PC.
    Each outcome displays its own dialogue before the deliveryman releases the
    player.

    Unlike ``endram``, ``end`` preserves the saved RAM script. Each later
    deliveryman interaction can therefore grant another reward when a party
    slot is free. Pass either ``flag`` directly or ``flag_id`` (the card's
    flagId) to derive it.
    """
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

    # Saved RAM scripts may not use ordinary absolute pointers.  ``setvaddress``
    # plus ``vgoto_if`` makes the target offset relative to this script's runtime
    # location [scrcmd.c:165-206].
    virtual_anchor = len(out)
    out += bytes([_OP_SETVADDRESS]) + _RAM_SCRIPT_VIRTUAL_BASE.to_bytes(4, "little")
    # An optional item remains repeatable, but Celebi is per-card. ``checkflag``
    # sets comparisonResult to FALSE/TRUE, which vgoto_if consumes directly.
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
    # For no-item cards, mark the Wonder Card received only once Celebi was
    # successfully added. Item-bearing cards already did so at item handout.
    if item is None:
        out += bytes([_OP_SETFLAG]) + _u16(flag)
    out += bytes([_OP_SETFLAG]) + _u16(_FLAG_REWARD_RECEIVED)

    def append_message_branch(text):
        """Append a vmessage/wait/release branch and return its text-pointer slot."""
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

    # The relative-address base is the address of the setvaddress opcode. All
    # branches and messages below use virtual addresses so the saved script may
    # live at any RAM address.
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
    """Encode one 40-byte Wonder Card text field (game charset, 0xFF-terminated + 0xFF pad)."""
    return charmap.encode(s or "", width=WONDER_CARD_TEXT_LENGTH, pad=0xFF)


def build_wonder_card(*, flag_id=1003, icon_species=1, id_number=0,
                      card_type=CARD_TYPE_GIFT, bg_type=0, send_type=SEND_TYPE_DISALLOWED,
                      max_stamps=0, title="", subtitle="", body=(), footer1="", footer2=""):
    """Build a 332-byte `struct WonderCard`. Defaults pass ValidateWonderCard: flagId != 0,
    type < 3, sendType in {0,1,2}, bgType < 8, maxStamps <= 7. flagId default 1003 -> the first
    unused receipt-flag slot (FLAG_WONDER_CARD_UNUSED_1), a clean receipt marker for a custom gift.
    `body` is up to 4 lines of <=39 chars each."""
    if flag_id == 0:
        raise ValueError("flagId 0 is rejected by ValidateWonderCard")
    if not (0 <= card_type < 3 and 0 <= bg_type < 8 and send_type in (0, 1, 2) and 0 <= max_stamps <= 7):
        raise ValueError("WonderCard field out of the range ValidateWonderCard accepts")
    flag_for_flag_id(flag_id)  # validate flagId range early

    bitfield = (card_type & 0x3) | ((bg_type & 0xF) << 2) | ((send_type & 0x3) << 6)
    out = bytearray()
    out += _u16(flag_id)                       # +0
    out += _u16(icon_species)                  # +2
    out += (id_number & 0xFFFFFFFF).to_bytes(4, "little")  # +4
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
    """A Wonder Card + deliveryman RAM script handing over Celebi and an optional item.

    Returns ``(card_bytes_332, ram_script_bytes)``. ``idNumber`` is zero so the
    Wonder Card viewer suppresses its top-right numeric label.
    """
    card = build_wonder_card(
        flag_id=flag_id, icon_species=DEFAULT_GIFT_ICON_SPECIES, id_number=0,
        title=title, subtitle=subtitle, body=body,
        footer1=DEFAULT_GIFT_SIGNATURE)
    script = build_delivery_ram_script(item=item, flag_id=flag_id)
    return card, script


def build_default_gift(**overrides):
    """The shipped payload: one level-50 Celebi per card and no item."""
    return build_berry_gift(**overrides)


def _selftest():
    card, script = build_default_gift()
    assert len(card) == WONDER_CARD_SIZE, len(card)
    # flagId, iconSpecies, bitfield readback
    assert int.from_bytes(card[0:2], "little") == 1003
    bitfield = card[8]
    assert (bitfield & 0x3) == CARD_TYPE_GIFT
    assert ((bitfield >> 2) & 0xF) < 8
    assert ((bitfield >> 6) & 0x3) == SEND_TYPE_DISALLOWED
    assert card[9] == 0  # maxStamps
    # RAM script: exact bytecode for the no-item, one-per-card Celebi reward
    # and its three distinct outcome messages.
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
