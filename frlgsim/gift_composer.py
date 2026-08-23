"""Declarative, validated authoring for future FRLG Mystery Gifts.

The hardware-proven legacy payloads remain in :mod:`wonder_card` and
:mod:`stamp_rally`.  This module is the authoring surface for new gifts: an
immutable description is validated and compiled into the same Wonder Card,
delivery RAM script, and optional stamp activation payloads consumed by the
existing host.

Saved-state layout used by compiled definitions::

    VAR_MYSTERY_GIFT_1      ordinary stages / rally completion stages
    VAR_MYSTERY_GIFT_2..7   rally stamp-slot stages (six slots maximum)
    FLAG_MYSTERY_GIFT_DONE  overall one-shot completion

Each variable is a u16 cursor.  Ordinary cursors equal the number of completed
stages.  A stamp cursor is zero while absent, one when activated, and advances
once for every completed delivery stage.

``WonderGift`` is the single top-level authoring type.  ``GiftSpec`` and
``StampRallySpec`` select ordinary or rally orchestration while the top-level
delivery plan supplies the reusable middle stages.  Rally slot and completion
plans wrap that middle with pre- and post-stages.
"""

from dataclasses import dataclass
from typing import TypeAlias

from . import charmap
from .mystery_gift import CARD_TYPE_GIFT, CARD_TYPE_STAMP, SEND_TYPE_DISALLOWED
from .stamp_rally import MysteryGiftDistribution
from .wonder_card import WONDER_CARD_SIZE, build_wonder_card, flag_for_flag_id


# Card-scoped FRLG event state [include/constants/{vars,flags}.h].
VAR_MYSTERY_GIFT_1 = 0x40B6
VAR_MYSTERY_GIFT_2 = 0x40B7
VAR_MYSTERY_GIFT_7 = 0x40BC
FLAG_MYSTERY_GIFT_DONE = 0x3D8

MAX_STAMP_SLOTS = 6
MAX_CURSOR = 0xFFFF
MAX_RAM_SCRIPT_SIZE = 995
MAX_POKEMON_SPECIES = 411       # NUM_SPECIES excludes SPECIES_EGG (412)
MAX_ICON_SPECIES = 412
MAX_ITEM = 374                  # ITEMS_COUNT - 1
MAX_MOVE = 354                  # MOVES_COUNT - 1
MAX_OBJECT_GRAPHICS = 151       # NUM_OBJ_EVENT_GFX - 1

MON_CANT_GIVE = 2
PARTY_SIZE = 6
LAST_PARTY_MON_INDEX = PARTY_SIZE + 1

DEFAULT_BAG_FULL_MESSAGE = (
    "There is no room in your BAG.\nPlease make room and come back!")
DEFAULT_STORAGE_FULL_MESSAGE = (
    "Your party and PC BOXES are full.\nPlease make room and come back!")
DEFAULT_PARTY_FULL_MESSAGE = (
    "Your party is full.\nPlease make room and come back!")
DEFAULT_COMPLETED_MESSAGE = (
    "You already received this MYSTERY GIFT.\nPlease look forward to future gifts!")


class GiftValidationError(ValueError):
    """A definition cannot be safely represented by an FRLG RAM script."""

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
    failure_message: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "moves", tuple(self.moves))


@dataclass(frozen=True)
class GiveEgg:
    species: int
    failure_message: str | None = None


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


GiftAction: TypeAlias = (
    Message | GiveItem | GivePokemon | GiveEgg | ShowSprite | BattlePokemon)
_FALLIBLE_REWARD_TYPES = (GiveItem, GivePokemon, GiveEgg)


@dataclass(frozen=True, init=False)
class DeliveryStage:
    actions: tuple[GiftAction, ...]

    def __init__(self, *positional_actions, actions=None):
        if actions is not None and positional_actions:
            raise TypeError("pass DeliveryStage actions positionally or by keyword, not both")
        selected = actions if actions is not None else positional_actions
        # Also accept DeliveryStage((action1, action2)) for generated callers.
        if (actions is None and len(selected) == 1
                and isinstance(selected[0], (tuple, list))):
            selected = selected[0]
        object.__setattr__(self, "actions", tuple(selected))


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
    """Ordinary-gift behavior not shared by stamp rallies."""

    repeatable: bool = False


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


