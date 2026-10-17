"""Codec protobuf minimo guiado por esquema (sem depender do pacote protobuf).

Suporta o que o protocolo do Twibi usa: varint (int/uint/bool/enum), string/bytes,
mensagens aninhadas, campos repetidos (inclusive packed na leitura), fixed32/64.
"""
from __future__ import annotations

import struct
from typing import Any

from .schema import SCHEMA

_VARINT = {"int32", "int64", "uint32", "uint64", "bool", "enum", "sint32", "sint64"}
_SIGNED = {"int32", "int64"}


class DecodeError(ValueError):
    """Bytes nao batem com o esquema esperado."""


def _read_varint(b: bytes, i: int) -> tuple[int, int]:
    r = sh = 0
    while True:
        if i >= len(b):
            raise DecodeError("varint truncado")
        x = b[i]
        i += 1
        r |= (x & 0x7F) << sh
        sh += 7
        if not x & 0x80:
            return r, i
        if sh > 70:
            raise DecodeError("varint grande demais")


def _varint(n: int) -> bytes:
    if n < 0:
        n += 1 << 64
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _conv(typ: str, v: int) -> Any:
    if typ == "bool":
        return bool(v)
    if typ in _SIGNED and v >= 1 << 63:
        v -= 1 << 64
    if typ == "sint32" or typ == "sint64":
        v = (v >> 1) ^ -(v & 1)
    return v


def decode(msg: str, b: bytes) -> dict[str, Any]:
    """Decodifica `b` como a mensagem `msg` (ex.: "Onhosts.hostLists")."""
    fields = SCHEMA[msg]
    out: dict[str, Any] = {}
    for num, (name, typ, rep, _ref) in fields.items():
        if rep:
            out[name] = []
    i = 0
    while i < len(b):
        key, i = _read_varint(b, i)
        num, wt = key >> 3, key & 7
        if num == 0:
            raise DecodeError("campo 0")
        if wt == 0:
            raw, i = _read_varint(b, i)
            val: Any = raw
        elif wt == 2:
            ln, i = _read_varint(b, i)
            if i + ln > len(b):
                raise DecodeError("tamanho alem do fim")
            val = b[i:i + ln]
            i += ln
        elif wt == 5:
            val = struct.unpack("<I", b[i:i + 4])[0]
            i += 4
        elif wt == 1:
            val = struct.unpack("<Q", b[i:i + 8])[0]
            i += 8
        else:
            raise DecodeError(f"wire type {wt}")
        spec = fields.get(num)
        if spec is None:
            out.setdefault("_unknown", {})[num] = val
            continue
        name, typ, rep, ref = spec
        if typ == "message" and isinstance(val, bytes):
            vals = [decode(ref, val)] if ref else [val]
        elif typ in ("string",) and isinstance(val, bytes):
            vals = [val.decode("utf-8", errors="replace")]
        elif typ in _VARINT and isinstance(val, bytes):  # packed
            vals, j = [], 0
            while j < len(val):
                v, j = _read_varint(val, j)
                vals.append(_conv(typ, v))
        elif typ in _VARINT:
            vals = [_conv(typ, val)]
        else:
            vals = [val]
        if rep:
            out[name].extend(vals)
        else:
            out[name] = vals[-1]
    return out


def encode(msg: str, data: dict[str, Any]) -> bytes:
    """Codifica o dict `data` (chaves = nomes dos campos) como `msg`."""
    fields = SCHEMA[msg]
    out = bytearray()
    for num in sorted(fields):
        name, typ, rep, ref = fields[num]
        if name not in data or data[name] is None:
            continue
        vals = data[name] if rep else [data[name]]
        for v in vals:
            if typ == "message":
                body = encode(ref, v) if isinstance(v, dict) else bytes(v)
                out += _varint(num << 3 | 2) + _varint(len(body)) + body
            elif typ in ("string", "bytes"):
                body = v.encode() if isinstance(v, str) else bytes(v)
                out += _varint(num << 3 | 2) + _varint(len(body)) + body
            elif typ in _VARINT:
                n = int(v)
                if typ in ("sint32", "sint64"):
                    n = (n << 1) ^ (n >> 63)
                out += _varint(num << 3) + _varint(n)
            elif typ in ("fixed32", "sfixed32", "float"):
                out += _varint(num << 3 | 5) + struct.pack("<I" if typ == "fixed32" else "<i", int(v))
            elif typ in ("fixed64", "sfixed64", "double"):
                out += _varint(num << 3 | 1) + struct.pack("<Q" if typ == "fixed64" else "<q", int(v))
    return bytes(out)
