"""Saved state used by compiled gifts: VAR_MYSTERY_GIFT_1 = ordinary/rally-completion stage cursor,
VAR_MYSTERY_GIFT_2..7 = stamp-slot cursors (0 absent, 1 activated, +1 per stage), FLAG_MYSTERY_GIFT_DONE = one-shot."""

import re
from dataclasses import dataclass
from typing import TypeAlias

from . import charmap, ereader_trainer, mystery_event, rom_map
from .mystery_gift import (
    CARD_TYPE_GIFT,
    CARD_TYPE_STAMP,
    SEND_TYPE_ALLOWED,
    SEND_TYPE_ALLOWED_ALWAYS,
    SEND_TYPE_DISALLOWED,
)
from .stamp_rally import MysteryGiftDistribution
from .wonder_card import build_wonder_card, flag_for_flag_id
from .scrcmd import (
    COMPARE_EQ as _COMPARE_EQ, OP_ADDVAR as _OP_ADDVAR,
    OP_BUFFERNUMBERSTRING as _OP_BUFFERNUMBERSTRING, OP_CALLSTD as _OP_CALLSTD,
    OP_CHECKFLAG as _OP_CHECKFLAG, OP_CHECKITEMSPACE as _OP_CHECKITEMSPACE,
    OP_CLEARFLAG as _OP_CLEARFLAG, OP_CLOSEMESSAGE as _OP_CLOSEMESSAGE,
    OP_COMPARE_VAR_TO_VALUE as _OP_COMPARE_VAR_TO_VALUE, OP_COPYBYTE as _OP_COPYBYTE,
    OP_CREATEVOBJECT as _OP_CREATEVOBJECT, OP_DELAY as _OP_DELAY,
    OP_DOWILDBATTLE as _OP_DOWILDBATTLE, OP_END as _OP_END, OP_FACEPLAYER as _OP_FACEPLAYER,
    OP_GETPARTYSIZE as _OP_GETPARTYSIZE, OP_GETPLAYERXY as _OP_GETPLAYERXY,
    OP_GIVEEGG as _OP_GIVEEGG, OP_GIVEMON as _OP_GIVEMON, OP_LOCK as _OP_LOCK,
    OP_PLAYFANFARE as _OP_PLAYFANFARE, OP_RELEASE as _OP_RELEASE, OP_SETFLAG as _OP_SETFLAG,
    OP_SETMONMETLOCATION as _OP_SETMONMETLOCATION,
    OP_SETMONMODERNFATEFULENCOUNTER as _OP_SETMONMODERNFATEFULENCOUNTER,
    OP_SETMONMOVE as _OP_SETMONMOVE, OP_SETVADDRESS as _OP_SETVADDRESS, OP_SETVAR as _OP_SETVAR,
    OP_SETVAR_OR_COPY as _OP_SETVAR_OR_COPY, OP_SETWILDBATTLE as _OP_SETWILDBATTLE,
    OP_SPECIAL as _OP_SPECIAL, OP_SPECIALVAR as _OP_SPECIALVAR, OP_VGOTO as _OP_VGOTO,
    OP_VGOTO_IF as _OP_VGOTO_IF, OP_VMESSAGE as _OP_VMESSAGE,
    OP_WAITBUTTONPRESS as _OP_WAITBUTTONPRESS, OP_WAITMESSAGE as _OP_WAITMESSAGE,
    RAM_SCRIPT_VIRTUAL_BASE as _RAM_SCRIPT_VIRTUAL_BASE, STD_OBTAIN_ITEM as _STD_OBTAIN_ITEM,
    VAR_0x8000 as _VAR_0x8000, VAR_0x8001 as _VAR_0x8001, VAR_0x8002 as _VAR_0x8002,
    VAR_0x8003 as _VAR_0x8003, VAR_PLAYER_X as _VAR_PLAYER_X, VAR_PLAYER_Y as _VAR_PLAYER_Y,
    VAR_RESULT as _VAR_RESULT,
)
from .mystery_event import ME_END as _ME_END, ME_RUNSCRIPT as _ME_RUNSCRIPT


# Card-scoped FRLG event state [include/constants/{vars,flags}.h].
VAR_MYSTERY_GIFT_1 = 0x40B6
VAR_MYSTERY_GIFT_2 = 0x40B7
VAR_MYSTERY_GIFT_3 = 0x40B8
VAR_MYSTERY_GIFT_4 = 0x40B9
VAR_MYSTERY_GIFT_5 = 0x40BA
VAR_MYSTERY_GIFT_6 = 0x40BB
VAR_MYSTERY_GIFT_7 = 0x40BC
VAR_MYSTERY_GIFT_SLOT_VARS = (
    VAR_MYSTERY_GIFT_2,
    VAR_MYSTERY_GIFT_3,
    VAR_MYSTERY_GIFT_4,
    VAR_MYSTERY_GIFT_5,
    VAR_MYSTERY_GIFT_6,
    VAR_MYSTERY_GIFT_7,
)
FLAG_MYSTERY_GIFT_DONE = 0x3D8

MAX_STAMP_SLOTS = 6
MAX_CURSOR = 0xFFFF
MAX_RAM_SCRIPT_SIZE = 995
MAX_POKEMON_SPECIES = 411       # NUM_SPECIES excludes SPECIES_EGG (412)
MAX_ICON_SPECIES = 412
MAX_ITEM = 374                  # ITEMS_COUNT - 1
MAX_MOVE = 354                  # MOVES_COUNT - 1
MAX_OBJECT_GRAPHICS = 151       # NUM_OBJ_EVENT_GFX - 1
MIN_SAVED_VAR = 0x4000
MAX_SAVED_VAR = 0x40FF
MIN_SPECIAL_VAR = 0x8000
MAX_SPECIAL_VAR = 0x8011
MIN_FLAG = 0x0001
MAX_FLAG = 0x08FF

SHARE_NEVER = "never"
SHARE_ONCE = "once"
SHARE_ALWAYS = "always"
SPECIAL_HAS_ALL_KANTO_MONS = 335
SPECIAL_START_LEGENDARY_BATTLE = 312
SHAREABLE_STATES = (SHARE_NEVER, SHARE_ONCE, SHARE_ALWAYS)
_SHAREABLE_SEND_TYPES = {
    SHARE_NEVER: SEND_TYPE_DISALLOWED,
    SHARE_ONCE: SEND_TYPE_ALLOWED,
    SHARE_ALWAYS: SEND_TYPE_ALLOWED_ALWAYS,
}

MON_CANT_GIVE = 2
PARTY_SIZE = 6
LAST_PARTY_MON_INDEX = PARTY_SIZE + 1

_DEFAULT_NO_ROOM_MESSAGE = "No room! Make space, then\ncome back."
DEFAULT_BAG_FULL_MESSAGE = _DEFAULT_NO_ROOM_MESSAGE
DEFAULT_STORAGE_FULL_MESSAGE = _DEFAULT_NO_ROOM_MESSAGE
DEFAULT_PARTY_FULL_MESSAGE = _DEFAULT_NO_ROOM_MESSAGE
DEFAULT_COMPLETED_MESSAGE = (
    "You already received this MYSTERY GIFT.\nPlease look forward to future gifts!")


class GiftValidationError(ValueError):
    def __init__(self, path, message):
        self.path = str(path)
        self.message = str(message)
        super().__init__(f"{self.path}: {self.message}")


@dataclass(frozen=True)
class WonderCardSpec:
    icon_species: int
    title: str
    subtitle: str = ""
    body: tuple[str, ...] = ()
    footer1: str = ""
    footer2: str = ""
    # 0 keeps the default ``flag_id % 100`` display number.
    id_number: int = 0
    bg_type: int = 0
    send_type: int = SEND_TYPE_DISALLOWED
    default_flag_id: int = 1003

    def __post_init__(self):
        object.__setattr__(self, "body",
                           (self.body,) if isinstance(self.body, str) else tuple(self.body))


@dataclass(frozen=True)
class Message:
    text: str


@dataclass(frozen=True)
class GiveItem:
    item: int
    quantity: int = 1
    failure_message: str | None = None


@dataclass(frozen=True)
class GivePokemon:
    species: int
    level: int
    held_item: int = 0
    moves: tuple[int, ...] = ()
    fateful_encounter: bool = False
    failure_message: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "moves", tuple(self.moves))


@dataclass(frozen=True)
class GiveEgg:
    species: int
    moves: tuple[int, ...] = ()
    fateful_encounter: bool = False
    failure_message: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "moves", tuple(self.moves))


@dataclass(frozen=True)
class RelativeToPlayer:
    dx: int = 0
    dy: int = 0


@dataclass(frozen=True)
class MapPosition:
    x: int
    y: int


