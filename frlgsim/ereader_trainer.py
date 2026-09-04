"""The visiting trainer: a BattleTowerEReaderTrainer pushed into the console's save over Mystery Gift.

`CLI_RECV_EREADER_TRAINER` memcpys 188 bytes straight into `gSaveBlock2Ptr->battleTower.ereaderTrainer`
and calls ValidateEReaderTrainer [decomp:src/mystery_gift_client.c:233]. Validation is only that the
struct is non-zero and that its trailing u32 is the sum of the 46 words before it
[SetEReaderTrainerChecksum, battle_tower.c:1384]; nothing else about the trainer or its party is
checked. The old woman in SevenIsland_House_Room1 then offers a 3v3 against it, and
StartSpecialBattle case 2 builds the party with CreateBattleTowerMon exactly as given -- no level
scaling and no Battle Tower banlist, both of which live on the (unreachable) tower path
[battle_tower.c:928, :232].

FRLG prints only the first FIVE characters of the name in battle and in the old woman's line
[CopyEReaderTrainerName5, battle_tower.c:1343]; the field is seven wide, so a longer name is stored
whole and displayed cut.
"""

from dataclasses import dataclass

from . import charmap, easychat

TRAINER_SIZE = 0xBC             # sizeof(struct BattleTowerEReaderTrainer) [decomp:include/global.h:286]
MON_SIZE = 0x2C                 # sizeof(struct BattleTowerPokemon) [decomp:include/pokemon.h:143]
PARTY_SIZE = 3
NAME_FIELD_SIZE = 8             # name[8]; only name[0..4] is ever displayed
NAME_DISPLAY_LENGTH = 5
NICKNAME_FIELD_SIZE = 11        # POKEMON_NAME_LENGTH + 1
MAX_MON_MOVES = 4
NUM_NATURES = 25

# gFacilityClassToPicIndex / gFacilityClassToTrainerClass pick the sprite and the class name
# [battle_tower.c:491, :505]. The Kanto block of FACILITY_CLASS_* [include/constants/trainers.h:379].
FACILITY_CLASSES = {
    "youngster": 88, "bug_catcher": 89, "lass": 90, "sailor": 91, "camper": 92,
    "picnicker": 93, "pokemaniac": 94, "super_nerd": 95, "hiker": 96, "biker": 97,
    "burglar": 98, "engineer": 99, "fisherman": 100, "swimmer_m": 101, "cue_ball": 102,
    "gamer": 103, "beauty": 104, "swimmer_f": 105, "psychic_m": 106, "rocker": 107,
    "juggler": 108, "tamer": 109, "bird_keeper": 110, "black_belt": 111, "rival_early": 112,
    "scientist": 113, "boss": 114, "rocket_grunt_m": 115, "cooltrainer_m": 116,
    "cooltrainer_f": 117, "elite_four_lorelei": 118, "elite_four_bruno": 119, "leader_m": 120,
    "leader_f": 121, "gentleman": 122, "rival_late": 123, "champion_rival": 124,
    "channeler": 125, "twins": 126, "cool_couple": 127, "young_couple": 128, "crush_kin": 129,
    "sis_and_bro": 130, "pkmn_prof": 131, "brendan": 132, "may": 133, "red": 134, "leaf": 135,
    "rocket_grunt_f": 136, "psychic_f": 137, "crush_girl": 138, "tuber": 139,
    "pkmn_breeder": 140, "pkmn_ranger_m": 141, "pkmn_ranger_f": 142, "aroma_lady": 143,
    "ruin_maniac": 144, "lady": 145, "painter": 146, "elite_four_agatha": 147,
    "elite_four_lance": 148, "champion_rival_2": 149,
}

NATURES = (
    "hardy", "lonely", "brave", "adamant", "naughty", "bold", "docile", "relaxed", "impish",
    "lax", "timid", "hasty", "serious", "jolly", "naive", "modest", "mild", "quiet", "bashful",
    "rash", "calm", "gentle", "sassy", "careful", "quirky",
)


