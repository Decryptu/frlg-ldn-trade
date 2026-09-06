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

from . import rom_map
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
MEMORY_DUMP_MULTI = "memory-dump-multi"
SAVE_DUMP = "save-dump"
ANCHORS = "anchors"
SAVE_WRITE = "save-write"

# save-write's operands, from its disassembly (ldr [pc,#0x44] -> 0x4C, [pc,#0x38] -> 0x50,
# [pc,#0x30] -> 0x54, add r1,pc,#0x2C -> 0x58). Proven by emulating a patched payload.
SAVE_WRITE_WHICH_OFFSET = 0x4C
SAVE_WRITE_OFFSET_OFFSET = 0x50
SAVE_WRITE_SIZE_OFFSET = 0x54
SAVE_WRITE_DATA_OFFSET = 0x58
MAX_SAVE_WRITE_BYTES = MAX_BUFFER_SCRIPT_SIZE - SAVE_WRITE_DATA_OFFSET


# The eleven words `anchors` sends back, in order. The first four cannot be obtained any other way.
ANCHORS_FIELDS = (
    "code",             # where the console put our payload: gDecompressionBuffer, measured
    "return_address",   # into ROM, after the call in Client_RunBufferScript; THUMB, so bit 0 set
    "stack_pointer",
    "client_param",     # r0
    "save_block_2",     # r1
    "save_block_1",     # r2
    "client_send_buffer",
    "client_recv_buffer",
    "client_script",
    "client_msg",
    "link_send_buffer",  # as MysteryGiftLink_InitSend left it; must equal client_send_buffer
)
ANCHORS_SIZE = 4 * len(ANCHORS_FIELDS)


def read_anchors(dump):
    """-> {field: u32} for the bytes `anchors` sent back."""
    dump = bytes(dump)
    if len(dump) < ANCHORS_SIZE:
        raise BufferScriptError(
            f"the anchors payload sends {ANCHORS_SIZE} bytes, got {len(dump)}")
    return {name: int.from_bytes(dump[4 * i:4 * i + 4], "little")
            for i, name in enumerate(ANCHORS_FIELDS)}


def describe_anchors(dump):
    """The same, as lines to log. Every consistency check this can make, it makes: an answer that
    looks plausible but is not self-consistent is worse than no answer."""
    a = read_anchors(dump)
    lines = [f"{name:<19} 0x{a[name]:08X}" for name in ANCHORS_FIELDS]
    rom = a["return_address"]
    lines.append(
        f"-> the ROM call site is 0x{rom & ~1:08X} ({'THUMB' if rom & 1 else 'ARM'} caller), "
        "the instruction after the call in Client_RunBufferScript [mystery_gift_client.c:276]")
    if not 0x08000000 <= (rom & ~1) < 0x0A000000:
        lines.append("   WARNING: that is not in the cartridge; the anchor is not what we think")
    lines.append(
        f"-> gDecompressionBuffer is 0x{a['code']:08X} "
        + ("(the 0x0201C000 deduction holds)" if a["code"] == 0x0201C000
           else "(NOT the deduced 0x0201C000 - docs/buffer_script.md is wrong)"))
    if a["link_send_buffer"] != a["client_send_buffer"]:
        lines.append("   WARNING: link->sendBuffer is not client->sendBuffer; "
                     "the struct offsets this project computes from r0 are wrong")
    return lines

# save-dump's operands, from its disassembly: ldr [pc,#36] -> 0x2C, [pc,#24] -> 0x30,
# [pc,#16] -> 0x34. Proven by emulating a patched payload, not by trusting these.
SAVE_DUMP_WHICH_OFFSET = 0x2C
SAVE_DUMP_OFFSET_OFFSET = 0x30
SAVE_DUMP_SIZE_OFFSET = 0x34

SAVE_BLOCK_2 = "sav2"       # r1, struct SaveBlock2: name, trainer id, pokedex, battle tower
SAVE_BLOCK_1 = "sav1"       # r2, struct SaveBlock1: party, bag, money, flags, vars
SAVE_BLOCKS = (SAVE_BLOCK_2, SAVE_BLOCK_1)
# Regions of the save the GAME NEVER READS, so a write there cannot break the player's game. Both
# are `u8 filler[]` in struct SaveBlock2 [decomp:include/global.h:345,357] and neither is referenced
# anywhere in src/. They are still saved to flash with the rest of the block, which is what makes
# them the right place to prove that a write lands and survives.
SAVE_SCRATCH = {
    SAVE_BLOCK_2: ((0x090, 0x008),      # filler_90
                   (0xB20, 0x400)),     # filler_B20, a kilobyte
    SAVE_BLOCK_1: (),
}

# Where build_memory_dump patches its two operands. The payload is six ARM instructions followed by
# a two-word literal pool; the disassembly reads `ldr r3, [pc, #16]` -> 0x18 and
# `ldr r3, [pc, #12]` -> 0x1C, and test_the_dump_payload_operands_are_where_we_patch_them proves it
# by emulating a patched payload rather than by trusting these numbers.
DUMP_TARGET_OFFSET = 0x18
DUMP_SIZE_OFFSET = 0x1C

# --- memory-dump-multi: several blocks in ONE session ---------------------------------------------
# MG_LINK_BUFFER_SIZE caps a MESSAGE, not a session. The client runs a script of commands, and
# CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED can appear in it repeatedly
# [decomp:src/mystery_gift_client.c:140]; each pass sends another block. The payload cannot keep the
# block index itself, because CLI_RUN_BUFFER_SCRIPT memcpys recvBuffer over gDecompressionBuffer on
# EVERY pass [:238] and restores our image; it keeps it in client->param, which we are handed a
# pointer to. asm/memory-dump-multi.s. The three offsets are the literal pool after 17 instructions,
# and test_the_multi_dump_operands_are_where_we_patch_them EMULATES a patched payload rather than
# trusting that count - which is what caught them being written down 0x10 too low.
DUMP_MULTI_MAGIC_OFFSET = 0x44
DUMP_MULTI_BASE_OFFSET = 0x48
DUMP_MULTI_SIZE_OFFSET = 0x4C
DUMP_MULTI_MAGIC = 0x5A5A0000
# The cursor is one byte of param and each block is MAX_BUFFER_SCRIPT_SIZE, so this is the ceiling
# the PAYLOAD imposes. The client script imposes a smaller one; see mg_script.MAX_DUMP_BLOCKS.
MAX_DUMP_MULTI_BLOCKS = 0x100

# --- memory-scan: searching instead of reading ---------------------------------------------------
# Client_RunBufferScript ends the call only when the payload returns 1 and is reached once a frame
# from Task_MysteryGift [decomp:src/mystery_gift_client.c:276-280], and the memcpy that loads us
# runs once, at CLI_RUN_BUFFER_SCRIPT [:239], not per call. So a payload that returns 0 is called
# again next frame with its own image intact, and a search over 16 MB becomes a loop across frames
# instead of 16384 runs of 1024 bytes. The offsets below are fixed BY CONSTRUCTION - the payload
# opens with a branch over its own parameter block - so none is recovered from a disassembly.
SCAN_CURSOR_OFFSET = 0x04       # patched to the start address; the payload advances it
SCAN_END_OFFSET = 0x08
SCAN_NEEDLE_OFFSET = 0x0C
SCAN_BLOCKS_OFFSET = 0x10       # 32-byte blocks per call: the frame budget
SCAN_MAX_CALLS_OFFSET = 0x14    # watchdog; a payload that never returns 1 hangs the menu
SCAN_RESULT_OFFSET = 0x18
SCAN_HITS_OFFSET = 0x28
SCAN_HIT_CAPACITY = 64
SCAN_BLOCK_BYTES = 32           # one ldmia of eight words
# What comes back, always, hits or no hits: four header words then the whole hit table. Fixed so
# that the host's length check stays the proof that the payload repointed the send.
SCAN_ANSWER_SIZE = 4 * 4 + 8 * SCAN_HIT_CAPACITY

# The cartridge, which is what this was built for. FireRed fills the first 16 MB of the window.
SCAN_ROM_START = 0x08000000
SCAN_ROM_END = 0x09000000
# One call scans this many blocks by default: 4096 words, ~14 ARM instructions per 8 words out of
# EWRAM, so single-digit milliseconds. The console is holding an RFU link open while we run.
SCAN_DEFAULT_BLOCKS = 512
MAX_SCAN_BLOCKS = 0x10000
MAX_SCAN_CALLS = 0x8000
# Everything the CPU can be asked to read without a bus abort it would notice: EWRAM, IWRAM, I/O,
# palette, VRAM, OAM and the cartridge window. Below EWRAM is the BIOS, which reads as garbage from
# outside it, and past 0x0A000000 is the second wait-state mirror of the same cartridge.
SCAN_MIN_ADDRESS = 0x02000000
SCAN_MAX_ADDRESS = 0x0A000000

MEMORY_SCAN = "memory-scan"


