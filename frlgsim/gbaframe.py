"""Emulator 0x57 frames: `57 <type:1> <len:u16 LE> <body>`; types C=0x43 A=0x41 T=0x54 K=0x4b D=0x44 G=0x47. The session
metadata (leading byte 0x4a) is a Reliable INIT payload (reliable.METADATA_FRAME), not a 0x57 'J' frame.
CHILD 'T' body = <ts:u32 LE><00><slot_len:u8 @body[5]><00 00><slot, pad mult-4>; HOST 'T' body = <ts:u32 LE>
<slot_len:u8 @body[4]><00 00 00><slot> (slot_len<=1 = host idle keepalive, still K-acked). `ts` is a per-NEW-frame
counter, reused on a Pia retransmit. 'K' = `57 4b 0c 00 <k_seq:u32><mid:u32><acked_host_ts:u32>` (all LE).
"""

GBA_MARKER = 0x57
TYPE_T = 0x54
TYPE_K = 0x4B
SLOT_LEN = 14


TYPE_J, TYPE_C, TYPE_A = 0x4A, 0x43, 0x41
TYPE_D = 0x44
TYPE_G = 0x47


def build_gba_frame(ftype, data):
    return bytes([GBA_MARKER, ftype]) + len(data).to_bytes(2, "little") + bytes(data)


def build_connect(connect_id):
    """`connect_id` is our self-chosen 2-byte RFU id; any nonzero value works and the host echoes it in its 'A' and 'D'."""
    return build_gba_frame(TYPE_C, connect_id)


def _roundup4(n):
    return (n + 3) & ~3


def wrap_t(slot, ts):
    """57 54 <body_len:u16 LE> | <ts:u32 LE> 00 <slot_len:u8> 00 00 | <slot, zero-padded to mult-4>; `slot` includes its LLSF."""
    slot = bytes(slot)
    padded = slot + b"\x00" * (_roundup4(len(slot)) - len(slot))
    body = (ts & 0xFFFFFFFF).to_bytes(4, "little") + bytes([0, len(slot) & 0xFF, 0, 0]) + padded
    return bytes([GBA_MARKER, TYPE_T]) + len(body).to_bytes(2, "little") + body


def wrap_t_parent(slot, ts):
    """Parent layout puts slot_len at body[4]: 57 54 <body_len:u16 LE> | <ts:u32 LE> <slot_len:u8> 00 00 00 | <slot, pad mult-4>."""
    slot = bytes(slot)
    padded = slot + b"\x00" * (_roundup4(len(slot)) - len(slot))
    body = (ts & 0xFFFFFFFF).to_bytes(4, "little") + bytes([len(slot) & 0xFF, 0, 0, 0]) + padded
    return bytes([GBA_MARKER, TYPE_T]) + len(body).to_bytes(2, "little") + body


def build_link_state(value):
    """57 47 04 00 <value:u32 LE>; a real parent sends 0 shortly after its 'A' and 1 once it has the child's NI.
    Emulator-to-emulator only (the ROM never sees it); our joiner ignores it.
    """
    return build_gba_frame(TYPE_G, (int(value) & 0xFFFFFFFF).to_bytes(4, "little"))


def build_accept(host_session_id, connect_id):
    """Body = <host_session_id:2><echoed connect_id:2><00 00>."""
    hsid = bytes(host_session_id)[:2].ljust(2, b"\x00")
    cid = bytes(connect_id)[:2].ljust(2, b"\x00")
    return build_gba_frame(TYPE_A, hsid + cid + b"\x00\x00")


def build_disconnect(connect_id):
    """57 44 02 00 <connect_id>."""
    return build_gba_frame(TYPE_D, bytes(connect_id)[:2].ljust(2, b"\x00"))


def build_k(k_seq, mid, acked_ts):
    """`k_seq` is the CUMULATIVE COUNT of host 'T' frames received, not a per-K counter: skipping a K is safe, under-reporting
    k_seq stalls the parent's DRAC ack. mid = 1-based position in the OUT datagram; acked_ts = the host 'T' ts verbatim.
    """
    body = ((k_seq & 0xFFFFFFFF).to_bytes(4, "little")
            + (mid & 0xFFFFFFFF).to_bytes(4, "little")
            + (acked_ts & 0xFFFFFFFF).to_bytes(4, "little"))
    return bytes([GBA_MARKER, TYPE_K]) + len(body).to_bytes(2, "little") + body


def parse_in(payload):
    """'T' -> {ts, slot_len, llsf_state, slots:[(mpId, 14-byte gRecvCmd)...], positional (alias of slots), payload, ni?};
    'A' -> {host_session_id, connect_id}; 'K' -> {k_seq, acked_ts}; else {type}. slot_len<=1 is a host idle keepalive.
    """
    if len(payload) < 4 or payload[0] != GBA_MARKER:
        return None
    typ = payload[1]
    ln = int.from_bytes(payload[2:4], "little")
    body = payload[4:4 + ln]
    if typ == TYPE_T:
        if len(body) < 5:
            return {"type": "T", "ts": None, "slot_len": 0, "slots": [], "positional": []}
        ts = int.from_bytes(body[0:4], "little")
        slot_len = body[4]
        rec = {"type": "T", "ts": ts, "slot_len": slot_len, "llsf_state": None,
               "slots": [], "positional": [], "payload": b""}
        if slot_len <= 1:
            return rec
        slot = body[8:8 + slot_len]
        llsf = int.from_bytes(slot[0:3], "little")
        rec["llsf_state"] = (llsf >> 14) & 0xF
        rec["payload"] = slot[3:]
        if rec["llsf_state"] == 4:
            for mpid, off in enumerate(range(0, len(rec["payload"]) - 13, SLOT_LEN)):
                rec["slots"].append((mpid, bytes(rec["payload"][off:off + SLOT_LEN])))
        else:
            rec["ni"] = {
                "state": rec["llsf_state"],
                "ack": (llsf >> 13) & 1,
                "n": (llsf >> 11) & 3,
                "phase": (llsf >> 9) & 3,
                "size": llsf & 0x7F,
                "payload": bytes(rec["payload"]),
            }
        rec["positional"] = rec["slots"]
        return rec
    if typ == TYPE_A:
        return {"type": "A", "host_session_id": body[0:2], "connect_id": body[2:4]}
    if typ == TYPE_K:
        return {"type": "K", "k_seq": int.from_bytes(body[0:4], "little"),
                "acked_ts": int.from_bytes(body[8:12], "little") if len(body) >= 12 else None}
    return {"type": typ}


def parse_out(payload):
    """Inverse of wrap_t -> {ts, slot_len, slot, llsf, cmd}; cmd = the 14-byte gSendCmd for a UNI slot, else None."""
    from . import rfu as _rfu
    if len(payload) < 4 or payload[0] != GBA_MARKER or payload[1] != TYPE_T:
        return None
    ln = int.from_bytes(payload[2:4], "little")
    body = payload[4:4 + ln]
    if len(body) < 8:
        return None
    ts = int.from_bytes(body[0:4], "little")
    slot_len = body[5]
    slot = bytes(body[8:8 + slot_len])
    rec = {"type": "T", "ts": ts, "slot_len": slot_len, "slot": slot,
           "llsf": None, "cmd": None}
    if slot_len >= 2:
        rec["llsf"] = _rfu.parse_llsf_child(slot)
        if rec["llsf"]["state"] == _rfu.LCOM_UNI:
            rec["cmd"] = slot[2:2 + SLOT_LEN]
    return rec