class EReaderTrainerError(ValueError):
    """The visiting trainer cannot be encoded as the console would read it."""


def _u16(value):
    return int(value).to_bytes(2, "little")


def _u32(value):
    return (int(value) & 0xFFFFFFFF).to_bytes(4, "little")


def _check_range(value, low, high, what):
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise EReaderTrainerError(f"{what} must be an integer in [{low}, {high}], got {value!r}")
    return value


def is_shiny(personality, ot_id):
    """The Gen III shininess test, so a preset can say whether it will sparkle."""
    value = (ot_id & 0xFFFF) ^ (ot_id >> 16) ^ (personality & 0xFFFF) ^ (personality >> 16)
    return value < 8


def personality_for(nature, *, ot_id=0, shiny=False, gender_byte=None):
    """-> the lowest personality with this nature (and, if asked, shiny against `ot_id`).

    Nature is `personality % 25` and the low byte drives gender, so `gender_byte` pins that byte
    when a species has a gender ratio worth choosing."""
    if isinstance(nature, str):
        key = nature.strip().lower()
        if key not in NATURES:
            raise EReaderTrainerError(f"unknown nature {nature!r}")
        nature = NATURES.index(key)
    _check_range(nature, 0, NUM_NATURES - 1, "nature")
    if gender_byte is not None:
        _check_range(gender_byte, 0, 0xFF, "gender_byte")
    for index in range(1 << 24):
        value = index if gender_byte is None else ((index << 8) | gender_byte)
        if value > 0xFFFFFFFF:
            break
        if value % NUM_NATURES != nature:
            continue
        if shiny and not is_shiny(value, ot_id):
            continue
        return value
    raise EReaderTrainerError("no personality satisfies that combination")


@dataclass(frozen=True)
class TrainerMon:
    """One of the visiting trainer's three Pokemon [struct BattleTowerPokemon]."""
    species: int
    nickname: str
    level: int = 50
    moves: tuple = ()
    held_item: int = 0
    ivs: object = 31                # int for all six, or a 6-tuple hp/atk/def/spe/spa/spd
    evs: object = 0                 # int for all six, or a 6-tuple in the same order
    ability_num: int = 0
    friendship: int = 255
    pp_bonuses: int = 0
    personality: int = 0
    ot_id: int = 0

    def _six(self, value, low, high, what):
        values = (value,) * 6 if isinstance(value, int) and not isinstance(value, bool) else tuple(value)
        if len(values) != 6:
            raise EReaderTrainerError(f"{what} must be one value or six, got {len(values)}")
        return tuple(_check_range(v, low, high, what) for v in values)

    def pack(self):
        _check_range(self.species, 1, 0xFFFF, "species")
        _check_range(self.level, 1, 100, "level")
        _check_range(self.held_item, 0, 0xFFFF, "held item")
        _check_range(self.ability_num, 0, 1, "abilityNum")
        _check_range(self.friendship, 0, 0xFF, "friendship")
        _check_range(self.pp_bonuses, 0, 0xFF, "ppBonuses")
        moves = tuple(self.moves)
        if not moves:
            raise EReaderTrainerError(f"{self.nickname!r} needs at least one move")
        if len(moves) > MAX_MON_MOVES:
            raise EReaderTrainerError(f"a Pokemon holds at most {MAX_MON_MOVES} moves")
        for move in moves:
            _check_range(move, 1, 0xFFFF, "move")
        ivs = self._six(self.ivs, 0, 31, "IV")
        evs = self._six(self.evs, 0, 255, "EV")
        out = bytearray(MON_SIZE)
        out[0x00:0x02] = _u16(self.species)
        out[0x02:0x04] = _u16(self.held_item)
        for slot in range(MAX_MON_MOVES):
            move = moves[slot] if slot < len(moves) else 0
            out[0x04 + slot * 2:0x06 + slot * 2] = _u16(move)
        out[0x0C] = self.level
        out[0x0D] = self.pp_bonuses
        out[0x0E:0x14] = bytes(evs)
        out[0x14:0x18] = _u32(self.ot_id)
        packed = 0
        for shift, value in enumerate(ivs):
            packed |= value << (5 * shift)
        packed |= (self.ability_num & 1) << 31
        out[0x18:0x1C] = _u32(packed)
        out[0x1C:0x20] = _u32(self.personality)
        out[0x20:0x2B] = charmap.encode(self.nickname, width=NICKNAME_FIELD_SIZE)
        out[0x2B] = self.friendship
        return bytes(out)


