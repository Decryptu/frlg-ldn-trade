"""LinkPlayerBlock: the 60-byte player record exchanged at entry [link.c:343,557-563]. The host strcmp-validates
BOTH GameFreak magics [link.c:1626-1631] and drops to CB2_LinkError on mismatch; on the wireless path it is
pulled as a fixed 200-byte buffer (count=17) with the block at offset 0."""

from dataclasses import dataclass

from . import charmap, easychat

GAMEFREAK_MAGIC = b"GameFreak inc.\x00\x00"      # 16 bytes: "GameFreak inc." + null + 0 pad
assert len(GAMEFREAK_MAGIC) == 16

VERSION_FIRE_RED = 0x4004                        # gGameVersion(4) + 0x4000
VERSION_LEAF_GREEN = 0x4005                      # gGameVersion(5) + 0x4000
LANGUAGE_ENGLISH = 2                             # include/constants/global.h:21-27
LANGUAGE_FRENCH = 3
LANGUAGE_ITALIAN = 4
LANGUAGE_GERMAN = 5
LANGUAGE_SPANISH = 7                             # 6 is unused (theorised Korean), so it is skipped
LP_FIELD2 = 0x8000                               # gLocalLinkPlayer.lp_field_2
HOST_NAME_PAD = 0xFF                             # robust host-role fixed-field terminators

LINK_PLAYER_SIZE = 28
LINK_PLAYER_BLOCK_SIZE = 60
PARTY_SIZE = 6                                   # struct TrainerCard.monSpecies[PARTY_SIZE]


@dataclass
class LinkPlayer:
    """struct LinkPlayer [include/link.h:158-171]; only the magics and a valid version matter to the host."""
    name: str = "EMU"
    trainer_id: int = 0x47ED8822             # full 32-bit OT id (capture EMU value)
    version: int = VERSION_LEAF_GREEN
    field2: int = LP_FIELD2
    progress_flags: int = 0
    never_read: int = 0
    progress_flags_copy: int = 0
    gender: int = 0
    link_type: int = 0
    player_id: int = 0
    language: int = LANGUAGE_ENGLISH

    def pack(self, *, name_pad=0x00):
        """name_pad fills the bytes after the 0xFF terminator: native storage leaves 0x00; a host crossing the
        RFU bridge may use 0xFF so every byte is a valid Gen III end-of-string marker."""
        return (self.version.to_bytes(2, "little")
                + self.field2.to_bytes(2, "little")
                + (self.trainer_id & 0xFFFFFFFF).to_bytes(4, "little")
                + charmap.encode(self.name, width=8, pad=name_pad)
                + bytes([self.progress_flags & 0xFF, self.never_read & 0xFF,
                         self.progress_flags_copy & 0xFF, self.gender & 0xFF])
                + (self.link_type & 0xFFFFFFFF).to_bytes(4, "little")
                + (self.player_id & 0xFFFF).to_bytes(2, "little")
                + (self.language & 0xFFFF).to_bytes(2, "little"))

    @classmethod
    def unpack(cls, b):
        return cls(
            version=int.from_bytes(b[0:2], "little"),
            field2=int.from_bytes(b[2:4], "little"),
            trainer_id=int.from_bytes(b[4:8], "little"),
            name=charmap.decode(b[8:16]),
            progress_flags=b[16], never_read=b[17], progress_flags_copy=b[18], gender=b[19],
            link_type=int.from_bytes(b[20:24], "little"),
            player_id=int.from_bytes(b[24:26], "little"),
            language=int.from_bytes(b[26:28], "little"),
        )


def build_block(link_player, *, name_pad=0x00):
    blk = GAMEFREAK_MAGIC + link_player.pack(name_pad=name_pad) + GAMEFREAK_MAGIC
    assert len(blk) == LINK_PLAYER_BLOCK_SIZE
    return blk


