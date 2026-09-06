---
title: Reverse-engineering a Switch title
nav_order: 5
---

# Reverse-engineering a Switch title

How to read a retail Switch game's own code, on a machine far too small to hold it. General to any
Unity/IL2CPP title; the worked example is Brilliant Diamond / Shining Pearl, whose two NSPs are
7.3 GB against 3.5 GB of free disk.

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
Decrypt the RomFS header off the share, walk the file metadata, and pull the one file you want.
**The RomFS header's size field reading back as `0x50` is the proof the counter is right.**

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

## The tools

All offline, none needs a console:

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