@dataclass(frozen=True)
class VisitingTrainer:
    """struct BattleTowerEReaderTrainer. `greeting`/`farewell_*` are Easy Chat phrases: a
    comma-separated string or a sequence of at most six `easychat_words.WORDS` keys."""
    name: str
    trainer_class: object
    party: tuple
    greeting: object = ()
    farewell_player_won: object = ()
    farewell_player_lost: object = ()
    trainer_id: int = 0
    win_streak: int = 0
    unk0: int = 0

    @property
    def class_id(self):
        value = self.trainer_class
        if isinstance(value, str):
            key = value.strip().lower().replace(" ", "_").replace("-", "_")
            if key not in FACILITY_CLASSES:
                raise EReaderTrainerError(f"unknown trainer class {value!r}")
            return FACILITY_CLASSES[key]
        return _check_range(value, 0, 149, "trainer class")

    @property
    def display_name(self):
        return self.name[:NAME_DISPLAY_LENGTH]

    def pack(self):
        if len(self.party) != PARTY_SIZE:
            raise EReaderTrainerError(
                f"the visiting trainer battles with exactly {PARTY_SIZE} Pokemon, "
                f"got {len(self.party)}")
        if not self.name:
            raise EReaderTrainerError("the visiting trainer needs a name")
        if len(self.name) > NAME_FIELD_SIZE - 1:
            raise EReaderTrainerError(
                f"a trainer name holds at most {NAME_FIELD_SIZE - 1} characters")
        _check_range(self.trainer_id, 0, 0xFFFFFFFF, "trainer id")
        _check_range(self.win_streak, 0, 0xFFFF, "win streak")
        _check_range(self.unk0, 0, 0xFF, "unk0")

        out = bytearray(TRAINER_SIZE)
        out[0x00] = self.unk0
        out[0x01] = self.class_id
        out[0x02:0x04] = _u16(self.win_streak)
        out[0x04:0x0C] = charmap.encode(self.name, width=NAME_FIELD_SIZE)
        out[0x0C:0x10] = _u32(self.trainer_id)
        for offset, phrase in ((0x10, self.greeting),
                               (0x1C, self.farewell_player_lost),
                               (0x28, self.farewell_player_won)):
            for slot, value in enumerate(easychat.resolve_line(phrase)):
                out[offset + slot * 2:offset + slot * 2 + 2] = _u16(value)
        for index, mon in enumerate(self.party):
            start = 0x34 + index * MON_SIZE
            out[start:start + MON_SIZE] = mon.pack()
        out[0xB8:0xBC] = _u32(checksum(out))
        return bytes(out)

    def describe(self):
        party = ", ".join(f"{mon.nickname} (species {mon.species}) Lv{mon.level}"
                          for mon in self.party)
        return (f"{self.display_name!r} (class {self.class_id}, TID {self.trainer_id & 0xFFFF}): "
                f"{party}")


def checksum(packed):
    """The console's own sum over every u32 but the last [battle_tower.c:1384]."""
    total = 0
    for offset in range(0, TRAINER_SIZE - 4, 4):
        total += int.from_bytes(packed[offset:offset + 4], "little")
    return total & 0xFFFFFFFF


