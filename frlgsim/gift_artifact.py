from __future__ import annotations

import hashlib
from pathlib import Path

from . import charmap, ereader_trainer
from .gift_composer import (
    BattleLegendary, BattlePokemon, GiftSpec, GiveEgg, GiveItem, GivePokemon,
    AddVar, Message, ReadSpecial, RequireSpecialResult, SetVar, ShowSprite,
    StampRallySpec,
    SPECIAL_START_LEGENDARY_BATTLE,
)
from .mystery_gift import crc16
from .save_inject import build_ram_script_struct


VIRTUAL_BASE = 0x08000000
MAX_RAM_SCRIPT_SIZE = 995


def _u16(data, offset):
    return int.from_bytes(data[offset:offset + 2], "little")


def _u32(data, offset):
    return int.from_bytes(data[offset:offset + 4], "little")


def _virtual_offset(pointer):
    return pointer - VIRTUAL_BASE if pointer >= VIRTUAL_BASE else None


def _event_text(data):
    fragments = []
    plain = bytearray()

    def flush():
        if plain:
            fragments.append(charmap.decode(bytes(plain)))
            plain.clear()

    index = 0
    while index < len(data):
        value = data[index]
        if value == 0xFF:
            flush()
            return "".join(fragments), index + 1
        if value == 0xFE:
            flush()
            fragments.append("\\n")
            index += 1
            continue
        if value == 0xFD and index + 1 < len(data) and data[index + 1] == 0x01:
            flush()
            fragments.append("{PLAYER}")
            index += 2
            continue
        plain.append(value)
        index += 1
    flush()
    return "".join(fragments), len(data)


def _action_summary(action):
    if isinstance(action, Message):
        return f'Message({action.text!r})'
    if isinstance(action, GiveItem):
        return f"GiveItem(item={action.item}, quantity={action.quantity})"
    if isinstance(action, GivePokemon):
        return f"GivePokemon(species={action.species}, level={action.level})"
    if isinstance(action, GiveEgg):
        return f"GiveEgg(species={action.species})"
    if isinstance(action, ShowSprite):
        return f"ShowSprite(graphics_id={action.graphics_id})"
    if isinstance(action, BattleLegendary):
        return f"BattleLegendary(species={action.species}, level={action.level})"
    if isinstance(action, BattlePokemon):
        return f"BattlePokemon(species={action.species}, level={action.level})"
    if isinstance(action, RequireSpecialResult):
        return (f"RequireSpecialResult(special_id={action.special_id}, "
                f"expected={action.expected})")
    if isinstance(action, SetVar):
        return f"SetVar(0x{action.variable:04X}, {action.value})"
    if isinstance(action, AddVar):
        return f"AddVar(0x{action.variable:04X}, +{action.value})"
    if isinstance(action, ReadSpecial):
        return f"ReadSpecial(0x{action.variable:04X}, special {action.special_id})"
    return type(action).__name__ + "()"


def _stage_summary(definition):
    if definition is None:
        return ["; Source definition metadata is unavailable for this legacy gift."]
    lines = ["; Source delivery plan:"]
    if isinstance(definition.event, GiftSpec):
        for index, stage in enumerate(definition.delivery.delivery):
            lines.extend(_one_stage_summary(
                f"{definition.slug}.delivery.delivery[{index}]", stage))
    elif isinstance(definition.event, StampRallySpec):
        lines.append("; Stamp-rally paths share one delivery script; see slot/completion entries.")
        for slot_index, slot in enumerate(definition.event.slots):
            for index, stage in enumerate(slot.delivery.pre_stages):
                lines.extend(_one_stage_summary(
                    f"{definition.slug}.slots[{slot_index}].pre_stages[{index}]", stage))
            for index, stage in enumerate(definition.delivery.delivery):
                lines.extend(_one_stage_summary(
                    f"{definition.slug}.shared.delivery[{index}]", stage))
            for index, stage in enumerate(slot.delivery.post_stages):
                lines.extend(_one_stage_summary(
                    f"{definition.slug}.slots[{slot_index}].post_stages[{index}]", stage))
    return lines


def _one_stage_summary(path, stage):
    condition = "" if stage.condition is None else f"; condition={stage.condition!r}"
    return [f"; {path} {condition}".rstrip(),
            *(f";   - {_action_summary(action)}" for action in stage.actions)]


