"""Reading a Switch title's RomFS in place, off the encrypted container.

The reader never extracts: a RomFS section is AES-128-CTR, CTR is seekable, and the counter for any
range is the section CTR's high half followed by (nca_relative_offset >> 4) big-endian. That is what
lets a 4.2 GB RomFS be walked, searched and single-file extracted with no disk cost - session 45
found BDSP's `cryptoKeyDataSeed` that way, and the same reader answers for any title.

WHAT SAYS A READ IS REAL: the RomFS header's first word is its own size, 0x50. A wrong key, a wrong
section offset or a wrong counter all land there first, and every one of them gives a header_size
that is not 0x50 - which is why the reader raises on it rather than parsing whatever came back.

These build a container in memory, so nothing here needs a key, a dump or the share.
"""

import os
import struct
import sys

import pytest
from Crypto.Cipher import AES

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "switch"))

from romfs_read import CtrReader, RomFs, scan               # noqa: E402

KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
CTR_HIGH = bytes.fromhex("0000000200000000")
NCA_OFFSET = 0x8000          # where the program NCA starts inside the container
ROMFS_OFFSET = 0x1000        # NCA-relative start of the level-5 data
END = 0xFFFFFFFF


def _dir_entry(parent, sibling, child_dir, child_file, name):
    raw = struct.pack("<6I", parent, sibling, child_dir, child_file, END, len(name)) + name
    return raw + b"\0" * (-len(raw) % 4)


def _file_entry(parent, sibling, data_off, data_size, name):
    raw = (struct.pack("<2I", parent, sibling) + struct.pack("<2Q", data_off, data_size)
           + struct.pack("<2I", END, len(name)) + name)
    return raw + b"\0" * (-len(raw) % 4)


def build_romfs(files):
    """-> the plaintext RomFS image for {name: content} in one root directory."""
    file_meta, blobs, data_off = b"", b"", 0
    names = list(files)
    for i, name in enumerate(names):
        content = files[name]
        sibling = END if i == len(names) - 1 else len(file_meta) + len(
            _file_entry(0, 0, 0, 0, name.encode()))
        file_meta += _file_entry(0, sibling, data_off, len(content), name.encode())
        blobs += content + b"\0" * (-len(content) % 16)
        data_off = len(blobs)
    dir_meta = _dir_entry(0, END, END, 0 if files else END, b"")

    head_size = 0x50
    dir_hash_off = head_size
    dir_meta_off = dir_hash_off + 4
    file_hash_off = dir_meta_off + len(dir_meta)
    file_meta_off = file_hash_off + 4
    file_data_off = file_meta_off + len(file_meta)
    file_data_off += -file_data_off % 16
    header = struct.pack("<10Q", head_size, dir_hash_off, 4, dir_meta_off, len(dir_meta),
                         file_hash_off, 4, file_meta_off, len(file_meta), file_data_off)
    image = bytearray(file_data_off)
    image[0:head_size] = header
    image[dir_hash_off:dir_hash_off + 4] = b"\0" * 4
    image[dir_meta_off:dir_meta_off + len(dir_meta)] = dir_meta
    image[file_hash_off:file_hash_off + 4] = b"\0" * 4
    image[file_meta_off:file_meta_off + len(file_meta)] = file_meta
    return bytes(image) + blobs


def write_container(tmp_path, romfs, key=KEY, ctr_high=CTR_HIGH):
    """Encrypt `romfs` into a container the reader can be pointed at, and -> its path."""
    body = bytearray(b"\0" * (ROMFS_OFFSET + len(romfs)))
    body[ROMFS_OFFSET:ROMFS_OFFSET + len(romfs)] = romfs
    out = bytearray(b"\xAA" * NCA_OFFSET)
    for off in range(0, len(body), 16):
        ctr = ctr_high + struct.pack(">Q", off >> 4)
        out += AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=ctr).encrypt(bytes(body[off:off + 16]))
    path = tmp_path / "container.nsp"
    path.write_bytes(bytes(out))
    return str(path)


@pytest.fixture
def romfs(tmp_path):
    files = {"global-metadata.dat": b"\xaf\x1b\xb1\xfa" + b"WirelessStrongCryptoKey2021" + b"\x11" * 300,
             "rawsettings": b"UNX0" + b"\x00" * 60,
             "boot.config": b"gfx-enable-gfx-debug=0\n"}
    path = write_container(tmp_path, build_romfs(files))
    reader = CtrReader(path, NCA_OFFSET, KEY, CTR_HIGH)
    yield RomFs(reader, ROMFS_OFFSET), files
    reader.close()


def test_header_size_is_what_proves_the_counter(romfs):
    fs, _ = romfs
    assert fs.header_size == 0x50


def test_a_wrong_key_is_refused_at_the_header_and_not_parsed(tmp_path):
    path = write_container(tmp_path, build_romfs({"a": b"x" * 32}))
    reader = CtrReader(path, NCA_OFFSET, bytes(16), CTR_HIGH)
    with pytest.raises(ValueError, match="header_size"):
        RomFs(reader, ROMFS_OFFSET)
    reader.close()


def test_a_wrong_section_offset_is_refused_the_same_way(tmp_path):
    path = write_container(tmp_path, build_romfs({"a": b"x" * 32}))
    reader = CtrReader(path, NCA_OFFSET, KEY, CTR_HIGH)
    with pytest.raises(ValueError, match="header_size"):
        RomFs(reader, ROMFS_OFFSET + 0x10)
    reader.close()


def test_walk_finds_every_file_with_its_size(romfs):
    fs, files = romfs
    walked = {path: size for path, _off, size in fs.walk()}
    assert walked == {"/" + name: len(content) for name, content in files.items()}


def test_a_file_reads_back_byte_for_byte(romfs):
    fs, files = romfs
    for path, off, size in fs.walk():
        assert fs.read_file(off, size) == files[path.lstrip("/")]


def test_an_unaligned_read_lands_on_the_same_bytes(romfs):
    """CTR is seekable only if the counter follows the aligned offset, not the requested one."""
    fs, files = romfs
    for path, off, size in fs.walk():
        whole = files[path.lstrip("/")]
        for skip in (1, 7, 15):
            if size > skip:
                assert fs.read_file(off + skip, size - skip) == whole[skip:]


def test_scan_finds_a_needle_at_its_offset_within_the_file(romfs):
    fs, _ = romfs
    hits = list(scan(fs, [b"WirelessStrongCryptoKey2021"]))
    assert hits == [("/global-metadata.dat", 4, b"WirelessStrongCryptoKey2021")]


def test_scan_takes_several_needles_in_one_pass(romfs):
    fs, _ = romfs
    hits = {(path, needle) for path, _off, needle in scan(fs, [b"UNX0", b"gfx-enable"])}
    assert hits == {("/rawsettings", b"UNX0"), ("/boot.config", b"gfx-enable")}


def test_scan_crosses_the_chunk_boundary(romfs):
    """A needle split across two reads is why the scan carries a tail; chunk it small to force it."""
    fs, _ = romfs
    hits = list(scan(fs, [b"WirelessStrongCryptoKey2021"], chunk=16))
    assert hits == [("/global-metadata.dat", 4, b"WirelessStrongCryptoKey2021")]


def test_scan_limits_itself_to_the_named_paths(romfs):
    fs, _ = romfs
    assert list(scan(fs, [b"UNX0"], names=["/global-metadata"])) == []
    assert len(list(scan(fs, [b"UNX0"], names=["/rawsettings"]))) == 1
