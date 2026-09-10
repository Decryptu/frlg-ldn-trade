---
title: Reverse-engineering a Switch title
nav_order: 3
---

# Reverse-engineering a Switch title

How to read a retail Switch game's own code on a machine too small to hold it. The worked examples
are Brilliant Diamond / Shining Pearl (Unity/IL2CPP, two NSPs totalling 7.3 GB against 3.5 GB of
free disk) and Sword / Shield (native C++, a 13.3 GB XCI on a network share).

## Order of work

1. **Search the published sources for a constant you already have.** The NintendoClients wiki is a
   repository, so code search reaches inside it, and it carries per-game pages its own summary
   tables never link to.

       gh search code "<a constant, a field name, a class name>" --limit 20
       gh api repos/kinnay/NintendoClientsWiki/contents --jq '.[].name'
       gh api repos/kinnay/NintendoClientsWiki/contents/<Page>.md --jq .content | base64 -d

   Read the per-game page, the protocol page for the right Pia version band, and the
   application-data page. A summary table gives one derived value; the pages give the rule.

2. **Look for the game's own code already dumped.** A decompiled C# recreation of a Unity title may
   be on GitHub (`TeamLumi/opendpr` for BDSP) and is faster to read than IL2CPP output. A game key
   or passphrase is also a good search term for finding third-party clients: searching Sword/Shield's
   Pia game key returns four published LAN-mode clients.

3. **Get the executable and the metadata, matching builds.** Then name everything before reading
   anything: IL2CPP metadata for the C# surface, C++ RTTI for the native one.

4. **Read the binary to verify, and to obtain what nobody wrote down.** For BDSP that was the
   `cryptoKeyDataSeed` constant and the rule that turns it into the published key.

5. **Only then search a key space.** A sweep with one input silently pinned wrong produces a
   confident negative over the wrong slice.

What a Pia LDN title needs, end to end: the LDN passphrase (to associate), the game's
`cryptoKeyDataSeed` and local communication version (which give the Pia game key), the session
parameter and network id from the advertisement, and the source MAC of each sender. The derivations
are on [The Pia layer](pia.md).

## Getting the executable out without unpacking

### From an NSP

An NSP is a PFS0 archive of NCA files. The executable is a section near the *end* of a multi-GB NCA.

1. **Parse the PFS0 header yourself.** hactool's `--listfiles` offsets are relative to the data base,
   not absolute; reading them as absolute makes the ticket come back as garbage.
2. **Decrypt the title key from the ticket.** The encrypted key is at ticket `+0x180` and the rights
   id at `+0x2A0`, both absolute in the file. The rights id's last byte is the key generation, so
   generation *n* uses `titlekek_{n-1}`. The rights id must equal the NSP's own filename. hactool
   wants the *encrypted* key on `--titlekey` and does the titlekek step itself.
3. **Build a sparse file.** `dd` the head of the NCA, `truncate -s` it to the NCA's real size, then
   `dd ... seek_bytes conv=notrunc` only the ranges needed into place. 109 MB on disk stands in for
   2.7 GB and hactool's bounds checks are satisfied. `du -h` reports the truth about such a file;
   `ls -l` does not.

### From an XCI

`tools/switch/xci_read.py` walks the HFS0 partitions, decrypts each NCA header in place (AES-128-XTS
under `header_key`, big-endian sector tweak) and prints the title id, content type, key generation,
and each section's offset, counter and key:

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --keys prod.keys --type Program

A cartridge NCA's rights id is all zeroes, so there is no ticket step: the body key is key area slot
2 under `key_area_key_application_<generation>`, where the generation is
`max(crypto_type, crypto_type2) - 1`. An update's exefs is section 0 of the update Program NCA, an
ordinary CTR PartitionFS — BKTR patching only touches its RomFS — so `main` comes out with:

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --nca <id> --exefs 0 --extract main