# struct TrainerCard [include/trainer_card.h:6-48] is 96 bytes; CreateTrainerCardInBuffer [union_room.c:1863-1870]
# appends a wonder-card u16 at offset 96, so the BLOCK_REQ_SIZE_100 buffer is card + u16 + 2 bytes residue.
# Cosmetic to the trade, but the host pulls it before the menu exists, so it must be structurally valid.
TRAINER_CARD_SIZE = 0x60                 # sizeof(struct TrainerCard) = 96
TRAINER_CARD_BLOCK_SIZE = 100            # BLOCK_REQ_SIZE_100 buffer [link.c:187]
TC_OFF_GENDER = 0x00
TC_OFF_STARS = 0x01
TC_OFF_HAS_POKEDEX = 0x02                # TrainerCardRSE.hasPokedex (bool8)
TC_OFF_TRAINER_ID = 0x0E                 # TrainerCardRSE.trainerId (u16)
TC_OFF_PLAYER_NAME = 0x30                # TrainerCardRSE.playerName[PLAYER_NAME_LENGTH+1]
TC_OFF_EASY_CHAT = 0x28                  # TrainerCardRSE.easyChatProfile (u16[4])
TC_OFF_VERSION = 0x38                    # TrainerCard.version (u8)
TC_OFF_MON_SPECIES = 0x54               # TrainerCard.monSpecies[PARTY_SIZE] (u16[6])
TC_OFF_WONDER_CARD = TRAINER_CARD_SIZE   # u16 written by CreateTrainerCardInBuffer @ offset 96


def build_trainer_card(link_player, wonder_card_id=0, mon_species=None, *, name_pad=0x00,
                       quote=None):
    """Reuses the LinkPlayer OT/trainerId/version so CopyTrainerCardData sees them aligned with the LinkPlayerBlock."""
    card = bytearray(TRAINER_CARD_BLOCK_SIZE)
    card[TC_OFF_GENDER] = link_player.gender & 0xFF
    # A LinkPlayer claiming the National Dex (progressFlags & 0x0F) owns a Pokedex [trainer_card.c:
    # hasPokedex = FLAG_SYS_POKEDEX_GET]; the partner displays this card after the exchange.
    card[TC_OFF_HAS_POKEDEX] = 1 if link_player.progress_flags & 0x0F else 0
    # the card's trainerId is the low 16 bits of the OT id
    card[TC_OFF_TRAINER_ID:TC_OFF_TRAINER_ID + 2] = \
        (link_player.trainer_id & 0xFFFF).to_bytes(2, "little")
    card[TC_OFF_PLAYER_NAME:TC_OFF_PLAYER_NAME + 8] = \
        charmap.encode(link_player.name, width=8, pad=name_pad)
    # The profile quote. All zeros is word 0, which CopyEasyChatWord rejects and prints as "???"
    # -- that is what the console showed for our card in u08-u11 [easychat.py].
    for i, w in enumerate(easychat.resolve_quote(quote)):
        o = TC_OFF_EASY_CHAT + i * 2
        card[o:o + 2] = (w & 0xFFFF).to_bytes(2, "little")
    # TrainerCard.version is the raw gGameVersion byte, not the 0x4000-tagged LinkPlayer.version
    card[TC_OFF_VERSION] = link_player.version & 0xFF
    if mon_species:
        for i, sp in enumerate(mon_species[:PARTY_SIZE]):
            o = TC_OFF_MON_SPECIES + i * 2
            card[o:o + 2] = (sp & 0xFFFF).to_bytes(2, "little")
    card[TC_OFF_WONDER_CARD:TC_OFF_WONDER_CARD + 2] = (wonder_card_id & 0xFFFF).to_bytes(2, "little")
    return bytes(card)


def parse_block(b):
    """60+ bytes -> (LinkPlayer, magics_ok)."""
    magic1 = b[0:16]
    struct = b[16:44]
    magic2 = b[44:60]
    ok = (magic1[:14] == b"GameFreak inc." and magic2[:14] == b"GameFreak inc.")
    return LinkPlayer.unpack(struct), ok
