#!/usr/bin/env python3
"""Name Pia's C++ classes and their virtual methods from the binary's own RTTI.

main.bin keeps Itanium-ABI type_info records for nn::pia (session 43, sp15). Each one is
{vtable-of-type_info, name*, [bases...]}, and every polymorphic class's vtable holds
{offset-to-top, type_info*, method0, method1, ...}. Both the name pointer and the type_info pointer
are RELATIVE relocations, so the whole map falls out of the relocation table - no heuristics.

This is the same move `scripts/gen_worker_names.py` makes for FRLG: stop guessing what a function is
and let the binary's own structure name it.
"""
import sys, os, struct, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nso_relocs import relatives


def cstr(img, off, limit=200):
    e = img.find(b"\0", off, off + limit)
    return img[off:e].decode("utf-8", "replace") if e > off else ""


def demangle(n):
    """Just enough of the Itanium nested-name grammar for nn::pia::x::Y."""
    if not n.startswith("N") or not n.endswith("E"):
        return n
    body, parts, i = n[1:-1], [], 0
    while i < len(body):
        j = i
        while j < len(body) and body[j].isdigit(): j += 1
        if j == i: break
        ln = int(body[i:j]); parts.append(body[j:j+ln]); i = j + ln
    return "::".join(parts) if parts else n


def build(img, text_end, rodata=None):
    """`rodata` bounds the band the mangled names live in; without it, everything
    above text_end is searched, which is right for any single-module image."""
    lo, hi = rodata if rodata else (text_end, len(img))
    rel = relatives(img)
    by_slot = dict(rel)
    targets = collections.defaultdict(list)
    for s, a in rel:
        targets[a].append(s)

    # a type_info: slot+8 holds the name pointer (a string), slot+0 the type_info vtable
    typeinfos = {}
    for s, a in rel:
        if not (lo <= a < hi):                    # the rodata band holding mangled names
            continue
        nm = cstr(img, a)
        if not nm or nm[0] not in "N123456789PK" or len(nm) < 5:
            continue
        typeinfos[s - 8] = demangle(nm)

    # a vtable: some slot holds a pointer to a type_info; methods follow it
    out = {}
    classes = collections.defaultdict(list)
    for ti_addr, name in typeinfos.items():
        for vslot in targets.get(ti_addr, []):
            i, idx = vslot + 8, 0
            while True:
                fn = by_slot.get(i)
                if fn is None or not (0 < fn < text_end):
                    break
                out.setdefault(fn, f"{name}::vfunc{idx}")
                classes[name].append(fn)
                i += 8; idx += 1
    return out, classes, typeinfos


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", help="the decompressed NSO, from nso_read.py")
    ap.add_argument("text_end", type=lambda s: int(s, 0),
                    help="end of .text; a vtable slot outside it is not a method")
    ap.add_argument("query", nargs="?", help="only classes whose name contains this")
    ap.add_argument("--rodata", help="LO:HI band the mangled names live in (default: above text)")
    ap.add_argument("--prefix", default="nn::pia",
                    help="the namespace to count and list; \"\" for every class")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args(argv)

    img = open(args.image, "rb").read()
    band = None
    if args.rodata:
        lo, _, hi = args.rodata.partition(":")
        band = (int(lo, 0), int(hi, 0))
    names, classes, tis = build(img, args.text_end, band)
    want = {k: v for k, v in names.items() if v.startswith(args.prefix)}
    print(f"{len(tis)} type_info records, {len(names)} named vfuncs, "
          f"{len(want)} of them {args.prefix or 'any'}")
    cls = sorted({v.split("::vfunc")[0] for v in want.values()})
    print(f"{len(cls)} {args.prefix or ''} classes")
    if args.query:
        q = args.query.lower()
        for c in cls:
            if q in c.lower():
                fns = sorted(set(classes[c]))
                print(f"  {c}: {len(fns)} vfunc(s) {[hex(f) for f in fns[:10]]}")
    else:
        for c in cls[:args.limit]:
            print("   " + c)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
