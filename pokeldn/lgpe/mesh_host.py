"""The mesh messages a Let's Go host sends, built rather than replayed.

Let's Go's mesh entries use the version-4 geometry `pokeldn.ldn.mesh_protocol` documents: a
64-byte entry holding a station location with the station index at 0x3E. A two-station join
response is 148 bytes and an update mesh is 524, both measured on a retail console.
"""
import struct

from pokeldn.ldn import mesh_protocol as mp

__all__ = ["build_station_info", "build_join_response", "build_update_mesh"]


def build_station_info(location, station_index):
    """One 64-byte mesh entry: the station location, then its index at 0x3E."""
    if len(location) > mp.INDEX_FIELD_V4:
        raise ValueError(f"a station location must fit in {mp.INDEX_FIELD_V4} bytes, "
                         f"this is {len(location)}")
    out = bytearray(mp.STATION_INFO_SIZE_V4)
    out[:len(location)] = location
    out[mp.INDEX_FIELD_V4] = station_index & 0xFF
    return bytes(out)


def build_join_response(entries, ack_id, host_index=0, joining_index=1, max_active=2,
                        max_total=8, update_counter=0, max_buffer=0):
    """The host's answer to a join request. `entries` is [(location, station index)] in mesh order,
    the host's first; `joining_index` is the seat the joiner is given."""
    out = bytearray(16)
    out[0] = mp.JOIN_RESPONSE
    out[1] = len(entries)
    out[2] = host_index & 0xFF
    out[3] = joining_index & 0xFF
    out[4] = 1                                  # fragments
    out[5] = 0                                  # fragment index
    out[6] = len(entries)
    out[7] = 0                                  # base index
    out[8] = max_active & 0xFF
    out[9] = max_buffer & 0xFF
    out[10] = max_total & 0xFF
    struct.pack_into(">I", out, 12, update_counter & 0xFFFFFFFF)
    for location, index in entries:
        out += build_station_info(location, index)
    return bytes(out) + struct.pack(">I", ack_id & 0xFFFFFFFF)


def build_update_mesh(entries, update_counter, host_index=0, seats=8):
    """The host's periodic statement of who is in the mesh: twelve bytes of header and room for
    every seat, the unused ones left zero."""
    out = bytearray(mp.UPDATE_MESH_HEADER)
    out[0] = mp.UPDATE_MESH
    out[1] = len(entries)
    out[2] = host_index & 0xFF
    struct.pack_into(">I", out, 4, update_counter & 0xFFFFFFFF)
    out[8] = 1                                  # fragments
    out[9] = 0                                  # fragment index
    out[10] = len(entries)
    out[11] = 0                                 # base index
    for location, index in entries:
        out += build_station_info(location, index)
    out += bytes(mp.STATION_INFO_SIZE_V4 * (seats - len(entries)))
    return bytes(out)