@dataclass(frozen=True)
class ShowSprite:
    graphics_id: int
    position: RelativeToPlayer | MapPosition
    direction: int = 3
    elevation: int = 3
    delay_frames: int = 0


@dataclass(frozen=True)
class BattlePokemon:
    species: int
    level: int
    held_item: int = 0


@dataclass(frozen=True)
class BattleLegendary:
    species: int
    level: int
    held_item: int = 0


@dataclass(frozen=True)
class RequireSpecialResult:
    special_id: int
    expected: int
    failure_message: str


@dataclass(frozen=True)
class SetVar:
    variable: int
    value: int


@dataclass(frozen=True)
class Exit:
    pass


@dataclass(frozen=True)
class VarEquals:
    variable: int
    value: int


@dataclass(frozen=True)
class FlagSet:
    flag: int


@dataclass(frozen=True)
class Not:
    condition: "Condition"


@dataclass(frozen=True)
class AllOf:
    conditions: tuple["Condition", ...]

    def __post_init__(self):
        object.__setattr__(self, "conditions", tuple(self.conditions))


@dataclass(frozen=True)
class AnyOf:
    conditions: tuple["Condition", ...]

    def __post_init__(self):
        object.__setattr__(self, "conditions", tuple(self.conditions))


Condition: TypeAlias = VarEquals | FlagSet | Not | AllOf | AnyOf
GiftAction: TypeAlias = (
    Message | GiveItem | GivePokemon | GiveEgg | ShowSprite
    | BattlePokemon | BattleLegendary | RequireSpecialResult | SetVar | Exit)
_FALLIBLE_REWARD_TYPES = (GiveItem, GivePokemon, GiveEgg)
_BATTLE_TYPES = (BattlePokemon, BattleLegendary)


@dataclass(frozen=True, init=False)
class DeliveryStage:
    actions: tuple[GiftAction, ...]
    condition: Condition | None

    def __init__(self, *positional_actions, actions=None, condition=None):
        if actions is not None and positional_actions:
            raise TypeError("pass DeliveryStage actions positionally or by keyword, not both")
        selected = actions if actions is not None else positional_actions
        if (actions is None and len(selected) == 1
                and isinstance(selected[0], (tuple, list))):
            selected = selected[0]
        object.__setattr__(self, "actions", tuple(selected))
        object.__setattr__(self, "condition", condition)


@dataclass(frozen=True)
class DeliveryPlan:
    pre_stages: tuple[DeliveryStage, ...] = ()
    delivery: tuple[DeliveryStage, ...] = ()
    post_stages: tuple[DeliveryStage, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "pre_stages", tuple(self.pre_stages))
        object.__setattr__(self, "delivery", tuple(self.delivery))
        object.__setattr__(self, "post_stages", tuple(self.post_stages))


@dataclass(frozen=True)
class GiftSpec:
    repeatable: bool = False
    shareable: str = SHARE_NEVER


@dataclass(frozen=True)
class StampSlot:
    slug: str
    stamp_species: int
    stamp_id: int
    delivery: DeliveryPlan


@dataclass(frozen=True)
class StampRallySpec:
    slots: tuple[StampSlot, ...]
    completion: DeliveryPlan

    def __post_init__(self):
        object.__setattr__(self, "slots", tuple(self.slots))


EventSpec: TypeAlias = GiftSpec | StampRallySpec


@dataclass(frozen=True)
class WonderGift:
    slug: str
    card: WonderCardSpec
    intro_message: str
    event: EventSpec
    delivery: DeliveryPlan
    completed_message: str = DEFAULT_COMPLETED_MESSAGE
    # A packed BattleTowerEReaderTrainer to push in the same session [ereader_trainer.py]; the
    # card and its script are delivered exactly as for any other gift.
    trainer: bytes | None = None
    # Assembled Mystery Event bytecode [mystery_event.py], run by the console at the Mystery Gift
    # menu right after the card is saved. Its status comes back to us as MG_LINKID_RESPONSE.
    mevent: bytes | None = None


def _fail(path, message):
    raise GiftValidationError(path, message)


def _validate_int(value, low, high, path, description):
    if type(value) is not int or not low <= value <= high:
        _fail(path, f"{description} must be an integer from {low} through {high}")


def _validate_slug(slug, path):
    if not isinstance(slug, str) or not slug:
        _fail(path, "slug must be a nonempty string")
    if any(not (char.islower() or char.isdigit() or char == "-") for char in slug):
        _fail(path, "slug may contain only lowercase letters, digits, and hyphens")
    if slug[0] == "-" or slug[-1] == "-" or "--" in slug:
        _fail(path, "slug may not start/end with or repeat a hyphen")


def _validate_plain_text(text, path, *, max_encoded=None):
    if not isinstance(text, str):
        _fail(path, "text must be a string")
    encoded = charmap.encode(text)
    if charmap.decode(encoded) != text:
        _fail(path, "text contains unsupported Gen III characters")
    if max_encoded is not None and len(encoded) > max_encoded:
        _fail(path, f"text encodes to {len(encoded)} bytes; maximum is {max_encoded}")


# The placeholders the field text engine substitutes at print time. 0xFD introduces one and the
# byte after it selects the source [decomp:charmap.txt:334]; STR_VAR_1..3 are gStringVar1..3, which
# `buffernumberstring` writes a decimal number into [ScrCmd_buffernumberstring, src/scrcmd.c:1678].
# {PLAYER} was the only one supported until the seed-reading script needed to print a number.
MESSAGE_TOKENS = {
    "{PLAYER}": b"\xFD\x01",
    "{STR_VAR_1}": b"\xFD\x02",
    "{STR_VAR_2}": b"\xFD\x03",
    "{STR_VAR_3}": b"\xFD\x04",
}
_TOKEN_RE = re.compile("(" + "|".join(re.escape(token) for token in MESSAGE_TOKENS) + ")")


def _validate_message(text, path):
    if not isinstance(text, str) or not text:
        _fail(path, "message must be a nonempty string")
    without_tokens = _TOKEN_RE.sub("", text)
    if "{" in without_tokens or "}" in without_tokens:
        _fail(path, "the supported message tokens are "
                    + ", ".join(sorted(MESSAGE_TOKENS)))
    for line in without_tokens.split("\n"):
        _validate_plain_text(line, path)


def _validate_card(card, path, *, flag_id):
    if not isinstance(card, WonderCardSpec):
        _fail(path, "card must be a WonderCardSpec")
    _validate_int(card.icon_species, 1, MAX_ICON_SPECIES,
                  f"{path}.icon_species", "icon species")
    _validate_int(card.id_number, 0, 0xFFFFFFFF, f"{path}.id_number", "card ID")
    _validate_int(card.bg_type, 0, 7, f"{path}.bg_type", "background type")
    if card.send_type not in (0, 1, 2):
        _fail(f"{path}.send_type", "send type must be 0, 1, or 2")
    try:
        flag_for_flag_id(flag_id)
    except (TypeError, ValueError) as exc:
        _fail(f"{path}.default_flag_id", str(exc))
    for name in ("title", "subtitle", "footer1", "footer2"):
        _validate_plain_text(getattr(card, name), f"{path}.{name}", max_encoded=39)
    if len(card.body) > 4:
        _fail(f"{path}.body", "Wonder Card body has at most four lines")
    for index, line in enumerate(card.body):
        _validate_plain_text(line, f"{path}.body[{index}]", max_encoded=39)


def _validate_position(position, path):
    if isinstance(position, RelativeToPlayer):
        _validate_int(position.dx, -0x8000, 0x7FFF, f"{path}.dx", "relative x")
        _validate_int(position.dy, -0x8000, 0x7FFF, f"{path}.dy", "relative y")
    elif isinstance(position, MapPosition):
        # Script operands >= 0x4000 are read as variable IDs.
        _validate_int(position.x, 0, 0x3FFF, f"{path}.x", "map x")
        _validate_int(position.y, 0, 0x3FFF, f"{path}.y", "map y")
    else:
        _fail(path, "position must be RelativeToPlayer or MapPosition")


