from frlgsim import mon


def test_the_misc_substruct_reads_back_what_was_written_into_it():
    """`modernFatefulEncounter` is BIT 31 of the ribbon word at Misc+0x08, not a byte of its own
    [decomp:include/pokemon.h:40-82], and `metLocation` is Misc+0x01. Both are in the encrypted,
    shuffled region, so the only way to read them is through the same decode every other field uses.
    Built here rather than asserted against a capture: a synthetic mon can set exactly one bit."""
    for pid in (0, 1, 23, 24, 0xDEADBEEF):
        for fateful in (0, 1):
            plain = bytearray(48)
            order = mon.SUBSTRUCT_ORDER[pid % 24]
            misc_at = order.index("M") * 12
            plain[misc_at + 1] = 0xFF                    # METLOC_FATEFUL_ENCOUNTER
            plain[misc_at + 2:misc_at + 4] = (50 | (2 << 7) | (4 << 11)).to_bytes(2, "little")
            plain[misc_at + 8:misc_at + 12] = (fateful << 31).to_bytes(4, "little")
            growth_at = order.index("G") * 12
            plain[growth_at:growth_at + 2] = (251).to_bytes(2, "little")

            otid = 0x0000E5BB
            key = pid ^ otid
            secure = bytearray(48)
            for i in range(12):
                word = int.from_bytes(plain[i * 4:i * 4 + 4], "little") ^ key
                secure[i * 4:i * 4 + 4] = (word & 0xFFFFFFFF).to_bytes(4, "little")
            checksum = sum(int.from_bytes(plain[i * 2:i * 2 + 2], "little")
                           for i in range(24)) & 0xFFFF

            raw = bytearray(100)
            raw[0:4] = pid.to_bytes(4, "little")
            raw[4:8] = otid.to_bytes(4, "little")
            raw[28:30] = checksum.to_bytes(2, "little")
            raw[32:80] = secure

            decoded = mon.decode_mon(bytes(raw))
            assert decoded["checksum_ok"], (pid, fateful)
            assert decoded["species"] == 251
            assert decoded["metLocation"] == 0xFF
            assert decoded["metLevel"] == 50
            assert decoded["metGame"] == 2
            assert decoded["pokeball"] == 4
            assert decoded["modernFatefulEncounter"] == fateful
