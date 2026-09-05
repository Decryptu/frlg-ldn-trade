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