def _validate_action(action, path):
    if isinstance(action, Message):
        _validate_message(action.text, f"{path}.text")
    elif isinstance(action, GiveItem):
        _validate_int(action.item, 1, MAX_ITEM, f"{path}.item", "item")
        _validate_int(action.quantity, 1, 0xFFFF, f"{path}.quantity", "quantity")
        if action.failure_message is not None:
            _validate_message(action.failure_message, f"{path}.failure_message")
    elif isinstance(action, GivePokemon):
        _validate_int(action.species, 1, MAX_POKEMON_SPECIES,
                      f"{path}.species", "species")
        _validate_int(action.level, 1, 100, f"{path}.level", "level")
        _validate_int(action.held_item, 0, MAX_ITEM,
                      f"{path}.held_item", "held item")
        if len(action.moves) > 4:
            _fail(f"{path}.moves", "a Pokémon may define at most four moves")
        for index, move in enumerate(action.moves):
            _validate_int(move, 1, MAX_MOVE, f"{path}.moves[{index}]", "move")
        if action.failure_message is not None:
            _validate_message(action.failure_message, f"{path}.failure_message")
    elif isinstance(action, GiveEgg):
        _validate_int(action.species, 1, MAX_POKEMON_SPECIES,
                      f"{path}.species", "species")
        if len(action.moves) > 4:
            _fail(f"{path}.moves", "an egg may define at most four moves")
        for index, move in enumerate(action.moves):
            _validate_int(move, 1, MAX_MOVE, f"{path}.moves[{index}]", "move")
        if action.failure_message is not None:
            _validate_message(action.failure_message, f"{path}.failure_message")
    elif isinstance(action, ShowSprite):
        _validate_int(action.graphics_id, 0, MAX_OBJECT_GRAPHICS,
                      f"{path}.graphics_id", "graphics ID")
        _validate_position(action.position, f"{path}.position")
        _validate_int(action.direction, 0, 8, f"{path}.direction", "direction")
        _validate_int(action.elevation, 0, 15, f"{path}.elevation", "elevation")
        _validate_int(action.delay_frames, 0, 0xFFFF,
                      f"{path}.delay_frames", "delay")
    elif isinstance(action, _BATTLE_TYPES):
        _validate_int(action.species, 1, MAX_POKEMON_SPECIES,
                      f"{path}.species", "species")
        _validate_int(action.level, 1, 100, f"{path}.level", "level")
        _validate_int(action.held_item, 0, MAX_ITEM,
                      f"{path}.held_item", "held item")
    elif isinstance(action, RequireSpecialResult):
        _validate_int(action.special_id, 0, 0xFFFF,
                      f"{path}.special_id", "special ID")
        _validate_int(action.expected, 0, 0xFFFF,
                      f"{path}.expected", "expected result")
        _validate_message(action.failure_message, f"{path}.failure_message")
    elif isinstance(action, SetVar):
        _validate_variable_id(action.variable, f"{path}.variable")
        _validate_int(action.value, 0, 0xFFFF, f"{path}.value", "value")
    elif isinstance(action, Exit):
        return
    else:
        _fail(path, f"unsupported action type {type(action).__name__}")


def _validate_variable_id(variable, path):
    if (type(variable) is not int
            or not (MIN_SAVED_VAR <= variable <= MAX_SAVED_VAR
                    or MIN_SPECIAL_VAR <= variable <= MAX_SPECIAL_VAR)):
        _fail(path, "variable must be a saved variable 0x4000..0x40FF "
              "or special variable 0x8000..0x8011")


def _validate_condition(condition, path):
    if isinstance(condition, VarEquals):
        _validate_variable_id(condition.variable, f"{path}.variable")
        _validate_int(condition.value, 0, 0xFFFF, f"{path}.value", "value")
    elif isinstance(condition, FlagSet):
        _validate_int(condition.flag, MIN_FLAG, MAX_FLAG, f"{path}.flag", "flag")
    elif isinstance(condition, Not):
        _validate_condition(condition.condition, f"{path}.condition")
    elif isinstance(condition, (AllOf, AnyOf)):
        if not condition.conditions:
            _fail(f"{path}.conditions", "boolean condition group must not be empty")
        for index, child in enumerate(condition.conditions):
            _validate_condition(child, f"{path}.conditions[{index}]")
    else:
        _fail(path, f"unsupported condition type {type(condition).__name__}")


def _plan_parts(plan):
    return (
        ("pre_stages", plan.pre_stages),
        ("delivery", plan.delivery),
        ("post_stages", plan.post_stages),
    )


def _effective_stages(*parts):
    return tuple(entry for part in parts for entry in part)


def _validate_plan_shape(plan, path):
    if not isinstance(plan, DeliveryPlan):
        _fail(path, "delivery must be a DeliveryPlan")
    result = []
    for part_name, stages in _plan_parts(plan):
        for stage_index, stage in enumerate(stages):
            stage_path = f"{path}.{part_name}[{stage_index}]"
            result.append((stage, stage_path))
            if not isinstance(stage, DeliveryStage):
                _fail(stage_path, "stage must be a DeliveryStage")
            if not stage.actions:
                _fail(stage_path, "delivery stage must contain at least one action")
            if stage.condition is not None:
                _validate_condition(stage.condition, f"{stage_path}.condition")
            fallible = sum(isinstance(action, _FALLIBLE_REWARD_TYPES)
                           for action in stage.actions)
            if fallible > 1:
                _fail(stage_path, "a stage may contain at most one fallible reward")
            for action_index, action in enumerate(stage.actions):
                _validate_action(action, f"{stage_path}.actions[{action_index}]")
    return tuple(result)


def _validate_effective_plan(stages, path, *, allow_battle):
    if not stages:
        _fail(path, "composed delivery path must contain at least one stage")
    if len(stages) > MAX_CURSOR:
        _fail(path, f"composed delivery path has {len(stages)} stages; "
              f"cursor maximum is {MAX_CURSOR}")
    battle_paths = []
    for stage_index, (stage, stage_path) in enumerate(stages):
        for action_index, action in enumerate(stage.actions):
            action_path = f"{stage_path}.actions[{action_index}]"
            if isinstance(action, _BATTLE_TYPES):
                battle_paths.append((stage_index, action_index, action_path, stage))
    if battle_paths and not allow_battle:
        _fail(battle_paths[0][2], "battles are not allowed in stamp-slot delivery plans")
    unconditional_battles = [
        (stage_index, action_path) for stage_index, _action_index, action_path, stage
        in battle_paths if stage.condition is None]
    if len(unconditional_battles) > 1:
        _fail(unconditional_battles[1][1],
              "a delivery plan may contain at most one unconditional battle")
    if unconditional_battles:
        battle_stage, battle_path = unconditional_battles[0]
        if battle_stage != len(stages) - 1:
            _fail(battle_path,
                  "an unconditional battle must be in the final stage")
    for stage_index, action_index, action_path, _stage in battle_paths:
        if action_index != len(stages[stage_index][0].actions) - 1:
            _fail(action_path, "battle must be the last action of its stage")
    for stage, stage_path in stages:
        for action_index, action in enumerate(stage.actions):
            if isinstance(action, Exit) and action_index != len(stage.actions) - 1:
                _fail(f"{stage_path}.actions[{action_index}]",
                      "exit must be the last action of its stage")
    return bool(battle_paths)


