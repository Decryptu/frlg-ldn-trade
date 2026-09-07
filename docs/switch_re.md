---
title: Reverse-engineering a Switch title
nav_order: 5
---

# Reverse-engineering a Switch title

How to read a retail Switch game's own code, on a machine far too small to hold it. General to any
Unity/IL2CPP title; the worked example is Brilliant Diamond / Shining Pearl, whose two NSPs are
7.3 GB against 3.5 GB of free disk.

## Bringing up a new title: do these in order

Written after BDSP, where steps 1 and 2 were skipped and cost two sessions of brute force that
steps 1 and 2 would have answered in minutes.

1. **Search the published sources for a constant you already have.** The NintendoClients wiki is a
   repository, so code search reaches inside it, and it carries per-game pages that its own summary
   tables never link to.

       gh search code "<a constant, a field name, a class name>" --limit 20
       gh api repos/kinnay/NintendoClientsWiki/contents --jq '.[].name'
       gh api repos/kinnay/NintendoClientsWiki/contents/<Page>.md --jq .content | base64 -d

   Read the *per-game* page, the protocol page for the right **Pia version band**, and the
   application-data page. A summary table gives one derived value; the pages give the rule.

2. **Look for the game's own code already dumped.** A decompiled C# dump of a Unity title may be on
   GitHub (`TeamLumi/opendpr` for BDSP) and is faster to read than IL2CPP output.

3. **Get the executable and the metadata**, matching builds - see below. Then name everything before
   reading anything: IL2CPP metadata for the C# surface, C++ RTTI for the native one.

4. **Read the binary to verify, and to get what nobody wrote down.** For BDSP that was the
   `cryptoKeyDataSeed` constant and the rule that turns it into the published key. Published values
   are transcriptions: they can be stale, wrong, or correct in a way that looks wrong.

5. **Only then search a key space.** A sweep is the last resort, not the first, and a sweep with one
   input silently pinned wrong produces a confident negative over the wrong slice.

What a Pia LDN title needs, end to end: the **LDN passphrase** (to associate at all), the game's
**cryptoKeyDataSeed** and **local communication version** (which give the Pia game key), the
**session param** and **network id** from the advertisement, and the **source MAC** of each sender.
`docs/pia.md` has the derivations.

## Do not unpack the NSP

An NSP is a PFS0 archive of NCA files. The executable is a section near the *end* of a multi-GB NCA,
and the trick is never to materialise the rest:

1. **Parse the PFS0 header yourself.** hactool's `--listfiles` offsets are relative to the data base,
   not absolute - reading them as absolute is what makes the ticket come back as garbage.
2. **Decrypt the title key from the ticket.** The encrypted key is at ticket `+0x180` and the rights
   id at `+0x2A0`, both absolute in the file; the rights id's last byte is the key generation, so
   generation *n* uses `titlekek_{n-1}`. The rights id must equal the NSP's own filename - that is
   the check. **hactool wants the *encrypted* key on `--titlekey`** and does the titlekek step
   itself.
3. **Build a sparse file.** `dd` the head of the NCA, `truncate -s` it to the NCA's real size (costs
   nothing), then `dd ... seek_bytes conv=notrunc` only the ranges you need into place. 109 MB on
   disk stands in for 2.7 GB and hactool's bounds checks are satisfied. `du -h` tells the truth
   about such a file; `ls -l` does not.

For a file inside romfs, skip hactool entirely: NCA sections are AES-128-CTR under the decrypted
title key, with the counter formed from the section's own CTR value and `offset >> 4` big-endian.
CTR is seekable, so any range decrypts on its own and nothing has to be extracted at all -
`tools/switch/romfs_read.py` walks, greps and single-file-extracts a 4.2 GB RomFS straight off the
share, with the container never copied and no disk spent. **The RomFS header's size field reading
back as `0x50` is the proof the counter is right**, and the reader raises rather than parse a header
that says anything else - a wrong key, a wrong section offset and a wrong counter all land there
first.

Traps: a `prod.keys` with malformed lines (34 hex digits instead of 32) aborts hactool on the first
one; filter to 32/64-digit values first. And hactool segfaults on `--listromfs` against a sparse
file whose tables are not present.

## Name everything before reading anything

The single most valuable lesson from this work: **a retail Unity title carries two independent
naming layers, and finding them first turns guesswork into reading.**

**IL2CPP metadata names the C# surface.** `global-metadata.dat` (in romfs, at
`Data/Managed/Metadata`) plus the executable is what Il2CppDumper needs; it produces a full C# class
dump with the RVA of every method. Pair the *matching* metadata and executable - a game update ships
its own metadata, and mixing an update's binary with the base game's metadata produces nonsense.

**C++ RTTI names the native surface.** Itanium-ABI `type_info` records survive in the executable, and
because both a `type_info`'s name pointer and a vtable's `type_info` pointer are ordinary relocations,
the whole map falls out of the relocation table with no heuristics. In BDSP this named **279
`nn::pia` classes and 2269 virtual methods** - the entire middleware architecture, including which
class each crypto routine belongs to.

That last point decided a question that days of guessing had not: whether a capture's session key
came from the LDN derivation or the LAN one. The two implementations are near-identical in shape and
live in `LocalProtocol` and `LanProtocol` respectively, and only the class names distinguish them.

## A constant that is in none of the places you would scan

A `[Serializable]` C# class is not necessarily an asset. If it is a plain class rather than a
`ScriptableObject`, its defaults are written by its **constructor**, and a constant `byte[]` there is
not built element by element - the compiler emits `RuntimeHelpers.InitializeArray` against a static
field of `<PrivateImplementationDetails>`. That field's bytes live in `global-metadata.dat`'s
field-default-value table, so:

- scanning the executables finds nothing (the bytes are not in code),
- scanning romfs finds nothing (they are not in an asset),
- and Il2CppDumper's own tables do not carry the value either.

The route in is the ADRP/LDR pair in the constructor: it names a metadata-usage slot, the slot
resolves to `Field$<PrivateImplementationDetails>.<HEX>`, and **that hex IS the SHA-1 of the initial
data** - a C# compiler names those fields after their own contents. So the value can be pulled out of
the metadata by field name and then *verified by hashing it back*, which makes the read self-proving
rather than a guess. Session 45 got BDSP's 16-byte Pia game key this way after five sessions of
scans had come up empty, and the same loop closes any `[Serializable]` constant in any IL2CPP title.

## Check which VERSION you dumped, before you believe a struct

A game on sale has a base release and an update, they are separate NSPs, and **the executable is
easy to take from one and the metadata from the other** - the base romfs is a plain RomFS while the
update's is a BKTR patch section, so the base is the one that extracts without a fight. That is
exactly what makes it the one you accidentally read.

It matters more than it sounds. BDSP's base game defines **24** network message classes and the
version on the console defines **65**; `PosData` went from `Vector3 pos, short rotY` to
`ushort posX, ushort posZ, short rotY`, so a point shrank from 16 bytes to 6, and `JoinData` gained
two fields and lost its alignment. A layout read out of the base dump is not a slightly stale
layout - it is a different protocol, and it decodes a real capture into plausible nonsense.

Two cheap checks, and run both:

- **Ask the metadata what it knows.** `strings global-metadata.dat | grep` for a class the newer
  version added and one the older version had. BDSP's carries `NetDataTradeStandbyData`, which the
  update deleted, and has no `NetPlayerNameData`, which the update added - so it is the base's, and
  no further reading is needed to know it.
- **Divide a captured length by the struct size.** A message of 72 bytes carrying a list of points
  is 12 of 6 and cannot be a whole number of 16-byte ones. The wire settles a version question
  without an opinion in it.

A constant is a different case and does not need re-reading: BDSP's Pia key seed came out of the
base metadata and decrypts 674 of 674 packets from the updated console. Something verified on the
wire is verified whatever it was read from. What needs the right version is anything **structural**
that a capture has not confirmed.

## "Who calls this?" has to count `b` as well as `bl`

Finding a known function's call sites in an ARM64 image needs no relocation table: `bl` is
`100101` followed by a signed 26-bit word offset, so a linear scan over the image words answers it
exactly. That is the right method, and it has one failure that is easy to miss.

**A tail call is `b`, opcode `000101`.** A compiler emits one wherever the call is the last thing a
method does, and a one-line C# forwarder - `void SendX(X d) => netData.SendReliableData(d, ...)` -
is exactly that shape, so the *senders of a message* are the population most likely to be invisible
to a BL-only scan. In BDSP, a scan that matched BL only reported **zero callers** for
`ANetData<SelectData>$$SendReliableData` and `ANetData<TransitionData>$$SendReliableData`, which was
written down as "the game never sends these". Counting both opcodes finds nine senders between
them, every one a `b`, in the Union Room's context menus:

    ANetData<SelectData>$$SendReliableData        UnionBattleContextMenu$$SendRuleSelectState + 1
    ANetData<TransitionData>$$SendReliableData    UnionContextMenu$$SendTransitionData,
                                                  UnionFrontDeskTradeController$$SendTransision,
                                                  and five yes/no-window closures

Three hardware runs were planned against the wrong reading. **A "0 callers" result is a claim about
your scan before it is a claim about the game** - and the two opcodes differ in one bit, so there is
no reason to scan for one of them.

The other half of the same caution: a method with no callers of *either* kind is not dead. It may be
a delegate. `TradeStateModel`'s `WriteSaveData`, `FirstSave` and `SendTradeState` have no branch to
them anywhere in the image because the state machine registers them as `Action`s, and the reference
is an ADRP/ADD pair - which is `arm64_xref.py`'s question, not the branch scanner's.

## The tools

All offline, none needs a console:

    tools/switch/romfs_read.py   walk, grep and single-file-extract a RomFS in place, off the
                                 encrypted container; nothing is unpacked and no disk is spent
    tools/switch/nso_read.py     decompress an NSO's three segments (pure-Python LZ4 block
                                 decoder) and lay them at their memory offsets, so a file offset
                                 IS an address
    tools/switch/nso_relocs.py   MOD0 -> dynamic -> relocations; NSO vtable slots are empty in the
                                 static image and filled at load time, so "who points at this
                                 function" is a relocation question, not a pointer scan
    tools/switch/rtti_names.py   type_info + vtables -> class and virtual-method names
    tools/switch/arm64_xref.py   ADRP(+ADD|+LDR) cross-references, BL call graph, function starts
    tools/switch/arm64_dis.py    capstone window disassembly

A caution on the reference material: published tables of packet formats and key derivations are
worth having, but where they conflict with the title's own code, the code wins. Prose that says a
game "encrypts the SSID **or** random values seeded with the session parameter" is describing two
different implementations, and only the binary says which one a given capture used.

The same caution applies to published *values*. A table of per-game keys is a transcription, and a
transcription can be wrong in a way that looks right: BDSP's published Pia game key differs from the
measured one in four bytes out of sixteen while keeping its shape, which is indistinguishable from
correct until you read the game. Where a constant can be verified against the binary - a SHA-1-named
field is the ideal case - verify it, and treat the table as a hint about where to look.
