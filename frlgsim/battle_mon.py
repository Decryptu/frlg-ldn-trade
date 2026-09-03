"""struct BattlePokemon [include/pokemon.h:170], the reply to GETMONDATA REQUEST_ALL_BATTLE.

The first command of every link battle is GETMONDATA with REQUEST_ALL_BATTLE, emitted to each
battler in turn [BattleIntroGetMonsData, battle_main.c:2519]. CopyPlayerMonData builds the answer
field by field [battle_controller_player.c:1519]; this rebuilds the same 0x58 bytes from one of our
party mons.

Note what CopyPlayerMonData does NOT write: statStages, ability, type1, type2, unknown and status2
are left as whatever was on the stack, because the receiver recomputes them from the species. We
send zeros there rather than garbage.
"""

import struct

from . import charmap, mon as monmod, stats

SIZE = 0x58
NICK_FIELD = 11             # POKEMON_NAME_LENGTH + 1 [constants/global.h:63]
OT_FIELD = 8                # PLAYER_NAME_LENGTH + 1  [:64]


def _substructs(party100):
    """-> (growth, attacks, evs, misc), the four canonical 12-byte substructs."""
    canon = monmod.to_decrypted(bytes(party100))
    sec = canon[monmod.SECURE_OFF:monmod.SECURE_END]
    return sec[0:12], sec[12:24], sec[24:36], sec[36:48]


def from_mon(m):
    """One BattlePokemon from a frlgsim.mon.Mon, exactly as CopyPlayerMonData would serialise it."""
    raw = m.party_bytes()
    growth, attacks, evs, misc = _substructs(raw)

    species = int.from_bytes(growth[0:2], "little")
    item = int.from_bytes(growth[2:4], "little")
    experience = int.from_bytes(growth[4:8], "little")
    pp_bonuses = growth[8]
    friendship = growth[9]

    moves = [int.from_bytes(attacks[i * 2:i * 2 + 2], "little") for i in range(4)]
    pp = list(attacks[8:12])

    iv_word = int.from_bytes(misc[4:8], "little")

    # The party tail is plaintext in both .pk3 and .ek3 [mon.py]: status, level and the six stats
    # the game already computed. Trust it, and fall back to our own calculator when it is absent.
    status1 = int.from_bytes(raw[80:84], "little")
    level = raw[84]
    hp = int.from_bytes(raw[86:88], "little")
    max_hp = int.from_bytes(raw[88:90], "little")
    attack, defense, speed, sp_attack, sp_defense = (
        int.from_bytes(raw[90 + i * 2:92 + i * 2], "little") for i in range(5))
    if level == 0:
        tail = stats.build_party_tail(monmod.to_decrypted(raw))
        if tail is None:
            raise ValueError(f"species {species} has no base stats; cannot build a BattlePokemon")
        level = tail[4]
        hp = max_hp = int.from_bytes(tail[6:8], "little")
        attack, defense, speed, sp_attack, sp_defense = (
            int.from_bytes(tail[10 + i * 2:12 + i * 2], "little") for i in range(5))

    out = bytearray(SIZE)
    struct.pack_into("<6H", out, 0x00, species, attack, defense, speed, sp_attack, sp_defense)
    struct.pack_into("<4H", out, 0x0C, *moves)
    # hpIV:5 attackIV:5 defenseIV:5 speedIV:5 spAttackIV:5 spDefenseIV:5 isEgg:1 abilityNum:1,
    # which is the misc substruct's ivEggAbility word verbatim.
    struct.pack_into("<I", out, 0x14, iv_word)
    # 0x18 statStages[8], 0x20 ability, 0x21 type1, 0x22 type2, 0x23 unknown: left zero, see above.
    out[0x24:0x28] = bytes(pp)
    struct.pack_into("<H", out, 0x28, hp)
    out[0x2A] = level
    out[0x2B] = friendship
    struct.pack_into("<HH", out, 0x2C, max_hp, item)
    out[0x30:0x30 + NICK_FIELD] = charmap.encode(monmod.gba_str(raw[8:18]), width=NICK_FIELD)
    out[0x3B] = pp_bonuses
    out[0x3C:0x3C + OT_FIELD] = charmap.encode(monmod.gba_str(raw[20:27]), width=OT_FIELD)
    struct.pack_into("<5I", out, 0x44,
                     experience,
                     int.from_bytes(raw[0:4], "little"),    # personality
                     status1,
                     0,                                     # status2, not written by the game
                     int.from_bytes(raw[4:8], "little"))    # otId
    return bytes(out)


def describe(data):
    """One line for the operator's log."""
    if len(data) < SIZE:
        return f"<{len(data)} bytes, not a BattlePokemon>"
    species, attack, defense, speed, sp_attack, sp_defense = struct.unpack_from("<6H", data, 0)
    nick = charmap.decode(data[0x30:0x30 + NICK_FIELD])
    hp, = struct.unpack_from("<H", data, 0x28)
    max_hp, = struct.unpack_from("<H", data, 0x2C)
    moves = struct.unpack_from("<4H", data, 0x0C)
    return (f"{nick or monmod.SPECIES.get(species, f'#{species}')} lv{data[0x2A]} "
            f"{hp}/{max_hp}HP atk{attack} def{defense} spe{speed} spa{sp_attack} spd{sp_defense} "
            f"moves {list(moves)}")