def validate_definition(definition, *, flag_id=None):
    if not isinstance(definition, WonderGift):
        _fail(type(definition).__name__, "expected WonderGift")
    path = definition.slug if isinstance(definition.slug, str) and definition.slug else "gift"
    _validate_slug(definition.slug, f"{path}.slug")
    actual_flag_id = definition.card.default_flag_id if flag_id is None else flag_id
    _validate_card(definition.card, f"{path}.card", flag_id=actual_flag_id)
    _validate_message(definition.intro_message, f"{path}.intro_message")
    _validate_message(definition.completed_message, f"{path}.completed_message")
    if definition.trainer is not None:
        if not isinstance(definition.trainer, (bytes, bytearray)):
            _fail(f"{path}.trainer", "trainer must be packed bytes")
        if len(definition.trainer) != ereader_trainer.TRAINER_SIZE:
            _fail(f"{path}.trainer",
                  f"a visiting trainer is {ereader_trainer.TRAINER_SIZE} bytes, "
                  f"got {len(definition.trainer)}")
        if not ereader_trainer.validate(definition.trainer):
            _fail(f"{path}.trainer",
                  "fails ValidateEReaderTrainer; the console would silently clear it")
        if not isinstance(definition.event, GiftSpec):
            _fail(f"{path}.trainer", "a stamp rally cannot also send a visiting trainer")
    if definition.mevent is not None:
        if not isinstance(definition.mevent, (bytes, bytearray)):
            _fail(f"{path}.mevent", "mevent must be assembled bytes from MysteryEventScript")
        if len(definition.mevent) > mystery_event.MAX_SCRIPT_SIZE:
            _fail(f"{path}.mevent",
                  f"a Mystery Event script is at most {mystery_event.MAX_SCRIPT_SIZE} bytes, "
                  f"got {len(definition.mevent)}")
        chain = mystery_event.decode(definition.mevent)
        if not chain or chain[-1][0] not in mystery_event.TERMINAL_OPCODES:
            _fail(f"{path}.mevent",
                  "no terminal command; the console would decode past the script into the rest "
                  "of its receive buffer")
        if any(opcode in mystery_event.DEAD_OPCODES for opcode, _, _ in chain):
            _fail(f"{path}.mevent",
                  "setrecordmixinggift and enableresetrtc both call SetIncompatible in FRLG")
        if definition.trainer is not None:
            _fail(f"{path}.mevent",
                  "a Mystery Event and a visiting trainer cannot share one session")
        if not isinstance(definition.event, GiftSpec):
            _fail(f"{path}.mevent", "a stamp rally already uses CLI_RUN_MEVENT_SCRIPT")
    shared = _validate_plan_shape(definition.delivery, f"{path}.delivery")
    if definition.delivery.pre_stages:
        _fail(f"{path}.delivery.pre_stages",
              "top-level delivery uses only the delivery section")
    if definition.delivery.post_stages:
        _fail(f"{path}.delivery.post_stages",
              "top-level delivery uses only the delivery section")

    if isinstance(definition.event, GiftSpec):
        if type(definition.event.repeatable) is not bool:
            _fail(f"{path}.event.repeatable", "repeatable must be a bool")
        if definition.event.shareable not in SHAREABLE_STATES:
            _fail(f"{path}.event.shareable",
                  f"shareable must be one of {', '.join(SHAREABLE_STATES)}")
        _validate_effective_plan(shared, f"{path}.delivery", allow_battle=True)
        sprite_count = sum(
            isinstance(action, ShowSprite)
            for stage, _stage_path in shared for action in stage.actions)
        if sprite_count > 0x100:
            _fail(f"{path}.delivery", "a script may create at most 256 virtual sprites")
        return definition

    if not isinstance(definition.event, StampRallySpec):
        _fail(f"{path}.event", "event must be GiftSpec or StampRallySpec")
    rally = definition.event
    if not 1 <= len(rally.slots) <= MAX_STAMP_SLOTS:
        _fail(f"{path}.event.slots",
              f"rally must contain 1 through {MAX_STAMP_SLOTS} slots")
    seen_slugs = set()
    seen_species = set()
    seen_ids = set()
    effective_plans = []
    for index, slot in enumerate(rally.slots):
        slot_path = f"{path}.event.slots[{index}]"
        if not isinstance(slot, StampSlot):
            _fail(slot_path, "slot must be a StampSlot")
        _validate_slug(slot.slug, f"{slot_path}.slug")
        if slot.slug in seen_slugs:
            _fail(f"{slot_path}.slug", f"duplicate stamp slug {slot.slug!r}")
        seen_slugs.add(slot.slug)
        _validate_int(slot.stamp_species, 1, MAX_ICON_SPECIES,
                      f"{slot_path}.stamp_species", "stamp species")
        _validate_int(slot.stamp_id, 1, 0xFFFF,
                      f"{slot_path}.stamp_id", "stamp ID")
        if slot.stamp_species in seen_species:
            _fail(f"{slot_path}.stamp_species", "stamp species must be unique within a rally")
        if slot.stamp_id in seen_ids:
            _fail(f"{slot_path}.stamp_id", "stamp ID must be unique within a rally")
        seen_species.add(slot.stamp_species)
        seen_ids.add(slot.stamp_id)
        hooks = _validate_plan_shape(slot.delivery, f"{slot_path}.delivery")
        if slot.delivery.delivery:
            _fail(f"{slot_path}.delivery.delivery",
                  "stamp slots use only pre_stages and post_stages")
        pre_count = len(slot.delivery.pre_stages)
        effective = _effective_stages(
            hooks[:pre_count], shared, hooks[pre_count:])
        _validate_effective_plan(effective, f"{slot_path}.delivery", allow_battle=False)
        effective_plans.append(effective)

    completion_path = f"{path}.event.completion"
    completion_hooks = _validate_plan_shape(rally.completion, completion_path)
    if rally.completion.delivery:
        _fail(f"{completion_path}.delivery",
              "rally completion uses only pre_stages and post_stages")
    pre_count = len(rally.completion.pre_stages)
    completion = _effective_stages(
        completion_hooks[:pre_count], shared, completion_hooks[pre_count:])
    _validate_effective_plan(completion, completion_path, allow_battle=True)
    effective_plans.append(completion)
    sprite_count = sum(
        isinstance(action, ShowSprite)
        for plan in effective_plans for stage, _stage_path in plan
        for action in stage.actions)
    if sprite_count > 0x100:
        _fail(path, "a script may create at most 256 virtual sprites")
    return definition


METLOC_FATEFUL_ENCOUNTER = 0xFF   # a #define in the generator template, so not version-bound
                                  # [decomp:src/data/region_map/region_map_sections.constants.json.txt]
MUS_OBTAIN_ITEM = 258



def _u16(value):
    return (value & 0xFFFF).to_bytes(2, "little")


def _encode_message(text):
    out = bytearray()
    lines = text.split("\n")
    for line_index, line in enumerate(lines):
        for piece in _TOKEN_RE.split(line):
            out += MESSAGE_TOKENS.get(piece) or charmap.encode(piece)
        if line_index < len(lines) - 1:
            out.append(0xFE)          # the line break charmap.encode silently drops
    out.append(0xFF)
    return bytes(out)


class _FieldScriptBuilder:
    def __init__(self):
        self.code = bytearray()
        self.labels = {}
        self.branch_fixups = []
        self.message_fixups = []
        self.messages = []
        self.stage_sizes = []

    def label(self, name):
        if name in self.labels:
            raise GiftValidationError("compiler", f"duplicate label {name!r}")
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
        encoded = _encode_message(text)
        self.code.append(_OP_VMESSAGE)
        self.message_fixups.append((len(self.code), len(self.messages)))
        self.code += b"\x00" * 4
        self.code += bytes([_OP_WAITMESSAGE, _OP_WAITBUTTONPRESS, _OP_CLOSEMESSAGE])
        self.messages.append(encoded)
        return len(encoded)

    def finish(self, path):
        code = bytearray(self.code)
        message_offsets = []
        blobs = []
        pool = {}
        offset = len(code)
        for message in self.messages:
            if message not in pool:
                pool[message] = offset
                blobs.append(message)
                offset += len(message)
            message_offsets.append(pool[message])
        for position, label in self.branch_fixups:
            if label not in self.labels:
                _fail(path, f"unresolved compiler label {label!r}")
            target = _RAM_SCRIPT_VIRTUAL_BASE + self.labels[label]
            code[position:position + 4] = target.to_bytes(4, "little")
        for position, message_index in self.message_fixups:
            target = _RAM_SCRIPT_VIRTUAL_BASE + message_offsets[message_index]
            code[position:position + 4] = target.to_bytes(4, "little")
        return bytes(code) + b"".join(blobs)


def _setvar(variable, value):
    return bytes([_OP_SETVAR]) + _u16(variable) + _u16(value)


def _compare(variable, value):
    return bytes([_OP_COMPARE_VAR_TO_VALUE]) + _u16(variable) + _u16(value)


def _specialvar(variable, special_id):
    return bytes([_OP_SPECIALVAR]) + _u16(variable) + _u16(special_id)


def _setflag(flag):
    return bytes([_OP_SETFLAG]) + _u16(flag)


def _clearflag(flag):
    return bytes([_OP_CLEARFLAG]) + _u16(flag)


def _givemon(species, level, item):
    return (bytes([_OP_GIVEMON]) + _u16(species) + bytes([level])
            + _u16(item) + b"\x00" * 9)


def _stage_label(prefix, index):
    return f"{prefix}_stage_{index}"


def _emit_cursor_dispatch(builder, cursor, stages, prefix, finished_label):
    for index in range(len(stages)):
        builder.emit(_compare(cursor, index))
        builder.vgoto_if(_COMPARE_EQ, _stage_label(prefix, index))
    builder.vgoto(finished_label)


def _emit_battle_checkpoint(builder, cursor, final_cursor, *, receipt_flag,
                            overall_completion):
    builder.emit(_setvar(cursor, final_cursor))
    builder.emit(_setflag(receipt_flag))
    if overall_completion:
        builder.emit(_setflag(FLAG_MYSTERY_GIFT_DONE))


def _emit_condition_branch(builder, condition, true_label, false_label, prefix):
    if isinstance(condition, VarEquals):
        builder.emit(_compare(condition.variable, condition.value))
        builder.vgoto_if(_COMPARE_EQ, true_label)
        builder.vgoto(false_label)
    elif isinstance(condition, FlagSet):
        builder.emit(bytes([_OP_CHECKFLAG]) + _u16(condition.flag))
        builder.vgoto_if(_COMPARE_EQ, true_label)
        builder.vgoto(false_label)
    elif isinstance(condition, Not):
        _emit_condition_branch(
            builder, condition.condition, false_label, true_label,
            f"{prefix}_not")
    elif isinstance(condition, AllOf):
        children = condition.conditions
        for index, child in enumerate(children[:-1]):
            next_label = f"{prefix}_all_{index}"
            _emit_condition_branch(
                builder, child, next_label, false_label,
                f"{prefix}_all_{index}")
            builder.label(next_label)
        _emit_condition_branch(
            builder, children[-1], true_label, false_label,
            f"{prefix}_all_{len(children) - 1}")
    elif isinstance(condition, AnyOf):
        children = condition.conditions
        for index, child in enumerate(children[:-1]):
            next_label = f"{prefix}_any_{index}"
            _emit_condition_branch(
                builder, child, true_label, next_label,
                f"{prefix}_any_{index}")
            builder.label(next_label)
        _emit_condition_branch(
            builder, children[-1], true_label, false_label,
            f"{prefix}_any_{len(children) - 1}")
    else:  # pragma: no cover - validation prevents this path.
        raise AssertionError(type(condition))


