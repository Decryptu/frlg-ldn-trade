"""FRLG stores the card and RAM script persistently and appends each four-byte stamp to WonderCardMetadata;
a Mystery Event wrapper runs right after an accepted stamp to make its reward eligible."""

from dataclasses import dataclass

from . import buffer_script, charmap, ereader_trainer, wonder_news
from .mystery_gift import CARD_TYPE_STAMP
from .wonder_card import (
    SPECIES_CELEBI, SPECIES_CLAYDOL, WONDER_CARD_SIZE, build_wonder_card,
    flag_for_flag_id,
)


GIFT_SOLROCK_STAMP = "solrock-stamp"
GIFT_LUNATONE_STAMP = "lunatone-stamp"
STAMP_GIFT_CHOICES = (GIFT_SOLROCK_STAMP, GIFT_LUNATONE_STAMP)

STAMP_RALLY_FLAG_ID = 1006
SPECIES_LUNATONE = 348
SPECIES_SOLROCK = 349
SOLROCK_STAMP_ID = 1
LUNATONE_STAMP_ID = 2

VAR_MYSTERY_GIFT_1 = 0x40B6
VAR_MYSTERY_GIFT_2 = 0x40B7
FLAG_MYSTERY_GIFT_DONE = 0x3D8

STAMP_ABSENT = 0
STAMP_ELIGIBLE = 1
STAMP_RECEIVED = 2

SOLROCK_LEVEL = 30
LUNATONE_LEVEL = 30
CELEBI_LEVEL = 50

MON_CANT_GIVE = 2


@dataclass(frozen=True)
class MysteryGiftDistribution:
    card: bytes | None
    ram_script: bytes | None
    stamp: bytes | None = None
    activation_script: bytes | None = None
    install_activation_script: bytes | None = None
    trainer: bytes | None = None
    news: bytes | None = None
    # Bytecode for the second VM, run by CLI_RUN_MEVENT_SCRIPT [mystery_event.py].
    mevent: bytes | None = None
    # Four Easy Chat word ids the console must be holding in its Poke Mart questionnaire before
    # anything is sent [SVR_CHECK_QUESTIONNAIRE, mg_server.py], and what a wrong one reads.
    questionnaire: tuple | None = None
    denied_message: str | None = None
    # Native ARM code, run by CLI_RUN_BUFFER_SCRIPT [buffer_script.py], and what its answer is
    # checked against (mg_server.BUFFER_EXPECT_TRAINER_ID, a u32, or None for "any answer").
    buffer_code: bytes | None = None
    buffer_expect: object | None = None
    # Set when the payload repoints the console's outgoing message: how many bytes of console
    # memory MG_LINKID_RESPONSE will carry instead of the usual 4.
    buffer_dump_size: int | None = None
    # memory-scan: those bytes are a hit table, not a region, so the log decodes them.
    buffer_scan: bool = False

    def __post_init__(self):
        if self.buffer_code is not None:
            # Not a gift: nothing is sent, nothing is saved, and no Wonder Card is involved, so a
            # buffer script travels as alone as Wonder News does.
            object.__setattr__(self, "buffer_code", bytes(self.buffer_code))
            buffer_script.validate(self.buffer_code)
            if self.card is not None or self.ram_script is not None:
                raise ValueError("a buffer script distribution carries no card or RAM script")
            if any(other is not None for other in
                   (self.news, self.stamp, self.trainer, self.mevent)):
                raise ValueError(
                    "a buffer script cannot share a session with news, a stamp, a visiting "
                    "trainer or a Mystery Event script")
            return
        if self.news is not None:
            # Wonder News travels alone: it has no flagId, no metadata and no delivery script,
            # so a news distribution carries neither card nor RAM script.
            object.__setattr__(self, "news", bytes(self.news))
            if self.card is not None or self.ram_script is not None:
                raise ValueError("a Wonder News distribution carries no card or RAM script")
            if len(self.news) != wonder_news.WONDER_NEWS_SIZE:
                raise ValueError(
                    f"Wonder News must be {wonder_news.WONDER_NEWS_SIZE} bytes")
            if not wonder_news.validate(self.news):
                raise ValueError("news id 0 fails ValidateWonderNews")
            if (self.stamp is not None or self.trainer is not None
                    or self.mevent is not None):
                raise ValueError(
                    "Wonder News cannot carry a stamp, a visiting trainer or a Mystery Event")
            return
        if self.card is None or self.ram_script is None:
            raise ValueError("a Mystery Gift distribution needs a card and a RAM script")
        object.__setattr__(self, "card", bytes(self.card))
        object.__setattr__(self, "ram_script", bytes(self.ram_script))
        if len(self.card) != WONDER_CARD_SIZE:
            raise ValueError(f"Wonder Card must be {WONDER_CARD_SIZE} bytes")
        extras = (self.stamp, self.activation_script,
                  self.install_activation_script)
        if any(value is not None for value in extras):
            if any(value is None for value in extras):
                raise ValueError("stamp distributions require both activation scripts")
            object.__setattr__(self, "stamp", bytes(self.stamp))
            object.__setattr__(self, "activation_script", bytes(self.activation_script))
            object.__setattr__(self, "install_activation_script",
                               bytes(self.install_activation_script))
            if len(self.stamp) != 4:
                raise ValueError("a stamp must be exactly four bytes")
        if self.trainer is not None:
            object.__setattr__(self, "trainer", bytes(self.trainer))
            if len(self.trainer) != ereader_trainer.TRAINER_SIZE:
                raise ValueError(
                    f"a visiting trainer must be {ereader_trainer.TRAINER_SIZE} bytes")
        if self.mevent is not None:
            object.__setattr__(self, "mevent", bytes(self.mevent))
            if self.stamp is not None or self.trainer is not None:
                raise ValueError(
                    "a Mystery Event cannot share a session with a stamp rally or a visiting "
                    "trainer")

    @property
    def is_stamp(self):
        return self.stamp is not None

    @property
    def has_trainer(self):
        return self.trainer is not None

    @property
    def is_news(self):
        return self.news is not None

    @property
    def has_mevent(self):
        return self.mevent is not None

    @property
    def is_gated(self):
        return self.questionnaire is not None