def _validate_message(text, path):
    if not isinstance(text, str) or not text:
        _fail(path, "message must be a nonempty string")
    without_player = text.replace("{PLAYER}", "")
    if "{" in without_player or "}" in without_player:
        _fail(path, "the only supported message token is {PLAYER}")
    # Newlines and the player-name expansion are field-script controls rather
    # than printable characters. Validate every printable fragment exactly.
    for line in text.split("\n"):
        fragments = line.split("{PLAYER}")
        for fragment in fragments:
            _validate_plain_text(fragment, path)


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
        # Script operands at 0x4000 and above are interpreted as variable IDs.
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
    elif isinstance(action, BattlePokemon):
        _validate_int(action.species, 1, MAX_POKEMON_SPECIES,
                      f"{path}.species", "species")
        _validate_int(action.level, 1, 100, f"{path}.level", "level")
        _validate_int(action.held_item, 0, MAX_ITEM,
                      f"{path}.held_item", "held item")
    else:
        _fail(path, f"unsupported action type {type(action).__name__}")


def _plan_parts(plan):
    return (
        ("pre_stages", plan.pre_stages),
        ("delivery", plan.delivery),
        ("post_stages", plan.post_stages),
    )


def _effective_stages(*parts):
    """Return ``((stage, source_path), ...)`` for a composed execution path."""
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
            if isinstance(action, BattlePokemon):
                battle_paths.append((stage_index, action_index, action_path))
    if battle_paths and not allow_battle:
        _fail(battle_paths[0][2], "battles are not allowed in stamp-slot delivery plans")
    if len(battle_paths) > 1:
        _fail(battle_paths[1][2], "a delivery plan may contain at most one battle")
    if battle_paths:
        stage_index, action_index, action_path = battle_paths[0]
        if (stage_index != len(stages) - 1
                or action_index != len(stages[stage_index][0].actions) - 1):
            _fail(action_path, "battle must be the last action of the final stage")
    return bool(battle_paths)


def validate_definition(definition, *, flag_id=None):
    """Validate a definition without mutating or compiling it.

    ``flag_id`` applies the same per-run override used by the host and static
    tools.  The definition's card default is used when it is omitted.
    """
    if not isinstance(definition, WonderGift):
        _fail(type(definition).__name__, "expected WonderGift")
    path = definition.slug if isinstance(definition.slug, str) and definition.slug else "gift"
    _validate_slug(definition.slug, f"{path}.slug")
    actual_flag_id = definition.card.default_flag_id if flag_id is None else flag_id
    _validate_card(definition.card, f"{path}.card", flag_id=actual_flag_id)
    _validate_message(definition.intro_message, f"{path}.intro_message")
    _validate_message(definition.completed_message, f"{path}.completed_message")
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


# Field-event bytecode [asm/macros/event.inc].
_OP_END = 0x02
_OP_CALLSTD = 0x09
_OP_SETVAR = 0x16
_OP_ADDVAR = 0x17
_OP_SETVAR_OR_COPY = 0x1A
_OP_COMPARE_VAR_TO_VALUE = 0x21
_OP_SETFLAG = 0x29
_OP_CLEARFLAG = 0x2A
_OP_CHECKFLAG = 0x2B
_OP_GETPLAYERXY = 0x42
_OP_GETPARTYSIZE = 0x43
_OP_CHECKITEMSPACE = 0x46
_OP_FACEPLAYER = 0x5A
_OP_CLOSEMESSAGE = 0x68
_OP_LOCK = 0x6A
_OP_RELEASE = 0x6C
_OP_WAITMESSAGE = 0x66
_OP_WAITBUTTONPRESS = 0x6D
_OP_GIVEMON = 0x79
_OP_GIVEEGG = 0x7A
_OP_SETMONMOVE = 0x7B
_OP_CREATEVOBJECT = 0xAA
_OP_SETWILDBATTLE = 0xB6
_OP_DOWILDBATTLE = 0xB7
_OP_SETVADDRESS = 0xB8
_OP_VGOTO = 0xB9
_OP_VGOTO_IF = 0xBB
_OP_VMESSAGE = 0xBD

_COMPARE_EQ = 1
_VAR_PLAYER_X = 0x8004
_VAR_PLAYER_Y = 0x8005
_VAR_0x8000 = 0x8000
_VAR_0x8001 = 0x8001
_VAR_RESULT = 0x800D
_STD_OBTAIN_ITEM = 0
_RAM_SCRIPT_VIRTUAL_BASE = 0x08000000


def _u16(value):
    return (value & 0xFFFF).to_bytes(2, "little")