# The slot the new mon lands in is the party count BEFORE it is given, which is what the official
# Surf Pichu script reads with `specialvar ... CalculatePlayerPartyCount` [data/mystery_event_msg.s:46].
# `getpartysize` is the same call without a version-bound special id, but it answers in VAR_RESULT and
# `givemon` overwrites VAR_RESULT with its own result - so the count has to be saved first.
_FATEFUL_SLOT_VAR = _VAR_0x8002


def _save_party_slot():
    """Keep the pre-give party count: it is the index the mon is about to occupy."""
    return bytes([_OP_SETVAR_OR_COPY]) + _u16(_FATEFUL_SLOT_VAR) + _u16(_VAR_RESULT)


def _mark_fateful_encounter():
    """The pair the official script emits together: the bit, and the met location that reads as one.

    TRAP: `ScrCmd_setmonmodernfatefulencounter` does NOT bounds-check its index - it is a plain
    `SetMonData(&gPlayerParty[VarGet(...)], ...)` [decomp:src/scrcmd.c:2239], unlike
    `setmonmove`, whose helper clamps anything above PARTY_SIZE to the last mon
    [ScriptSetMonMoveSlot, src/script_pokemon_util.c:144]. So LAST_PARTY_MON_INDEX (7) must NOT be
    handed to it: that writes 100 bytes past the party. The real slot is used instead, and the
    caller's full-party guard is what keeps it inside 0..5 - a party of 6 jumps to the failure
    label before the mon is given, so a mon sent to the PC is never marked either.
    `setmonmetlocation` does check [`:2261`], and is passed the same var for the same reason.
    """
    return (bytes([_OP_SETMONMODERNFATEFULENCOUNTER]) + _u16(_FATEFUL_SLOT_VAR)
            + bytes([_OP_SETMONMETLOCATION]) + _u16(_FATEFUL_SLOT_VAR)
            + bytes([METLOC_FATEFUL_ENCOUNTER]))


def _emit_action(builder, action, *, sprite_id, failure_label, completed_label):
    if isinstance(action, Message):
        builder.message(action.text)
    elif isinstance(action, GiveItem):
        builder.emit(bytes([_OP_CHECKITEMSPACE]) + _u16(action.item) + _u16(action.quantity))
        builder.emit(_compare(_VAR_RESULT, 0))
        builder.vgoto_if(_COMPARE_EQ, failure_label)
        builder.emit(bytes([_OP_SETVAR_OR_COPY]) + _u16(_VAR_0x8000) + _u16(action.item))
        builder.emit(bytes([_OP_SETVAR_OR_COPY]) + _u16(_VAR_0x8001) + _u16(action.quantity))
        builder.emit(bytes([_OP_CALLSTD, _STD_OBTAIN_ITEM]))
    elif isinstance(action, GivePokemon):
        if action.moves or action.fateful_encounter:
            builder.emit(bytes([_OP_GETPARTYSIZE]))
            if action.fateful_encounter:
                builder.emit(_save_party_slot())
            builder.emit(_compare(_VAR_RESULT, PARTY_SIZE))
            builder.vgoto_if(_COMPARE_EQ, failure_label)
        builder.emit(_givemon(action.species, action.level, action.held_item))
        builder.emit(_compare(_VAR_RESULT, MON_CANT_GIVE))
        builder.vgoto_if(_COMPARE_EQ, failure_label)
        for slot, move in enumerate(action.moves):
            builder.emit(bytes([_OP_SETMONMOVE, LAST_PARTY_MON_INDEX, slot]) + _u16(move))
        if action.fateful_encounter:
            builder.emit(_mark_fateful_encounter())
        builder.emit(bytes([_OP_PLAYFANFARE]) + _u16(MUS_OBTAIN_ITEM))
    elif isinstance(action, GiveEgg):
        if action.moves or action.fateful_encounter:
            builder.emit(bytes([_OP_GETPARTYSIZE]))
            if action.fateful_encounter:
                builder.emit(_save_party_slot())
            builder.emit(_compare(_VAR_RESULT, PARTY_SIZE))
            builder.vgoto_if(_COMPARE_EQ, failure_label)
        builder.emit(bytes([_OP_GIVEEGG]) + _u16(action.species))
        builder.emit(_compare(_VAR_RESULT, MON_CANT_GIVE))
        builder.vgoto_if(_COMPARE_EQ, failure_label)
        for slot, move in enumerate(action.moves):
            builder.emit(bytes([_OP_SETMONMOVE, LAST_PARTY_MON_INDEX, slot]) + _u16(move))
        if action.fateful_encounter:
            builder.emit(_mark_fateful_encounter())
        builder.emit(bytes([_OP_PLAYFANFARE]) + _u16(MUS_OBTAIN_ITEM))
    elif isinstance(action, ShowSprite):
        if isinstance(action.position, RelativeToPlayer):
            builder.emit(bytes([_OP_GETPLAYERXY]) + _u16(_VAR_PLAYER_X) + _u16(_VAR_PLAYER_Y))
            if action.position.dx:
                builder.emit(bytes([_OP_ADDVAR]) + _u16(_VAR_PLAYER_X)
                             + _u16(action.position.dx))
            if action.position.dy:
                builder.emit(bytes([_OP_ADDVAR]) + _u16(_VAR_PLAYER_Y)
                             + _u16(action.position.dy))
            x, y = _VAR_PLAYER_X, _VAR_PLAYER_Y
        else:
            x, y = action.position.x, action.position.y
        builder.emit(bytes([_OP_CREATEVOBJECT, action.graphics_id, sprite_id])
                     + _u16(x) + _u16(y)
                     + bytes([action.elevation, action.direction]))
        if action.delay_frames:
            builder.emit(bytes([0x28]) + _u16(action.delay_frames))
    elif isinstance(action, BattlePokemon):
        builder.emit(bytes([_OP_SETWILDBATTLE]) + _u16(action.species)
                     + bytes([action.level]) + _u16(action.held_item)
                     + bytes([_OP_DOWILDBATTLE]))
    elif isinstance(action, BattleLegendary):
        builder.emit(bytes([_OP_SETWILDBATTLE]) + _u16(action.species)
                     + bytes([action.level]) + _u16(action.held_item)
                     + bytes([_OP_SPECIAL])
                     + _u16(SPECIAL_START_LEGENDARY_BATTLE))
    elif isinstance(action, RequireSpecialResult):
        builder.emit(_specialvar(_VAR_RESULT, action.special_id))
        builder.emit(_compare(_VAR_RESULT, action.expected))
        builder.vgoto_if(_COMPARE_EQ, f"{failure_label}_success")
        builder.vgoto(failure_label)
        builder.label(f"{failure_label}_success")
    elif isinstance(action, SetVar):
        builder.emit(_setvar(action.variable, action.value))
    elif isinstance(action, Exit):
        builder.vgoto(completed_label)
    else:  # pragma: no cover - validation prevents this path.
        raise AssertionError(type(action))


def _failure_message(action):
    if isinstance(action, GiveItem):
        return action.failure_message or DEFAULT_BAG_FULL_MESSAGE
    if isinstance(action, (GivePokemon, GiveEgg)):
        if action.failure_message:
            return action.failure_message
        # Without moves a full party is not a failure at all - the mon goes to the PC, and only a
        # full PC reaches the label. Moves and fateful_encounter both need the mon to be IN the
        # party, so both emit the party-size guard, and then a full party is what the player hit.
        needs_party = bool(action.moves) or action.fateful_encounter
        return DEFAULT_PARTY_FULL_MESSAGE if needs_party else DEFAULT_STORAGE_FULL_MESSAGE
    if isinstance(action, RequireSpecialResult):
        return action.failure_message
    return None