def scan_call_count(start, end, blocks):
    """How many frames a scan of this range takes at this budget."""
    span_blocks = (int(end) - int(start)) // SCAN_BLOCK_BYTES
    return -(-span_blocks // int(blocks))


def build_memory_scan(needle, start=SCAN_ROM_START, end=SCAN_ROM_END,
                      blocks=SCAN_DEFAULT_BLOCKS, max_calls=None):
    """The memory-scan payload, patched with a needle, a range and a frame budget.

    `max_calls` defaults to what the range needs plus a margin: the watchdog exists so that a
    payload cannot sit in the Mystery Gift menu for ever, not to cut a scan short.
    """
    needle = int(needle) & 0xFFFFFFFF
    start, end, blocks = int(start), int(end), int(blocks)
    if not 0 < blocks <= MAX_SCAN_BLOCKS:
        raise BufferScriptError(
            f"a call scans 1..{MAX_SCAN_BLOCKS} blocks of {SCAN_BLOCK_BYTES} bytes, got {blocks}")
    if start % SCAN_BLOCK_BYTES or end % SCAN_BLOCK_BYTES:
        raise BufferScriptError(
            f"the range is scanned in {SCAN_BLOCK_BYTES}-byte blocks, so 0x{start:X}..0x{end:X} "
            f"must both be {SCAN_BLOCK_BYTES}-byte aligned")
    if not start < end:
        raise BufferScriptError(f"0x{start:X}..0x{end:X} is not a range")
    if start < SCAN_MIN_ADDRESS or end > SCAN_MAX_ADDRESS:
        raise BufferScriptError(
            f"0x{start:X}..0x{end:X} leaves the memory the CPU can read: "
            f"0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
    needed = scan_call_count(start, end, blocks)
    max_calls = needed + 2 if max_calls is None else int(max_calls)
    if not 0 < max_calls <= MAX_SCAN_CALLS:
        raise BufferScriptError(
            f"the watchdog allows 1..{MAX_SCAN_CALLS} calls, got {max_calls}")
    code = bytearray(payload(MEMORY_SCAN))
    for offset, value in ((SCAN_CURSOR_OFFSET, start), (SCAN_END_OFFSET, end),
                          (SCAN_NEEDLE_OFFSET, needle), (SCAN_BLOCKS_OFFSET, blocks),
                          (SCAN_MAX_CALLS_OFFSET, max_calls)):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(code)


def scan_parameters(code):
    """-> {needle, start, end, blocks, max_calls} read back out of a built payload.

    The parameters are in the image at fixed offsets, so whoever holds the code can say what was
    asked for without being told a second time - which is what lets the log report whether the
    range was finished.
    """
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    return {"start": word(SCAN_CURSOR_OFFSET), "end": word(SCAN_END_OFFSET),
            "needle": word(SCAN_NEEDLE_OFFSET), "blocks": word(SCAN_BLOCKS_OFFSET),
            "max_calls": word(SCAN_MAX_CALLS_OFFSET)}


def read_scan(dump):
    """-> what the scan found, from the bytes it sent back."""
    dump = bytes(dump)
    if len(dump) < SCAN_ANSWER_SIZE:
        raise BufferScriptError(
            f"a scan answers with {SCAN_ANSWER_SIZE} bytes, got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little") for i in range(0, SCAN_ANSWER_SIZE, 4)]
    found, cursor, calls, stored = words[:4]
    stored = min(stored, SCAN_HIT_CAPACITY)
    hits = [(words[4 + 2 * i], words[5 + 2 * i]) for i in range(stored)]
    return {"found": found, "cursor": cursor, "calls": calls, "hits": hits}


def describe_scan(dump, needle=None, start=None, end=None):
    """The same, as lines to log. A scan that answers 0 hits is a result; a scan that stopped
    early is not, and the difference is the cursor against the end of the range."""
    scan = read_scan(dump)
    lines = [f"scan: {scan['found']} match(es) for "
             + ("the needle" if needle is None else f"0x{int(needle):08X}")
             + f", {scan['calls']} call(s) = frames, stopped at 0x{scan['cursor']:08X}"]
    if end is not None:
        if scan["cursor"] >= int(end):
            lines.append(f"   the whole range 0x{int(start):08X}..0x{int(end):08X} was scanned")
        else:
            done = scan["cursor"] - int(start)
            lines.append(
                f"   STOPPED EARLY: {done} of {int(end) - int(start)} bytes. The watchdog "
                f"(max_calls) ended it; re-run from 0x{scan['cursor']:08X}")
    if scan["found"] > len(scan["hits"]):
        lines.append(f"   only the first {len(scan['hits'])} of {scan['found']} are listed "
                     f"(the table holds {SCAN_HIT_CAPACITY})")
    for address, value in scan["hits"]:
        lines.append(f"   0x{address:08X}  0x{value:08X}")
    return lines


# --- table-scan: finding a table by its shape ----------------------------------------------------
# memory-scan answers "where is this word", which needs the word first. A table of pointers carries
# no such constant - its entries ARE the addresses being looked for - so this searches for a
# RELATION instead: a run of N words each exactly D above the one before. gSpecialVars' first twelve
# entries point at twelve consecutive u16s, so D is 2. The answer carries the run's first value
# beside its address, so locating and reading are one run. docs/buffer_script.md.
TABLE_CURSOR_OFFSET = 0x04       # patched to the start address; the payload advances it
TABLE_END_OFFSET = 0x08
TABLE_DELTA_OFFSET = 0x0C        # what each word must exceed its predecessor by
TABLE_BLOCKS_OFFSET = 0x10       # 16-byte blocks per call: the frame budget
TABLE_MAX_CALLS_OFFSET = 0x14    # watchdog; a payload that never returns 1 hangs the menu
TABLE_RESULT_OFFSET = 0x18
TABLE_HITS_OFFSET = 0x28
TABLE_HIT_CAPACITY = 64
TABLE_RUNLEN_OFFSET = 0x228      # how many words in a row make a run worth reporting
TABLE_RUN_OFFSET = 0x22C         # state, carried across the ldmia AND the frame boundary
TABLE_RUNSTART_OFFSET = 0x230
TABLE_EXPECT_OFFSET = 0x234
TABLE_BLOCK_BYTES = 16           # one ldmia of four words
TABLE_ANSWER_SIZE = 4 * 4 + 8 * TABLE_HIT_CAPACITY
MAX_TABLE_RUN_LENGTH = 0x1000
# A shape test is ~7 ARM instructions a word where memory-scan's is ~1.75, so the block count that
# keeps the SAME load on the frame is smaller, not the same. 192 blocks is 768 words, ~6.7k
# instructions a call, which is what memory-scan's 512 blocks cost - and the console is holding an
# RFU link open while we run, so matching the proven budget matters more than covering ground.
TABLE_SCAN_DEFAULT_BLOCKS = 192

# The fingerprint this was built for. Twelve is gSpecialVar_0x8000 .. gSpecialVar_0x800B; the
# entries past those are the named vars, which event_data.c declares in a DIFFERENT order from the
# one gSpecialVars lists them in, so the ascending run stops at twelve and asking for more finds
# nothing. Two is sizeof(u16).
SPECIAL_VARS_DELTA = 2
SPECIAL_VARS_RUN_LENGTH = 12

TABLE_SCAN = "table-scan"


def table_scan_call_count(start, end, blocks):
    """How many frames a shape search over this range takes at this budget."""
    span_blocks = (int(end) - int(start)) // TABLE_BLOCK_BYTES
    return -(-span_blocks // int(blocks))


def build_table_scan(delta=SPECIAL_VARS_DELTA, runlen=SPECIAL_VARS_RUN_LENGTH,
                     start=SCAN_ROM_START, end=SCAN_ROM_END,
                     blocks=TABLE_SCAN_DEFAULT_BLOCKS, max_calls=None):
    """The table-scan payload, patched with a shape, a range and a frame budget."""
    delta = int(delta) & 0xFFFFFFFF
    runlen, start, end, blocks = int(runlen), int(start), int(end), int(blocks)
    if not 0 < blocks <= MAX_SCAN_BLOCKS:
        raise BufferScriptError(
            f"a call scans 1..{MAX_SCAN_BLOCKS} blocks of {TABLE_BLOCK_BYTES} bytes, got {blocks}")
    if not 1 < runlen <= MAX_TABLE_RUN_LENGTH:
        raise BufferScriptError(
            f"a run is 2..{MAX_TABLE_RUN_LENGTH} words; one word is not a shape, got {runlen}")
    if delta == 0:
        raise BufferScriptError(
            "a delta of 0 matches every stretch of repeated words - use memory-scan for a value")
    if start % TABLE_BLOCK_BYTES or end % TABLE_BLOCK_BYTES:
        raise BufferScriptError(
            f"the range is scanned in {TABLE_BLOCK_BYTES}-byte blocks, so 0x{start:X}..0x{end:X} "
            f"must both be {TABLE_BLOCK_BYTES}-byte aligned")
    if not start < end:
        raise BufferScriptError(f"0x{start:X}..0x{end:X} is not a range")
    if start < SCAN_MIN_ADDRESS or end > SCAN_MAX_ADDRESS:
        raise BufferScriptError(
            f"0x{start:X}..0x{end:X} leaves the memory the CPU can read: "
            f"0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
    needed = table_scan_call_count(start, end, blocks)
    max_calls = needed + 2 if max_calls is None else int(max_calls)
    if not 0 < max_calls <= MAX_SCAN_CALLS:
        raise BufferScriptError(
            f"the watchdog allows 1..{MAX_SCAN_CALLS} calls, got {max_calls}")
    code = bytearray(payload(TABLE_SCAN))
    for offset, value in ((TABLE_CURSOR_OFFSET, start), (TABLE_END_OFFSET, end),
                          (TABLE_DELTA_OFFSET, delta), (TABLE_BLOCKS_OFFSET, blocks),
                          (TABLE_MAX_CALLS_OFFSET, max_calls),
                          (TABLE_RUNLEN_OFFSET, runlen)):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(code)


def table_scan_parameters(code):
    """-> {delta, runlen, start, end, blocks, max_calls} read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    return {"start": word(TABLE_CURSOR_OFFSET), "end": word(TABLE_END_OFFSET),
            "delta": word(TABLE_DELTA_OFFSET), "blocks": word(TABLE_BLOCKS_OFFSET),
            "max_calls": word(TABLE_MAX_CALLS_OFFSET), "runlen": word(TABLE_RUNLEN_OFFSET)}


def read_table_scan(dump, start=None, end=None):
    """-> what the shape search found, from the bytes it sent back.

    A hit whose address falls outside the range asked for is dropped: that is the payload's one
    documented edge, a run credited to the very first word of the range when that word happens to
    equal the expectation the state starts at, whose `runstart` was never written.
    """
    dump = bytes(dump)
    if len(dump) < TABLE_ANSWER_SIZE:
        raise BufferScriptError(
            f"a table scan answers with {TABLE_ANSWER_SIZE} bytes, got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little") for i in range(0, TABLE_ANSWER_SIZE, 4)]
    found, cursor, calls, stored = words[:4]
    stored = min(stored, TABLE_HIT_CAPACITY)
    hits = [(words[4 + 2 * i], words[5 + 2 * i]) for i in range(stored)]
    dropped = []
    if start is not None and end is not None:
        keep = [(a, v) for a, v in hits if int(start) <= a < int(end)]
        dropped = [(a, v) for a, v in hits if not (int(start) <= a < int(end))]
        hits = keep
    return {"found": found, "cursor": cursor, "calls": calls, "hits": hits, "dropped": dropped}


def describe_table_scan(dump, delta=None, runlen=None, start=None, end=None):
    """The same, as lines to log. A run reported here is self-verifying: its address and its
    first value are two independent readings of the same table, and for gSpecialVars the value
    IS the answer - &gSpecialVar_0x8000."""
    scan = read_table_scan(dump, start, end)
    shape = ("a run" if runlen is None or delta is None
             else f"a run of {runlen} words rising by {delta}")
    lines = [f"table: {scan['found']} match(es) for {shape}, "
             f"{scan['calls']} call(s) = frames, stopped at 0x{scan['cursor']:08X}"]
    if end is not None:
        if scan["cursor"] >= int(end):
            lines.append(f"   the whole range 0x{int(start):08X}..0x{int(end):08X} was scanned")
        else:
            done = scan["cursor"] - int(start)
            lines.append(
                f"   STOPPED EARLY: {done} of {int(end) - int(start)} bytes. The watchdog "
                f"(max_calls) ended it; re-run from 0x{scan['cursor']:08X}")
    if scan["found"] > len(scan["hits"]) + len(scan["dropped"]):
        lines.append(f"   only the first {TABLE_HIT_CAPACITY} of {scan['found']} are listed")
    for address, value in scan["hits"]:
        lines.append(f"   table at 0x{address:08X}  first entry 0x{value:08X}")
    for address, value in scan["dropped"]:
        lines.append(f"   (dropped, outside the range asked for: 0x{address:08X} 0x{value:08X})")
    return lines


# --- string-gather: following a pointer array instead of reading a window ------------------------
# A dump reads a window, so a table of pointers costs one run for the pointers and another for every
# kilobyte they point at, two thirds of it struct EasyChatWordInfo's alphabeticalOrder and enabled
# [decomp:include/easy_chat.h:11]. This payload dereferences and sends back the strings themselves,
# a whole Easy Chat group a run.
#
# It never truncates: a string that does not fit ends the run before it and `next` names where to
# resume, because a half-copied word would be indistinguishable from a French word that short.
# `maxlen` bounds the walk so a pointer that is not a string stops the run instead of copying until
# it meets an 0xFF. docs/buffer_script.md.
STRING_GATHER = "string-gather"
GATHER_SRC_OFFSET = 0x04        # the address of the first pointer; the payload advances it
GATHER_STRIDE_OFFSET = 0x08     # 12 for struct EasyChatWordInfo, whose `text` is at offset 0
GATHER_COUNT_OFFSET = 0x0C
GATHER_BUDGET_OFFSET = 0x10
GATHER_MAXLEN_OFFSET = 0x14
GATHER_RESULT_OFFSET = 0x18
GATHER_STRINGS_OFFSET = 0x28
# Fixed in asm/string-gather.s so that the whole image is exactly MAX_BUFFER_SCRIPT_SIZE.
GATHER_STRING_AREA = 760
GATHER_ANSWER_SIZE = 4 * 4 + GATHER_STRING_AREA
# Longest string accepted, terminator included. The longest word in the English tables is 15
# characters, and a French one will not be four times that; anything longer means the pointer was
# not a string.
GATHER_DEFAULT_MAXLEN = 64
GATHER_STOP = {0: "followed every pointer asked for",
               1: "the budget ran out - re-run from `next`",
               2: "a pointer with no terminator within maxlen: NOT a string table"}
EOS = 0xFF                      # [decomp:include/characters.h]


def build_string_gather(src, count, stride=12, budget=None, maxlen=GATHER_DEFAULT_MAXLEN):
    """The string-gather payload, patched with an array of pointers to follow.

    `src` is the address of the FIRST POINTER, not of the string; `stride` is how far apart the
    pointers are, so an array of plain `const u8 *` is stride 4 and struct EasyChatWordInfo is 12.
    """
    src, count, stride = int(src), int(count), int(stride)
    budget = GATHER_STRING_AREA if budget is None else int(budget)
    maxlen = int(maxlen)
    if not 0 <= src <= 0xFFFFFFFF or src % 4:
        raise BufferScriptError(
            f"0x{src:X} is not a word-aligned address, so it is not an array of pointers")
    if not 0 < stride <= 0x1000 or stride % 4:
        raise BufferScriptError(f"the stride between pointers is a positive multiple of 4, got {stride}")
    if not 0 < count <= 0x10000:
        raise BufferScriptError(f"a run follows 1..65536 pointers, got {count}")
    if not 0 < budget <= GATHER_STRING_AREA:
        raise BufferScriptError(
            f"the answer holds 1..{GATHER_STRING_AREA} bytes of string, got {budget}")
    if not 0 < maxlen <= GATHER_STRING_AREA:
        raise BufferScriptError(f"maxlen is 1..{GATHER_STRING_AREA}, got {maxlen}")
    code = bytearray(payload(STRING_GATHER))
    for offset, value in ((GATHER_SRC_OFFSET, src), (GATHER_STRIDE_OFFSET, stride),
                          (GATHER_COUNT_OFFSET, count), (GATHER_BUDGET_OFFSET, budget),
                          (GATHER_MAXLEN_OFFSET, maxlen)):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(code)


def gather_parameters(code):
    """-> {src, stride, count, budget, maxlen} read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    return {"src": word(GATHER_SRC_OFFSET), "stride": word(GATHER_STRIDE_OFFSET),
            "count": word(GATHER_COUNT_OFFSET), "budget": word(GATHER_BUDGET_OFFSET),
            "maxlen": word(GATHER_MAXLEN_OFFSET)}


def read_gather(dump):
    """-> what the walk collected, from the bytes it sent back.

    `strings` are still in the game's own encoding, terminators stripped; charmap decodes them.
    """
    dump = bytes(dump)
    if len(dump) < GATHER_ANSWER_SIZE:
        raise BufferScriptError(
            f"a string-gather answers with {GATHER_ANSWER_SIZE} bytes, got {len(dump)}")
    copied, written, resume, reason = (
        int.from_bytes(dump[i:i + 4], "little") for i in range(0, 16, 4))
    written = min(written, GATHER_STRING_AREA)
    blob = dump[16:16 + written]
    strings = [piece for piece in blob.split(bytes([EOS]))][:copied]
    return {"copied": copied, "written": written, "next": resume, "reason": reason,
            "strings": strings}


def describe_gather(dump, src=None, stride=None, count=None):
    """The same, as lines to log. A short run is not a failure - it is the budget, and `next` is
    where the following run starts."""
    from . import charmap
    gathered = read_gather(dump)
    lines = [f"gather: {gathered['copied']} string(s), {gathered['written']} bytes"
             + ("" if src is None else f", from 0x{int(src):08X}")
             + (f" of {int(count)} asked for" if count is not None else "")
             + f"; resume at 0x{gathered['next']:08X}"]
    lines.append("   " + GATHER_STOP.get(gathered["reason"], f"reason {gathered['reason']}"))
    for index, raw in enumerate(gathered["strings"]):
        lines.append(f"   {index:>3}  {charmap.decode(raw)!r}")
    return lines


# --- rng-trace: a word sampled once a frame, and the first call into the ROM ---------------------
# bs13 found RAND_MULT in the cartridge and bs14's dump named gRngValue at 0x03004220 from Random's
# own literal pool [rom_map.py]. A word that changes proves nothing, though, and at the Mystery Gift
# menu the game may not call Random at all - so this payload proves the address by the LCG's own
# recurrence: read the word, call the function, read it again, and check
#     after == before * RAND_MULT + RAND_ADD   [decomp:include/random.h:18-19]
# which settles the address, the ROM call and what was called, in one run.
RNG_TRACE = "rng-trace"
TRACE_ADDRESS_OFFSET = 0x04
TRACE_FUNCTION_OFFSET = 0x08
TRACE_SAMPLES_OFFSET = 0x0C
TRACE_MAX_CALLS_OFFSET = 0x10
TRACE_RESULT_OFFSET = 0x14
TRACE_SAMPLE_CAPACITY = 96          # 2 words each; the image is 1012 bytes of the 1024
TRACE_HEADER_SIZE = 16

RAND_MULT = 1103515245              # 0x41C64E6D [decomp:include/random.h:18]
RAND_ADD = 24691                    # ISO_RANDOMIZE1's addend [:19]


def rand_step(value):
    """One turn of the game's LCG."""
    return (value * RAND_MULT + RAND_ADD) & 0xFFFFFFFF


def trace_answer_size(samples):
    return TRACE_HEADER_SIZE + 8 * int(samples)


def build_rng_trace(address, function=0, samples=TRACE_SAMPLE_CAPACITY, max_calls=None):
    """The rng-trace payload, patched with what to sample and what to call between the two reads.

    `function` is a THUMB pointer (bit 0 set), or 0 for a plain per-frame sampler. It is called with
    our own lr, so it must be an ordinary function that returns - the addresses that qualify are the
    ones read out of the console in rom_map.py.
    """
    address, function, samples = int(address), int(function), int(samples)
    if address % 4:
        raise BufferScriptError(f"0x{address:X} is not word aligned")
    if not SCAN_MIN_ADDRESS <= address < SCAN_MAX_ADDRESS:
        raise BufferScriptError(
            f"0x{address:X} is outside the memory the CPU can read: "
            f"0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
    if function:
        if not function & 1:
            raise BufferScriptError(
                f"0x{function:X} is an ARM pointer; the ROM is THUMB, so a callable address has "
                "bit 0 set (the `bx` selects the state from it)")
        if not ROM_BASE <= function < SCAN_MAX_ADDRESS:
            raise BufferScriptError(
                f"0x{function:X} is not in the cartridge; calling it would run whatever is there")
    if not 0 < samples <= TRACE_SAMPLE_CAPACITY:
        raise BufferScriptError(
            f"a trace takes 1..{TRACE_SAMPLE_CAPACITY} samples, got {samples}")
    max_calls = samples + 2 if max_calls is None else int(max_calls)
    if not 0 < max_calls <= MAX_SCAN_CALLS:
        raise BufferScriptError(f"the watchdog allows 1..{MAX_SCAN_CALLS} calls, got {max_calls}")
    code = bytearray(payload(RNG_TRACE))
    for offset, value in ((TRACE_ADDRESS_OFFSET, address), (TRACE_FUNCTION_OFFSET, function),
                          (TRACE_SAMPLES_OFFSET, samples), (TRACE_MAX_CALLS_OFFSET, max_calls)):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(code)


def trace_parameters(code):
    """-> {address, function, samples, max_calls} read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    return {"address": word(TRACE_ADDRESS_OFFSET), "function": word(TRACE_FUNCTION_OFFSET),
            "samples": word(TRACE_SAMPLES_OFFSET), "max_calls": word(TRACE_MAX_CALLS_OFFSET)}


def read_rng_trace(dump):
    """-> what the trace sampled, from the bytes it sent back."""
    dump = bytes(dump)
    if len(dump) < TRACE_HEADER_SIZE:
        raise BufferScriptError(f"a trace answers with at least {TRACE_HEADER_SIZE} bytes, "
                                f"got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little") for i in range(0, len(dump) - 3, 4)]
    calls, taken, address, function = words[:4]
    taken = min(taken, (len(words) - 4) // 2, TRACE_SAMPLE_CAPACITY)
    pairs = [(words[4 + 2 * i], words[5 + 2 * i]) for i in range(taken)]
    return {"calls": calls, "taken": taken, "address": address, "function": function,
            "samples": pairs}


def lcg_distance(start, target, limit=1 << 16):
    """How many turns of the LCG take `start` to `target`, or None within `limit`.

    The frame-to-frame gaps are what say how often the GAME called Random while we watched, which
    is a measurement of the console's own behaviour that nothing else here can make.
    """
    value = start & 0xFFFFFFFF
    for steps in range(int(limit)):
        if value == (target & 0xFFFFFFFF):
            return steps
        value = rand_step(value)
    return None


def describe_rng_trace(dump):
    """The same, as lines to log, with the recurrence CHECKED rather than displayed."""
    trace = read_rng_trace(dump)
    lines = [f"rng-trace: {trace['taken']} sample(s) of 0x{trace['address']:08X} over "
             f"{trace['calls']} call(s) = frames"
             + (f", calling 0x{trace['function']:08X}" if trace["function"] else
                ", calling nothing")]
    samples = trace["samples"]
    if not samples:
        return lines + ["   nothing was sampled"]
    if trace["function"]:
        held = sum(1 for before, after in samples if after == rand_step(before))
        lines.append(
            f"   the LCG recurrence after == before * {RAND_MULT} + {RAND_ADD} holds on "
            f"{held}/{len(samples)} samples"
            + (" - THE ADDRESS IS gRngValue AND THE ROM CALL RAN" if held == len(samples)
               else " - it does NOT hold, so one of the two is wrong"))
    changed = sum(1 for i in range(1, len(samples)) if samples[i][0] != samples[i - 1][1])
    gaps = [lcg_distance(samples[i - 1][1], samples[i][0]) for i in range(1, len(samples))]
    known = [g for g in gaps if g is not None]
    lines.append(
        f"   between frames the word changed {changed}/{len(samples) - 1} times"
        + (f"; the game's own Random calls per frame: min {min(known)}, max {max(known)}, "
           f"total {sum(known)}" if known and len(known) == len(gaps) else
           "; some frame-to-frame gaps are not on the LCG orbit"))
    lines.append("   first: " + ", ".join(f"0x{b:08X}->0x{a:08X}" for b, a in samples[:3]))
    lines.append("   last:  " + ", ".join(f"0x{b:08X}->0x{a:08X}" for b, a in samples[-3:]))
    return lines


# --- call: any function in the ROM, with arguments we choose --------------------------------------
# The general form of what rng-trace and create-mon each do specially: an address, up to eight
# argument words, the r0 that comes back, and one address watched either side of the call.
#
# The convention is bs42's disassembly of CreateMon's prologue, proven on hardware by bs43/bs44:
# r0..r3 then [sp+0..12] at the moment of the call, and the callee does not pop them. asm/call.s
# pushes the sixteen bytes for every call; a function taking fewer never reads them.
#
# `watch` is what makes an answer evidence: SeedRng returns nothing at all [decomp:src/random.c:15],
# so only reading gRngValue before and after says whether the seed took. docs/buffer_script.md.

CALL = "call"
CALL_FUNCTION_OFFSET = 0x04
CALL_ARGC_OFFSET = 0x08
CALL_ARGS_OFFSET = 0x0C
CALL_WATCH_OFFSET = 0x2C
CALL_RESULT_OFFSET = 0x30
CALL_MAX_ARGS = 8
CALL_ANSWER_SIZE = 24


def build_call(function, args=(), watch=0):
    """The `call` payload: a THUMB function pointer, up to eight argument words, a watched address.

    `function` 0 calls nothing, which reads `watch` twice and is how the send path is checked with
    the ROM left out. `watch` 0 watches nothing.
    """
    function, watch = int(function), int(watch)
    args = [int(a) & 0xFFFFFFFF for a in args]
    if len(args) > CALL_MAX_ARGS:
        raise BufferScriptError(
            f"the call passes at most {CALL_MAX_ARGS} arguments - four in r0..r3 and four on the "
            f"stack, which is what bs43/bs44 proved - got {len(args)}")
    if function:
        if not function & 1:
            raise BufferScriptError(
                f"0x{function:X} is an ARM pointer; the ROM is THUMB, so a callable address has "
                "bit 0 set (the `bx` selects the state from it)")
        if not ROM_BASE <= function < SCAN_MAX_ADDRESS:
            raise BufferScriptError(
                f"0x{function:X} is not in the cartridge; calling it would run whatever is there")
    if watch:
        if watch % 4:
            raise BufferScriptError(f"0x{watch:X} is not word aligned")
        if not SCAN_MIN_ADDRESS <= watch < SCAN_MAX_ADDRESS:
            raise BufferScriptError(
                f"0x{watch:X} is outside the memory the CPU can read: "
                f"0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
    code = bytearray(payload(CALL))
    def put(offset, value):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    put(CALL_FUNCTION_OFFSET, function)
    put(CALL_ARGC_OFFSET, len(args))
    put(CALL_WATCH_OFFSET, watch)
    for index, value in enumerate(args):
        put(CALL_ARGS_OFFSET + 4 * index, value)
    return bytes(code)


def call_parameters(code):
    """-> {function, argc, args, watch} read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    argc = word(CALL_ARGC_OFFSET)
    return {"function": word(CALL_FUNCTION_OFFSET), "argc": argc, "watch": word(CALL_WATCH_OFFSET),
            "args": [word(CALL_ARGS_OFFSET + 4 * i) for i in range(CALL_MAX_ARGS)][:argc]}


def read_call(dump):
    """-> what the call answered, from the 24 bytes it sent back."""
    dump = bytes(dump)
    if len(dump) < CALL_ANSWER_SIZE:
        raise BufferScriptError(f"a call answers with {CALL_ANSWER_SIZE} bytes, got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little") for i in range(0, CALL_ANSWER_SIZE, 4)]
    calls, function, argc, returned, before, after = words
    return {"calls": calls, "function": function, "argc": argc, "returned": returned,
            "before": before, "after": after}


def describe_call(dump, expected=None):
    """The same, as lines to log, with `expected` CHECKED against the watched word after the call."""
    got = read_call(dump)
    lines = [f"call: 0x{got['function']:08X} with {got['argc']} argument(s) in {got['calls']} "
             f"call(s), returned 0x{got['returned']:08X} ({got['returned'] & 0xFFFF} as a u16)"]
    if got["function"] == 0:
        lines[0] = (f"call: nothing was called ({got['calls']} call(s)); the two reads of the "
                    "watched word are the whole answer")
    lines.append(f"   watched word: 0x{got['before']:08X} before -> 0x{got['after']:08X} after"
                 + (" (unchanged)" if got["before"] == got["after"] else ""))
    if expected is not None:
        expected &= 0xFFFFFFFF
        lines.append(f"   expected 0x{expected:08X} after the call: "
                     + ("IT HOLDS - the call ran and did what it was called for"
                        if got["after"] == expected else
                        "IT DOES NOT - the call did not do what it was called for"))
    return lines


# --- call-chain: a list of calls and memory accesses, in one frame -------------------------------
# `call` makes one call. This makes up to CHAIN_MAX_STEPS, in order, in a single frame, and sends
# back one word per step. The reason is not convenience: every question about the console's game
# state is read-change-read, and bs84 named twenty-four workers to ask them of. A run is the
# expensive thing, not a call.
#
# The one new mechanism is PREV - a step can take its target or its first argument from the
# previous step's result - and it exists for exactly one shape:
#
#     call GetVarPointer(0x4024); write16 [prev] = 7; read16 [prev]
#
# There is no VarSet among the workers: ScrCmd_setvar writes through GetVarPointer's return
# [decomp:src/scrcmd.c:472], so setting a var the game's own way IS a call followed by an indirect
# store, and no single-call payload can do it. asm/call-chain.s has the step layout.

CALL_CHAIN = "call-chain"
CHAIN_COUNT_OFFSET = 0x04
CHAIN_STEPS_OFFSET = 0x10
CHAIN_STEP_SIZE = 24
CHAIN_MAX_STEPS = 16
CHAIN_MAX_ARGS = 4                  # r0..r3; the stack arguments are `call`'s business
CHAIN_RESULT_OFFSET = 0x190
CHAIN_VALUES_OFFSET = 0x1A0
CHAIN_ANSWER_SIZE = 16 + 4 * CHAIN_MAX_STEPS

# The opcodes, as asm/call-chain.s dispatches them.
CHAIN_END = 0
CHAIN_CALL = 1
CHAIN_READ32 = 2
CHAIN_READ16 = 3
CHAIN_READ8 = 4
CHAIN_WRITE32 = 5
CHAIN_WRITE16 = 6
CHAIN_WRITE8 = 7
# The two modifier bits in the op word, and the argument count above them. The payload does not
# read the count - it loads all four argument words every time, exactly as call.s pushes all four
# stack words whatever `argc` says, because a callee that takes fewer never reads them. It is here
# so that a BUILT payload still says what it was asked for, which is what the log prints.
CHAIN_TARGET_FROM_PREV = 0x100
CHAIN_ARG_FROM_PREV = 0x200      # the first argument is PREV + a0, so a0 is an offset
CHAIN_KEEP_PREV = 0x400
CHAIN_ARGC_SHIFT = 16
CHAIN_ARGC_MASK = 0xF

CHAIN_OPS = {
    "call": CHAIN_CALL,
    "read32": CHAIN_READ32,
    "read16": CHAIN_READ16,
    "read8": CHAIN_READ8,
    "write32": CHAIN_WRITE32,
    "write16": CHAIN_WRITE16,
    "write8": CHAIN_WRITE8,
}
CHAIN_OP_NAMES = {value: name for name, value in CHAIN_OPS.items()}
CHAIN_READS = (CHAIN_READ32, CHAIN_READ16, CHAIN_READ8)
CHAIN_WRITES = (CHAIN_WRITE32, CHAIN_WRITE16, CHAIN_WRITE8)
# How wide each access is, which is also what its target must be aligned to.
CHAIN_WIDTH = {CHAIN_READ32: 4, CHAIN_READ16: 2, CHAIN_READ8: 1,
               CHAIN_WRITE32: 4, CHAIN_WRITE16: 2, CHAIN_WRITE8: 1}


@dataclass(frozen=True)
class ChainStep:
    """One step: an opcode, a target, and up to four argument words.

    `target_from_prev` makes the target the previous result plus `target` (so 0 is the pointer
    itself and 4 is the word after it); `arg_from_prev` does the same to the first argument, which
    is how a ROM function is handed an address inside a block whose base only the console knows -
    `AddMoney(&gSaveBlock1Ptr->money, ...)` is prev + 0x290. Both are the payload's op-word bits,
    not a builder convenience: the console resolves them, which is the whole point.
    """
    op: int
    target: int = 0
    args: tuple = ()
    target_from_prev: bool = False
    arg_from_prev: bool = False
    keep_prev: bool = False

    @property
    def op_word(self):
        return (int(self.op) & 0xFF
                | (CHAIN_TARGET_FROM_PREV if self.target_from_prev else 0)
                | (CHAIN_ARG_FROM_PREV if self.arg_from_prev else 0)
                | (CHAIN_KEEP_PREV if self.keep_prev else 0)
                | (min(len(self.args), CHAIN_ARGC_MASK) << CHAIN_ARGC_SHIFT))

    @property
    def name(self):
        return CHAIN_OP_NAMES.get(int(self.op) & 0xFF, f"op {int(self.op) & 0xFF}")

    def describe(self):
        keep = " keep" if self.keep_prev else ""
        target = "prev" if self.target_from_prev else f"0x{self.target:08X}"
        if self.target_from_prev and self.target:
            target = f"prev + 0x{self.target:X}"
        if self.op == CHAIN_CALL:
            def argument(index, value):
                if index or not self.arg_from_prev:
                    return f"0x{value:X}"
                return f"prev + 0x{value:X}" if value else "prev"
            args = [argument(i, a) for i, a in enumerate(self.args)] \
                or (["prev"] if self.arg_from_prev else [])
            return f"call {target}({', '.join(args)}){keep}"
        if self.op in CHAIN_READS:
            return f"{self.name} [{target}]{keep}"
        first = (self.args or (0,))[0]
        value = (("prev" if not first else f"prev + 0x{first:X}") if self.arg_from_prev
                 else f"0x{first:X}")
        return f"{self.name} [{target}] = {value}"


def chain_call(function, args=(), *, arg_from_prev=False):
    """A CALL step. `function` is a THUMB pointer - rom_map.callable_function(name) gives one."""
    return ChainStep(CHAIN_CALL, int(function), tuple(int(a) & 0xFFFFFFFF for a in args),
                     arg_from_prev=bool(arg_from_prev))


def chain_read(address, size=4, *, from_prev=False, keep_prev=False):
    """A READ step of 1, 2 or 4 bytes. `from_prev` reads through the previous result, and
    `keep_prev` leaves that pointer in place instead of replacing it with what was read."""
    op = {4: CHAIN_READ32, 2: CHAIN_READ16, 1: CHAIN_READ8}.get(int(size))
    if op is None:
        raise BufferScriptError(f"a read is 1, 2 or 4 bytes, got {size}")
    return ChainStep(op, int(address), target_from_prev=bool(from_prev),
                     keep_prev=bool(keep_prev))


def chain_write(address, value=0, size=2, *, from_prev=False, value_from_prev=False):
    """A WRITE step of 1, 2 or 4 bytes, which reads itself back into the answer."""
    op = {4: CHAIN_WRITE32, 2: CHAIN_WRITE16, 1: CHAIN_WRITE8}.get(int(size))
    if op is None:
        raise BufferScriptError(f"a write is 1, 2 or 4 bytes, got {size}")
    return ChainStep(op, int(address), (int(value) & 0xFFFFFFFF,),
                     target_from_prev=bool(from_prev), arg_from_prev=bool(value_from_prev))


def parse_chain_step(text, resolve=None):
    """-> a ChainStep from `OP:TARGET[,ARG]...`, which is how the CLI takes one.

    `call:FlagSet,0x828`, `read16:0x02024EA4`, `write16:prev,7`, `read32:prev+4`. A target of
    `prev` is the previous step's result and `prev+N` is N bytes past it; a FIRST argument of
    `prev`/`prev+N` is the same thing, which is how `AddMoney(&money, n)` is reached when only the
    console knows the base. `resolve` turns a name into a THUMB pointer and defaults to
    rom_map.callable_function, so only the functions this project has MEASURED are nameable.
    """
    resolve = rom_map.callable_function if resolve is None else resolve
    head, _, rest = str(text).strip().partition(":")
    head = head.strip().lower()
    keep_prev = head.endswith("+keep")
    if keep_prev:
        head = head[:-len("+keep")].strip()
    op = CHAIN_OPS.get(head)
    if op is None:
        raise BufferScriptError(
            f"{text!r}: a step starts with one of {', '.join(sorted(CHAIN_OPS))}, each of which "
            "may carry a +keep suffix meaning `do not make this step's result the new prev`")
    fields = [f.strip() for f in rest.split(",")] if rest.strip() else []
    if not fields:
        raise BufferScriptError(f"{text!r}: a step needs a target")

    def number(field):
        try:
            return int(field, 0) & 0xFFFFFFFF
        except ValueError:
            raise BufferScriptError(f"{text!r}: {field!r} is not a number") from None

    target_text, args_text = fields[0], fields[1:]
    target_from_prev, target = False, 0
    if target_text.lower().startswith("prev"):
        target_from_prev = True
        tail = target_text[4:].strip()
        if tail:
            if not tail.startswith("+"):
                raise BufferScriptError(
                    f"{text!r}: a prev target is `prev` or `prev+N`, got {target_text!r}")
            target = number(tail[1:].strip())
    elif op == CHAIN_CALL:
        try:
            target = resolve(target_text)
        except KeyError:
            target = number(target_text)
    else:
        target = number(target_text)

    arg_from_prev = False
    args = []
    for index, field in enumerate(args_text):
        if field.lower().startswith("prev"):
            if index:
                raise BufferScriptError(
                    f"{text!r}: only the FIRST argument can be prev - the payload carries one "
                    "previous result, not a register file")
            arg_from_prev = True
            tail = field[4:].strip()
            if tail and not tail.startswith("+"):
                raise BufferScriptError(
                    f"{text!r}: a prev argument is `prev` or `prev+N`, got {field!r}")
            args.append(number(tail[1:].strip()) if tail else 0)
        else:
            args.append(number(field))
    return ChainStep(op, target, tuple(args), target_from_prev=target_from_prev,
                     arg_from_prev=arg_from_prev, keep_prev=keep_prev)


def build_call_chain(steps, *, unsafe=False):
    """The `call-chain` payload: up to CHAIN_MAX_STEPS steps, executed in order in one frame.

    Every write needs `unsafe`: unlike save-write there is no scratch region here to be safe in,
    because the target is wherever the game keeps the thing we are changing.
    """
    steps = list(steps)
    if not steps:
        raise BufferScriptError(
            "a chain needs at least one step; an empty one would send back sixteen zeroes")
    if len(steps) > CHAIN_MAX_STEPS:
        raise BufferScriptError(
            f"a chain is at most {CHAIN_MAX_STEPS} steps, got {len(steps)}")
    code = bytearray(payload(CALL_CHAIN))
    def put(offset, value):
        code[offset:offset + 4] = (int(value) & 0xFFFFFFFF).to_bytes(4, "little")
    put(CHAIN_COUNT_OFFSET, len(steps))
    for index, step in enumerate(steps):
        op = int(step.op) & 0xFF
        if op not in CHAIN_OP_NAMES:
            raise BufferScriptError(
                f"step {index + 1}: {op} is not an opcode asm/call-chain.s dispatches; "
                "the payload would stop there")
        if len(step.args) > CHAIN_MAX_ARGS:
            raise BufferScriptError(
                f"step {index + 1}: a chained call passes at most {CHAIN_MAX_ARGS} arguments, in "
                f"r0..r3; the stack arguments are what `{CALL}` is for (got {len(step.args)})")
        if op == CHAIN_CALL:
            if step.target_from_prev:
                raise BufferScriptError(
                    f"step {index + 1}: a call to an address computed on the console cannot be "
                    "checked from here, and a wrong one hangs the Mystery Gift menu with no way "
                    "out. Name the function.")
            if not step.target & 1:
                raise BufferScriptError(
                    f"step {index + 1}: 0x{step.target:X} is an ARM pointer; the ROM is THUMB, so "
                    "a callable address has bit 0 set (the `bx` selects the state from it)")
            if not ROM_BASE <= step.target < SCAN_MAX_ADDRESS:
                raise BufferScriptError(
                    f"step {index + 1}: 0x{step.target:X} is not in the cartridge; calling it "
                    "would run whatever is there")
        else:
            width = CHAIN_WIDTH[op]
            if not step.target_from_prev:
                if step.target % width:
                    raise BufferScriptError(
                        f"step {index + 1}: 0x{step.target:X} is not {width}-byte aligned")
                if not SCAN_MIN_ADDRESS <= step.target < SCAN_MAX_ADDRESS:
                    raise BufferScriptError(
                        f"step {index + 1}: 0x{step.target:X} is outside the memory the CPU can "
                        f"reach: 0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
            if op in CHAIN_WRITES and not unsafe:
                raise BufferScriptError(
                    f"step {index + 1}: {CHAIN_OP_NAMES[op]} writes the console's live memory, "
                    "which the console commits to flash when it saves. There is no scratch "
                    "region to be safe in here, so every write needs --write-unsafe.")
        base = CHAIN_STEPS_OFFSET + CHAIN_STEP_SIZE * index
        put(base, step.op_word)
        put(base + 4, step.target)
        for slot in range(CHAIN_MAX_ARGS):
            put(base + 8 + 4 * slot, step.args[slot] if slot < len(step.args) else 0)
    return bytes(code)


def chain_parameters(code):
    """-> {count, steps} read back out of a built payload, as ChainSteps."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    count = min(word(CHAIN_COUNT_OFFSET), CHAIN_MAX_STEPS)
    steps = []
    for index in range(count):
        base = CHAIN_STEPS_OFFSET + CHAIN_STEP_SIZE * index
        op_word = word(base)
        argc = min((op_word >> CHAIN_ARGC_SHIFT) & CHAIN_ARGC_MASK, CHAIN_MAX_ARGS)
        steps.append(ChainStep(
            op_word & 0xFF, word(base + 4),
            tuple(word(base + 8 + 4 * slot) for slot in range(argc)),
            target_from_prev=bool(op_word & CHAIN_TARGET_FROM_PREV),
            arg_from_prev=bool(op_word & CHAIN_ARG_FROM_PREV),
            keep_prev=bool(op_word & CHAIN_KEEP_PREV)))
    return {"count": word(CHAIN_COUNT_OFFSET), "steps": steps}


def read_call_chain(dump):
    """-> what the chain answered, from the 80 bytes it sent back."""
    dump = bytes(dump)
    if len(dump) < CHAIN_ANSWER_SIZE:
        raise BufferScriptError(
            f"a chain answers with {CHAIN_ANSWER_SIZE} bytes, got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little") for i in range(0, CHAIN_ANSWER_SIZE, 4)]
    calls, count, executed, refused = words[:4]
    return {"calls": calls, "count": count, "executed": min(executed, CHAIN_MAX_STEPS),
            "refused": refused, "values": words[4:4 + CHAIN_MAX_STEPS]}


def describe_call_chain(dump, steps=None):
    """The same, as lines to log, each result beside the step that produced it."""
    got = read_call_chain(dump)
    lines = [f"call-chain: {got['executed']} of {got['count']} step(s) ran in {got['calls']} "
             "call(s) = frames"]
    asked = list(steps or ())
    for index in range(got["executed"]):
        value = got["values"][index]
        step = asked[index].describe() if index < len(asked) else "step"
        lines.append(f"   {index + 1}. {step} -> 0x{value:08X} ({value & 0xFFFF} as a u16)")
    if got["refused"]:
        lines.append(f"   STOPPED: op word 0x{got['refused']:08X} is not one this payload has, "
                     "so nothing after it ran")
    elif got["executed"] < got["count"]:
        lines.append(f"   STOPPED after {got['executed']} of {got['count']}: a step's op word was "
                     "zero, which is END")
    return lines


# --- create-mon: a ROM call that takes eight arguments -------------------------------------------
#   void CreateMon(struct Pokemon *mon, u16 species, u8 level, u8 fixedIV,
#                  u8 hasFixedPersonality, u32 fixedPersonality, u8 otIdType, u32 fixedOtId)
#
# Four in r0..r3 and four at entry sp + 0, 4, 8 and 12, which is where the console's own prologue
# reads them [bs42's dump: push of five registers, then r8, then `sub sp,#28`, then [sp,#52..64]].
#
# The mon is always built inside our own 1024 bytes, where nothing but the payload can be hurt, and
# read back from there. `destination` copies the finished 100 bytes on afterwards and is a live-save
# write when it names the party, so it is guarded like build_save_write's offsets.
# docs/buffer_script.md.
CREATE_MON = "create-mon"
CREATE_MON_FUNCTION_OFFSET = 0x04
CREATE_MON_DESTINATION_OFFSET = 0x08
CREATE_MON_PARTY_APPEND_OFFSET = 0x0C
CREATE_MON_PARTY_BASE_OFFSET = 0x10
CREATE_MON_PARTY_COUNT_OFFSET = 0x14
CREATE_MON_SPECIES_OFFSET = 0x18
CREATE_MON_LEVEL_OFFSET = 0x1C
CREATE_MON_FIXED_IV_OFFSET = 0x20
CREATE_MON_HAS_FIXED_PERSONALITY_OFFSET = 0x24
CREATE_MON_FIXED_PERSONALITY_OFFSET = 0x28
CREATE_MON_OT_ID_TYPE_OFFSET = 0x2C
CREATE_MON_FIXED_OT_ID_OFFSET = 0x30
CREATE_MON_RESULT_OFFSET = 0x34
CREATE_MON_MON_OFFSET = 0x44
CREATE_MON_PARTY_OFFSET = 0xA8
# struct Pokemon [decomp:include/pokemon.h]: an 80-byte BoxPokemon and 20 bytes of party data.
PARTY_MON_SIZE = 100
PARTY_SIZE = 6                      # [decomp:include/constants/party_menu.h]
CREATE_MON_HEADER_SIZE = 16
# The first 116 bytes are exactly what bs43 and bs44 returned - header then mon - and the party
# word is an addendum past them, so those dumps still read.
CREATE_MON_ANSWER_SIZE = CREATE_MON_HEADER_SIZE + PARTY_MON_SIZE + 4

# struct SaveBlock1 [decomp:include/global.h:772]. THIS IS NOT WHERE A PARTY WRITE GOES: it is
# only where SavePlayerParty copies TO [decomp:src/load_save.c:160], so bs46's append here was
# erased by the console's own save seconds later. The offsets stay for reading it.
SAV1_PARTY_COUNT = 0x34
SAV1_PARTY = 0x38
SAV1_VARS = 0x1000                  # u16 vars[VARS_COUNT], indexed by (id - VARS_START)

# struct MysteryGiftSave [decomp:include/global.h:681], at SaveBlock1 + 0x3120: newsCrc, 444 B of
# WonderNews, cardCrc, 332 B of WonderCard, cardMetadataCrc, then the metadata. The counters a
# Battle Count Card reads live here, and MysteryGift_GetCardStat reads them with no CRC check
# [decomp:src/mystery_gift.c:490] - only the CARD is CRC-guarded.
SAV1_MYSTERY_GIFT = 0x3120
SAV1_CARD_METADATA = SAV1_MYSTERY_GIFT + 0x314
SAV1_CARD_BATTLES_WON = SAV1_CARD_METADATA + 0
SAV1_CARD_BATTLES_LOST = SAV1_CARD_METADATA + 2
SAV1_CARD_NUM_TRADES = SAV1_CARD_METADATA + 4
SAV1_CARD_ICON_SPECIES = SAV1_CARD_METADATA + 6


def sav1_var_offset(var_id):
    """-> where a saved var sits in SaveBlock1, for `save-dump --dump-block sav1 --dump-offset`.
    `GetVarPointer` is `gSaveBlock1Ptr->vars[idx - VARS_START]` [decomp:src/event_data.c:186]."""
    if not 0x4000 <= int(var_id) <= 0x40FF:
        raise ValueError(f"0x{int(var_id):04X} is not a saved var (0x4000..0x40FF)")
    return SAV1_VARS + 2 * (int(var_id) - 0x4000)

# The status half of the party word the payload sends back.
PARTY_WRITE_NONE = 0                # no party write was asked for
PARTY_WRITE_APPENDED = 1            # written at slot == the count that was there, count raised
PARTY_WRITE_FULL = 2                # six mons already: nothing written, nothing changed
PARTY_WRITE_DRY_RUN = 3             # nothing written, and the 100 bytes are the SLOT'S contents

# What an EMPTY party slot actually looks like, which is NOT a hundred zero bytes. ZeroMonData
# zeroes everything and then ends `arg = MAIL_NONE; SetMonData(mon, MON_DATA_MAIL, &arg)`
# [decomp:src/pokemon.c:1737], and mail is at offset 0x55 of struct Pokemon. So byte 85 is 0xFF and
# every other byte is 0. bs45 read exactly that off the console, and it is BETTER evidence than a
# hundred zeros would have been: unclaimed memory does not look like this, a slot the game itself
# zeroed does.
EMPTY_PARTY_SLOT = bytes(85) + b"\xFF" + bytes(PARTY_MON_SIZE - 86)


def is_empty_party_slot(raw):
    """-> whether these 100 bytes are a slot the game zeroed, and so hold no Pokemon."""
    return bytes(raw) == EMPTY_PARTY_SLOT or bytes(raw) == bytes(PARTY_MON_SIZE)
PARTY_WRITE_STATUS = {
    PARTY_WRITE_NONE: "no party write was asked for",
    PARTY_WRITE_APPENDED: "APPENDED to the player's party, and the count was raised",
    PARTY_WRITE_FULL: "the party was already full - NOTHING was written",
    PARTY_WRITE_DRY_RUN: "DRY RUN - nothing was written; the 100 bytes are what is in that slot",
}

# The value that goes in the image, by what was asked for.
PARTY_APPEND_NO = 0
PARTY_APPEND_WRITE = 1
PARTY_APPEND_DRY_RUN = 2

# NUM_SPECIES [decomp:include/constants/species.h]: 412 slots with SPECIES_EGG at 411, and 0 is
# SPECIES_NONE. CreateBoxMon indexes gSpeciesInfo AND gLevelUpLearnsets by this, and the second is
# a table of POINTERS - an out-of-range species is a dereference of whatever follows it.
MAX_SPECIES = 411
MAX_LEVEL = 100
# fixedIV at or above this rolls the IVs instead of setting them [USE_RANDOM_IVS, pokemon.h:232].
USE_RANDOM_IVS = 32
OT_ID_PLAYER_ID = 0                 # the OT is the player, and the id comes off the real save
OT_ID_PRESET = 1                    # fixedOtId is used verbatim
OT_ID_RANDOM_NO_SHINY = 2           # rolled until GET_SHINY_VALUE fails [pokemon.c:1783]
OT_ID_TYPES = (OT_ID_PLAYER_ID, OT_ID_PRESET, OT_ID_RANDOM_NO_SHINY)
SHINY_ODDS = 8                      # [decomp:include/constants/pokemon.h:185]


def shiny_value(ot_id, personality):
    """GET_SHINY_VALUE [decomp:include/pokemon.h:282]; below SHINY_ODDS is a shiny."""
    ot_id, personality = int(ot_id) & 0xFFFFFFFF, int(personality) & 0xFFFFFFFF
    return ((ot_id >> 16) ^ (ot_id & 0xFFFF)
            ^ (personality >> 16) ^ (personality & 0xFFFF))


def is_shiny(ot_id, personality):
    return shiny_value(ot_id, personality) < SHINY_ODDS


def shiny_personality(tid, sid, low=0):
    """A personality that is shiny for this trainer, with `low` as its bottom half.

    The check is symmetric in the two halves, so the top half is simply whatever makes the four
    XOR to zero - which is why bs01's SECRET id matters: without it there is no way to aim this.
    """
    ot_id = (int(sid) << 16 | int(tid)) & 0xFFFFFFFF
    low = int(low) & 0xFFFF
    return (((ot_id >> 16) ^ (ot_id & 0xFFFF) ^ low) << 16 | low) & 0xFFFFFFFF


def build_create_mon(function, species, level, *, fixed_iv=USE_RANDOM_IVS,
                     has_fixed_personality=1, fixed_personality=0,
                     ot_id_type=OT_ID_PLAYER_ID, fixed_ot_id=0, destination=0,
                     party_append=False, party_base=None, party_count=None):
    """The create-mon payload, patched with the eight arguments and where to put the result.

    `function` is a THUMB pointer (bit 0 set), or 0 to call nothing and answer the zeroed buffer -
    which is how the send path is checked with the ROM left out of it.

    `party_append` APPENDS the finished mon to gPlayerParty - the array the GAME uses - at slot ==
    the current gPlayerPartyCount, and raises the count, which is what the game does when a mon is
    caught, so an occupied slot is never touched. NOT the save block's party: SavePlayerParty
    copies gPlayerParty over that when the console saves [decomp:src/load_save.c:160], which is
    what erased bs46. `party_base` and `party_count` default to the addresses bs47 measured.

    `destination` is the general form: an absolute address, which touches no count. Either one is
    a write to the console's live memory and the config layer gates both behind the same override
    as an unsafe save-write.
    """
    from . import rom_map
    party_base = rom_map.GPLAYER_PARTY if party_base is None else int(party_base)
    party_count = rom_map.GPLAYER_PARTY_COUNT if party_count is None else int(party_count)
    function, species, level = int(function), int(species), int(level)
    fixed_iv, ot_id_type = int(fixed_iv), int(ot_id_type)
    has_fixed_personality = int(has_fixed_personality)
    fixed_personality, fixed_ot_id = int(fixed_personality), int(fixed_ot_id)
    destination = int(destination)
    if party_append is True:
        party_append = PARTY_APPEND_WRITE
    elif party_append is False or party_append is None:
        party_append = PARTY_APPEND_NO
    party_append = int(party_append)
    if party_append not in (PARTY_APPEND_NO, PARTY_APPEND_WRITE, PARTY_APPEND_DRY_RUN):
        raise BufferScriptError(
            f"party_append is {PARTY_APPEND_NO} (no), {PARTY_APPEND_WRITE} (append) or "
            f"{PARTY_APPEND_DRY_RUN} (dry run), got {party_append}")
    if party_append:
        for name, address in (("gPlayerParty", party_base),
                              ("gPlayerPartyCount", party_count)):
            if not EWRAM_BASE <= address < EWRAM_BASE + EWRAM_SIZE:
                raise BufferScriptError(
                    f"{name} at 0x{address:X} is not in EWRAM; these are link-time globals "
                    f"[rom_map.py], not something to guess at")
        if not party_base + PARTY_SIZE * PARTY_MON_SIZE <= EWRAM_BASE + EWRAM_SIZE:
            raise BufferScriptError(
                f"gPlayerParty at 0x{party_base:X} does not have "
                f"{PARTY_SIZE * PARTY_MON_SIZE} bytes of EWRAM after it")
    if party_append and destination:
        raise BufferScriptError(
            "a party append computes its own destination from gSaveBlock1Ptr; an absolute address "
            "as well would be two answers to the same question")
    if party_append == PARTY_APPEND_WRITE and not function:
        raise BufferScriptError(
            "with no function to call the mon is a hundred zero bytes, and appending those would "
            "put a corrupt entry in the player's party")
    if function:
        if not function & 1:
            raise BufferScriptError(
                f"0x{function:X} is an ARM pointer; the ROM is THUMB, so a callable address has "
                "bit 0 set (the `bx` selects the state from it)")
        if not ROM_BASE <= function < SCAN_MAX_ADDRESS:
            raise BufferScriptError(
                f"0x{function:X} is not in the cartridge; calling it would run whatever is there")
    if not 0 < species <= MAX_SPECIES:
        raise BufferScriptError(
            f"species must be 1..{MAX_SPECIES}; CreateBoxMon indexes gLevelUpLearnsets, a table "
            f"of pointers, by it [decomp:src/pokemon.c:1861], so {species} is a dereference of "
            "whatever follows the table")
    if not 0 < level <= MAX_LEVEL:
        raise BufferScriptError(f"level must be 1..{MAX_LEVEL}, got {level}")
    if not 0 <= fixed_iv <= 0xFF:
        raise BufferScriptError(f"fixedIV is a u8, got {fixed_iv}")
    if ot_id_type not in OT_ID_TYPES:
        raise BufferScriptError(
            f"otIdType is {OT_ID_PLAYER_ID} (the player's own id), {OT_ID_PRESET} (fixedOtId) or "
            f"{OT_ID_RANDOM_NO_SHINY} (rolled until not shiny), got {ot_id_type}")
    if destination and not SCAN_MIN_ADDRESS <= destination <= SCAN_MAX_ADDRESS - PARTY_MON_SIZE:
        raise BufferScriptError(
            f"0x{destination:X} is not somewhere {PARTY_MON_SIZE} bytes can be written: "
            f"0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
    if ROM_BASE <= destination:
        raise BufferScriptError(
            f"0x{destination:X} is the cartridge, which is read-only; the copy would do nothing "
            "and the answer would look exactly as if it had worked")
    code = bytearray(payload(CREATE_MON))
    for offset, value in (
            (CREATE_MON_FUNCTION_OFFSET, function),
            (CREATE_MON_DESTINATION_OFFSET, destination),
            (CREATE_MON_PARTY_APPEND_OFFSET, party_append),
            (CREATE_MON_PARTY_BASE_OFFSET, party_base),
            (CREATE_MON_PARTY_COUNT_OFFSET, party_count),
            (CREATE_MON_SPECIES_OFFSET, species),
            (CREATE_MON_LEVEL_OFFSET, level),
            (CREATE_MON_FIXED_IV_OFFSET, fixed_iv),
            (CREATE_MON_HAS_FIXED_PERSONALITY_OFFSET, has_fixed_personality),
            (CREATE_MON_FIXED_PERSONALITY_OFFSET, fixed_personality),
            (CREATE_MON_OT_ID_TYPE_OFFSET, ot_id_type),
            (CREATE_MON_FIXED_OT_ID_OFFSET, fixed_ot_id)):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(code)


def create_mon_parameters(code):
    """-> the eight arguments and the destination, read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    return {"function": word(CREATE_MON_FUNCTION_OFFSET),
            "destination": word(CREATE_MON_DESTINATION_OFFSET),
            "party_append": word(CREATE_MON_PARTY_APPEND_OFFSET),
            "party_base": word(CREATE_MON_PARTY_BASE_OFFSET),
            "party_count": word(CREATE_MON_PARTY_COUNT_OFFSET),
            "species": word(CREATE_MON_SPECIES_OFFSET),
            "level": word(CREATE_MON_LEVEL_OFFSET),
            "fixed_iv": word(CREATE_MON_FIXED_IV_OFFSET),
            "has_fixed_personality": word(CREATE_MON_HAS_FIXED_PERSONALITY_OFFSET),
            "fixed_personality": word(CREATE_MON_FIXED_PERSONALITY_OFFSET),
            "ot_id_type": word(CREATE_MON_OT_ID_TYPE_OFFSET),
            "fixed_ot_id": word(CREATE_MON_FIXED_OT_ID_OFFSET)}


def read_create_mon(dump):
    """-> what the call left, from the bytes it sent back.

    An answer of only header + mon is bs43's and bs44's shape, from before the party word existed;
    it reads the same and reports `party` as None rather than inventing one.
    """
    dump = bytes(dump)
    body = CREATE_MON_HEADER_SIZE + PARTY_MON_SIZE
    if len(dump) < body:
        raise BufferScriptError(
            f"create-mon answers with {CREATE_MON_ANSWER_SIZE} bytes, got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little")
             for i in range(0, CREATE_MON_HEADER_SIZE, 4)]
    calls, destination, function, built_at = words
    party = None
    if len(dump) >= body + 4:
        raw = int.from_bytes(dump[body:body + 4], "little")
        party = {"count_before": raw & 0xFF, "slot": (raw >> 8) & 0xFF,
                 "status": (raw >> 16) & 0xFF}
    return {"calls": calls, "destination": destination, "function": function,
            "built_at": built_at, "party": party,
            "mon": dump[CREATE_MON_HEADER_SIZE:body]}


def describe_create_mon(dump, expected=None):
    """The same, as lines to log, with the mon DECODED rather than shown as hex.

    `expected` is create_mon_parameters of the payload that was sent: every field of it that the
    ROM stores in the mon is checked against what came back, so the log says whether the eight
    arguments arrived rather than that something arrived.
    """
    from . import mon as monlib             # here: it reads the decomp at import
    result = read_create_mon(dump)
    raw = result["mon"]
    party = result["party"]
    dry = bool(party and party["status"] == PARTY_WRITE_DRY_RUN)
    lines = [f"create-mon: {result['calls']} call(s), built at 0x{result['built_at']:08X}"
             + (f", calling 0x{result['function']:08X}" if result["function"]
                else ", calling nothing")
             + ((f", WOULD have written 0x{result['destination']:08X}" if dry else
                 f", written to 0x{result['destination']:08X}") if result["destination"] else "")]
    if party and party["status"] != PARTY_WRITE_NONE:
        lines.append(
            f"   party: {PARTY_WRITE_STATUS.get(party['status'], party['status'])}"
            f" - the console held {party['count_before']} mon(s)"
            + (f" and this one is slot {party['slot'] + 1} of {PARTY_SIZE}"
               if party["status"] == PARTY_WRITE_APPENDED else
               f", so a real run would write slot {party['slot'] + 1} of {PARTY_SIZE}"
               if party["status"] == PARTY_WRITE_DRY_RUN else ""))
    if party and party["status"] == PARTY_WRITE_DRY_RUN:
        slot = result["mon"]
        if is_empty_party_slot(slot):
            lines.append(
                "   the slot a real run would write is EMPTY exactly as ZeroMonData leaves one "
                "(every byte 0, mail 0xFF at offset 85) - nothing would be overwritten")
        else:
            live = [i for i, b in enumerate(slot) if b]
            lines.append(
                f"   the slot a real run would write HOLDS SOMETHING - {len(live)} non-zero "
                f"byte(s) at {live[:12]}{'...' if len(live) > 12 else ''} - DO NOT APPEND until "
                "this is understood")
        return lines
    if not result["function"]:
        lines.append("   nothing was called, so the 100 bytes are the buffer as it was sent")
        return lines
    info = monlib.decode_mon(raw)
    if info is None:
        return lines + ["   the answer is too short to decode as a struct Pokemon"]
    pid, ot_id = info["pid"], info["otid"]
    lines.append(f"   personality 0x{pid:08X}  otId 0x{ot_id:08X}  "
                 f"checksum {'VALID' if info['checksum_ok'] else 'WRONG'}"
                 + ("  SHINY" if is_shiny(ot_id, pid) else ""))
    lines.append(f"   species {info['species']} {info['species_name']}  Lv{info['level']}  "
                 f"nickname {info['nickname']!r}  OT {info['otName']!r}  "
                 f"moves {info['moves']}")
    ivs = create_mon_ivs(raw)
    if ivs is not None:
        lines.append(f"   IVs (HP ATK DEF SPE SPA SPD) {ivs}")
    lines.append("   stats (maxHP ATK DEF SPE SPA SPD) "
                 + str([int.from_bytes(raw[o:o + 2], "little")
                        for o in (0x58, 0x5A, 0x5C, 0x5E, 0x60, 0x62)]))
    if expected:
        lines.extend("   " + line for line in check_create_mon(raw, expected))
    return lines


def create_mon_substructs(raw):
    """The decrypted, unshuffled 48 bytes as {G,A,E,M} - the same decode a party dump gets."""
    from . import mon as monlib
    raw = bytes(raw)
    if len(raw) < monlib.BOX_SIZE:
        return None
    pid = int.from_bytes(raw[0:4], "little")
    key = pid ^ int.from_bytes(raw[4:8], "little")
    sec = bytearray(raw[32:80])
    for i in range(12):
        value = int.from_bytes(sec[i * 4:i * 4 + 4], "little") ^ key
        sec[i * 4:i * 4 + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    order = monlib.SUBSTRUCT_ORDER[pid % 24]
    return {k: bytes(sec[order.index(k) * 12:][:12]) for k in "GAEM"}


def create_mon_ivs(raw):
    """-> [HP, ATK, DEF, SPE, SPA, SPD], or None if the 100 bytes are not there."""
    subs = create_mon_substructs(raw)
    if subs is None:
        return None
    word = int.from_bytes(subs["M"][4:8], "little")
    return [(word >> (5 * i)) & 31 for i in range(6)]


def check_create_mon(raw, expected):
    """-> lines saying, field by field, whether the eight arguments reached the ROM.

    This is what makes one run evidence instead of an observation: species, level and the IVs come
    back out of the mon's own encrypted substructs, and the personality and OT id out of the two
    words the key is made of - so a mon that decodes at all already agrees with two of the
    arguments, and the rest are checked one by one.
    """
    from . import mon as monlib
    raw = bytes(raw)
    info = monlib.decode_mon(raw)
    lines = []
    if info is None:
        return ["the answer is too short to check"]
    def verdict(name, want, got):
        lines.append(f"{name}: asked {want}, got {got}"
                     + ("  OK" if want == got else "  <<< MISMATCH"))
    verdict("species", expected["species"], info["species"])
    verdict("level", expected["level"], info["level"])
    if expected["has_fixed_personality"]:
        verdict("personality", f"0x{expected['fixed_personality']:08X}", f"0x{info['pid']:08X}")
    if expected["ot_id_type"] == OT_ID_PRESET:
        verdict("otId", f"0x{expected['fixed_ot_id']:08X}", f"0x{info['otid']:08X}")
    if expected["fixed_iv"] < USE_RANDOM_IVS:
        ivs = create_mon_ivs(raw)
        verdict("IVs", [expected["fixed_iv"]] * 6, ivs)
    lines.append("checksum: " + ("VALID - the ROM encrypted it with its own key"
                                 if info["checksum_ok"] else
                                 "WRONG - these 100 bytes are not a mon the ROM built"))
    return lines


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
    MEMORY_DUMP_MULTI: BufferScriptSpec(
        MEMORY_DUMP_MULTI,
        "the same, but SEVERAL consecutive blocks in one session (--dump-address --dump-blocks N): "
        "the client script runs the payload once per block and each pass sends the next kilobyte",
        None),
    SAVE_WRITE: BufferScriptSpec(
        SAVE_WRITE,
        "write bytes into a save block and read the same region back in the same run; the console "
        "saves afterwards, so the write reaches flash (--write-hex, --dump-block, --dump-offset)",
        None),
    RNG_TRACE: BufferScriptSpec(
        RNG_TRACE,
        "sample one word of memory once a frame, optionally calling a ROM function between the two "
        "halves of each sample, and check the LCG recurrence on what comes back (--trace-address, "
        "--trace-call, --trace-samples; reads only, plus whatever the callee does)",
        None),
    MEMORY_SCAN: BufferScriptSpec(
        MEMORY_SCAN,
        "search memory for a 32-bit value and send back where it is; it returns 0 to be called again "
        "next frame, so one run covers a range no dump could (--scan-word, --scan-start, "
        "--scan-end, --scan-blocks; reads only, writes nothing)",
        None),
    TABLE_SCAN: BufferScriptSpec(
        TABLE_SCAN,
        "search memory for a table by its shape, a run of N words each exactly D above the one before "
        "it, and send back where each run starts and what value it starts with; this is how a table "
        "of pointers is found when no constant in it is known (--table-delta, --table-runlen, "
        "--table-start, --table-end, --table-blocks; reads only, writes nothing)",
        None),
    ANCHORS: BufferScriptSpec(
        ANCHORS,
        "ask the machine where it is: our own load address, the return address into ROM, the stack "
        "and the client's five buffers (writes only its own outgoing buffer)",
        None),
    CREATE_MON: BufferScriptSpec(
        CREATE_MON,
        "call CreateMon, a ROM function taking eight arguments, and send back the 100-byte struct "
        "Pokemon it built; the mon is built inside our own image, so nothing on the console is "
        "written unless --create-mon-append or --create-mon-destination asks for it "
        "(--create-mon-call, --create-mon-species, --create-mon-level, --create-mon-personality)",
        None),
    STRING_GATHER: BufferScriptSpec(
        STRING_GATHER,
        "follow an array of pointers and send back the strings themselves, back to back, instead of "
        "a window of mostly-pointers: a whole Easy Chat group in one run (--gather-address, "
        "--gather-count, --gather-stride; reads only, writes nothing)",
        None),
    CALL: BufferScriptSpec(
        CALL,
        "call any ROM function with arguments we choose, up to eight words in r0..r3 then the stack, "
        "and send back its r0 with one address read either side of the call (--call-address, "
        "--call-arg, --call-watch); the payload writes nothing itself, but the callee may, so the "
        "address has to have been read as code first",
        None),
    CALL_CHAIN: BufferScriptSpec(
        CALL_CHAIN,
        "run a LIST of ROM calls and memory accesses in one frame and send back a word for each, "
        "any step able to use the previous step's result as its address - which is how a function "
        "that returns a pointer (GetVarPointer) becomes a write (--chain-step, repeatable; a write "
        "step needs --write-unsafe)",
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


def scratch_regions(block):
    """-> the (offset, length) spans of that block the game never reads."""
    return SAVE_SCRATCH.get(block, ())


def is_scratch(block, offset, size):
    return any(start <= offset and offset + size <= start + length
               for start, length in scratch_regions(block))


def build_save_write(data, block=SAVE_BLOCK_2, offset=0xB20, *, unsafe=False):
    """The save-write payload, patched to write `data` at `offset` into one save block.

    Refuses, by default, anything the game actually reads. This is the player's live save, the
    console writes it to flash at the end of the session, and a wrong offset here is not a failed
    run but a damaged game. `unsafe=True` is the deliberate override, and the caller that passes it
    is saying it knows which field it is editing.
    """
    if block not in SAVE_BLOCKS:
        raise BufferScriptError(f"block is one of {SAVE_BLOCKS}, got {block!r}")
    data = bytes(data)
    offset = int(offset)
    if not 0 < len(data) <= MAX_SAVE_WRITE_BYTES:
        raise BufferScriptError(
            f"a save write carries 1..{MAX_SAVE_WRITE_BYTES} bytes of data (the payload itself "
            f"takes the first {SAVE_WRITE_DATA_OFFSET}), got {len(data)}")
    if offset < 0 or offset % 2:
        raise BufferScriptError(f"offset {offset} must be positive and halfword aligned")
    if not unsafe and not is_scratch(block, offset, len(data)):
        spans = ", ".join(f"0x{start:X}..0x{start + length:X}"
                          for start, length in scratch_regions(block)) or "nothing"
        raise BufferScriptError(
            f"writing {len(data)} bytes at {block} 0x{offset:X} touches a field the game reads. "
            f"The scratch region of {block} is {spans} (struct SaveBlock2's u8 filler[], never "
            f"referenced in src/). Pass unsafe=True only if you mean to edit a live field.")
    code = bytearray(payload(SAVE_WRITE))
    code[SAVE_WRITE_WHICH_OFFSET:SAVE_WRITE_WHICH_OFFSET + 4] = (
        (0 if block == SAVE_BLOCK_2 else 1).to_bytes(4, "little"))
    code[SAVE_WRITE_OFFSET_OFFSET:SAVE_WRITE_OFFSET_OFFSET + 4] = offset.to_bytes(4, "little")
    code[SAVE_WRITE_SIZE_OFFSET:SAVE_WRITE_SIZE_OFFSET + 4] = len(data).to_bytes(4, "little")
    code[SAVE_WRITE_DATA_OFFSET:] = data.ljust((len(data) + 3) & ~3, b"\x00")
    return bytes(code)


# A DUMPED REGION MUST NOT CHANGE WHILE THE BLOCK IS BEING SENT, and lg172/lg173 paid for it.
# MGL_Send takes the header CRC in one frame, sends the payload in the next and re-checks the CRC in
# the one after [decomp:src/mystery_gift_link.c:155], so a region that changes in between produces a
# header CRC the payload cannot match and the console calls LinkRfu_FatalError - which the player
# reads as "erreur de connexion" mid transmission.
#
# gRngValue is the only address guaranteed to move every frame, so it is the only one named here.
# Anything else volatile has to be found the way this was. docs/leafgreen.md.
MOVING_REGIONS = (
    (rom_map.GRNG_VALUE, 4, "gRngValue, which advances two turns every frame"),
)


def _refuse_a_moving_region(address, size):
    for base, length, what in MOVING_REGIONS:
        if address < base + length and base < address + size:
            raise BufferScriptError(
                f"0x{address:X}..0x{address + size - 1:X} overlaps {what}. MGL_Send takes the "
                "header CRC one frame and sends the bytes the next "
                "[decomp:src/mystery_gift_link.c:155], so a region that moves between them makes "
                "the console call LinkRfu_FatalError - 'erreur de connexion' mid transmission "
                "(lg172, lg173). Dump around it, or read it with rng-trace, which returns it "
                "through the 4-byte channel instead of the block.")


def build_memory_dump_multi(address, size=MAX_BUFFER_SCRIPT_SIZE, blocks=1):
    """The multi-block dump payload, patched with the BASE address and the per-block length.

    How many blocks come back is the CLIENT SCRIPT's business, not the payload's: the payload sends
    whichever block the cursor in `client->param` names and advances it, so the same image serves
    every pass. `mg_script.client_script_dump_memory(blocks)` is what decides the count. `blocks`
    is passed here only so the readability guard covers the WHOLE span - a base that is readable
    says nothing about the kilobyte sixteen blocks later, and CalcCRC16WithTable would walk it.
    """
    address = int(address)
    size = int(size)
    blocks = int(blocks)
    if not 0 < size <= MAX_BUFFER_SCRIPT_SIZE:
        raise BufferScriptError(
            f"a block is 1..{MAX_BUFFER_SCRIPT_SIZE} bytes (MG_LINK_BUFFER_SIZE), got {size}")
    if not 0 <= address <= 0xFFFFFFFF:
        raise BufferScriptError(f"0x{address:X} is not a 32-bit address")
    if address % 2:
        raise BufferScriptError(f"0x{address:X} is not halfword aligned")
    _refuse_a_moving_region(address, size * blocks)
    code = bytearray(payload(MEMORY_DUMP_MULTI))
    code[DUMP_MULTI_BASE_OFFSET:DUMP_MULTI_BASE_OFFSET + 4] = address.to_bytes(4, "little")
    code[DUMP_MULTI_SIZE_OFFSET:DUMP_MULTI_SIZE_OFFSET + 4] = size.to_bytes(4, "little")
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
    _refuse_a_moving_region(address, size)
    code = bytearray(payload(MEMORY_DUMP))
    code[DUMP_TARGET_OFFSET:DUMP_TARGET_OFFSET + 4] = address.to_bytes(4, "little")
    code[DUMP_SIZE_OFFSET:DUMP_SIZE_OFFSET + 4] = size.to_bytes(4, "little")
    return bytes(code)


def script_choices():
    return tuple(sorted(SCRIPT_REGISTRY))


# Which payloads answer with BYTES on ident 19 rather than the 4-byte channel, and which of those
# have a structure the log can decode rather than a region to hex-dump. These live here, beside the
# payloads, because they were duplicated as two hand-maintained tuples in config.py and bs56 was
# lost to exactly that: table-scan ran on the console and found its table, and the host asked for
# 4 bytes because a new payload had been added to neither list. A new payload goes in here.
DUMP_SCRIPTS = frozenset({
    MEMORY_DUMP, MEMORY_DUMP_MULTI, SAVE_DUMP, ANCHORS, SAVE_WRITE, MEMORY_SCAN, TABLE_SCAN,
    RNG_TRACE, STRING_GATHER, CREATE_MON, CALL, CALL_CHAIN,
})
DECODED_SCRIPTS = frozenset({
    MEMORY_SCAN, TABLE_SCAN, RNG_TRACE, STRING_GATHER, CREATE_MON, CALL, CALL_CHAIN,
})
# A payload whose answer the log decodes must first be one whose answer comes back as bytes.
assert DECODED_SCRIPTS <= DUMP_SCRIPTS
# And neither may name a payload that does not exist.
assert DUMP_SCRIPTS <= set(SCRIPT_REGISTRY)


def format_script_help():
    return "; ".join(f"{spec.name}: {spec.description}"
                     for spec in SCRIPT_REGISTRY.values())

# The spans each builder patches, so that a BUILT payload is still recognisable as the payload it
# was built from. Without this every dump, write and scan logs as "unknown buffer script" - the
# operands are the only thing that differs, and they are exactly what the builders change.
PATCHED_SPANS = {
    MEMORY_DUMP: ((DUMP_TARGET_OFFSET, 8),),
    MEMORY_DUMP_MULTI: ((DUMP_MULTI_BASE_OFFSET, 8),),
    SAVE_DUMP: ((SAVE_DUMP_WHICH_OFFSET, 12),),
    SAVE_WRITE: ((SAVE_WRITE_WHICH_OFFSET, MAX_BUFFER_SCRIPT_SIZE),),
    RNG_TRACE: ((TRACE_ADDRESS_OFFSET,
                 TRACE_RESULT_OFFSET - TRACE_ADDRESS_OFFSET + TRACE_HEADER_SIZE
                 + 8 * TRACE_SAMPLE_CAPACITY),),
    MEMORY_SCAN: ((SCAN_CURSOR_OFFSET,
                   SCAN_HITS_OFFSET - SCAN_CURSOR_OFFSET + 8 * SCAN_HIT_CAPACITY),),
    # The parameters and the results and the run state: everything ahead of the code.
    TABLE_SCAN: ((TABLE_CURSOR_OFFSET, TABLE_EXPECT_OFFSET + 4 - TABLE_CURSOR_OFFSET),),
    STRING_GATHER: ((GATHER_SRC_OFFSET,
                     GATHER_STRINGS_OFFSET - GATHER_SRC_OFFSET + GATHER_STRING_AREA),),
    # Everything from the first operand to the end of the mon: the parameters, the four result
    # words and the 100 bytes CreateMon writes into the image itself.
    CREATE_MON: ((CREATE_MON_FUNCTION_OFFSET,
                  CREATE_MON_PARTY_OFFSET - CREATE_MON_FUNCTION_OFFSET + 4),),
    # The operands and the six result words: everything a built call differs from the payload by.
    CALL: ((CALL_FUNCTION_OFFSET,
            CALL_RESULT_OFFSET - CALL_FUNCTION_OFFSET + CALL_ANSWER_SIZE),),
    # The count, the sixteen steps and the answer: everything ahead of the code.
    CALL_CHAIN: ((CHAIN_COUNT_OFFSET,
                  CHAIN_RESULT_OFFSET - CHAIN_COUNT_OFFSET + CHAIN_ANSWER_SIZE),),
}


def describe(code):
    """Name a payload from its bytes, operands and all."""
    code = bytes(code)
    for name, (committed, _) in PAYLOADS.items():
        # save-write is the one payload whose length varies: the bytes it writes are its tail.
        longer_is_fine = name == SAVE_WRITE
        if len(code) != len(committed) and not (longer_is_fine and len(code) > len(committed)):
            continue
        image, reference = bytearray(code[:len(committed)]), bytearray(committed)
        for offset, length in PATCHED_SPANS.get(name, ()):
            image[offset:offset + length] = reference[offset:offset + length]
        if bytes(image) == bytes(reference):
            return f"{name} ({len(code)} bytes of ARM)"
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
    armed_buffer: int = _SEND_BUFFER_ADDRESS    # what CLI_LOAD_TOSS_RESPONSE's InitSend left
    armed_size: int = 4

    @property
    def send_repointed(self):
        """The payload aimed the console's outgoing message at another address."""
        return self.send_buffer != self.armed_buffer

    @property
    def send_resized(self):
        """It kept the address and changed how much goes out - `anchors` fills client->sendBuffer
        itself, so it only has to widen the size."""
        return self.send_size != self.armed_size

    @property
    def send_changed(self):
        """MGL_Send reads BOTH fields at send time [mystery_gift_link.c:166], so either one makes
        what goes out different from the 4-byte response that was armed."""
        return self.send_repointed or self.send_resized


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


# --- models of CreateMon, for running a calling payload offline ----------------------------------
# The emulated cartridge is a header and zeros, so a payload that calls a ROM function would execute
# the zeros. These two THUMB stubs stand in for CreateMon at whatever address the payload was built
# to call, placed with `memory={address: stub}`.
#
# CREATE_MON_ARG_MODEL answers "did eight arguments arrive, in the order the console's own prologue
# reads them?" by writing r0..r3 and the four stack arguments into the destination as eight words.
# It pushes nothing, so [sp,#0] IS the caller's first stack argument. Assembled from:
#
#     str r1,[r0,#4]   str r2,[r0,#8]   str r3,[r0,#12]
#     ldr r1,[sp,#0]   str r1,[r0,#16]  ldr r1,[sp,#4]   str r1,[r0,#20]
#     ldr r1,[sp,#8]   str r1,[r0,#24]  ldr r1,[sp,#12]  str r1,[r0,#28]
#     str r0,[r0,#0]   bx lr
CREATE_MON_ARG_MODEL = bytes.fromhex(
    "41608260c3600099016101994161029981610399c16100607047")
CREATE_MON_ARG_FIELDS = ("mon", "species", "level", "fixedIV", "hasFixedPersonality",
                         "fixedPersonality", "otIdType", "fixedOtId")

# create_mon_copy_model answers the other question - does the answer decode as a struct Pokemon all
# the way through? - by copying 100 bytes a caller prepared over the destination. Assembled from:
#
#     push {r4, lr}    ldr r1,.Lsource   movs r2,#100
#   1: ldrb r4,[r1]    strb r4,[r0]      adds r1,#1   adds r0,#1   subs r2,#1   bne 1b
#     pop {r4}         pop {r0}          bx r0
#     .Lsource: .word 0
_CREATE_MON_COPY_MODEL = bytes.fromhex(
    "10b5054964220c78047001310130013af9d110bc01bc0047")
CREATE_MON_COPY_MODEL_SOURCE = len(_CREATE_MON_COPY_MODEL)      # where the .word goes


def create_mon_copy_model(source):
    """A model of CreateMon that copies the 100 bytes at `source` into its first argument."""
    return _CREATE_MON_COPY_MODEL + (int(source) & 0xFFFFFFFF).to_bytes(4, "little")


class _Machine:
    """The console's memory across a whole CLI_RUN_BUFFER_SCRIPT, not just one call.

    The copy into gDecompressionBuffer happens ONCE, at the CLI_RUN_BUFFER_SCRIPT command
    [decomp:src/mystery_gift_client.c:239]; after that Client_RunBufferScript calls the payload
    every frame until it returns 1 [:276]. So a payload that returns anything else is called again
    with its own image - code and data - exactly as it left it. One instance of this class is one
    such session, and `call` is one frame.
    """

    def __init__(self, code, *, param=0, sav2=b"", sav1=b"", memory=None, send_size=4,
                 send_ident=0, rom=None):
        try:
            import unicorn
            from unicorn import arm_const
        except ImportError:  # pragma: no cover - exercised only on a machine without unicorn
            raise BufferScriptError(
                "offline execution needs unicorn (pip install unicorn)") from None
        self._unicorn = unicorn
        self._arm = arm_const

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

        self.uc = uc
        self.armed_size = send_size
        self._sav2_len, self._sav1_len = len(sav2), len(sav1)
        self.calls = 0

    def call(self, instruction_limit=_INSTRUCTION_LIMIT):
        """One frame: what Client_RunBufferScript does with our payload, once."""
        uc, unicorn, arm_const = self.uc, self._unicorn, self._arm
        uc.reg_write(arm_const.UC_ARM_REG_R0, _CLIENT_ADDRESS + CLIENT_PARAM)
        uc.reg_write(arm_const.UC_ARM_REG_R1, _SAV2_ADDRESS)
        uc.reg_write(arm_const.UC_ARM_REG_R2, _SAV1_ADDRESS)
        uc.reg_write(arm_const.UC_ARM_REG_SP, STACK_POINTER)
        uc.reg_write(arm_const.UC_ARM_REG_LR, _RETURN_ADDRESS | 1)

        executed = [0]

        def count(uc_, address, size, user_data):
            executed[0] += 1

        handle = uc.hook_add(unicorn.UC_HOOK_CODE, count)
        try:
            uc.emu_start(GDECOMPRESSION_BUFFER, _RETURN_ADDRESS, count=instruction_limit)
        except unicorn.UcError as exc:
            pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
            raise BufferScriptError(
                f"the payload faulted at pc=0x{pc:08X} (offset "
                f"{pc - GDECOMPRESSION_BUFFER}): {exc}") from None
        finally:
            uc.hook_del(handle)
        pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
        if pc != _RETURN_ADDRESS:
            raise BufferScriptError(
                f"the payload never returned: stopped at pc=0x{pc:08X} after {executed[0]} "
                "instructions. On the console that is a hang inside the Mystery Gift menu.")
        self.calls += 1

        def read_word(offset):
            return int.from_bytes(uc.mem_read(_CLIENT_ADDRESS + offset, 4), "little")

        def read_half(offset):
            return int.from_bytes(uc.mem_read(_CLIENT_ADDRESS + offset, 2), "little")

        client = ClientState(
            param=read_word(CLIENT_PARAM),
            send_buffer=read_word(CLIENT_LINK + LINK_SEND_BUFFER),
            send_size=read_half(CLIENT_LINK + LINK_SEND_SIZE),
            send_ident=read_half(CLIENT_LINK + LINK_SEND_IDENT),
            armed_buffer=_SEND_BUFFER_ADDRESS, armed_size=self.armed_size)
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
            sav2=bytes(uc.mem_read(_SAV2_ADDRESS, self._sav2_len)) if self._sav2_len else b"",
            sav1=bytes(uc.mem_read(_SAV1_ADDRESS, self._sav1_len)) if self._sav1_len else b"",
            instructions=executed[0],
            client=client,
            pending_send=pending,
        )


def emulate(code, *, param=0, sav2=b"", sav1=b"", memory=None, send_size=4,
            send_ident=0, rom=None, instruction_limit=_INSTRUCTION_LIMIT):
    """Run a payload the way Client_RunBufferScript does, on a model of the console's memory.

    `send_size`/`send_ident` are the send a preceding client-script command already set up (4 bytes
    of MG_LINKID_RESPONSE after CLI_LOAD_TOSS_RESPONSE); `memory` places extra regions the payload
    may read, as {address: bytes}; `rom` seeds the cartridge at 0x08000000. The result's
    `pending_send` is what a following CLI_SEND_LOADED would actually transmit - the bytes at
    link->sendBuffer, wherever the payload left it pointing.

    ONE call. A payload that returns anything but 1 is called again on the console, so use
    `emulate_repeating` for those; this reports what a single frame did.

    The caller is a THUMB function, so lr carries bit 0 set; a payload that returns with anything
    but `bx lr` (a `mov pc, lr`, say) would leave the console in ARM state and crash, and this
    reproduces that faithfully.
    """
    return _Machine(code, param=param, sav2=sav2, sav1=sav1, memory=memory,
                    send_size=send_size, send_ident=send_ident,
                    rom=rom).call(instruction_limit=instruction_limit)


@dataclass
class RepeatedRun:
    """A whole multi-frame payload: every call it took, and what the last one left."""
    calls: int
    final: BufferScriptRun
    instructions: int       # summed over the calls, which is what a frame budget is spent on

    @property
    def done(self):
        return self.final.done


def emulate_repeating(code, *, max_calls=MAX_SCAN_CALLS + 2,
                      instruction_limit=_INSTRUCTION_LIMIT, **kwargs):
    """Call a payload until it returns 1, as the console does, once a frame.

    `max_calls` is this side's own bound, not the payload's watchdog: a payload that would hang the
    Mystery Gift menu with no way out is a BufferScriptError here instead, which is the whole
    reason to run it offline first.
    """
    machine = _Machine(code, **kwargs)
    instructions = 0
    for _ in range(int(max_calls)):
        run = machine.call(instruction_limit=instruction_limit)
        instructions += run.instructions
        if run.done:
            return RepeatedRun(calls=machine.calls, final=run, instructions=instructions)
    raise BufferScriptError(
        f"the payload had not returned {BUFFER_SCRIPT_DONE} after {max_calls} calls. On the "
        "console that is the Mystery Gift menu calling it every frame for ever, with no way out.")