def _encode_message(text):
    out = bytearray()
    for line_index, line in enumerate(text.split("\n")):
        fragments = line.split("{PLAYER}")
        for fragment_index, fragment in enumerate(fragments):
            out += charmap.encode(fragment)
            if fragment_index < len(fragments) - 1:
                out += b"\xFD\x01"
        if line_index < len(text.split("\n")) - 1:
            out.append(0xFE)
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
        offset = len(code)
        for message in self.messages:
            message_offsets.append(offset)
            offset += len(message)
        for position, label in self.branch_fixups:
            if label not in self.labels:
                _fail(path, f"unresolved compiler label {label!r}")
            target = _RAM_SCRIPT_VIRTUAL_BASE + self.labels[label]
            code[position:position + 4] = target.to_bytes(4, "little")
        for position, message_index in self.message_fixups:
            target = _RAM_SCRIPT_VIRTUAL_BASE + message_offsets[message_index]
            code[position:position + 4] = target.to_bytes(4, "little")
        return bytes(code) + b"".join(self.messages)


def _setvar(variable, value):
    return bytes([_OP_SETVAR]) + _u16(variable) + _u16(value)


def _compare(variable, value):
    return bytes([_OP_COMPARE_VAR_TO_VALUE]) + _u16(variable) + _u16(value)


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
    if overall_completion:
        builder.emit(_setflag(FLAG_MYSTERY_GIFT_DONE))
        builder.emit(_setflag(receipt_flag))


def _emit_action(builder, action, *, sprite_id, failure_label):
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
        if action.moves:
            builder.emit(bytes([_OP_GETPARTYSIZE]))
            builder.emit(_compare(_VAR_RESULT, PARTY_SIZE))
            builder.vgoto_if(_COMPARE_EQ, failure_label)
        builder.emit(_givemon(action.species, action.level, action.held_item))
        builder.emit(_compare(_VAR_RESULT, MON_CANT_GIVE))
        builder.vgoto_if(_COMPARE_EQ, failure_label)
        for slot, move in enumerate(action.moves):
            builder.emit(bytes([_OP_SETMONMOVE, LAST_PARTY_MON_INDEX, slot]) + _u16(move))
    elif isinstance(action, GiveEgg):
        builder.emit(bytes([_OP_GIVEEGG]) + _u16(action.species))
        builder.emit(_compare(_VAR_RESULT, MON_CANT_GIVE))
        builder.vgoto_if(_COMPARE_EQ, failure_label)
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
    else:  # pragma: no cover - validation prevents this path.
        raise AssertionError(type(action))


def _failure_message(action):
    if isinstance(action, GiveItem):
        return action.failure_message or DEFAULT_BAG_FULL_MESSAGE
    if isinstance(action, GivePokemon):
        if action.failure_message:
            return action.failure_message
        return DEFAULT_PARTY_FULL_MESSAGE if action.moves else DEFAULT_STORAGE_FULL_MESSAGE
    if isinstance(action, GiveEgg):
        return action.failure_message or DEFAULT_STORAGE_FULL_MESSAGE
    return None


def _emit_plan(builder, stages, cursor, prefix, finished_label, failures,
               sprite_counter, *, receipt_flag, overall_completion=False):
    """Emit stage bodies after a dispatch and return the next sprite id."""
    for stage_index, (stage, source_path) in enumerate(stages):
        builder.label(_stage_label(prefix, stage_index))
        stage_start = len(builder.code)
        for action_index, action in enumerate(stage.actions):
            failure_label = f"{prefix}_failure_{stage_index}_{action_index}"
            message = _failure_message(action)
            if message is not None:
                failures.append((failure_label, message))
            if isinstance(action, BattlePokemon):
                _emit_battle_checkpoint(
                    builder, cursor, len(stages), receipt_flag=receipt_flag,
                    overall_completion=overall_completion)
            _emit_action(
                builder, action, sprite_id=sprite_counter,
                failure_label=failure_label)
            if isinstance(action, ShowSprite):
                sprite_counter += 1
        # Battle is validated as the final action. If it returns normally these
        # writes are harmless; the pre-battle checkpoint handles interruption.
        builder.emit(_setvar(cursor, stage_index + 1))
        if stage_index + 1 == len(stages):
            builder.vgoto(finished_label)
        builder.stage_sizes.append(
            (source_path, len(builder.code) - stage_start))
    return sprite_counter


