"""Party struct Pokemon (100 B) [decomp:include/pokemon.h] = BoxPokemon (80 B) + tail: [80] status u32, [84] level,
[85] mail, [86] hp, [88] maxHP, [90..98] atk/def/spe/spa/spd u16. The wire form is the PKHeX .ek3 layout. The only
validity gate is the 16-bit checksum over the 48-byte secure region; the party tail is not covered."""

from . import stats

# Substructure order by personality % 24; G=Growth A=Attacks E=EVs M=Misc.
SUBSTRUCT_ORDER = [
    "GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA",
    "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
    "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG",
    "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG",
]

_CHARS = {0x00: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xAF: "·", 0xB0: "…",
          0xB1: "“", 0xB2: "”", 0xB3: "‘", 0xB4: "’", 0xB5: "♂", 0xB6: "♀", 0xB7: "¥",
          0xB8: ",", 0xB9: "×", 0xBA: "/", 0xFF: ""}
for _i in range(10):
    _CHARS[0xA1 + _i] = "0123456789"[_i]
for _i in range(26):
    _CHARS[0xBB + _i] = chr(ord("A") + _i)
    _CHARS[0xD5 + _i] = chr(ord("a") + _i)


def gba_str(b):
    out = []
    for x in b:
        if x == 0xFF:
            break
        out.append(_CHARS.get(x, "."))
    return "".join(out)


DECOMP_PATHS = ("~/pokefirered", "~/Git/pokefirered")


def load_species(decomp=None):
    """Internal species index -> name; not the National Dex number: 252-276 are OLD_UNOWN, Hoenn starts at 277.

    The decomp is not vendored, so try where it actually lives before falling back to a stub. With
    only the stub every dumped or traded mon prints as `#N`, which is legible but not readable.
    """
    import os
    import re
    for candidate in ((decomp,) if decomp is not None else DECOMP_PATHS):
        path = os.path.expanduser(os.path.join(candidate, "include/constants/species.h"))
        m = {}
        try:
            for line in open(path):
                g = re.match(r"#define SPECIES_(\w+)\s+(\d+)", line.strip())
                if g:
                    m.setdefault(int(g.group(2)), g.group(1))
        except OSError:
            continue
        if m:
            return m
    return {4: "CHARMANDER", 5: "CHARMELEON", 16: "PIDGEY", 19: "RATTATA"}


SPECIES = load_species()


def decode_mon(mon):
    if len(mon) < 80:
        return None
    pid = int.from_bytes(mon[0:4], "little")
    otid = int.from_bytes(mon[4:8], "little")
    key = pid ^ otid
    sec = bytearray(mon[32:80])
    for i in range(12):
        v = (int.from_bytes(sec[i * 4:i * 4 + 4], "little") ^ key) & 0xFFFFFFFF
        sec[i * 4:i * 4 + 4] = v.to_bytes(4, "little")
    calc = sum(int.from_bytes(sec[i * 2:i * 2 + 2], "little") for i in range(24)) & 0xFFFF
    stored = int.from_bytes(mon[28:30], "little")
    order = SUBSTRUCT_ORDER[pid % 24]
    growth = sec[order.index("G") * 12:][:12]
    attacks = sec[order.index("A") * 12:][:12]
    species = int.from_bytes(growth[0:2], "little")
    return {
        "pid": pid, "otid": otid,
        "nickname": gba_str(mon[8:18]),
        "otName": gba_str(mon[20:27]),
        "language": mon[18],
        "checksum_ok": calc == stored,
        "stored": stored, "calc": calc,
        "species": species, "species_name": SPECIES.get(species, f"#{species}"),
        "heldItem": int.from_bytes(growth[2:4], "little"),
        "exp": int.from_bytes(growth[4:8], "little"),
        "moves": [int.from_bytes(attacks[i * 2:i * 2 + 2], "little") for i in range(4)],
        "level": mon[84] if len(mon) >= 100 else None,
    }

BOX_SIZE = 80
PARTY_MON_SIZE = 100
PARTY_SIZE = 6
PARTY_BLOCK_SIZE = 200          # 2 mons; BLOCK_REQ_200, count=17
SECURE_OFF = 32                 # 48-byte encrypted+shuffled substruct region
SECURE_END = 80


# .ek3 (wire/save) = secure region XOR PID^OTID with the substructs shuffled by PID%24; .pk3 = decrypted,
# canonical G,A,E,M order. Header (incl. checksum) and party tail are plaintext in both.
def _xor_secure(buf, key):
    out = bytearray(buf)
    for i in range(12):
        o = SECURE_OFF + i * 4
        v = (int.from_bytes(out[o:o + 4], "little") ^ key) & 0xFFFFFFFF
        out[o:o + 4] = v.to_bytes(4, "little")
    return out


def to_decrypted(wire):
    pid = int.from_bytes(wire[0:4], "little")
    key = pid ^ int.from_bytes(wire[4:8], "little")
    dec = _xor_secure(wire, key)
    order = SUBSTRUCT_ORDER[pid % 24]
    sec = dec[SECURE_OFF:SECURE_END]
    canon = bytearray(48)
    for ci, letter in enumerate("GAEM"):
        p = order.index(letter)
        canon[ci * 12:ci * 12 + 12] = sec[p * 12:p * 12 + 12]
    dec[SECURE_OFF:SECURE_END] = canon
    return bytes(dec)