def _emit_plan(builder, stages, cursor, prefix, finished_label, failures,
               sprite_counter, *, receipt_flag, completed_label,
               overall_completion=False, reset_on_terminal_battle=False):
    for stage_index, (stage, source_path) in enumerate(stages):
        builder.label(_stage_label(prefix, stage_index))
        stage_start = len(builder.code)
        checkpoint_label = f"{prefix}_stage_{stage_index}_checkpoint"
        if stage.condition is not None:
            run_label = f"{prefix}_stage_{stage_index}_condition_true"
            _emit_condition_branch(
                builder, stage.condition, run_label, checkpoint_label,
                f"{prefix}_stage_{stage_index}_condition")
            builder.label(run_label)
        has_battle = any(isinstance(action, _BATTLE_TYPES) for action in stage.actions)
        for action_index, action in enumerate(stage.actions):
            failure_label = f"{prefix}_failure_{stage_index}_{action_index}"
            message = _failure_message(action)
            if message is not None:
                failures.append((failure_label, message))
            if isinstance(action, _BATTLE_TYPES):
                if reset_on_terminal_battle:
                    builder.emit(_setvar(cursor, 0))
                    builder.emit(_setflag(receipt_flag))
                else:
                    _emit_battle_checkpoint(
                        builder, cursor, len(stages), receipt_flag=receipt_flag,
                        overall_completion=overall_completion)
                builder.emit(bytes([_OP_RELEASE]))
            _emit_action(
                builder, action, sprite_id=sprite_counter,
                failure_label=failure_label, completed_label=completed_label)
            if isinstance(action, ShowSprite):
                sprite_counter += 1
        # END after a battle: a conditional battle must not fall through, and a saved RAM
        # script must not leave BattleLegendary's special as the suspended pointer.
        if has_battle:
            builder.emit(bytes([_OP_END]))
        builder.label(checkpoint_label)
        builder.emit(_setvar(cursor, stage_index + 1))
        if stage_index + 1 == len(stages):
            builder.vgoto(finished_label)
        builder.stage_sizes.append(
            (source_path, len(builder.code) - stage_start))
    return sprite_counter


def _build_card(card, *, flag_id, card_type, max_stamps, send_type=None):
    selected_send_type = card.send_type if send_type is None else send_type
    return build_wonder_card(
        flag_id=flag_id, icon_species=card.icon_species,
        id_number=card.id_number, card_type=card_type,
        bg_type=card.bg_type, send_type=selected_send_type,
        max_stamps=max_stamps, title=card.title, subtitle=card.subtitle,
        body=card.body, footer1=card.footer1, footer2=card.footer2)


def _check_script_size(script, builder, path):
    if len(script) <= MAX_RAM_SCRIPT_SIZE:
        return
    largest = sorted(builder.stage_sizes, key=lambda pair: pair[1], reverse=True)[:4]
    detail = ", ".join(f"{name}={size}B" for name, size in largest)
    message_bytes = sum(len(message) for message in builder.messages)
    _fail(path, f"compiled RAM script is {len(script)} bytes; maximum is "
          f"{MAX_RAM_SCRIPT_SIZE} (messages={message_bytes}B"
          + (f", largest stages: {detail})" if detail else ")"))


def _append_failures(builder, failures, exit_label):
    for label, message in failures:
        builder.label(label)
        builder.message(message)
        builder.vgoto(exit_label)


def _entries(stages, path):
    return tuple((stage, f"{path}[{index}]")
                 for index, stage in enumerate(stages))


def _shared_entries(definition):
    return _entries(definition.delivery.delivery,
                    f"{definition.slug}.delivery.delivery")


def _rally_entries(definition, plan, path):
    return (_entries(plan.pre_stages, f"{path}.pre_stages")
            + _shared_entries(definition)
            + _entries(plan.post_stages, f"{path}.post_stages"))


def _compile_gift(definition, flag_id):
    builder = _FieldScriptBuilder()
    failures = []
    receipt_flag = flag_for_flag_id(flag_id)
    repeatable = definition.event.repeatable
    stages = _shared_entries(definition)
    builder.emit(bytes([_OP_SETVADDRESS])
                 + _RAM_SCRIPT_VIRTUAL_BASE.to_bytes(4, "little"))
    builder.emit(bytes([_OP_LOCK, _OP_FACEPLAYER]))
    if not repeatable:
        builder.emit(bytes([_OP_CHECKFLAG]) + _u16(FLAG_MYSTERY_GIFT_DONE))
        builder.vgoto_if(_COMPARE_EQ, "completed")
    builder.message(definition.intro_message)
    # A replacement Wonder Card clears the card-scoped vars but not sReceivedGiftFlags.
    builder.emit(_clearflag(receipt_flag))
    _emit_cursor_dispatch(
        builder, VAR_MYSTERY_GIFT_1, stages,
        "main", "finish")
    _emit_plan(
        builder, stages, VAR_MYSTERY_GIFT_1, "main", "finish",
        failures, 0, receipt_flag=receipt_flag, completed_label="completed",
        overall_completion=not repeatable,
        reset_on_terminal_battle=repeatable)

    builder.label("finish")
    if repeatable:
        builder.emit(_setvar(VAR_MYSTERY_GIFT_1, 0))
        builder.emit(_setflag(receipt_flag))
    else:
        builder.emit(_setflag(FLAG_MYSTERY_GIFT_DONE))
        builder.emit(_setflag(receipt_flag))
    builder.vgoto("exit")
    builder.label("completed")
    builder.message(definition.completed_message)
    builder.vgoto("exit")
    _append_failures(builder, failures, "exit")
    builder.label("exit")
    builder.emit(bytes([_OP_RELEASE, _OP_END]))
    script = builder.finish(definition.slug)
    _check_script_size(script, builder, definition.slug)
    card = _build_card(
        definition.card, flag_id=flag_id,
        card_type=CARD_TYPE_GIFT, max_stamps=0,
        send_type=_SHAREABLE_SEND_TYPES[definition.event.shareable])
    return MysteryGiftDistribution(card, script, trainer=definition.trainer,
                                   mevent=definition.mevent)




def _build_activation(cursor, *, receipt_flag, install):
    embedded = bytearray()
    if install:
        embedded += _clearflag(receipt_flag)
    embedded += _setvar(cursor, 1)
    embedded.append(_OP_END)
    embedded_offset = 6
    return (bytes([_ME_RUNSCRIPT]) + embedded_offset.to_bytes(4, "little")
            + bytes([_ME_END]) + bytes(embedded))


def _compile_rally(definition, flag_id):
    builder = _FieldScriptBuilder()
    failures = []
    rally = definition.event
    receipt_flag = flag_for_flag_id(flag_id)
    builder.emit(bytes([_OP_SETVADDRESS])
                 + _RAM_SCRIPT_VIRTUAL_BASE.to_bytes(4, "little"))
    builder.emit(bytes([_OP_LOCK, _OP_FACEPLAYER]))
    builder.emit(bytes([_OP_CHECKFLAG]) + _u16(FLAG_MYSTERY_GIFT_DONE))
    builder.vgoto_if(_COMPARE_EQ, "completed")
    builder.message(definition.intro_message)

    sprite_counter = 0
    for slot_index, slot in enumerate(rally.slots):
        cursor = VAR_MYSTERY_GIFT_SLOT_VARS[slot_index]
        prefix = f"slot_{slot_index}"
        next_label = f"slot_{slot_index + 1}_dispatch"
        stages = _rally_entries(
            definition, slot.delivery,
            f"{definition.slug}.event.slots[{slot_index}].delivery")
        builder.label(f"slot_{slot_index}_dispatch")
        builder.emit(_compare(cursor, 0))
        builder.vgoto_if(_COMPARE_EQ, next_label)
        final_cursor = len(stages) + 1
        builder.emit(_compare(cursor, final_cursor))
        builder.vgoto_if(_COMPARE_EQ, next_label)
        for stage_index in range(len(stages)):
            builder.emit(_compare(cursor, stage_index + 1))
            builder.vgoto_if(_COMPARE_EQ, _stage_label(prefix, stage_index))
        builder.vgoto(next_label)
        sprite_counter = _emit_plan(
            builder, stages, cursor, prefix, next_label,
            failures, sprite_counter, receipt_flag=receipt_flag,
            completed_label="completed")
        # Slot cursors are offset by one (1 = activated): rewrite checkpoints 1..N to 2..N+1.
        for stage_index in range(len(stages)):
            start = builder.labels[_stage_label(prefix, stage_index)]
            end = (builder.labels[_stage_label(prefix, stage_index + 1)]
                   if stage_index + 1 < len(stages)
                   else len(builder.code))
            needle = bytes([_OP_SETVAR]) + _u16(cursor) + _u16(stage_index + 1)
            position = builder.code.rfind(needle, start, end)
            if position < 0:
                _fail(definition.slug, "compiler could not locate stamp cursor checkpoint")
            builder.code[position + 3:position + 5] = _u16(stage_index + 2)

    builder.label(f"slot_{len(rally.slots)}_dispatch")
    for slot_index, slot in enumerate(rally.slots):
        cursor = VAR_MYSTERY_GIFT_SLOT_VARS[slot_index]
        stages = _rally_entries(
            definition, slot.delivery,
            f"{definition.slug}.event.slots[{slot_index}].delivery")
        builder.emit(_compare(cursor, len(stages) + 1))
        builder.vgoto_if(_COMPARE_EQ, f"slot_{slot_index}_complete")
        builder.vgoto("waiting")
        builder.label(f"slot_{slot_index}_complete")

    completion = _rally_entries(
        definition, rally.completion,
        f"{definition.slug}.event.completion")
    _emit_cursor_dispatch(
        builder, VAR_MYSTERY_GIFT_1, completion, "completion", "finish")
    _emit_plan(
        builder, completion, VAR_MYSTERY_GIFT_1,
        "completion", "finish", failures, sprite_counter,
        receipt_flag=receipt_flag, completed_label="completed",
        overall_completion=True)

    builder.label("finish")
    builder.emit(_setflag(FLAG_MYSTERY_GIFT_DONE))
    builder.emit(_setflag(receipt_flag))
    builder.vgoto("exit")
    builder.label("waiting")
    builder.vgoto("exit")
    builder.label("completed")
    builder.message(definition.completed_message)
    builder.vgoto("exit")
    _append_failures(builder, failures, "exit")
    builder.label("exit")
    builder.emit(bytes([_OP_RELEASE, _OP_END]))
    script = builder.finish(definition.slug)
    _check_script_size(script, builder, definition.slug)

    card = _build_card(
        definition.card, flag_id=flag_id,
        card_type=CARD_TYPE_STAMP, max_stamps=len(rally.slots))
    distributions = {}
    for slot_index, slot in enumerate(rally.slots):
        cursor = VAR_MYSTERY_GIFT_SLOT_VARS[slot_index]
        stamp = _u16(slot.stamp_species) + _u16(slot.stamp_id)
        distributions[slot.slug] = MysteryGiftDistribution(
            card=card, ram_script=script, stamp=stamp,
            activation_script=_build_activation(
                cursor, receipt_flag=receipt_flag, install=False),
            install_activation_script=_build_activation(
                cursor, receipt_flag=receipt_flag, install=True))
    return distributions


