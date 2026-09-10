"""SEAD's random number generator - the middleware Nintendo seeds key material from.

Game-independent: SEAD is Nintendo's own standard library, and the same generator turns up under
Pia and under ENL. This project needs it because Pia's LDN session key is AES over sixteen bytes of
its output (`pia5.ldn_session_key`).

TWO INDEPENDENT READINGS AGREE, which is why the generator is not a suspect when a derivation
fails. It is read instruction by instruction off BDSP's own ARM64: the init at
main.bin 0x15691c8 and the draw at 0x1569250, checked against the
NintendoClients wiki's "SEAD RNG" page. Identical, down to the state rotation and the order the
draws are packed in.

`create_key` is ENL's key generator (the wiki's "ENL Key Generation"). ENL is NOT Pia and no Pokemon
title uses it, but the routine is here because it is what says a sixteen-byte "seed" is not
necessarily a key: ENL runs the generator over a game-supplied table to MAKE one, and SEAD takes a
four-integer state as readily as an integer seed.
"""

import struct

M32 = 0xFFFFFFFF
INIT_MULTIPLIER = 0x6C078965          # MT19937's, used here only to fill four words


class Sead:
    """SEAD's xorshift128. Construct from an integer `seed` or a four-word `state`."""

    __slots__ = ("state",)

    def __init__(self, seed=None, state=None):
        if (seed is None) == (state is None):
            raise ValueError("give exactly one of seed= or state=")
        if state is not None:
            state = list(state)
            if len(state) != 4:
                raise ValueError(f"a SEAD state is four words, not {len(state)}")
            self.state = [w & M32 for w in state]
        else:
            temp, self.state = seed & M32, []
            for i in range(1, 5):
                temp ^= temp >> 30
                temp = (temp * INIT_MULTIPLIER + i) & M32
                self.state.append(temp)

    def u32(self):
        s0, s3 = self.state[0], self.state[3]
        t = (s0 ^ (s0 << 11)) & M32
        t ^= t >> 8
        t ^= s3
        t ^= s3 >> 19
        t &= M32
        self.state = [self.state[1], self.state[2], s3, t]
        return t

    def u64(self):
        return (self.u32() << 32) | self.u32()

    def uint(self, maximum):
        """A draw in [0, maximum), the way SEAD reduces it - a multiply, not a modulo."""
        return (self.u32() * maximum) >> 32

    def bytes(self, size):
        """`size` bytes of output, each draw packed little-endian, as Pia consumes them."""
        if size % 4:
            raise ValueError(f"{size} is not a multiple of 4")
        return b"".join(struct.pack("<I", self.u32()) for _ in range(size // 4))


def create_key(rand, table, size=16):
    """ENL's key generator: `size` bytes assembled a byte at a time out of `table`.

    Each byte is two draws - which word of the table, and which of its four bytes.
    """
    if size % 4:
        raise ValueError(f"{size} is not a multiple of 4")
    out = b""
    for _ in range(size // 4):
        value = 0
        for _ in range(4):
            word = table[rand.uint(len(table))]
            value = (value << 8) | ((word >> (rand.uint(4) * 8)) & 0xFF)
        out += struct.pack("<I", value)
    return out