def to_encrypted(pk3):
    pid = int.from_bytes(pk3[0:4], "little")
    key = pid ^ int.from_bytes(pk3[4:8], "little")
    order = SUBSTRUCT_ORDER[pid % 24]
    canon = pk3[SECURE_OFF:SECURE_END]
    shuf = bytearray(48)
    for p in range(4):
        ci = "GAEM".index(order[p])
        shuf[p * 12:p * 12 + 12] = canon[ci * 12:ci * 12 + 12]
    out = bytearray(pk3)
    out[SECURE_OFF:SECURE_END] = shuf
    return bytes(_xor_secure(out, key))


def _wire_valid(b):
    d = decode_mon(b)
    return bool(d and d["checksum_ok"])


class Mon:
    def __init__(self, party100):
        if len(party100) != PARTY_MON_SIZE:
            raise ValueError(f"party mon must be {PARTY_MON_SIZE} bytes, got {len(party100)}")
        self.raw = bytes(party100)

    @classmethod
    def from_pk3(cls, data):
        """Accepts .ek3 or .pk3, 80 or 100 bytes; a missing party tail is derived from the box data
        (a zero tail shows as level 0 on the receiver)."""
        data = bytes(data)
        if len(data) not in (BOX_SIZE, PARTY_MON_SIZE):
            raise ValueError(f".pk3/.ek3 must be {BOX_SIZE} or {PARTY_MON_SIZE} bytes, "
                             f"got {len(data)}")
        # When PID == OTID the key is 0 and .pk3/.ek3 both checksum-validate, so an unshuffled mon
        # would ship; treat key == 0 as a decrypted .pk3.
        key = int.from_bytes(data[0:4], "little") ^ int.from_bytes(data[4:8], "little")
        if _wire_valid(data) and key != 0:
            wire = data
        else:
            enc = to_encrypted(data)
            wire = enc if _wire_valid(enc) else data
        if len(wire) == BOX_SIZE:
            # mail must be MAIL_NONE (0xFF): a zero byte is mail slot 0, which the host treats as real mail.
            wire = bytearray(wire) + b"\x00" * (PARTY_MON_SIZE - BOX_SIZE)
            wire[85] = 0xFF
            wire = bytes(wire)
        if _wire_valid(wire) and wire[84] == 0:
            tail = stats.build_party_tail(to_decrypted(wire))
            if tail is not None:
                wire = wire[:BOX_SIZE] + tail
        wire = wire[:85] + b"\xFF" + wire[86:]
        return cls(wire)

    @classmethod
    def from_file(cls, path):
        with open(path, "rb") as f:
            return cls.from_pk3(f.read())

    @classmethod
    def empty(cls):
        return cls(b"\x00" * PARTY_MON_SIZE)

    def party_bytes(self):
        return self.raw

    def box_bytes(self):
        return self.raw[:BOX_SIZE]

    def decode(self):
        return decode_mon(self.raw)

    @property
    def is_empty(self):
        return int.from_bytes(self.raw[0:8], "little") == 0

    @property
    def checksum_ok(self):
        d = self.decode()
        return bool(d and d["checksum_ok"])

    @property
    def species(self):
        d = self.decode()
        return d["species"] if d else None

    @property
    def species_name(self):
        d = self.decode()
        return d["species_name"] if d else "?"

    @property
    def pid(self):
        return int.from_bytes(self.raw[0:4], "little")

    @property
    def otid(self):
        return int.from_bytes(self.raw[4:8], "little")

    @property
    def nickname(self):
        d = self.decode()
        return d["nickname"] if d else ""

    @property
    def ot_name(self):
        d = self.decode()
        return d["otName"] if d else ""

    def describe(self):
        d = self.decode()
        if not d:
            return "<undecodable>"
        ck = "OK" if d["checksum_ok"] else f"BAD({d['calc']:04x}!={d['stored']:04x})"
        return (f"{d['species_name']} (#{d['species']}) nick={d['nickname']!r} "
                f"OT={d['otName']!r} PID={d['pid']:08x} lv={d['level']} checksum={ck}")

    def save_pk3(self, path, size=PARTY_MON_SIZE):
        if size not in (BOX_SIZE, PARTY_MON_SIZE):
            raise ValueError("size must be 80 (box) or 100 (party)")
        with open(path, "wb") as f:
            f.write(to_decrypted(self.raw)[:size])
        return path

    def save_ek3(self, path, size=PARTY_MON_SIZE):
        if size not in (BOX_SIZE, PARTY_MON_SIZE):
            raise ValueError("size must be 80 (box) or 100 (party)")
        with open(path, "wb") as f:
            f.write(self.raw[:size])
        return path


def build_player_party(mons):
    if len(mons) > PARTY_SIZE:
        raise ValueError(f"party holds at most {PARTY_SIZE} mons")
    buf = bytearray(PARTY_MON_SIZE * PARTY_SIZE)
    for i, m in enumerate(mons):
        buf[i * PARTY_MON_SIZE:(i + 1) * PARTY_MON_SIZE] = m.party_bytes()
    return bytes(buf)


def party_blocks(party600):
    return [party600[i:i + PARTY_BLOCK_SIZE] for i in range(0, 600, PARTY_BLOCK_SIZE)]
