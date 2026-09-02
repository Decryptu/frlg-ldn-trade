"""GBA Gen-3 (international/English) character map - encode/decode names.

Mon nicknames/OT names inside a .pk3 are already stored in this charmap, so injecting a
mon needs no re-encoding. We need encode() only for the SIM's own LinkPlayer OT name and
trainer-card text, which we build from a Python string (link.c InitLocalLinkPlayer). decode()
mirrors the name decoder used elsewhere for display. Terminator = 0xFF; padding after the terminator is also
0xFF (FRLG name fields are fixed width, 0xFF-filled).
"""

EOS = 0xFF
PAD = 0xFF

# Decode table: byte -> ASCII. Covers the printable range used by English names. Punctuation values
# verified against the decomp charmap.txt: 0xAD='.', 0xAE='-', 0xAF='·', 0xB0='…', 0xB7='¥', 0xB9='×',
# 0xBA='/'. The old table had 0xAD/0xAE/0xB0/0xBA wrong + was missing 0xAF/0xB7/0xB9 - WIRE-AFFECTING via
# encode() (the LinkPlayer name + NI uname) for any OT name with . - / · … ¥ ×.
_DEC = {0x00: " ", 0xAD: ".", 0xAE: "-", 0xAF: "·", 0xB0: "…",
        0xB7: "¥", 0xB9: "×", 0xBA: "/", 0xB1: "“", 0xB2: "”",
        0xB3: "‘", 0xB4: "’", 0xB5: "♂", 0xB6: "♀", 0xB8: ",",
        0xAB: "!", 0xAC: "?"}
for _i in range(10):
    _DEC[0xA1 + _i] = "0123456789"[_i]
for _i in range(26):
    _DEC[0xBB + _i] = chr(ord("A") + _i)   # 0xBB..0xD4 = A..Z
    _DEC[0xD5 + _i] = chr(ord("a") + _i)   # 0xD5..0xEE = a..z

# Latin-1 accented range 0x01-0x2E, from the decomp charmap.txt (the INTERNATIONAL table, i.e.
# everything above its "@ Hiragana" marker at line 158). Without these, encode() silently DROPPED
# every accented character - "Zoe\u0301" went on the wire as "Zo" - which made a French or German OT
# name wrong rather than merely untranslated.
# NOTE: charmap.txt reuses these same byte values for the Japanese kana (0x01 is BOTH 'A\u0300' and
# 'HIRAGANA A'). The byte's meaning depends on the ROM's language build and this table is the
# international one, so the kana are deliberately NOT included and LANGUAGE_JAPANESE is not offered.
_DEC.update({
    0x01: "\u00c0", 0x02: "\u00c1", 0x03: "\u00c2", 0x04: "\u00c7", 0x05: "\u00c8", 0x06: "\u00c9", 0x07: "\u00ca",
    0x08: "\u00cb", 0x09: "\u00cc", 0x0B: "\u00ce", 0x0C: "\u00cf", 0x0D: "\u00d2", 0x0E: "\u00d3", 0x0F: "\u00d4",
    0x10: "\u0152", 0x11: "\u00d9", 0x12: "\u00da", 0x13: "\u00db", 0x14: "\u00d1", 0x15: "\u00df", 0x16: "\u00e0",
    0x17: "\u00e1", 0x19: "\u00e7", 0x1A: "\u00e8", 0x1B: "\u00e9", 0x1C: "\u00ea", 0x1D: "\u00eb", 0x1E: "\u00ec",
    0x20: "\u00ee", 0x21: "\u00ef", 0x22: "\u00f2", 0x23: "\u00f3", 0x24: "\u00f4", 0x25: "\u0153", 0x26: "\u00f9",
    0x27: "\u00fa", 0x28: "\u00fb", 0x29: "\u00f1", 0x2A: "\u00ba", 0x2B: "\u00aa", 0x2D: "&", 0x2E: "+",
})

# The rest of the international table's Latin glyphs, same source. Umlauts sit up at 0xF1-0xF6 and
# I/i-acute at 0x5A/0x6F, well outside the 0x01-0x2E accented block, so a German or Spanish name
# needs these too. Verified against the decomp with zero conflicts on the bytes we already had.
# 0xFF is '$' in charmap.txt but is our EOS/pad terminator, so it is deliberately excluded.
_DEC.update({
    0x35: "=", 0x36: ";", 0x51: "\u00bf", 0x52: "\u00a1", 0x5A: "\u00cd", 0x5B: "%", 0x5C: "(",
    0x5D: ")", 0x68: "\u00e2", 0x6F: "\u00ed", 0x85: "<", 0x86: ">", 0xF0: ":",
    0xF1: "\u00c4", 0xF2: "\u00d6", 0xF3: "\u00dc", 0xF4: "\u00e4", 0xF5: "\u00f6", 0xF6: "\u00fc",
})

# Encode table is the inverse (first byte wins for any duplicate glyphs).
_ENC = {}
for _b, _c in _DEC.items():
    _ENC.setdefault(_c, _b)


def decode(b, stop_at_eos=True):
    """GBA name bytes -> str. Stops at the 0xFF terminator by default."""
    out = []
    for x in b:
        if x == EOS:
            if stop_at_eos:
                break
            continue
        out.append(_DEC.get(x, "."))
    return "".join(out)


def encode(s, width=None, pad=PAD):
    """str -> GBA name bytes. If `width` is given, append the 0xFF terminator then `pad` to
    exactly `width` bytes. Mon nickname/OT fields pad with 0xFF (pad=0xFF, the default); the
    struct LinkPlayer `name` field pads with 0x00 after the terminator (pad=0x00), matching
    InitLocalLinkPlayer over a zero-initialised struct. Unknown chars are dropped."""
    out = bytearray()
    for ch in s:
        if ch in _ENC:
            out.append(_ENC[ch])
    if width is not None:
        out = out[:width - 1] if width else out
        out.append(EOS)
        while len(out) < width:
            out.append(pad)
        out = out[:width]
    return bytes(out)
