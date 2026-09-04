"""CLI_RUN_BUFFER_SCRIPT: native ARM code the console executes out of gDecompressionBuffer.

The last unopened door in the Mystery Gift client. Client_Run copies our whole 1024-byte receive
buffer into gDecompressionBuffer and then calls it every frame until it returns 1
[decomp:src/mystery_gift_client.c:237,276]:

    u32 (*func)(u32 *, struct SaveBlock2 *, struct SaveBlock1 *) = (void *)gDecompressionBuffer;
    if (func(&client->param, gSaveBlock2Ptr, gSaveBlock1Ptr) == 1)

so a payload gets r0 = &client->param, r1 = gSaveBlock2Ptr, r2 = gSaveBlock1Ptr, and whatever it
leaves in *param comes back to us through the CLI_LOAD_TOSS_RESPONSE + CLI_SEND_LOADED return
channel already proven by the Mystery Event VM [mg_script.py, docs/mystery_event.md].

FACT: the payload is ARM, not THUMB. The console reaches it with a bx through a function pointer,
which selects the state from bit 0 of the address, and gDecompressionBuffer is word aligned.
DEDUCTION: it sits at 0x0201C000 - ld_script.ld puts ewram at 0x2000000 under ALIGN(4), reserves
gHeap 0x1C000, then links src/main.o(ewram_data) first, whose first EWRAM_DATA is
gDecompressionBuffer [src/main.c:87]. Nothing here depends on that address: every payload is
position independent, and the deduction is recorded only because a later payload may want it.

`emulate` runs a payload against a model of the GBA memory map (unicorn), which is how a payload
is proven before it is ever put on the air.
"""

from dataclasses import dataclass

from .buffer_payloads import PAYLOADS

# MG_LINK_BUFFER_SIZE [decomp:include/mystery_gift_link.h:4]. Client_Run memcpys exactly this many
# bytes, but the link only fills what we actually send, so a payload must be self-contained.
MAX_BUFFER_SCRIPT_SIZE = 0x400

# Where the console runs it from (see the deduction above). Documentation, not a dependency.
GDECOMPRESSION_BUFFER = 0x0201C000

# The value a payload returns to end the call. Anything else means "call me again next frame"
# [decomp:src/mystery_gift_client.c:279], which is a hang if the payload never changes its mind.
BUFFER_SCRIPT_DONE = 1

# struct SaveBlock2 [decomp:include/global.h:327].
SAV2_PLAYER_NAME = 0x00
SAV2_PLAYER_GENDER = 0x08
SAV2_PLAYER_TRAINER_ID = 0x0A

TRAINER_ID_PROBE = "trainer-id-probe"

# What the host checks the returned u32 against. The trainer id is the one oracle the console can
# be asked for twice by two different routes: our ARM code reads gSaveBlock2Ptr directly, and the
# ROM had already assembled the same field into the MysteryGiftLinkGameData we read seconds
# earlier. Agreement is proof the payload ran, with the arguments the decomp promises, on the real
# save - not a coincidence and not an echo of anything we sent.
EXPECT_TRAINER_ID = "trainer-id"


class BufferScriptError(ValueError):
    """A payload that the console could not safely be asked to run.

    A ValueError so that the config layer and the host CLI, which turn ValueError into
    parser.error, report a bad operand as a refusal rather than a traceback.
    """


def payload(name):
    """The committed machine code for one asm/<name>.s."""
    try:
        code = PAYLOADS[name][0]
    except KeyError:
        raise BufferScriptError(
            f"unknown buffer script {name!r}; have {sorted(PAYLOADS)}") from None
    validate(code)
    return code


def validate(code):
    """Everything checkable about a payload without running it."""
    if not isinstance(code, (bytes, bytearray)):
        raise BufferScriptError("a buffer script is raw ARM machine code")
    if not code:
        raise BufferScriptError("a buffer script is empty")
    if len(code) > MAX_BUFFER_SCRIPT_SIZE:
        raise BufferScriptError(
            f"a buffer script is at most {MAX_BUFFER_SCRIPT_SIZE} bytes, got {len(code)}")
    if len(code) % 4:
        # The console enters in ARM state; a payload that is not a whole number of ARM words
        # either has a data tail it never reaches or was assembled for the wrong state.
        raise BufferScriptError(
            f"ARM code is a multiple of 4 bytes, got {len(code)}")
    return code



