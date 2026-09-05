"""The field-script command table: one opcode number per command, and the event var ids the
commands take [asm/macros/event.inc, data/script_cmd_table.inc; decomp:src/scrcmd.c].

Every RAM script this project builds is assembled out of these bytes, whether the builder is
`gift_composer`, `wonder_card` or `stamp_rally`, so they are stated once here rather than once
per builder. `native_script` adds the two commands that stage and run code (`setptr` 0x11,
`callnative` 0x23); docs/mystery_gift_composer.md is the composer that emits the rest.
"""

OP_END = 0x02
OP_RETURN = 0x03
OP_GOTO = 0x05
OP_GOTOSTD = 0x08
OP_CALLSTD = 0x09
OP_COPYBYTE = 0x15
OP_SETVAR = 0x16
OP_ADDVAR = 0x17
OP_SETVAR_OR_COPY = 0x1A
OP_COMPARE_VAR_TO_VALUE = 0x21
OP_SPECIAL = 0x25
OP_SPECIALVAR = 0x26
OP_DELAY = 0x28
OP_SETFLAG = 0x29
OP_CLEARFLAG = 0x2A
OP_CHECKFLAG = 0x2B
OP_PLAYFANFARE = 0x31
OP_GETPLAYERXY = 0x42
OP_GETPARTYSIZE = 0x43
OP_CHECKITEMSPACE = 0x46
OP_FACEPLAYER = 0x5A
OP_WAITMESSAGE = 0x66
OP_CLOSEMESSAGE = 0x68
OP_LOCK = 0x6A
OP_RELEASE = 0x6C
OP_WAITBUTTONPRESS = 0x6D
OP_GIVEMON = 0x79
OP_GIVEEGG = 0x7A
OP_SETMONMOVE = 0x7B
OP_BUFFERNUMBERSTRING = 0x83
OP_CREATEVOBJECT = 0xAA
OP_SETWILDBATTLE = 0xB6
OP_DOWILDBATTLE = 0xB7
OP_SETVADDRESS = 0xB8
OP_VGOTO = 0xB9
OP_VGOTO_IF = 0xBB
OP_VMESSAGE = 0xBD
OP_SETMONMODERNFATEFULENCOUNTER = 0xCD
OP_SETMONMETLOCATION = 0xD2

COMPARE_EQ = 1
COMPARE_NE = 5

VAR_0x8000 = 0x8000
VAR_0x8001 = 0x8001
VAR_0x8002 = 0x8002
VAR_0x8003 = 0x8003
VAR_0x8008 = 0x8008
VAR_PLAYER_X = 0x8004
VAR_PLAYER_Y = 0x8005
VAR_RESULT = 0x800D
VAR_STARTER_MON = 0x4031        # 0 Bulbasaur, 1 Squirtle, 2 Charmander

STD_OBTAIN_ITEM = 0             # gStdScripts index [event_scripts.s:78]

# A saved RAM script is copied to a fixed EWRAM address and run from there, but its vgoto/vmessage
# operands are relocated against this base [setvaddress, src/scrcmd.c].
RAM_SCRIPT_VIRTUAL_BASE = 0x08000000


# --- reading a script the console holds -----------------------------------------------------------
# The opcode table is bs82's (scrcmd_names.COMMANDS) and the operand widths are the decomp's own
# macros (scrcmd_args.ARGS, generated). Together they turn a dump into the script it is - which is
# the only way to check a pointer into script data is really a script. docs/buffer_script.md.

# Control never falls through these, so a linear walk stops: they are where one script ends and the
# next begins. `goto` is in the set because the decomp's own labels sit right behind one -
# EventScript_TryDoNormalTrainerBattle ends `goto EventScript_DoTrainerBattle` and
# EventScript_NoTrainerBattle is the next byte [data/scripts/trainer_battle.inc:17].
TERMINATORS = (OP_END, OP_RETURN, OP_GOTO, OP_GOTOSTD)


def shape(data, base, cursor):
    """-> (name, operands, length) for the instruction at offset `cursor`, or None if there is not
    one there. An operand is (width, value). `length` counts the opcode byte.

    Most commands have one fixed shape [scrcmd_args.ARGS]. The trainerbattle family has a fixed
    head and a tail chosen by the head's own type byte [scrcmd_args.VARIABLE]: a type outside that
    table is not a trainerbattle at all, so this answers None rather than walk on at a guessed
    length - which is the whole point, since every byte after a mis-measured instruction is noise.
    """
    from . import scrcmd_args, scrcmd_names
    if not 0 <= cursor < len(data):
        return None
    opcode = data[cursor]
    name = scrcmd_names.COMMANDS[opcode] if opcode < scrcmd_names.SCRIPT_CMD_COUNT else "?"

    def read(widths, at):
        operands = []
        for width in widths:
            chunk = data[at:at + width]
            if len(chunk) < width:
                return None, at
            operands.append((width, int.from_bytes(chunk, "little")))
            at += width
        return operands, at

    widths = scrcmd_args.ARGS.get(opcode)
    if widths is not None:
        operands, at = read(widths, cursor + 1)
        return None if operands is None else (name, operands, at - cursor)

    variable = scrcmd_args.VARIABLE.get(opcode)
    if variable is None:
        return None
    head, at = read(variable["head"], cursor + 1)
    if head is None:
        return None
    tail_widths = variable["tails"].get(head[variable["select"]][1])
    if tail_widths is None:
        return None
    tail, at = read(tail_widths, at)
    return None if tail is None else (name, head + tail, at - cursor)


def disassemble(data, base, start=None, limit=64):
    """-> lines of `ADDRESS  opcode  name  operands` for the script at `start` in a dump loaded at
    `base`. Stops at a TERMINATOR, at an opcode it cannot measure, or when the dump runs out."""
    from . import scrcmd_names
    data = bytes(data)
    cursor = (base if start is None else start) - base
    lines = []
    for _ in range(limit):
        if not 0 <= cursor < len(data):
            lines.append(f"  0x{base + cursor:08X}  (past the end of the dump)")
            break
        opcode = data[cursor]
        measured = shape(data, base, cursor)
        if measured is None:
            name = (scrcmd_names.COMMANDS[opcode] if opcode < scrcmd_names.SCRIPT_CMD_COUNT
                    else "?")
            lines.append(f"  0x{base + cursor:08X}  {opcode:02X}  {name}: "
                         "no shape here, stopping")
            break
        name, operands, length = measured
        rendered = ", ".join(f"0x{value:0{2 * width}X}" for width, value in operands)
        lines.append(f"  0x{base + cursor:08X}  {opcode:02X}  {name} " + rendered)
        cursor += length
        if opcode in TERMINATORS:
            break
    return lines


def looks_like_a_script(data, base, start, steps=6):
    """-> whether `steps` instructions decode with known shapes and stay inside the dump. A pointer
    into script data answers True; a pointer into code or a table does not, which is what makes
    this a check on gStdScripts rather than a rendering of it."""
    data, cursor = bytes(data), start - base
    for _ in range(steps):
        measured = shape(data, base, cursor)
        if measured is None:
            return False
        if data[cursor] in TERMINATORS:
            return True
        cursor += measured[2]
    return True
