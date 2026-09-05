"""The 214 field-script command handlers, in table order [decomp:data/script_cmd_table.inc].

The index IS the opcode: `gScriptCmdTable[opcode]` is the handler the field engine `bx`es to
[ScriptContext_Run, src/script.c]. Generated from the decomp; the names are the decomp's with the
`ScrCmd_` prefix dropped. `frlgsim/scrcmd.py` holds the opcodes this project actually emits.

The table's own address is not searched for: `script_data` opens with it and puts `gSpecialVars`
immediately after [ld_script_rev10.ld:318], and gSpecialVars was measured at bs57, so the table
starts SCRIPT_CMD_TABLE_SIZE bytes below it. docs/buffer_script.md.
"""

COMMANDS = (
    "nop", "nop1", "end", "return",
    "call", "goto", "goto_if", "call_if",
    "gotostd", "callstd", "gotostd_if", "callstd_if",
    "returnram", "endram", "setmysteryeventstatus", "loadword",
    "loadbyte", "setptr", "loadbytefromptr", "setptrbyte",
    "copylocal", "copybyte", "setvar", "addvar",
    "subvar", "copyvar", "setorcopyvar", "compare_local_to_local",
    "compare_local_to_value", "compare_local_to_ptr", "compare_ptr_to_local", "compare_ptr_to_value",
    "compare_ptr_to_ptr", "compare_var_to_value", "compare_var_to_var", "callnative",
    "gotonative", "special", "specialvar", "waitstate",
    "delay", "setflag", "clearflag", "checkflag",
    "initclock", "dotimebasedevents", "gettime", "playse",
    "waitse", "playfanfare", "waitfanfare", "playbgm",
    "savebgm", "fadedefaultbgm", "fadenewbgm", "fadeoutbgm",
    "fadeinbgm", "warp", "warpsilent", "warpdoor",
    "warphole", "warpteleport", "setwarp", "setdynamicwarp",
    "setdivewarp", "setholewarp", "getplayerxy", "getpartysize",
    "additem", "removeitem", "checkitemspace", "checkitem",
    "checkitemtype", "addpcitem", "checkpcitem", "adddecoration",
    "removedecoration", "checkdecor", "checkdecorspace", "applymovement",
    "applymovementat", "waitmovement", "waitmovementat", "removeobject",
    "removeobjectat", "addobject", "addobjectat", "setobjectxy",
    "showobjectat", "hideobjectat", "faceplayer", "turnobject",
    "trainerbattle", "dotrainerbattle", "gotopostbattlescript", "gotobeatenscript",
    "checktrainerflag", "settrainerflag", "cleartrainerflag", "setobjectxyperm",
    "copyobjectxytoperm", "setobjectmovementtype", "waitmessage", "message",
    "closemessage", "lockall", "lock", "releaseall",
    "release", "waitbuttonpress", "yesnobox", "multichoice",
    "multichoicedefault", "multichoicegrid", "drawbox", "erasebox",
    "drawboxtext", "showmonpic", "hidemonpic", "showcontestpainting",
    "braillemessage", "givemon", "giveegg", "setmonmove",
    "checkpartymove", "bufferspeciesname", "bufferleadmonspeciesname", "bufferpartymonnick",
    "bufferitemname", "bufferdecorationname", "buffermovename", "buffernumberstring",
    "bufferstdstring", "bufferstring", "pokemart", "pokemartdecoration",
    "pokemartdecoration2", "playslotmachine", "setberrytree", "choosecontestmon",
    "startcontest", "showcontestresults", "contestlinktransfer", "random",
    "addmoney", "removemoney", "checkmoney", "showmoneybox",
    "hidemoneybox", "updatemoneybox", "getpokenewsactive", "fadescreen",
    "fadescreenspeed", "setflashlevel", "animateflash", "messageautoscroll",
    "dofieldeffect", "setfieldeffectargument", "waitfieldeffect", "setrespawn",
    "checkplayergender", "playmoncry", "setmetatile", "resetweather",
    "setweather", "doweather", "setstepcallback", "setmaplayoutindex",
    "setobjectsubpriority", "resetobjectsubpriority", "createvobject", "turnvobject",
    "opendoor", "closedoor", "waitdooranim", "setdooropen",
    "setdoorclosed", "addelevmenuitem", "showelevmenu", "checkcoins",
    "addcoins", "removecoins", "setwildbattle", "dowildbattle",
    "setvaddress", "vgoto", "vcall", "vgoto_if",
    "vcall_if", "vmessage", "vbuffermessage", "vbufferstring",
    "showcoinsbox", "hidecoinsbox", "updatecoinsbox", "incrementgamestat",
    "setescapewarp", "waitmoncry", "bufferboxname", "textcolor",
    "loadhelp", "unloadhelp", "signmsg", "normalmsg",
    "comparestat", "setmonmodernfatefulencounter", "checkmonmodernfatefulencounter", "trywondercardscript",
    "setworldmapflag", "warpspinenter", "setmonmetlocation", "getbraillestringwidth",
    "bufferitemnameplural", "nop",
)