@dataclass(frozen=True)
class BufferScriptSpec:
    """One payload: what it does, and what its answer should be checked against."""
    name: str
    description: str
    expect: object          # EXPECT_TRAINER_ID, a u32 we demanded, or None for "any answer"


MEMORY_DUMP = "memory-dump"
SAVE_DUMP = "save-dump"

# save-dump's operands, from its disassembly: ldr [pc,#36] -> 0x2C, [pc,#24] -> 0x30,
# [pc,#16] -> 0x34. Proven by emulating a patched payload, not by trusting these.
SAVE_DUMP_WHICH_OFFSET = 0x2C
SAVE_DUMP_OFFSET_OFFSET = 0x30
SAVE_DUMP_SIZE_OFFSET = 0x34

SAVE_BLOCK_2 = "sav2"       # r1, struct SaveBlock2: name, trainer id, pokedex, battle tower
SAVE_BLOCK_1 = "sav1"       # r2, struct SaveBlock1: party, bag, money, flags, vars
SAVE_BLOCKS = (SAVE_BLOCK_2, SAVE_BLOCK_1)

# Where build_memory_dump patches its two operands. The payload is six ARM instructions followed by
# a two-word literal pool; the disassembly reads `ldr r3, [pc, #16]` -> 0x18 and
# `ldr r3, [pc, #12]` -> 0x1C, and test_the_dump_payload_operands_are_where_we_patch_them proves it
# by emulating a patched payload rather than by trusting these numbers.
DUMP_TARGET_OFFSET = 0x18
DUMP_SIZE_OFFSET = 0x1C

SCRIPT_REGISTRY = {
    TRAINER_ID_PROBE: BufferScriptSpec(
        TRAINER_ID_PROBE,
        "read playerTrainerId out of gSaveBlock2Ptr and return it (reads only, writes nothing)",
        EXPECT_TRAINER_ID),
    SAVE_DUMP: BufferScriptSpec(
        SAVE_DUMP,
        "read out any part of either save block, using the pointers the console hands us - no "
        "absolute address needed (reads only, writes nothing)",
        None),
    MEMORY_DUMP: BufferScriptSpec(
        MEMORY_DUMP,
        "read out any region of the console's memory by repointing the console's own outgoing "
        "message at it (needs --dump-address; reads only, writes nothing)",
        None),
}


def build_save_dump(block=SAVE_BLOCK_2, offset=0, size=MAX_BUFFER_SCRIPT_SIZE):
    """The save-dump payload, patched to read `size` bytes at `offset` into one save block.

    Needs no absolute address: Client_RunBufferScript passes gSaveBlock2Ptr and gSaveBlock1Ptr
    [decomp:src/mystery_gift_client.c:276], so the payload works on any console and any build.
    """
    if block not in SAVE_BLOCKS:
        raise BufferScriptError(f"block is one of {SAVE_BLOCKS}, got {block!r}")
    offset, size = int(offset), int(size)
    if not 0 < size <= MAX_BUFFER_SCRIPT_SIZE:
        raise BufferScriptError(
            f"a dump is 1..{MAX_BUFFER_SCRIPT_SIZE} bytes (MG_LINK_BUFFER_SIZE), got {size}")
    if offset < 0 or offset % 2:
        raise BufferScriptError(f"offset {offset} must be positive and halfword aligned")
    code = bytearray(payload(SAVE_DUMP))
    code[SAVE_DUMP_WHICH_OFFSET:SAVE_DUMP_WHICH_OFFSET + 4] = (
        (0 if block == SAVE_BLOCK_2 else 1).to_bytes(4, "little"))
    code[SAVE_DUMP_OFFSET_OFFSET:SAVE_DUMP_OFFSET_OFFSET + 4] = offset.to_bytes(4, "little")
    code[SAVE_DUMP_SIZE_OFFSET:SAVE_DUMP_SIZE_OFFSET + 4] = size.to_bytes(4, "little")
    return bytes(code)