def _instructions(script, code_end):
    simple = {
        0x02: "end", 0x09: "callstd obtain_item", 0x28: None,
        0x29: None, 0x2A: None, 0x2B: None, 0x42: None, 0x43: "getpartysize",
        0x46: None, 0x5A: "faceplayer", 0x66: "waitmessage",
        0x68: "closemessage", 0x6A: "lock", 0x6C: "release",
        0x6D: "waitbuttonpress", 0x79: None, 0x7A: None, 0x7B: None,
        0xAA: None, 0xB6: None, 0xB7: "dowildbattle", 0xB8: None,
        0xB9: None, 0xBB: None, 0xBD: None,
    }
    offset = 0
    while offset < code_end:
        opcode = script[offset]
        targets = ()
        if opcode == 0x16 and offset + 5 <= code_end:
            raw = script[offset:offset + 5]
            text = f"setvar 0x{_u16(script, offset + 1):04X}, {_u16(script, offset + 3)}"
        elif opcode == 0x17 and offset + 5 <= code_end:
            raw = script[offset:offset + 5]
            text = f"addvar 0x{_u16(script, offset + 1):04X}, {_u16(script, offset + 3)}"
        elif opcode == 0x1A and offset + 5 <= code_end:
            raw = script[offset:offset + 5]
            text = (f"setorcopyvar 0x{_u16(script, offset + 1):04X}, "
                    f"0x{_u16(script, offset + 3):04X}")
        elif opcode == 0x21 and offset + 5 <= code_end:
            raw = script[offset:offset + 5]
            text = f"compare 0x{_u16(script, offset + 1):04X}, {_u16(script, offset + 3)}"
        elif opcode == 0x25 and offset + 3 <= code_end:
            raw = script[offset:offset + 3]
            special_id = _u16(script, offset + 1)
            special_name = (
                "StartLegendaryBattle"
                if special_id == SPECIAL_START_LEGENDARY_BATTLE
                else f"special_{special_id}"
            )
            text = f"special {special_name} ({special_id})"
        elif opcode == 0x26 and offset + 5 <= code_end:
            raw = script[offset:offset + 5]
            text = f"specialvar 0x{_u16(script, offset + 1):04X}, {_u16(script, offset + 3)}"
        elif opcode in (0x28, 0x29, 0x2A, 0x2B) and offset + 3 <= code_end:
            raw = script[offset:offset + 3]
            names = {0x28: "delay", 0x29: "setflag", 0x2A: "clearflag", 0x2B: "checkflag"}
            text = f"{names[opcode]} 0x{_u16(script, offset + 1):04X}"
        elif opcode == 0x42 and offset + 5 <= code_end:
            raw = script[offset:offset + 5]
            text = (f"getplayerxy 0x{_u16(script, offset + 1):04X}, "
                    f"0x{_u16(script, offset + 3):04X}")
        elif opcode == 0x46 and offset + 5 <= code_end:
            raw = script[offset:offset + 5]
            text = (f"checkitemspace item={_u16(script, offset + 1)}, "
                    f"quantity={_u16(script, offset + 3)}")
        elif opcode == 0x79 and offset + 15 <= code_end:
            raw = script[offset:offset + 15]
            text = (f"givemon species={_u16(script, offset + 1)}, "
                    f"level={script[offset + 3]}, "
                    f"item={_u16(script, offset + 4)}")
        elif opcode == 0x7A and offset + 3 <= code_end:
            raw = script[offset:offset + 3]
            text = f"giveegg species={_u16(script, offset + 1)}"
        elif opcode == 0x7B and offset + 5 <= code_end:
            raw = script[offset:offset + 5]
            text = (f"setmonmove party={script[offset + 1]}, "
                    f"slot={script[offset + 2]}, "
                    f"move={_u16(script, offset + 3)}")
        elif opcode == 0xAA and offset + 9 <= code_end:
            raw = script[offset:offset + 9]
            text = (f"createvobject graphics={script[offset + 1]}, id={script[offset + 2]}, "
                    f"x=0x{_u16(script, offset + 3):04X}, y=0x{_u16(script, offset + 5):04X}, "
                    f"elevation={script[offset + 7]}, direction={script[offset + 8]}")
        elif opcode == 0xB6 and offset + 6 <= code_end:
            raw = script[offset:offset + 6]
            text = (f"setwildbattle species={_u16(script, offset + 1)}, "
                    f"level={script[offset + 3]}, "
                    f"item={_u16(script, offset + 4)}")
        elif opcode == 0xB8 and offset + 5 <= code_end:
            raw = script[offset:offset + 5]
            text = f"setvaddress 0x{_u32(script, offset + 1):08X}"
        elif opcode == 0xB9 and offset + 5 <= code_end:
            raw = script[offset:offset + 5]
            pointer = _u32(script, offset + 1)
            targets = (_virtual_offset(pointer),)
            text = f"vgoto 0x{pointer:08X}"
        elif opcode == 0xBB and offset + 6 <= code_end:
            raw = script[offset:offset + 6]
            pointer = _u32(script, offset + 2)
            targets = (_virtual_offset(pointer),)
            text = f"vgoto_if condition={script[offset + 1]}, 0x{pointer:08X}"
        elif opcode == 0xBD and offset + 5 <= code_end:
            raw = script[offset:offset + 5]
            pointer = _u32(script, offset + 1)
            targets = (_virtual_offset(pointer),)
            text = f"vmessage 0x{pointer:08X}"
        elif opcode in simple and simple[opcode] is not None:
            raw = script[offset:offset + (2 if opcode == 0x09 else 1)]
            text = simple[opcode]
        else:
            raw = script[offset:offset + 1]
            text = f".byte 0x{opcode:02X}  ; unknown or truncated opcode"
        yield offset, raw, text, tuple(target for target in targets if target is not None)
        offset += len(raw)


