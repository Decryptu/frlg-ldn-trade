
from __future__ import annotations

from collections.abc import Callable, Iterable

import struct


Float = float


class ParseError(Exception):
    """Raised when an input stream encounters an error."""


class StreamOut:
    _endian: str
    _data: bytearray
    _pos: int

    def __init__(self, endian: str):
        self._endian = endian
        self._data = bytearray()
        self._pos = 0

    def set_endian(self, endian: str) -> None:
        self._endian = endian
        
    def get(self) -> bytes:
        return bytes(self._data)
    
    def size(self) -> int:
        return len(self._data)
    
    def tell(self) -> int:
        return self._pos

    def seek(self, pos: int) -> None:
        """Seeking past the end zero-extends the buffer."""
        if pos > len(self._data):
            self._data += bytes(pos - len(self._data))
        self._pos = pos
    
    def skip(self, num: int) -> None:
        self.seek(self._pos + num)
    
    def align(self, num: int) -> None:
        self.skip((num - self._pos % num) % num)

    def available(self) -> int:
        return len(self._data) - self._pos
    
    def eof(self) -> bool:
        return self._pos >= len(self._data)
        
    def write(self, data: bytes) -> None:
        self._data[self._pos : self._pos + len(data)] = data
        self._pos += len(data)
        
    def pad(self, num: int, value: int = 0) -> None:
        self.write(bytes([value]) * num)
        
    def ascii(self, data: str) -> None:
        self.write(data.encode("ascii"))
        
    def u8(self, value: int) -> None:
        self.write(bytes([value]))
    
    def u16(self, value: int) -> None:
        self.write(struct.pack(self._endian + "H", value))
    
    def u32(self, value: int) -> None:
        self.write(struct.pack(self._endian + "I", value))
    
    def u32_be(self, value: int) -> None:
        self.write(struct.pack(">I", value))

    def u64(self, value: int) -> None:
        self.write(struct.pack(self._endian + "Q", value))

    def s8(self, value: int) -> None:
        self.write(struct.pack("b", value))
    
    def s16(self, value: int) -> None:
        self.write(struct.pack(self._endian + "h", value))
    
    def s32(self, value: int) -> None:
        self.write(struct.pack(self._endian + "i", value))
    
    def s64(self, value: int) -> None:
        self.write(struct.pack(self._endian + "q", value))
    
    def u24(self, value: int) -> None:
        if self._endian == ">":
            self.u16(value >> 8)
            self.u8(value & 0xFF)
        else:
            self.u8(value & 0xFF)
            self.u16(value >> 8)
    
    def u128(self, value: int) -> None:
        if self._endian == ">":
            self.u64(value >> 64)
            self.u64(value & ((1 << 64) - 1))
        else:
            self.u64(value & ((1 << 64) - 1))
            self.u64(value >> 64)
    
    def float(self, value: Float) -> None:
        self.write(struct.pack(self._endian + "f", value))
    
    def double(self, value: Float) -> None:
        self.write(struct.pack(self._endian + "d", value))
    
    def bool(self, value: bool) -> None:
        self.u8(1 if value else 0)
    
    def char(self, value: str) -> None:
        self.u8(ord(value))
    
    def wchar(self, value: str) -> None:
        self.u16(ord(value))
    
    def chars(self, data: str) -> None:
        self.repeat(data, self.char)
    
    def wchars(self, data: str) -> None:
        self.repeat(data, self.wchar)
    
    def repeat[T](self, list: Iterable[T], func: Callable[[T], None]) -> None:
        for value in list:
            func(value)


class StreamIn:
    """Any read or seek past the end of the buffer raises ParseError."""

    _endian: str
    _data: bytes
    _pos: int

    def __init__(self, data: bytes, endian: str):
        self._endian = endian
        self._data = data
        self._pos = 0
    
    def set_endian(self, endian: str) -> None:
        self._endian = endian
        
    def get(self) -> bytes:
        return self._data
    
    def size(self) -> int:
        return len(self._data)
    
    def tell(self) -> int:
        return self._pos
    
    def seek(self, pos: int) -> None:
        if pos > self.size():
            raise ParseError("Buffer overflow")
        self._pos = pos
    
    def skip(self, num: int) -> None:
        self.seek(self._pos + num)
    
    def align(self, num: int) -> None:
        self.skip((num - self._pos % num) % num)
    
    def eof(self) -> bool:
        return self._pos == len(self._data)
    
    def available(self) -> int:
        return len(self._data) - self._pos
    
    def peek(self, num: int) -> bytes:
        if self.available() < num:
            raise ParseError("Buffer overflow")
        return self._data[self._pos : self._pos + num]
        
    def read(self, num: int) -> bytes:
        data = self.peek(num)
        self.skip(num)
        return data
        
    def readall(self) -> bytes:
        return self.read(self.available())
        
    def pad(self, num: int, value: int = 0) -> None:
        """Raises ParseError unless all num bytes equal value."""
        if self.read(num) != bytes([value]) * num:
            raise ParseError("Incorrect padding")
            
    def ascii(self, num: int) -> str:
        try:
            return self.read(num).decode("ascii")
        except UnicodeDecodeError:
            raise ParseError("Failed to decode ASCII characters")
        
    def u8(self) -> int:
        return self.read(1)[0]
    
    def u16(self) -> int:
        return struct.unpack(self._endian + "H", self.read(2))[0]
    
    def u32(self) -> int:
        return struct.unpack(self._endian + "I", self.read(4))[0]
    
    def u32_be(self) -> int:
        return struct.unpack(">I", self.read(4))[0]
    
    def u64(self) -> int:
        return struct.unpack(self._endian + "Q", self.read(8))[0]
    
    def s8(self) -> int:
        return struct.unpack("b", self.read(1))[0]
    
    def s16(self) -> int:
        return struct.unpack(self._endian + "h", self.read(2))[0]
    
    def s32(self) -> int:
        return struct.unpack(self._endian + "i", self.read(4))[0]
    
    def s64(self) -> int:
        return struct.unpack(self._endian + "q", self.read(8))[0]
    
    def u24(self) -> int:
        if self._endian == ">":
            return (self.u16() << 8) | self.u8()
        return self.u8() | (self.u16() << 8)
    
    def u128(self) -> int:
        if self._endian == ">":
            return (self.u64() << 64) | self.u64()
        return self.u64() | (self.u64() << 64)
    
    def float(self) -> Float:
        return struct.unpack(self._endian + "f", self.read(4))[0]
    
    def double(self) -> Float:
        return struct.unpack(self._endian + "d", self.read(8))[0]
    
    def bool(self) -> bool:
        return bool(self.u8())
    
    def char(self) -> str:
        return chr(self.u8())
    
    def wchar(self) -> str:
        return chr(self.u16())
    
    def chars(self, num: int) -> str:
        return "".join(self.repeat(self.char, num))
    
    def wchars(self, num: int) -> str:
        return "".join(self.repeat(self.wchar, num))
    
    def repeat[T](self, func: Callable[[], T], count: int) -> list[T]:
        return [func() for i in range(count)]