def build_memory_dump(address, size=MAX_BUFFER_SCRIPT_SIZE):
    """The memory-dump payload with its target address and length patched in.

    `size` is what link->sendSize becomes, so it is bounded by what the receiving side will accept:
    MGL_Receive rejects anything past MG_LINK_BUFFER_SIZE outright
    [decomp:src/mystery_gift_link.c:102].
    """
    address = int(address)
    size = int(size)
    if not 0 < size <= MAX_BUFFER_SCRIPT_SIZE:
        raise BufferScriptError(
            f"a dump is 1..{MAX_BUFFER_SCRIPT_SIZE} bytes (MG_LINK_BUFFER_SIZE), got {size}")
    if not 0 <= address <= 0xFFFFFFFF:
        raise BufferScriptError(f"0x{address:X} is not a 32-bit address")
    if address % 2:
        # CalcCRC16WithTable walks the region and the link sends it in halfwords; an odd base
        # would also make every later offset calculation lie about what was read.
        raise BufferScriptError(f"0x{address:X} is not halfword aligned")
    code = bytearray(payload(MEMORY_DUMP))
    code[DUMP_TARGET_OFFSET:DUMP_TARGET_OFFSET + 4] = address.to_bytes(4, "little")
    code[DUMP_SIZE_OFFSET:DUMP_SIZE_OFFSET + 4] = size.to_bytes(4, "little")
    return bytes(code)


def script_choices():
    return tuple(sorted(SCRIPT_REGISTRY))


def format_script_help():
    return "; ".join(f"{spec.name}: {spec.description}"
                     for spec in SCRIPT_REGISTRY.values())

def describe(code):
    for name, (committed, _) in PAYLOADS.items():
        if bytes(code[:len(committed)]) == committed:
            return f"{name} ({len(committed)} bytes of ARM)"
    return f"unknown buffer script ({len(code)} bytes of ARM, head {bytes(code[:8]).hex()})"


# --- The client the payload is called from -------------------------------------------------------
# r0 is &client->param, and everything else in struct MysteryGiftClient
# [decomp:include/mystery_gift_client.h:71] is at a fixed offset from it. That makes the console's
# own outgoing message reachable: MysteryGiftLink_InitSend stores the POINTER
# [decomp:src/mystery_gift_link.c:59] and the CRC is taken later, at send time, over
# link->sendBuffer for link->sendSize bytes [mystery_gift_link.c:166]. A payload that repoints
# those two fields between the InitSend and the send makes the console read out any address it
# likes, with a CRC the console computes for us.
CLIENT_UNUSED = 0x00
CLIENT_PARAM = 0x04                 # what r0 points at
CLIENT_FUNC_ID = 0x08
CLIENT_FUNC_STATE = 0x0C
CLIENT_CMDIDX = 0x10
CLIENT_SEND_BUFFER = 0x14
CLIENT_RECV_BUFFER = 0x18
CLIENT_SCRIPT = 0x1C
CLIENT_MSG = 0x20
CLIENT_LINK = 0x24

# struct MysteryGiftLink [decomp:include/mystery_gift_link.h].
LINK_STATE = 0x00
LINK_SEND_IDENT = 0x0E
LINK_SEND_COUNTER = 0x10
LINK_SEND_CRC = 0x12
LINK_SEND_SIZE = 0x14
LINK_RECV_BUFFER = 0x18
LINK_SEND_BUFFER = 0x1C

# Offsets a payload uses, measured from r0 rather than from the struct base.
FROM_PARAM_SEND_BUFFER = CLIENT_SEND_BUFFER - CLIENT_PARAM            # 0x10
FROM_PARAM_LINK_SEND_SIZE = CLIENT_LINK + LINK_SEND_SIZE - CLIENT_PARAM    # 0x34
FROM_PARAM_LINK_SEND_BUFFER = CLIENT_LINK + LINK_SEND_BUFFER - CLIENT_PARAM  # 0x3C


