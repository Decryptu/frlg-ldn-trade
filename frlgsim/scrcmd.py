"""The field-script command table: one opcode number per command, and the event var ids the
commands take [asm/macros/event.inc, data/script_cmd_table.inc; decomp:src/scrcmd.c].

Every RAM script this project builds is assembled out of these bytes, whether the builder is
`gift_composer`, `wonder_card` or `stamp_rally`, so they are stated once here rather than once
per builder. `native_script` adds the two commands that stage and run code (`setptr` 0x11,
`callnative` 0x23); docs/mystery_gift_composer.md is the composer that emits the rest.
"""

OP_END = 0x02
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

def disassemble(data, base, start=None, limit=64):
    """-> lines of `ADDRESS  opcode  name  operands` for the script at `start` in a dump loaded at
    `base`. Stops at `end`/`return`, at an opcode with no fixed shape, or when the dump runs out."""
    from . import scrcmd_args, scrcmd_names
    data = bytes(data)
    cursor = (base if start is None else start) - base
    lines = []
    for _ in range(limit):
        if not 0 <= cursor < len(data):
            lines.append(f"  0x{base + cursor:08X}  (past the end of the dump)")
            break
        opcode = data[cursor]
        name = (scrcmd_names.COMMANDS[opcode] if opcode < scrcmd_names.SCRIPT_CMD_COUNT
                else "?")
        widths = scrcmd_args.ARGS.get(opcode)
        if widths is None:
            lines.append(f"  0x{base + cursor:08X}  {opcode:02X}  {name}: no fixed shape, stopping")
            break
        operands, at = [], cursor + 1
        for width in widths:
            chunk = data[at:at + width]
            if len(chunk) < width:
                operands.append("(truncated)")
                break
            operands.append(f"0x{int.from_bytes(chunk, 'little'):0{2 * width}X}")
            at += width
        lines.append(f"  0x{base + cursor:08X}  {opcode:02X}  {name} " + ", ".join(operands))
        cursor = at
        if opcode in (OP_END, 0x03):        # end, return
            break
    return lines


def looks_like_a_script(data, base, start, steps=6):
    """-> whether `steps` instructions decode with known shapes and stay inside the dump. A pointer
    into script data answers True; a pointer into code or a table does not, which is what makes
    this a check on gStdScripts rather than a rendering of it."""
    from . import scrcmd_args
    data, cursor = bytes(data), start - base
    for _ in range(steps):
        if not 0 <= cursor < len(data):
            return False
        widths = scrcmd_args.ARGS.get(data[cursor])
        if widths is None:
            return False
        cursor += 1 + sum(widths)
        if data[cursor - 1 - sum(widths)] in (OP_END, 0x03):
            return True
    return True