def build_bound_script(actions, *, slug="bound"):
    """Composer actions -> a standalone field script, the kind `initramscript` binds to an object.

    `build_talk_script` below is this with only Message allowed. Everything the delivery plan can do
    - give an item, give a mon, show a sprite, start a battle, read a special - is the same bytecode
    running in the same interpreter out of the same `gSaveBlock1Ptr->ramScript.data.script`, so the
    only thing that was missing was somewhere to put it that is not a DeliveryPlan.

    WHAT IS DELIBERATELY NOT HERE: the stage cursor, the receipt flag and the completion bookkeeping.
    A delivery plan is resumable because the delivery man can be talked to again mid-sequence and
    must not repeat what he already gave. A bound script has no such contract - it ends in `end` and
    not `endram`, so the binding survives and the player can simply run the whole thing again
    [rng_script's header, and mev03]. Anything that must happen once needs its own flag, as an
    explicit SetVar or a condition, rather than getting one by accident.

    THE TRAP THAT GOVERNS ALL OF THIS: a Wonder Card and an NPC-bound script share one RAM script
    slot, so installing this takes the card's slot and the console then reports it holds no card
    [ValidateSavedWonderCard requires ValidateRamScript, decomp:src/mystery_gift.c:186]. The card is
    intact; the menu will not show it. Sending any ordinary card afterwards takes the slot back.
    """
    builder = _FieldScriptBuilder()
    builder.emit(bytes([_OP_SETVADDRESS])
                 + _RAM_SCRIPT_VIRTUAL_BASE.to_bytes(4, "little"))
    builder.emit(bytes([_OP_LOCK, _OP_FACEPLAYER]))
    failures = []
    sprite_counter = 0
    for action_index, action in enumerate(actions):
        failure_label = f"{slug}_failure_{action_index}"
        message = _failure_message(action)
        if message is not None:
            failures.append((failure_label, message))
        _emit_action(builder, action, sprite_id=sprite_counter,
                     failure_label=failure_label, completed_label="exit")
        if isinstance(action, ShowSprite):
            sprite_counter += 1
    builder.vgoto("exit")
    _append_failures(builder, failures, "exit")
    builder.label("exit")
    builder.emit(bytes([_OP_RELEASE, _OP_END]))
    script = builder.finish(slug)
    _check_script_size(script, builder, slug)
    return script


def build_talk_script(messages, *, slug="talk"):
    """A minimal field script: lock, face the player, say each line, release.

    The Mystery Event `initramscript` opcode binds a field script to any map and object, and what it
    binds is exactly the bytecode a delivery script is made of -- same interpreter, same
    `setvaddress` base, because both end up in `gSaveBlock1Ptr->ramScript.data.script`.
    """
    builder = _FieldScriptBuilder()
    builder.emit(bytes([_OP_SETVADDRESS])
                 + _RAM_SCRIPT_VIRTUAL_BASE.to_bytes(4, "little"))
    builder.emit(bytes([_OP_LOCK, _OP_FACEPLAYER]))
    for message in messages:
        _validate_message(message, f"{slug}.messages")
        builder.message(message)
    builder.emit(bytes([_OP_RELEASE, _OP_END]))
    script = builder.finish(slug)
    _check_script_size(script, builder, slug)
    return script


# --- the seed-reading script --------------------------------------------------------------------

SEED_READ_DEFAULT_LINES = ("RNG HI {STR_VAR_2}\n"
                           "RNG LO {STR_VAR_1}",)


def _copybyte(dest, src):
    """`copybyte` (0x15): one byte from any absolute address to any absolute address.

        u8 *dest = (u8 *)ScriptReadWord(ctx);
        *dest = *(const u8 *)ScriptReadWord(ctx);
    [decomp:src/scrcmd.c:329] - DESTINATION FIRST, then source. It returns FALSE.
    """
    return bytes([_OP_COPYBYTE]) + int(dest).to_bytes(4, "little") + int(src).to_bytes(4, "little")


def _buffernumberstring(string_var_index, var_id):
    """`buffernumberstring` (0x83): a var's value as decimal into gStringVar1..3.

        u8 stringVarIndex = ScriptReadByte(ctx);
        u16 num = VarGet(ScriptReadHalfword(ctx));
    [decomp:src/scrcmd.c:1678]. It takes a VAR ID, not an address, so this half needs no address
    hunt - `VarGet` resolves 0x8000 through gSpecialVars itself. The number is a **u16**, which is
    why the 32-bit seed takes two of these.
    """
    return bytes([_OP_BUFFERNUMBERSTRING, int(string_var_index)]) + _u16(var_id)


def build_seed_read_script(*, address=None, var_address=None, lines=SEED_READ_DEFAULT_LINES,
                           slug="rng-seed-reader"):
    """A field script that PRINTS gRngValue and changes nothing.

    Four `copybyte`s move the four bytes of gRngValue into gSpecialVar_0x8000 and 0x8001 - which
    are adjacent u16s, so the four destinations are var_address + 0..3 - and two
    `buffernumberstring`s turn those into the decimal halves the message prints.

    **THE READ IS ATOMIC AND THAT IS NOT AN ACCIDENT.** The RNG never idles, so four byte copies
    spread over four frames would tear: the halves would come from different states and the
    reassembled word would be a value the console never held. `copybyte` and `buffernumberstring`
    both return FALSE, and the field engine runs commands until one returns TRUE
    [decomp:src/script.c], so all six run back to back inside a single frame. Nothing that yields
    may be emitted between the first copybyte and the last buffernumberstring, and a test asserts
    none is - the same rule, for the same reason, as the seed-and-generate script.

    It ends with `end` (0x02), not `endram` (0x0d), so the binding survives and the NPC can be
    asked again - which is what makes a miss cost nothing.

    Nothing here writes gRngValue, the save, or any Pokemon. The one write is installing the
    script, which is a Wonder Card session like any other.
    """
    address = rom_map.GRNG_VALUE if address is None else int(address)
    var_address = (rom_map.G_SPECIAL_VAR_0X8000 if var_address is None else int(var_address))
    builder = _FieldScriptBuilder()
    builder.emit(bytes([_OP_SETVADDRESS])
                 + _RAM_SCRIPT_VIRTUAL_BASE.to_bytes(4, "little"))
    builder.emit(bytes([_OP_LOCK, _OP_FACEPLAYER]))
    for i in range(4):
        builder.emit(_copybyte(var_address + i, address + i))
    builder.emit(_buffernumberstring(0, _VAR_0x8000))       # gStringVar1 = the LOW half
    builder.emit(_buffernumberstring(1, _VAR_0x8001))       # gStringVar2 = the HIGH half
    for message in lines:
        _validate_message(message, f"{slug}.lines")
        builder.message(message)
    builder.emit(bytes([_OP_RELEASE, _OP_END]))
    script = builder.finish(slug)
    _check_script_size(script, builder, slug)
    return script