# --- Offline execution ----------------------------------------------------------------------------
# The GBA map, only as much of it as a payload can touch. Addresses are the real ones so that a
# payload which ever does use an absolute address is tested against the layout it will meet.
EWRAM_BASE, EWRAM_SIZE = 0x02000000, 0x00040000
IWRAM_BASE, IWRAM_SIZE = 0x03000000, 0x00008000
# The cartridge, readable by the CPU like any other region, so a dump aimed at it is legal and the
# CRC walk over it cannot fault. 32 MB is the GBA's window; FireRed fills the first 16.
ROM_BASE, ROM_SIZE = 0x08000000, 0x02000000
# [GBA cartridge header] 0xA0 game title, 0xAC game code, 0xB0 maker, 0xBC software version. This is
# how a dump names the build the console is running, which is the prerequisite for calling into it.
ROM_HEADER_TITLE = ROM_BASE + 0xA0
ROM_HEADER_GAME_CODE = ROM_BASE + 0xAC
STACK_POINTER = 0x03007F00          # SP_usr as the BIOS leaves it
_RETURN_ADDRESS = 0x0F000000        # our own sentinel: where bx lr lands and emulation stops
# The client and its buffers are AllocZeroed [mystery_gift_client.c:72], so they live in gHeap,
# which is EWRAM 0x02000000..0x0201C000 - below the code buffer, as on the console.
_CLIENT_ADDRESS = 0x02001000
_SEND_BUFFER_ADDRESS = 0x02002000
_RECV_BUFFER_ADDRESS = 0x02003000
SAV2_ADDRESS = 0x02025000           # clear of the code buffer at 0x0201C000
SAV1_ADDRESS = 0x0202C000
_SAV2_ADDRESS = SAV2_ADDRESS
_SAV1_ADDRESS = SAV1_ADDRESS
_INSTRUCTION_LIMIT = 100000


@dataclass
class ClientState:
    """struct MysteryGiftClient as the payload left it."""
    param: int
    send_buffer: int
    send_size: int
    send_ident: int

    @property
    def send_repointed(self):
        return self.send_buffer != _SEND_BUFFER_ADDRESS


@dataclass
class BufferScriptRun:
    """What one call of a payload did."""
    returned: int           # r0: BUFFER_SCRIPT_DONE ends the call
    param: int              # *param, which CLI_LOAD_TOSS_RESPONSE ships back to us
    sav2: bytes             # the save blocks as the payload left them
    sav1: bytes
    instructions: int
    client: ClientState
    pending_send: bytes     # what a following CLI_SEND_LOADED would actually put on the wire

    @property
    def done(self):
        return self.returned == BUFFER_SCRIPT_DONE


def emulation_available():
    try:
        import unicorn  # noqa: F401
    except ImportError:
        return False
    return True


# Enough of a cartridge header for a dump aimed at ROM to come back with something to identify. The
# real console's is whatever the Switch release ships; that is exactly what a hardware dump answers.
_DEFAULT_ROM_HEADER = (b"\x00" * 0xA0
                       + b"POKEMON FIRE"            # 0xA0 game title, 12 bytes
                       + b"BPRF"                    # 0xAC game code: BPR = FireRed, F = French
                       + b"01"                      # 0xB0 maker code
                       + b"\x96")                   # 0xB2 fixed value