Two struct-layout traps cost a pass each: the FS header's `fs_type` is at +0x2 and the hash type at
+0x3 (hactool's struct names them the other way round), and the 8-byte section counter is used
**reversed**.

### From a RomFS

Skip hactool entirely. NCA sections are AES-128-CTR under the decrypted title key, with the counter
formed from the section's own CTR value and `offset >> 4` big-endian. CTR is seekable, so any range
decrypts on its own and nothing has to be extracted. `tools/switch/romfs_read.py` walks, greps and
single-file-extracts a 4.2 GB RomFS straight off the container.

The RomFS header's size field reading back as `0x50` is the check that the counter is right; the
reader raises rather than parse a header that says anything else. A wrong key, a wrong section
offset and a wrong counter all land there first.

Two hactool traps: a `prod.keys` with malformed lines (34 hex digits instead of 32) aborts it on the
first one, and it segfaults on `--listromfs` against a sparse file whose tables are not present.

## Naming everything before reading anything

A retail Unity title carries two independent naming layers.

**IL2CPP metadata names the C# surface.** `global-metadata.dat` (in romfs, at `Data/Managed/Metadata`)
plus the executable is what Il2CppDumper needs; it produces a full C# class dump with the RVA of
every method. Pair the *matching* metadata and executable — a game update ships its own metadata, and
mixing an update's binary with the base game's metadata produces nonsense.

**C++ RTTI names the native surface.** Itanium-ABI `type_info` records survive in the executable, and
because both a `type_info`'s name pointer and a vtable's `type_info` pointer are ordinary
relocations, the whole map falls out of the relocation table with no heuristics.
`tools/switch/rtti_names.py` reports 279 `nn::pia` classes and 2269 virtual methods for BDSP, and 252
classes and 2036 virtual methods for Sword/Shield.

That layer answers questions guessing cannot: whether a capture's session key came from the LDN
derivation or the LAN one is decided by the class the routine belongs to (`LocalProtocol` against
`LanProtocol`), and the two implementations are near-identical in shape.

It also turns "find the handler" into a table lookup. `vfunc4` is `GetProtocolId` on every Pia
protocol object and `vfunc9` is its receive slot, so naming one protocol's dispatcher names every
other protocol's the same way. `scratchpad/swsh_vtable.py` prints a vtable in index order.

A vtable with holes in it is a vtable **group** for a class with multiple inheritance: the "empty
slots" are the next sub-object's offset-to-top and typeinfo.

## A constant in none of the places you would scan

A `[Serializable]` C# class is not necessarily an asset. If it is a plain class rather than a
`ScriptableObject`, its defaults are written by its **constructor**, and a constant `byte[]` there is
not built element by element — the compiler emits `RuntimeHelpers.InitializeArray` against a static
field of `<PrivateImplementationDetails>`. That field's bytes live in `global-metadata.dat`'s
field-default-value table, so scanning the executables finds nothing (the bytes are not in code),
scanning romfs finds nothing (they are not in an asset), and Il2CppDumper's tables do not carry the
value either.

The route in is the ADRP/LDR pair in the constructor: it names a metadata-usage slot, the slot
resolves to `Field$<PrivateImplementationDetails>.<HEX>`, and **that hex is the SHA-1 of the initial
data** — a C# compiler names those fields after their own contents. The value can therefore be pulled
out of the metadata by field name and verified by hashing it back. This is how BDSP's 16-byte Pia
game key seed was found, and the same loop closes any `[Serializable]` constant in any IL2CPP title.

A native C++ title needs none of this: its constants are in rodata where a cross-reference finds
them.

## Check which version you dumped

A game on sale has a base release and an update, they are separate NSPs, and it is easy to take the
executable from one and the metadata from the other — the base romfs is a plain RomFS while the
update's is a BKTR patch section, so the base is the one that extracts without a fight.

The difference is not cosmetic. BDSP's base game defines **24** network message classes and 1.3.0
defines **65**; `PosData` went from `Vector3 pos, short rotY` to `ushort posX, ushort posZ, short
rotY`, so a point shrank from 16 bytes to 6, and `JoinData` gained two fields and lost its alignment.
A layout read out of the base dump decodes a real capture into plausible nonsense.

Two cheap checks:

- **Ask the metadata what it knows.** `strings global-metadata.dat | grep` for a class the newer
  version added and one the older version had. BDSP's base metadata carries
  `NetDataTradeStandbyData`, which the update deleted, and has no `NetPlayerNameData`, which the
  update added.
- **Divide a captured length by the struct size.** A 72-byte message carrying a list of points is 12
  of 6 and cannot be a whole number of 16-byte ones.

A **constant** does not need re-reading: BDSP's Pia key seed came out of the base metadata and
decrypts 674 of 674 packets from an updated console. Anything **structural** that a capture has not
confirmed does.

## Reading a game update's RomFS

An update's Program NCA carries its executable in an ordinary CTR exefs and its RomFS as a BKTR
section: a patch over the base game's RomFS rather than a copy of it. Two tables at the end of the
update's section, both under the section's ordinary CTR, decide every byte of the virtual RomFS:

- the relocation table maps a virtual range to a physical one, in the update's own section or in the
  base game's RomFS section (`is_patch`);
- the subsection table gives each physical range of the update's section its own counter value,
  which replaces bytes 4..8 of the section counter.

Entries sit in 0x4000-byte buckets keyed by offset (hactool `bktr.c`). `tools/switch/bktr_read.py`
composes the two containers into one seekable section and hands it to the RomFS reader, so an
update's `global-metadata.dat` comes out of the two NSPs in place:

    ./.venv/bin/python tools/switch/bktr_read.py UPDATE.nsp --base BASE.nsp \
        --extract /Data/Managed/Metadata/global-metadata.dat

An NSP's Program NCA has a rights id, and `xci_read.py` reads its title key from the `<rights id>.tik`
in the same container: the encrypted key is at ticket `+0x180` and decrypts under
`titlekek_<keygen>`. BDSP 1.3.0's metadata is 12,496,504 bytes and carries `NetPlayerNameData`; the
base game's does not.

## Finding callers

Finding a known function's call sites in an ARM64 image needs no relocation table: `bl` is `100101`
followed by a signed 26-bit word offset, so a linear scan over the image words answers it exactly.

**A tail call is `b`, opcode `000101`,** and the two opcodes differ in one bit. A compiler emits a
tail call wherever the call is the last thing a method does, and a one-line C# forwarder —
`void SendX(X d) => netData.SendReliableData(d, ...)` — is exactly that shape, so *the senders of a
message* are the population most likely to be invisible to a BL-only scan. In BDSP a BL-only scan
reported zero callers for `ANetData<SelectData>$$SendReliableData` and
`ANetData<TransitionData>$$SendReliableData`; counting both opcodes finds nine senders between them,
every one a `b`, in the Union Room's context menus. Scan for both.

A method with no callers of either kind is not necessarily dead. It may be a delegate:
`TradeStateModel`'s `WriteSaveData`, `FirstSave` and `SendTradeState` have no branch to them anywhere
in the image because the state machine registers them as `Action`s, and the reference is an ADRP/ADD
pair — `arm64_xref.py`'s question, not the branch scanner's.

Function bounds matter as much as opcodes. `arm64_xref.function_start` walks back through `udf`
padding, so a store can be attributed to the function before the one that contains it; check the
prologue. Bounding a function by "the first N bytes after its entry" walks through the `ret` into the
next function's body and stitches two unrelated bodies into one call-graph edge.

Decode constants with a disassembler rather than by pattern: `mov w0, #0x80` is encoded as an
ORR-immediate on ARM64, so a naive protocol-id sweep misses it.

## Calling into nnSdk

A call into nnSdk goes through a GOT slot filled by a JUMP_SLOT relocation naming the symbol, so the
slot is the thing to cross-reference and its one PLT stub is the thing to count callers of.
`tools/switch/nso_imports.py` maps imported symbol to GOT slot.

## The tools

All offline; none needs a console.

    tools/switch/xci_read.py     walk an XCI's HFS0 partitions (or an NSP's PFS0), decrypt every
                                 NCA header in place and print the title id, key generation and each
                                 section's offset, counter and key; --exefs N lists the exefs and
                                 --extract pulls one file out without unpacking the image
    tools/switch/romfs_read.py   walk, grep and single-file-extract a RomFS in place, off the
                                 encrypted container
    tools/switch/nso_read.py     decompress an NSO's three segments (pure-Python LZ4 block decoder)
                                 and lay them at their memory offsets, so a file offset IS an address
    tools/switch/nso_relocs.py   MOD0 -> dynamic -> relocations. NSO vtable slots are empty in the
                                 static image and filled at load time, so "who points at this
                                 function" is a relocation question, not a pointer scan
    tools/switch/nso_imports.py  imported symbol -> the GOT slot that holds it
    tools/switch/rtti_names.py   type_info + vtables -> class and virtual-method names
    tools/switch/arm64_xref.py   ADRP(+ADD|+LDR) cross-references, BL call graph, function starts
    tools/switch/arm64_dis.py    capstone window disassembly

`scratchpad/swsh_offset_writes.py OFF [SIZE] [LO] [HI]` lists every store to one struct offset in an
address window, with the enclosing function — the fastest way to find every writer of a state field.
