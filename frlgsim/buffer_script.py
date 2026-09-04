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


class BufferScriptError(Exception):
    """A payload that the console could not safely be asked to run."""


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


SCRIPT_REGISTRY = {
    TRAINER_ID_PROBE: BufferScriptSpec(
        TRAINER_ID_PROBE,
        "read playerTrainerId out of gSaveBlock2Ptr and return it (reads only, writes nothing)",
        EXPECT_TRAINER_ID),
}


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


# --- Offline execution ----------------------------------------------------------------------------
# The GBA map, only as much of it as a payload can touch. Addresses are the real ones so that a
# payload which ever does use an absolute address is tested against the layout it will meet.
EWRAM_BASE, EWRAM_SIZE = 0x02000000, 0x00040000
IWRAM_BASE, IWRAM_SIZE = 0x03000000, 0x00008000
STACK_POINTER = 0x03007F00          # SP_usr as the BIOS leaves it
_RETURN_ADDRESS = 0x0F000000        # our own sentinel: where bx lr lands and emulation stops
_PARAM_ADDRESS = 0x03004000         # stands in for &client->param, which lives in the heap
_SAV2_ADDRESS = 0x02025000          # clear of the code buffer at 0x0201C000
_SAV1_ADDRESS = 0x0202C000
_INSTRUCTION_LIMIT = 100000


@dataclass
class BufferScriptRun:
    """What one call of a payload did."""
    returned: int           # r0: BUFFER_SCRIPT_DONE ends the call
    param: int              # *param, which CLI_LOAD_TOSS_RESPONSE ships back to us
    sav2: bytes             # the save blocks as the payload left them
    sav1: bytes
    instructions: int

    @property
    def done(self):
        return self.returned == BUFFER_SCRIPT_DONE


def emulation_available():
    try:
        import unicorn  # noqa: F401
    except ImportError:
        return False
    return True


def emulate(code, *, param=0, sav2=b"", sav1=b"", instruction_limit=_INSTRUCTION_LIMIT):
    """Run a payload the way Client_RunBufferScript does, on a model of the console's memory.

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
    uc.mem_map(_RETURN_ADDRESS, 0x1000)

    uc.mem_write(GDECOMPRESSION_BUFFER, bytes(code))
    uc.mem_write(_PARAM_ADDRESS, int(param).to_bytes(4, "little"))
    sav2, sav1 = bytes(sav2), bytes(sav1)
    if sav2:
        uc.mem_write(_SAV2_ADDRESS, sav2)
    if sav1:
        uc.mem_write(_SAV1_ADDRESS, sav1)

    uc.reg_write(arm_const.UC_ARM_REG_R0, _PARAM_ADDRESS)
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
    return BufferScriptRun(
        returned=uc.reg_read(arm_const.UC_ARM_REG_R0),
        param=int.from_bytes(uc.mem_read(_PARAM_ADDRESS, 4), "little"),
        sav2=bytes(uc.mem_read(_SAV2_ADDRESS, len(sav2))) if sav2 else b"",
        sav1=bytes(uc.mem_read(_SAV1_ADDRESS, len(sav1))) if sav1 else b"",
        instructions=executed[0],
    )
