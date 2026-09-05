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