SCRIPT_CMD_COUNT = len(COMMANDS)
SCRIPT_CMD_TABLE_SIZE = SCRIPT_CMD_COUNT * 4


def read_table(dump, base):
    """-> [(opcode, name, address, thumb_bit)] for a dump of gScriptCmdTable at `base`."""
    out = []
    for i in range(min(SCRIPT_CMD_COUNT, len(dump) // 4)):
        value = int.from_bytes(bytes(dump[4 * i:4 * i + 4]), "little")
        out.append((i, COMMANDS[i], value & ~1, bool(value & 1)))
    return out


def plausible(entries, low=0x08000000, high=0x08400000):
    """-> the entries that look like THUMB ROM function pointers, which is what every one should be.
    A table read at the wrong address fails this immediately."""
    return [e for e in entries if low <= e[2] < high and e[3]]


# --- measured, bs82 -----------------------------------------------------------------------------
# The table read off the console at G_SCRIPT_CMD_TABLE, 856 bytes in one dump. Every one of the 214
# words came back a THUMB pointer into 0x0806D7C0..0x080700B8, and the ONLY two entries sharing an
# address are 0 and 213 - exactly the two the decomp names ScrCmd_nop, with ScrCmd_nop1 distinct at
# index 1. An off-by-one read of the table cannot produce that, which is what makes the derived
# address a measurement rather than an assumption. The thumb bit is stripped; add it back for a bx.
HANDLERS = (
    0x0806D7C0, 0x0806D7C4, 0x0806D7C8, 0x0806D888,
    0x0806D894, 0x0806D870, 0x0806D8AC, 0x0806D8E8,
    0x0806DA10, 0x0806DA40, 0x0806DA70, 0x0806DABC,
    0x0806DB08, 0x0806DB1C, 0x0806DB34, 0x0806DB74,
    0x0806DBD4, 0x0806DBBC, 0x0806DB98, 0x0806DBF0,
    0x0806DC14, 0x0806DC34, 0x0806DC50, 0x0806DE44,
    0x0806DE6C, 0x0806DC74, 0x0806DCA0, 0x0806DCEC,
    0x0806DD1C, 0x0806DD44, 0x0806DD70, 0x0806DD9C,
    0x0806DDBC, 0x0806DDE0, 0x0806DE10, 0x0806D854,
    0x0806D7D4, 0x0806D7EC, 0x0806D814, 0x0806D864,
    0x0806E270, 0x0806E0EC, 0x0806E100, 0x0806E114,
    0x0806E294, 0x0806E298, 0x0806E29C, 0x0806E928,
    0x0806E954, 0x0806E968, 0x0806E98C, 0x0806E9A0,
    0x0806E9E0, 0x0806E9F4, 0x0806EA14, 0x0806EA3C,
    0x0806EA88, 0x0806E324, 0x0806E3AC, 0x0806E434,
    0x0806E4BC, 0x0806E530, 0x0806E64C, 0x0806E6CC,
    0x0806E750, 0x0806E7D0, 0x0806E8D0, 0x0806E90C,
    0x0806DED0, 0x0806DF1C, 0x0806DF60, 0x0806DFA4,
    0x0806DFE8, 0x0806E014, 0x0806E058, 0x0806E09C,
    0x0806E0B0, 0x0806E0D8, 0x0806E0C4, 0x0806EAC0,
    0x0806EB04, 0x0806EB70, 0x0806EBC4, 0x0806EC18,
    0x0806EC40, 0x0806EC70, 0x0806EC98, 0x0806ECC8,
    0x0806EDB0, 0x0806EDE0, 0x0806EE7C, 0x0806EEB4,
    0x0806FB38, 0x0806FB4C, 0x0806FB58, 0x0806FB6C,
    0x0806FB80, 0x0806FBA4, 0x0806FBC0, 0x0806ED30,
    0x0806ED88, 0x0806EEE8, 0x0806F138, 0x0806F0CC,
    0x0806F14C, 0x0806EF9C, 0x0806EFC4, 0x0806F01C,
    0x0806F054, 0x0806F2FC, 0x0806F340, 0x0806F36C,
    0x0806F3A8, 0x0806F3FC, 0x0806F3F8, 0x0806F44C,
    0x0806F458, 0x0806F45C, 0x0806F498, 0x0806F4B8,
    0x0806F4C4, 0x0806F834, 0x0806F8C4, 0x0806F8F0,
    0x0806F91C, 0x0806F548, 0x0806F588, 0x0806F5D4,
    0x0806F61C, 0x0806F698, 0x0806F6B4, 0x0806F6F4,
    0x0806F738, 0x0806F778, 0x0806FC20, 0x0806FC34,
    0x0806FC48, 0x0806FC5C, 0x0806FC84, 0x0806FC8C,
    0x0806FC98, 0x0806FC9C, 0x0806FCA0, 0x0806DE9C,
    0x0806F998, 0x0806F9CC, 0x0806FA00, 0x0806FA40,
    0x0806FA90, 0x0806FA9C, 0x0806FC88, 0x0806E1F8,
    0x0806E220, 0x0806E1BC, 0x0806E1A0, 0x0806F11C,
    0x0806FCA4, 0x0806FCCC, 0x0806FD1C, 0x0806FD48,
    0x0806FD64, 0x0806FD7C, 0x0806FDC8, 0x0806E2D8,
    0x0806E2BC, 0x0806E2E4, 0x0806E2F0, 0x0806E308,
    0x0806EE10, 0x0806EE4C, 0x0806EF10, 0x0806EF80,
    0x0806FE48, 0x0806FEA0, 0x0806FEFC, 0x0806FF10,
    0x0806FF54, 0x0806FF98, 0x0806FF9C, 0x0806FFA0,
    0x0806FFC0, 0x0806FFF8, 0x0806FBDC, 0x0806FC10,
    0x0806D924, 0x0806D940, 0x0806D964, 0x0806D988,
    0x0806D9CC, 0x0806F52C, 0x0806F7A0, 0x0806F7C4,
    0x0806FACC, 0x0806FB08, 0x0806FB1C, 0x0806E130,
    0x0806E850, 0x0806FDB4, 0x0806F7F8, 0x0806F0AC,
    0x0806F0E8, 0x0806F110, 0x08070030, 0x0807003C,
    0x0806E148, 0x08070048, 0x08070080, 0x0806DB4C,
    0x0806E180, 0x0806E5B8, 0x080700B8, 0x0806F500,
    0x0806F650, 0x0806D7C0,
)


def handler(name):
    """-> the ROM address of a field-script command's handler, by the decomp's name without the
    `ScrCmd_` prefix. `nop` resolves to opcode 0, the first of its two entries."""
    return HANDLERS[COMMANDS.index(name)]