def build_stamp_rally_card(*, flag_id=STAMP_RALLY_FLAG_ID):
    return build_wonder_card(
        flag_id=flag_id,
        icon_species=SPECIES_CLAYDOL,
        card_type=CARD_TYPE_STAMP,
        max_stamps=2,
        title="SUN AND MOON RALLY",
        subtitle="Collect both stamps!",
        body=(
            "Collect SOLROCK and LUNATONE",
            "stamps from event hosts.",
            "Claim each Pokemon, then",
            "receive a special grand prize!",
        ),
        footer1="frlg-ldn-trade",
    )


def _u16(value):
    return int(value).to_bytes(2, "little")


def _stamp(species, stamp_id):
    return _u16(species) + _u16(stamp_id)


def _script_text(text):
    out = bytearray()
    lines = text.split("\n")
    for line_index, line in enumerate(lines):
        out += charmap.encode(line)
        if line_index < len(lines) - 1:
            out.append(0xFE)
    out.append(0xFF)
    return bytes(out)


# Field-event bytecode [asm/macros/event.inc].
_OP_END = 0x02
_OP_SETVAR = 0x16
_OP_COMPARE_VAR_TO_VALUE = 0x21
_OP_SETFLAG = 0x29
_OP_CLEARFLAG = 0x2A
_OP_CHECKFLAG = 0x2B
_OP_FACEPLAYER = 0x5A
_OP_WAITMESSAGE = 0x66
_OP_LOCK = 0x6A
_OP_WAITBUTTONPRESS = 0x6D
_OP_RELEASE = 0x6C
_OP_GIVEMON = 0x79
_OP_SETVADDRESS = 0xB8
_OP_VGOTO = 0xB9
_OP_VGOTO_IF = 0xBB
_OP_VMESSAGE = 0xBD

_COMPARE_EQ = 1
_COMPARE_NE = 5
_VAR_RESULT = 0x800D
_RAM_SCRIPT_VIRTUAL_BASE = 0x08000000