def validate(packed):
    """Port of ValidateEReaderTrainer [decomp:src/battle_tower.c:1354]: -> True when the console
    would keep it. A struct that fails is silently cleared and the old woman says nothing."""
    if len(packed) != TRAINER_SIZE:
        raise EReaderTrainerError(
            f"a visiting trainer is {TRAINER_SIZE} bytes, got {len(packed)}")
    nonzero = 0
    for offset in range(0, TRAINER_SIZE - 4, 4):
        nonzero |= int.from_bytes(packed[offset:offset + 4], "little")
    if nonzero == 0:
        return False
    return int.from_bytes(packed[0xB8:0xBC], "little") == checksum(packed)


# Species, move and item ids as the ROM numbers them [decomp:include/constants/{species,moves,items}.h].
SPECIES_CHARIZARD = 6
SPECIES_BLASTOISE = 9
SPECIES_PIKACHU = 25
MOVE_BITE = 44
MOVE_FLAMETHROWER = 53
MOVE_SURF = 57
MOVE_ICE_BEAM = 58
MOVE_THUNDERBOLT = 85
MOVE_THUNDER_WAVE = 86
MOVE_EARTHQUAKE = 89
MOVE_QUICK_ATTACK = 98
MOVE_IRON_TAIL = 231
MOVE_AERIAL_ACE = 332
MOVE_DRAGON_CLAW = 337
ITEM_LEFTOVERS = 200
ITEM_LIGHT_BALL = 202
ITEM_CHARCOAL = 215

_RED_OT_ID = 0x00010F2B


def _red():
    """The visiting trainer we send first: Red, silent, with the Kanto starters' finals.

    Level 70 across the board and 252/252 spreads -- the console applies neither the Battle Tower
    level rule nor its banlist on this path, so these are exactly the mons it will build."""
    return VisitingTrainer(
        name="RED",
        trainer_class="red",
        trainer_id=_RED_OT_ID,
        greeting=("ellipsis_ellipsis_ellipsis", "ellipsis_ellipsis_ellipsis", "excl"),
        farewell_player_won=("you_re", "too_strong", "ellipsis_ellipsis_ellipsis"),
        farewell_player_lost=("ellipsis_ellipsis_ellipsis", "well_then", "see_ya"),
        party=(
            TrainerMon(
                species=SPECIES_PIKACHU, nickname="PIKACHU", level=70,
                held_item=ITEM_LIGHT_BALL,
                moves=(MOVE_THUNDERBOLT, MOVE_IRON_TAIL, MOVE_QUICK_ATTACK, MOVE_THUNDER_WAVE),
                evs=(6, 0, 0, 252, 252, 0),
                personality=personality_for("timid", ot_id=_RED_OT_ID),
                ot_id=_RED_OT_ID),
            TrainerMon(
                species=SPECIES_CHARIZARD, nickname="CHARIZARD", level=70,
                held_item=ITEM_CHARCOAL,
                moves=(MOVE_FLAMETHROWER, MOVE_DRAGON_CLAW, MOVE_AERIAL_ACE, MOVE_EARTHQUAKE),
                evs=(6, 252, 0, 252, 0, 0),
                personality=personality_for("adamant", ot_id=_RED_OT_ID),
                ot_id=_RED_OT_ID),
            TrainerMon(
                species=SPECIES_BLASTOISE, nickname="BLASTOISE", level=70,
                held_item=ITEM_LEFTOVERS,
                moves=(MOVE_SURF, MOVE_ICE_BEAM, MOVE_EARTHQUAKE, MOVE_BITE),
                evs=(252, 0, 0, 6, 252, 0),
                personality=personality_for("modest", ot_id=_RED_OT_ID),
                ot_id=_RED_OT_ID),
        ),
    )


PRESETS = {"red": _red}


def build(name="red"):
    """-> the packed 188 bytes for one named preset."""
    if name not in PRESETS:
        raise EReaderTrainerError(
            f"unknown visiting trainer {name!r}; choose from {', '.join(sorted(PRESETS))}")
    return PRESETS[name]().pack()