def emulate(code, *, param=0, sav2=b"", sav1=b"", memory=None, send_size=4,
            send_ident=0, rom=None, instruction_limit=_INSTRUCTION_LIMIT):
    """Run a payload the way Client_RunBufferScript does, on a model of the console's memory.

    `send_size`/`send_ident` are the send a preceding client-script command already set up (4 bytes
    of MG_LINKID_RESPONSE after CLI_LOAD_TOSS_RESPONSE); `memory` places extra regions the payload
    may read, as {address: bytes}; `rom` seeds the cartridge at 0x08000000. The result's `pending_send` is what a following CLI_SEND_LOADED
    would actually transmit - the bytes at link->sendBuffer, wherever the payload left it pointing.

    The caller is a THUMB function, so lr carries bit 0 set; a payload that returns with anything
    but `bx lr` (a `mov pc, lr`, say) would leave the console in ARM state and crash, and this
    reproduces that faithfully.
    """
    try:
        import unicorn
        from unicorn import arm_const
    except ImportError:  # pragma: no cover - exercised only on a machine without unicorn
        raise BufferScriptError(
            "offline execution needs unicorn (pip install unicorn)") from None

    validate(code)
    uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM | unicorn.UC_MODE_LITTLE_ENDIAN)
    uc.mem_map(EWRAM_BASE, EWRAM_SIZE)
    uc.mem_map(IWRAM_BASE, IWRAM_SIZE)
    uc.mem_map(ROM_BASE, ROM_SIZE)
    uc.mem_write(ROM_BASE, bytes(rom if rom is not None else _DEFAULT_ROM_HEADER))
    uc.mem_map(_RETURN_ADDRESS, 0x1000)

    def word(offset, value):
        uc.mem_write(_CLIENT_ADDRESS + offset, (value & 0xFFFFFFFF).to_bytes(4, "little"))

    def half(offset, value):
        uc.mem_write(_CLIENT_ADDRESS + offset, (value & 0xFFFF).to_bytes(2, "little"))

    uc.mem_write(GDECOMPRESSION_BUFFER, bytes(code))
    word(CLIENT_PARAM, int(param))
    word(CLIENT_SEND_BUFFER, _SEND_BUFFER_ADDRESS)
    word(CLIENT_RECV_BUFFER, _RECV_BUFFER_ADDRESS)
    uc.mem_write(_RECV_BUFFER_ADDRESS, bytes(code))     # the console's copy is made FROM here
    # As CLI_LOAD_TOSS_RESPONSE leaves it: the send is armed and points at client->sendBuffer.
    word(CLIENT_LINK + LINK_SEND_BUFFER, _SEND_BUFFER_ADDRESS)
    half(CLIENT_LINK + LINK_SEND_SIZE, send_size)
    half(CLIENT_LINK + LINK_SEND_IDENT, send_ident)
    word(CLIENT_LINK + LINK_RECV_BUFFER, _RECV_BUFFER_ADDRESS)
    uc.mem_write(_SEND_BUFFER_ADDRESS, int(param).to_bytes(4, "little"))

    sav2, sav1 = bytes(sav2), bytes(sav1)
    if sav2:
        uc.mem_write(_SAV2_ADDRESS, sav2)
    if sav1:
        uc.mem_write(_SAV1_ADDRESS, sav1)
    for address, blob in (memory or {}).items():
        uc.mem_write(address, bytes(blob))

    uc.reg_write(arm_const.UC_ARM_REG_R0, _CLIENT_ADDRESS + CLIENT_PARAM)
    uc.reg_write(arm_const.UC_ARM_REG_R1, _SAV2_ADDRESS)
    uc.reg_write(arm_const.UC_ARM_REG_R2, _SAV1_ADDRESS)
    uc.reg_write(arm_const.UC_ARM_REG_SP, STACK_POINTER)
    uc.reg_write(arm_const.UC_ARM_REG_LR, _RETURN_ADDRESS | 1)

    executed = [0]

    def count(uc_, address, size, user_data):
        executed[0] += 1

    uc.hook_add(unicorn.UC_HOOK_CODE, count)
    try:
        uc.emu_start(GDECOMPRESSION_BUFFER, _RETURN_ADDRESS, count=instruction_limit)
    except unicorn.UcError as exc:
        pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
        raise BufferScriptError(
            f"the payload faulted at pc=0x{pc:08X} (offset "
            f"{pc - GDECOMPRESSION_BUFFER}): {exc}") from None
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    if pc != _RETURN_ADDRESS:
        raise BufferScriptError(
            f"the payload never returned: stopped at pc=0x{pc:08X} after {executed[0]} "
            "instructions. On the console that is a hang inside the Mystery Gift menu.")

    def read_word(offset):
        return int.from_bytes(uc.mem_read(_CLIENT_ADDRESS + offset, 4), "little")

    def read_half(offset):
        return int.from_bytes(uc.mem_read(_CLIENT_ADDRESS + offset, 2), "little")

    client = ClientState(
        param=read_word(CLIENT_PARAM),
        send_buffer=read_word(CLIENT_LINK + LINK_SEND_BUFFER),
        send_size=read_half(CLIENT_LINK + LINK_SEND_SIZE),
        send_ident=read_half(CLIENT_LINK + LINK_SEND_IDENT))
    try:
        pending = bytes(uc.mem_read(client.send_buffer, client.send_size))
    except unicorn.UcError:
        raise BufferScriptError(
            f"the payload left link->sendBuffer at 0x{client.send_buffer:08X} for "
            f"{client.send_size} bytes, which is not readable memory. The console would fault "
            "computing the CRC over it [mystery_gift_link.c:166].") from None
    return BufferScriptRun(
        returned=uc.reg_read(arm_const.UC_ARM_REG_R0),
        param=client.param,
        sav2=bytes(uc.mem_read(_SAV2_ADDRESS, len(sav2))) if sav2 else b"",
        sav1=bytes(uc.mem_read(_SAV1_ADDRESS, len(sav1))) if sav1 else b"",
        instructions=executed[0],
        client=client,
        pending_send=pending,
    )
