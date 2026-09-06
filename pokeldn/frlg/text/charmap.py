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


# The text control codes [decomp:include/characters.h:177]. A NAME field never holds one, so they
# are decoded only by `decode_message`: a message string is the one place they appear, and rendering
# them as "." is what made the first script string read off the console come back as 'Obtenu: .A!'.
CHAR_PROMPT_SCROLL = 0xFA       # wait for a press, then scroll
CHAR_PROMPT_CLEAR = 0xFB        # wait for a press, then clear
EXT_CTRL_CODE_BEGIN = 0xFC      # one argument byte follows, sometimes more
PLACEHOLDER_BEGIN = 0xFD        # one id byte follows
CHAR_NEWLINE = 0xFE

# What `StringExpandPlaceholders` substitutes for each id [decomp:include/characters.h:267].
PLACEHOLDERS = {0x0: "UNKNOWN", 0x1: "PLAYER", 0x2: "STR_VAR_1", 0x3: "STR_VAR_2",
                0x4: "STR_VAR_3", 0x5: "KUN", 0x6: "RIVAL", 0x7: "VERSION", 0x8: "MAGMA",
                0x9: "AQUA", 0xA: "MAXIE", 0xB: "ARCHIE", 0xC: "GROUDON", 0xD: "KYOGRE"}

# How many bytes follow EXT_CTRL_CODE_BEGIN's selector [decomp:src/text.c, GetExtCtrlCodeLength].
_EXT_CTRL_ARGS = {0x01: 1, 0x02: 1, 0x03: 1, 0x04: 3, 0x05: 1, 0x06: 1, 0x07: 0, 0x08: 1,
                  0x09: 0, 0x0A: 0, 0x0B: 2, 0x0C: 1, 0x0D: 1, 0x0E: 1, 0x0F: 0, 0x10: 0,
                  0x11: 0, 0x12: 1, 0x13: 1, 0x14: 1, 0x15: 0, 0x16: 0, 0x17: 0, 0x18: 0}


def decode_message(b):
    """-> a message string with its control codes rendered, not swallowed.

    `decode` is for a NAME: fixed width, no control codes, unknown bytes become '.'. A string a
    script points at is dialogue, and its placeholders and line breaks are most of its meaning -
    "{PLAYER} a obtenu\n{STR_VAR_2}!" says what the box will read; "..a obtenu..!" says nothing."""
    out, index = [], 0
    while index < len(b):
        byte = b[index]
        index += 1
        if byte == EOS:
            break
        if byte == PLACEHOLDER_BEGIN and index < len(b):
            out.append("{%s}" % PLACEHOLDERS.get(b[index], f"PLACEHOLDER_{b[index]:02X}"))
            index += 1
        elif byte == EXT_CTRL_CODE_BEGIN and index < len(b):
            selector = b[index]
            index += 1 + _EXT_CTRL_ARGS.get(b[index], 0)
            out.append("{EXT_%02X}" % selector)
        elif byte == CHAR_NEWLINE:
            out.append("\n")
        elif byte == CHAR_PROMPT_SCROLL:
            out.append("{SCROLL}")
        elif byte == CHAR_PROMPT_CLEAR:
            out.append("{CLEAR}")
        else:
            out.append(_DEC.get(byte, "."))
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
