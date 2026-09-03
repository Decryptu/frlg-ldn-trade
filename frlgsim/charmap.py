"""International Gen-3 charmap. Terminator 0xFF; name fields are fixed width and 0xFF-filled after it."""

EOS = 0xFF
PAD = 0xFF

# Decode table, verified against the decomp charmap.txt.
_DEC = {0x00: " ", 0xAD: ".", 0xAE: "-", 0xAF: "·", 0xB0: "…",
        0xB7: "¥", 0xB9: "×", 0xBA: "/", 0xB1: "“", 0xB2: "”",
        0xB3: "‘", 0xB4: "’", 0xB5: "♂", 0xB6: "♀", 0xB8: ",",
        0xAB: "!", 0xAC: "?"}
for _i in range(10):
    _DEC[0xA1 + _i] = "0123456789"[_i]
for _i in range(26):
    _DEC[0xBB + _i] = chr(ord("A") + _i)
    _DEC[0xD5 + _i] = chr(ord("a") + _i)

# Accented Latin range 0x01-0x2E from the international charmap.txt. The Japanese build reuses these bytes for
# kana (0x01 is both A-grave and HIRAGANA A), so the kana are excluded and Japanese is not offered.
_DEC.update({
    0x01: "\u00c0", 0x02: "\u00c1", 0x03: "\u00c2", 0x04: "\u00c7", 0x05: "\u00c8", 0x06: "\u00c9", 0x07: "\u00ca",
    0x08: "\u00cb", 0x09: "\u00cc", 0x0B: "\u00ce", 0x0C: "\u00cf", 0x0D: "\u00d2", 0x0E: "\u00d3", 0x0F: "\u00d4",
    0x10: "\u0152", 0x11: "\u00d9", 0x12: "\u00da", 0x13: "\u00db", 0x14: "\u00d1", 0x15: "\u00df", 0x16: "\u00e0",
    0x17: "\u00e1", 0x19: "\u00e7", 0x1A: "\u00e8", 0x1B: "\u00e9", 0x1C: "\u00ea", 0x1D: "\u00eb", 0x1E: "\u00ec",
    0x20: "\u00ee", 0x21: "\u00ef", 0x22: "\u00f2", 0x23: "\u00f3", 0x24: "\u00f4", 0x25: "\u0153", 0x26: "\u00f9",
    0x27: "\u00fa", 0x28: "\u00fb", 0x29: "\u00f1", 0x2A: "\u00ba", 0x2B: "\u00aa", 0x2D: "&", 0x2E: "+",
})

# Umlauts sit at 0xF1-0xF6 and I/i-acute at 0x5A/0x6F, outside the accented block. 0xFF is '$' in
# charmap.txt but is our terminator, so it is excluded.
_DEC.update({
    0x35: "=", 0x36: ";", 0x51: "\u00bf", 0x52: "\u00a1", 0x5A: "\u00cd", 0x5B: "%", 0x5C: "(",
    0x5D: ")", 0x68: "\u00e2", 0x6F: "\u00ed", 0x85: "<", 0x86: ">", 0xF0: ":",
    0xF1: "\u00c4", 0xF2: "\u00d6", 0xF3: "\u00dc", 0xF4: "\u00e4", 0xF5: "\u00f6", 0xF6: "\u00fc",
})

_ENC = {}
for _b, _c in _DEC.items():
    _ENC.setdefault(_c, _b)


def decode(b, stop_at_eos=True):
    out = []
    for x in b:
        if x == EOS:
            if stop_at_eos:
                break
            continue
        out.append(_DEC.get(x, "."))
    return "".join(out)


def encode(s, width=None, pad=PAD):
    """With `width`: truncate, append 0xFF, pad to `width`. Mon name fields pad with 0xFF; struct LinkPlayer.name
    pads with 0x00 (InitLocalLinkPlayer over a zeroed struct). Unknown chars are dropped."""
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
