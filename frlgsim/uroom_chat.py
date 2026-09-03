"""Union Room chat blocks [src/union_room_chat.c].

Chat rides the ordinary SendBlock path: one 0x28-byte block per event, unsolicited (no BLOCK_REQ
first). Every member sends JOIN on entry [ChatEntryRoutine_Join], a CHAT block per line typed, and
one of LEAVE / DISBAND / DROP on the way out. The leader (multiplayer id 0, the parent) disbands;
a child leaves.

Layout, from PrepareSendBuffer_* and ProcessReceivedChatMessage:

    [0]      command
    [1..8]   player name, PLAYER_NAME_LENGTH + 1 bytes, EOS-terminated
    [9]      multiplayer id            (JOIN / LEAVE / DROP / DISBAND)
    [9..39]  message text, EOS-terminated (CHAT)
"""

from . import charmap

BLOCK_SIZE = 0x28
NAME_FIELD = 8              # PLAYER_NAME_LENGTH + 1 [include/constants/global.h:64]
PAYLOAD_OFF = 1 + NAME_FIELD
# messageEntryBuffer is 2 * MESSAGE_BUFFER_NCHAR + 1: the keyboard's 15 entries are up to two bytes
# each, so a full line plus its terminator is exactly the 31 bytes left in the block.
TEXT_FIELD = BLOCK_SIZE - PAYLOAD_OFF

NULL = 0
CHAT = 1
JOIN = 2
LEAVE = 3
DROP = 4
DISBAND = 5

NAMES = {NULL: "NULL", CHAT: "CHAT", JOIN: "JOIN", LEAVE: "LEAVE", DROP: "DROP", DISBAND: "DISBAND"}


def check_text(text):
    """Raise unless `text` survives the Gen-3 charmap and the 30-character message field, so a bad
    --chat-message fails at start-up instead of arriving on the console as dots."""
    if not text:
        raise ValueError("a chat message must not be empty")
    if len(text) > TEXT_FIELD - 1:
        raise ValueError(f"chat message {text!r} is longer than {TEXT_FIELD - 1} characters")
    if charmap.decode(charmap.encode(text, width=TEXT_FIELD)) != text:
        raise ValueError(f"chat message {text!r} has characters outside the Gen-3 charmap")
    return text


def build(cmd, name, *, multiplayer_id=0, text=""):
    """One 0x28-byte chat block. StringCopy leaves the tail of the console's buffer untouched; we
    pad with EOS, which every reader stops at."""
    if cmd not in NAMES:
        raise ValueError(f"unknown chat command {cmd!r}")
    if cmd == CHAT:
        check_text(text)
    out = bytearray([charmap.EOS]) * BLOCK_SIZE
    out[0] = cmd
    out[1:1 + NAME_FIELD] = charmap.encode(name, width=NAME_FIELD)
    if cmd == CHAT:
        out[PAYLOAD_OFF:PAYLOAD_OFF + TEXT_FIELD] = charmap.encode(text, width=TEXT_FIELD)
    else:
        out[PAYLOAD_OFF] = multiplayer_id & 0xFF
    return bytes(out)


def parse(data):
    """-> {cmd, name, multiplayer_id, text}. `text` is empty unless the command is CHAT, and
    `multiplayer_id` is meaningless for CHAT (the byte is the first character of the message)."""
    if len(data) < BLOCK_SIZE:
        raise ValueError(f"chat block is {len(data)} bytes, expected {BLOCK_SIZE}")
    cmd = data[0]
    return {
        "cmd": cmd,
        "name": charmap.decode(data[1:1 + NAME_FIELD]),
        "multiplayer_id": data[PAYLOAD_OFF] if cmd != CHAT else None,
        "text": charmap.decode(data[PAYLOAD_OFF:BLOCK_SIZE]) if cmd == CHAT else "",
    }


def describe(msg):
    """One line for the operator's log."""
    kind = NAMES.get(msg["cmd"], f"0x{msg['cmd']:02x}")
    if msg["cmd"] == CHAT:
        return f"{msg['name']}: {msg['text']}"
    return f"[{kind}] {msg['name']}"