class _FieldScriptBuilder:
    def __init__(self):
        self.code = bytearray()
        self.labels = {}
        self.branch_fixups = []
        self.message_fixups = []
        self.messages = []

    def label(self, name):
        if name in self.labels:
            raise ValueError(f"duplicate script label {name}")
        self.labels[name] = len(self.code)

    def emit(self, data):
        self.code += bytes(data)

    def vgoto(self, label):
        self.code.append(_OP_VGOTO)
        self.branch_fixups.append((len(self.code), label))
        self.code += b"\x00" * 4

    def vgoto_if(self, condition, label):
        self.code += bytes([_OP_VGOTO_IF, condition])
        self.branch_fixups.append((len(self.code), label))
        self.code += b"\x00" * 4

    def message(self, text):
        self.code.append(_OP_VMESSAGE)
        self.message_fixups.append((len(self.code), len(self.messages)))
        self.code += b"\x00" * 4
        self.code += bytes([_OP_WAITMESSAGE, _OP_WAITBUTTONPRESS])
        self.messages.append(_script_text(text))

    def finish(self, *, anchor=0):
        code = bytearray(self.code)
        message_offsets = []
        offset = len(code)
        for message in self.messages:
            message_offsets.append(offset)
            offset += len(message)

        def virtual(offset_):
            return _RAM_SCRIPT_VIRTUAL_BASE + offset_ - anchor

        for position, label in self.branch_fixups:
            code[position:position + 4] = virtual(self.labels[label]).to_bytes(4, "little")
        for position, message_index in self.message_fixups:
            code[position:position + 4] = virtual(
                message_offsets[message_index]).to_bytes(4, "little")
        return bytes(code) + b"".join(self.messages)


def _setvar(variable, value):
    return bytes([_OP_SETVAR]) + _u16(variable) + _u16(value)


def _compare(variable, value):
    return bytes([_OP_COMPARE_VAR_TO_VALUE]) + _u16(variable) + _u16(value)


def _setflag(flag):
    return bytes([_OP_SETFLAG]) + _u16(flag)


def _givemon(species, level):
    return (bytes([_OP_GIVEMON]) + _u16(species) + bytes([level])
            + _u16(0) + b"\x00" * 9)


def build_stamp_rally_delivery_script(*, flag_id=STAMP_RALLY_FLAG_ID):
    receipt_flag = flag_for_flag_id(flag_id)
    b = _FieldScriptBuilder()
    b.emit(bytes([_OP_SETVADDRESS])
           + _RAM_SCRIPT_VIRTUAL_BASE.to_bytes(4, "little"))
    b.emit(bytes([_OP_LOCK, _OP_FACEPLAYER]))

    b.emit(bytes([_OP_CHECKFLAG]) + _u16(FLAG_MYSTERY_GIFT_DONE))
    b.vgoto_if(_COMPARE_EQ, "completed")
    b.emit(_compare(VAR_MYSTERY_GIFT_1, STAMP_ELIGIBLE))
    b.vgoto_if(_COMPARE_EQ, "give_solrock")
    b.emit(_compare(VAR_MYSTERY_GIFT_2, STAMP_ELIGIBLE))
    b.vgoto_if(_COMPARE_EQ, "give_lunatone")
    b.vgoto("evaluate_final")

    b.label("give_solrock")
    b.message("Your SOLROCK STAMP checks out!\nPlease accept this SOLROCK.")
    b.emit(_givemon(SPECIES_SOLROCK, SOLROCK_LEVEL))
    b.emit(_compare(_VAR_RESULT, MON_CANT_GIVE))
    b.vgoto_if(_COMPARE_EQ, "storage_full")
    b.emit(_setvar(VAR_MYSTERY_GIFT_1, STAMP_RECEIVED))
    b.emit(_compare(VAR_MYSTERY_GIFT_2, STAMP_ELIGIBLE))
    b.vgoto_if(_COMPARE_EQ, "give_lunatone")
    b.vgoto("evaluate_final")

    b.label("give_lunatone")
    b.message("Your LUNATONE STAMP checks out!\nPlease accept this LUNATONE.")
    b.emit(_givemon(SPECIES_LUNATONE, LUNATONE_LEVEL))
    b.emit(_compare(_VAR_RESULT, MON_CANT_GIVE))
    b.vgoto_if(_COMPARE_EQ, "storage_full")
    b.emit(_setvar(VAR_MYSTERY_GIFT_2, STAMP_RECEIVED))

    b.label("evaluate_final")
    b.emit(_compare(VAR_MYSTERY_GIFT_1, STAMP_RECEIVED))
    b.vgoto_if(_COMPARE_NE, "status")
    b.emit(_compare(VAR_MYSTERY_GIFT_2, STAMP_RECEIVED))
    b.vgoto_if(_COMPARE_NE, "status")
    b.message("Both STAMP rewards are yours!\nPlease accept the grand prize.")
    b.emit(_givemon(SPECIES_CELEBI, CELEBI_LEVEL))
    b.emit(_compare(_VAR_RESULT, MON_CANT_GIVE))
    b.vgoto_if(_COMPARE_EQ, "storage_full")
    b.emit(_setflag(FLAG_MYSTERY_GIFT_DONE))
    b.emit(_setflag(receipt_flag))
    b.message("Congratulations! CELEBI is yours!\nThe STAMP RALLY is complete.")
    b.vgoto("exit")

    b.label("status")
    b.emit(_compare(VAR_MYSTERY_GIFT_1, STAMP_RECEIVED))
    b.vgoto_if(_COMPARE_EQ, "wait_lunatone")
    b.emit(_compare(VAR_MYSTERY_GIFT_2, STAMP_RECEIVED))
    b.vgoto_if(_COMPARE_EQ, "wait_solrock")
    b.message("Welcome to the STAMP RALLY!\nBring me a SOLROCK or LUNATONE STAMP.")
    b.vgoto("exit")

    b.label("wait_lunatone")
    b.message("SOLROCK is yours!\nBring me the LUNATONE STAMP.")
    b.vgoto("exit")

    b.label("wait_solrock")
    b.message("LUNATONE is yours!\nBring me the SOLROCK STAMP.")
    b.vgoto("exit")

    b.label("completed")
    b.emit(_setflag(receipt_flag))
    b.message("You completed the STAMP RALLY!\nThank you for participating.")
    b.vgoto("exit")

    b.label("storage_full")
    b.message("Your party and PC BOXES are full.\nPlease make room and come back!")

    b.label("exit")
    b.emit(bytes([_OP_RELEASE, _OP_END]))
    result = b.finish(anchor=0)
    if len(result) > 995:
        raise ValueError(f"Stamp Rally RAM script is too large ({len(result)} bytes)")
    return result