def _build_card(card, *, flag_id, card_type, max_stamps):
    return build_wonder_card(
        flag_id=flag_id, icon_species=card.icon_species,
        id_number=card.id_number, card_type=card_type,
        bg_type=card.bg_type, send_type=card.send_type,
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
    # Saving a replacement Wonder Card clears the card-scoped state above but
    # not sReceivedGiftFlags. Incomplete/new composed gifts must therefore
    # clear their mapped receipt flag before beginning delivery.
    builder.emit(_clearflag(receipt_flag))
    _emit_cursor_dispatch(
        builder, VAR_MYSTERY_GIFT_1, stages,
        "main", "finish")
    _emit_plan(
        builder, stages, VAR_MYSTERY_GIFT_1, "main", "finish",
        failures, 0, receipt_flag=receipt_flag,
        overall_completion=not repeatable)

    builder.label("finish")
    if repeatable:
        builder.emit(_setvar(VAR_MYSTERY_GIFT_1, 0))
        builder.emit(_setflag(receipt_flag))
    else:
        builder.emit(_setflag(FLAG_MYSTERY_GIFT_DONE))
        builder.emit(_setflag(receipt_flag))
    builder.vgoto("exit")
    if not repeatable:
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
        card_type=CARD_TYPE_GIFT, max_stamps=0)
    return MysteryGiftDistribution(card, script)


# Mystery Event bytecode used by CLI_RUN_MEVENT_SCRIPT.
_ME_RUNSCRIPT = 5
_ME_END = 2


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
        cursor = VAR_MYSTERY_GIFT_2 + slot_index
        prefix = f"slot_{slot_index}"
        next_label = f"slot_{slot_index + 1}_dispatch"
        stages = _rally_entries(
            definition, slot.delivery,
            f"{definition.slug}.event.slots[{slot_index}].delivery")
        builder.label(f"slot_{slot_index}_dispatch")
        # Zero means absent. final_cursor means this slot is already delivered.
        builder.emit(_compare(cursor, 0))
        builder.vgoto_if(_COMPARE_EQ, next_label)
        final_cursor = len(stages) + 1
        builder.emit(_compare(cursor, final_cursor))
        builder.vgoto_if(_COMPARE_EQ, next_label)
        for stage_index in range(len(stages)):
            builder.emit(_compare(cursor, stage_index + 1))
            builder.vgoto_if(_COMPARE_EQ, _stage_label(prefix, stage_index))
        # Unknown/corrupt cursor values do not grant rewards.
        builder.vgoto(next_label)
        sprite_counter = _emit_plan(
            builder, stages, cursor, prefix, next_label,
            failures, sprite_counter, receipt_flag=receipt_flag)
        # Slot cursor values have an activation offset of one. Patch the
        # compiler-emitted post-stage setvar values in a simple explicit tail:
        # rather than byte surgery, each stage label gets an overriding cursor
        # write immediately after its actions via the helper below.
        # _emit_plan wrote 1..N; activation needs 2..N+1. Locate the last setvar
        # in every stage using the tracked labels and replace its immediate.
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
        cursor = VAR_MYSTERY_GIFT_2 + slot_index
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
        receipt_flag=receipt_flag, overall_completion=True)

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
        cursor = VAR_MYSTERY_GIFT_2 + slot_index
        stamp = _u16(slot.stamp_species) + _u16(slot.stamp_id)
        distributions[slot.slug] = MysteryGiftDistribution(
            card=card, ram_script=script, stamp=stamp,
            activation_script=_build_activation(
                cursor, receipt_flag=receipt_flag, install=False),
            install_activation_script=_build_activation(
                cursor, receipt_flag=receipt_flag, install=True))
    return distributions


def compile_definition(definition, *, flag_id=None):
    """Compile an ordinary gift or rally into host-ready distributions.

    Ordinary definitions return one :class:`MysteryGiftDistribution`.  Rally
    definitions return ``{slot_slug: distribution}``, one entry per stamp.
    """
    validate_definition(definition, flag_id=flag_id)
    actual_flag_id = definition.card.default_flag_id if flag_id is None else flag_id
    if isinstance(definition.event, GiftSpec):
        return _compile_gift(definition, actual_flag_id)
    return _compile_rally(definition, actual_flag_id)


__all__ = [
    "BattlePokemon", "DeliveryPlan", "DeliveryStage", "GiftSpec",
    "GiftValidationError", "GiveEgg", "GiveItem", "GivePokemon",
    "MapPosition", "Message", "RelativeToPlayer", "ShowSprite",
    "StampRallySpec", "StampSlot", "WonderCardSpec", "WonderGift",
    "FLAG_MYSTERY_GIFT_DONE", "MAX_RAM_SCRIPT_SIZE", "MAX_STAMP_SLOTS",
    "VAR_MYSTERY_GIFT_1", "VAR_MYSTERY_GIFT_2", "VAR_MYSTERY_GIFT_7",
    "compile_definition", "validate_definition",
]
