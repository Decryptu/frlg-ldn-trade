"""The Local Protocol message a Let's Go host broadcasts: its statement of the session.

`pokeldn.ldn.local_protocol` reads one; this builds one. The layout is that module's, confirmed by
rebuilding a retail console's own message byte for byte.
"""
import struct

from pokeldn.ldn import local_protocol as lp

__all__ = ["build_update_session"]


def build_update_session(sequence_id, network_id, host_variable_id, host_service_variable_id,
                         host_constant_id, nodes, allow_participating=True,
                         host_migration_state=0):
    """One 0x11 update session. `nodes` is [(ip, port, ranking)] in seat order; the seats it does
    not fill are left empty, which is a ranking of 255."""
    # the size field counts what follows the fixed part, not what follows the header
    size = lp.NODE_COUNT * lp.NODE_SIZE + 1
    out = bytearray(lp.UPDATE_SESSION_FIXED + lp.NODE_COUNT * lp.NODE_SIZE + 1)
    struct.pack_into("<BBH", out, 0, 1, lp.UPDATE_SESSION, size)
    struct.pack_into("<4I", out, 0x0C, sequence_id & 0xFFFFFFFF, network_id & 0xFFFFFFFF,
                     host_variable_id & 0xFFFFFFFF, host_service_variable_id & 0xFFFFFFFF)
    out[0x20:0x28] = bytes(host_constant_id)[:8].ljust(8, b"\0")
    out[0x28] = 1 if allow_participating else 0
    for i in range(lp.NODE_COUNT):
        off = lp.UPDATE_SESSION_FIXED + i * lp.NODE_SIZE
        if i < len(nodes):
            ip, port, ranking = nodes[i]
            out[off:off + 4] = bytes(int(p) for p in ip.split("."))
            struct.pack_into(">H", out, off + 4, port & 0xFFFF)
            out[off + 8] = ranking & 0xFF
        else:
            out[off + 8] = lp.RANKING_EMPTY
    out[lp.UPDATE_SESSION_FIXED + lp.NODE_COUNT * lp.NODE_SIZE] = host_migration_state & 0xFF
    return bytes(out)