# Mystery Event opcodes [data/mystery_event_script_cmd_table.s].
_ME_RUNSCRIPT = 5
_ME_END = 2


def build_stamp_activation_script(state_var, *, flag_id=STAMP_RALLY_FLAG_ID,
                                  install=False):
    """``runscript`` relocates its zero-based pointer against the received buffer (CLI_RUN_MEVENT_SCRIPT)."""
    if state_var not in (VAR_MYSTERY_GIFT_1, VAR_MYSTERY_GIFT_2):
        raise ValueError("state_var must be a Stamp Rally state variable")
    embedded = bytearray()
    if install:
        embedded += bytes([_OP_CLEARFLAG]) + _u16(flag_for_flag_id(flag_id))
    embedded += _setvar(state_var, STAMP_ELIGIBLE)
    embedded.append(_OP_END)
    embedded_offset = 6            # runscript + u32 pointer + mevent end
    return (bytes([_ME_RUNSCRIPT]) + embedded_offset.to_bytes(4, "little")
            + bytes([_ME_END]) + bytes(embedded))


def _build_stamp_event(species, stamp_id, state_var, *, flag_id):
    return MysteryGiftDistribution(
        card=build_stamp_rally_card(flag_id=flag_id),
        ram_script=build_stamp_rally_delivery_script(flag_id=flag_id),
        stamp=_stamp(species, stamp_id),
        activation_script=build_stamp_activation_script(
            state_var, flag_id=flag_id, install=False),
        install_activation_script=build_stamp_activation_script(
            state_var, flag_id=flag_id, install=True),
    )


def build_solrock_stamp_event(*, flag_id=STAMP_RALLY_FLAG_ID):
    return _build_stamp_event(
        SPECIES_SOLROCK, SOLROCK_STAMP_ID, VAR_MYSTERY_GIFT_1,
        flag_id=flag_id)


def build_lunatone_stamp_event(*, flag_id=STAMP_RALLY_FLAG_ID):
    return _build_stamp_event(
        SPECIES_LUNATONE, LUNATONE_STAMP_ID, VAR_MYSTERY_GIFT_2,
        flag_id=flag_id)