# --- the self-timing rate probe -------------------------------------------------------------------
# `ScrCmd_delay` yields and resumes after an exact number of frames [decomp:src/scrcmd.c:651], so a
# script that reads gRngValue, delays N frames and reads it again measures turns-per-frame with no
# clock in it: lcg.distance gives the numerator exactly and N is the denominator exactly. Every
# earlier attempt divided by a hand-timed elapsed, and one of them was circular. docs/rng.md.
RATE_PROBE_DEFAULT_FRAMES = 600         # ~10 s at 59.7275 Hz; the seconds are commentary, not data

RATE_PROBE_DEFAULT_LINES = ("FIRST HI {STR_VAR_2}\n"
                            "FIRST LO {STR_VAR_1}",
                            "AFTER HI {STR_VAR_2}\n"
                            "AFTER LO {STR_VAR_1}")


def build_seed_rate_script(*, address=None, var_address=None, frames=RATE_PROBE_DEFAULT_FRAMES,
                           lines=RATE_PROBE_DEFAULT_LINES, lock=True, slug="rng-rate-probe"):
    """A field script that reads gRngValue, waits an EXACT number of frames, and reads it again.

    The answer is two 32-bit states and a frame count that is not an estimate, so
    `rng_script.measure_rate` divides one exact number by another. This is the first measurement of
    the overworld rate with no clock in it since bs15 measured the Mystery Gift menu's.

    WHAT IT ACTUALLY MEASURES, stated precisely because the distinction is the whole reason the old
    numbers were wrong: the rate while a FIELD SCRIPT IS DELAYING, with the player locked. That is
    not self-evidently the rate while the player is walking around, and it must not be reported as
    if it were. It IS exactly the rate that a script which waits for a target state would run at -
    the design where the game does the aiming instead of a human with a stopwatch - so it is the
    number that design needs. Pass `lock=False` to measure with the player unlocked and compare;
    changing one variable at a time is the point.

    Both reads are atomic for the same reason the single read is: four `copybyte`s and nothing
    between them. `delay` sits BETWEEN the two reads deliberately - it is the only command here
    that yields, and a test asserts that it is.
    """
    address = rom_map.GRNG_VALUE if address is None else int(address)
    var_address = (rom_map.G_SPECIAL_VAR_0X8000 if var_address is None else int(var_address))
    frames = int(frames)
    if not 1 <= frames <= 0xFFFF:
        raise GiftValidationError(slug, f"delay takes a u16 of frames, got {frames}")
    if len(lines) != 2:
        raise GiftValidationError(slug, "the rate probe prints two readings, so two messages")
    builder = _FieldScriptBuilder()
    builder.emit(bytes([_OP_SETVADDRESS])
                 + _RAM_SCRIPT_VIRTUAL_BASE.to_bytes(4, "little"))
    if lock:
        builder.emit(bytes([_OP_LOCK, _OP_FACEPLAYER]))
    for i in range(4):                              # reading one -> vars 0x8000, 0x8001
        builder.emit(_copybyte(var_address + i, address + i))
    builder.emit(bytes([_OP_DELAY]) + _u16(frames))
    for i in range(4):                              # reading two -> vars 0x8002, 0x8003
        builder.emit(_copybyte(var_address + 4 + i, address + i))
    for pair, message in zip(((_VAR_0x8000, _VAR_0x8001), (_VAR_0x8002, _VAR_0x8003)), lines):
        builder.emit(_buffernumberstring(0, pair[0]))
        builder.emit(_buffernumberstring(1, pair[1]))
        _validate_message(message, f"{slug}.lines")
        builder.message(message)
    builder.emit(bytes([_OP_RELEASE] if lock else b"") + bytes([_OP_END]))
    script = builder.finish(slug)
    _check_script_size(script, builder, slug)
    return script


# --- the draw counter: how many turns the generation itself costs ---------------------------------
# `setwildbattle` and `copybyte` both return FALSE, so a read, the generation and a second read run
# back to back inside one frame and none of the 2-per-frame overworld consumption falls between them.
# `distance(before, after)` is therefore exactly what CreateScriptedWildMon took, which measures two
# things: that the offset between a reading and the generation is zero by construction, and the draw
# count itself (Method 1 says four; a stray draw shows up here as a 5 or a 6).
#
# It needs no Pokemon caught. `dowildbattle` calls ScriptContext_Stop [decomp:src/scrcmd.c:1945], so
# nothing can be printed after the battle - which is why both readings and both messages come first,
# and why the player's button press sits after the measured interval where it cannot reach it.
DRAW_COUNT_DEFAULT_LINES = ("BEFORE HI {STR_VAR_2}\n"
                            "BEFORE LO {STR_VAR_1}",
                            "AFTER HI {STR_VAR_2}\n"
                            "AFTER LO {STR_VAR_1}")


def build_draw_count_script(*, species, level, item=0, address=None, var_address=None,
                            lines=DRAW_COUNT_DEFAULT_LINES, slug="rng-draw-count"):
    """Read gRngValue, generate a scripted wild mon, read gRngValue again, print both, then fight.

    The two readings bracket the generation and nothing else: no yielding command sits between
    them, so no frame passes and no per-frame draw is counted. A test asserts that.
    """
    address = rom_map.GRNG_VALUE if address is None else int(address)
    var_address = (rom_map.G_SPECIAL_VAR_0X8000 if var_address is None else int(var_address))
    if len(lines) != 2:
        raise GiftValidationError(slug, "two readings, so two messages")
    builder = _FieldScriptBuilder()
    builder.emit(bytes([_OP_SETVADDRESS]) + _RAM_SCRIPT_VIRTUAL_BASE.to_bytes(4, "little"))
    builder.emit(bytes([_OP_LOCK, _OP_FACEPLAYER]))
    for i in range(4):                                   # BEFORE -> vars 0x8000, 0x8001
        builder.emit(_copybyte(var_address + i, address + i))
    builder.emit(bytes([_OP_SETWILDBATTLE]) + _u16(species)
                 + bytes([int(level)]) + _u16(item))      # the four draws happen HERE
    for i in range(4):                                   # AFTER -> vars 0x8002, 0x8003
        builder.emit(_copybyte(var_address + 4 + i, address + i))
    for pair, message in zip(((_VAR_0x8000, _VAR_0x8001), (_VAR_0x8002, _VAR_0x8003)), lines):
        builder.emit(_buffernumberstring(0, pair[0]))
        builder.emit(_buffernumberstring(1, pair[1]))
        _validate_message(message, f"{slug}.lines")
        builder.message(message)
    builder.emit(bytes([_OP_DOWILDBATTLE]))              # stops the script; nothing may follow
    script = builder.finish(slug)
    _check_script_size(script, builder, slug)
    return script


def compile_definition(definition, *, flag_id=None):
    """Returns one MysteryGiftDistribution for a GiftSpec, or ``{slot_slug: distribution}`` for a rally."""
    validate_definition(definition, flag_id=flag_id)
    actual_flag_id = definition.card.default_flag_id if flag_id is None else flag_id
    if isinstance(definition.event, GiftSpec):
        return _compile_gift(definition, actual_flag_id)
    return _compile_rally(definition, actual_flag_id)


__all__ = [
    "AllOf", "AnyOf", "BattleLegendary", "BattlePokemon", "DeliveryPlan",
    "DeliveryStage",
    "Exit", "FlagSet", "GiftSpec", "GiftValidationError", "GiveEgg", "GiveItem",
    "GivePokemon", "MapPosition", "Message", "RelativeToPlayer", "SetVar", "ShowSprite",
    "Not", "RequireSpecialResult", "SHARE_ALWAYS", "SHARE_NEVER", "SHARE_ONCE",
    "SPECIAL_HAS_ALL_KANTO_MONS", "SPECIAL_START_LEGENDARY_BATTLE",
    "SHAREABLE_STATES", "StampRallySpec", "StampSlot", "VarEquals",
    "WonderCardSpec", "WonderGift",
    "FLAG_MYSTERY_GIFT_DONE", "MAX_RAM_SCRIPT_SIZE", "MAX_STAMP_SLOTS",
    "VAR_MYSTERY_GIFT_1", "VAR_MYSTERY_GIFT_2", "VAR_MYSTERY_GIFT_3",
    "VAR_MYSTERY_GIFT_4", "VAR_MYSTERY_GIFT_5", "VAR_MYSTERY_GIFT_6",
    "VAR_MYSTERY_GIFT_7", "VAR_MYSTERY_GIFT_SLOT_VARS",
    "build_draw_count_script", "build_seed_rate_script", "build_seed_read_script",
    "build_talk_script",
    "compile_definition",
    "validate_definition",
]