def _trainer_summary(distribution):
    """The visiting trainer travels beside the card, so the artifact has to account for it too."""
    trainer = getattr(distribution, "trainer", None)
    if trainer is None:
        return ()
    party = []
    for index in range(ereader_trainer.PARTY_SIZE):
        start = 0x34 + index * ereader_trainer.MON_SIZE
        mon = trainer[start:start + ereader_trainer.MON_SIZE]
        moves = ", ".join(str(int.from_bytes(mon[4 + i * 2:6 + i * 2], "little"))
                          for i in range(4))
        party.append(
            f";   {charmap.decode(mon[0x20:0x2B])}: species "
            f"{int.from_bytes(mon[0:2], 'little')} Lv{mon[0x0C]} "
            f"item {int.from_bytes(mon[2:4], 'little')} moves [{moves}]")
    return (
        f"; Visiting trainer: {len(trainer)} bytes, "
        f"checksum 0x{int.from_bytes(trainer[0xB8:0xBC], 'little'):08X} "
        f"(valid={ereader_trainer.validate(trainer)})",
        f";   name {charmap.decode(trainer[4:12])!r} "
        f"(the console displays {charmap.decode(trainer[4:12])[:5]!r}), "
        f"facility class {trainer[1]}",
        *party,
    )


def render_artifact(*, gift, flag_id, distribution, definition=None):
    script = distribution.ram_script
    message_targets = []
    for offset, raw, text, targets in _instructions(script, len(script)):
        if raw[0] == 0xBD:
            message_targets.extend(targets)
    code_end = min((target for target in message_targets if 0 <= target < len(script)),
                   default=len(script))
    instructions = tuple(_instructions(script, code_end))
    branch_targets = {target for _offset, raw, _text, targets in instructions
                      if raw[0] in (0xB9, 0xBB) for target in targets
                      if 0 <= target < code_end}
    labels = {target: f"L_{target:04X}" for target in sorted(branch_targets)}
    message_offsets = sorted({target for _offset, raw, _text, targets in instructions
                              if raw[0] == 0xBD for target in targets
                              if code_end <= target < len(script)})
    messages = {}
    for offset in message_offsets:
        text, size = _event_text(script[offset:])
        messages[offset] = (text, script[offset:offset + size])

    ram_data, ram_crc = build_ram_script_struct(script)
    lines = [
        f"; Mystery Gift artifact: {gift}",
        f"; Wonder Card flag ID: {flag_id}",
        f"; RAM script: {len(script)} / {MAX_RAM_SCRIPT_SIZE} bytes",
        f"; RAM script SHA-256: {hashlib.sha256(script).hexdigest()}",
        f"; Wonder Card CRC-16: 0x{crc16(distribution.card):04X}",
        f"; RamScriptData CRC-16: 0x{ram_crc:04X} ({len(ram_data)} bytes)",
        "; Offsets are from the beginning of the raw 995-byte-capacity RAM script.",
        "; Branch/message operands are virtual addresses based at 0x08000000.",
        *_trainer_summary(distribution),
        "",
        *_stage_summary(definition),
        "",
        "; Generated field script:",
    ]
    for offset, raw, text, targets in instructions:
        if offset in labels:
            lines.append(f"{labels[offset]}:")
        suffix = ""
        if raw[0] in (0xB9, 0xBB) and targets:
            suffix = f"  ; -> {labels.get(targets[0], f'0x{targets[0]:04X}') }"
        if raw[0] == 0xBD and targets:
            suffix = f"  ; -> text_{targets[0]:04X}"
        lines.append(f"{offset:04X}  {raw.hex(' ').upper():<23}  {text}{suffix}")
    if messages:
        lines.extend(("", "; Message data:"))
        for offset, (text, raw) in messages.items():
            lines.append(f"text_{offset:04X}:")
            lines.append(f"{offset:04X}  {raw.hex(' ').upper()}  {text!r}")
    if distribution.is_stamp:
        lines.extend((
            "", "; Stamp package extras:",
            f"; stamp: {distribution.stamp.hex(' ').upper()}",
            f"; activation_script: {distribution.activation_script.hex(' ').upper()}",
            "; install_activation_script: "
            f"{distribution.install_activation_script.hex(' ').upper()}",
        ))
    return "\n".join(lines) + "\n"


def write_artifact(directory, *, gift, flag_id, distribution, definition=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(distribution.ram_script).hexdigest()[:12]
    path = directory / f"{gift}-{flag_id}-{digest}.ram.lst"
    path.write_text(render_artifact(
        gift=gift, flag_id=flag_id, distribution=distribution,
        definition=definition), encoding="utf-8")
    return path
