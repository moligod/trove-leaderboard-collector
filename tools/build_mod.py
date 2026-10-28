#!/usr/bin/env python3
"""Build a Trove TMOD from the bundled SWF (not a Flash source compiler).

Container layout reference: Better Trove Tools core/src/modfile/format.rs and
core/src/game/hash.rs, https://github.com/AallynReed/BetterTroveTools.
The upstream UI asset's provenance and redistribution rights are not verified.
"""
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWF = ROOT / 'mod' / 'leaderboard.swf'
OUTPUT = ROOT / 'mod' / 'Redesigned - Leaderboard.tmod'


def uleb(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def trove_checksum(data):
    # FNV-style game checksum works on little-endian 4-byte words; the final
    # 1-3 bytes are sign-extended as C chars by the original format.
    mask = 0xffffffff
    h = 2166136261
    full = len(data) & ~3
    for i in range(0, full, 4):
        h = ((h ^ int.from_bytes(data[i:i+4], 'little')) * 16777619) & mask
    tail = data[full:]
    if tail:
        def sign(byte): return byte if byte < 128 else byte - 256
        value = sign(tail[0]) & mask
        for byte in tail[1:]:
            value = ((value << 8) | (sign(byte) & mask)) & mask
        h = ((h ^ value) * 16777619) & mask
    return h


def build(swf):
    if swf[:3] not in (b'FWS', b'CWS', b'ZWS'):
        raise ValueError('Expected a SWF file')
    # The title must match the cfg name used by the collector.
    props = [('title', 'Redesigned - Leaderboard'), ('author', 'Unknown'),
             ('modVersion', '1.0'), ('notes', 'Leaderboard collection; original UI attribution unverified'),
             ('tags', 'GUI')]
    header = bytearray(struct.pack('<QHH', 0, 1, len(props)))
    for key, value in props:
        for text in (key, value):
            raw = text.encode('utf-8')
            header += uleb(len(raw)) + raw
    name = b'ui/leaderboard.swf'
    header += bytes([len(name)]) + name + uleb(0) + uleb(0) + uleb(len(swf)) + uleb(trove_checksum(swf))
    struct.pack_into('<Q', header, 0, len(header))
    body = swf + b'\0' * ((-len(swf)) % 4)
    compressor = zlib.compressobj(level=0)
    return bytes(header) + compressor.compress(body) + compressor.flush(zlib.Z_SYNC_FLUSH)


def main():
    data = SWF.read_bytes()
    OUTPUT.write_bytes(build(data))
    print(f'Built {OUTPUT.name} from {SWF.name} ({len(data)} bytes).')
    print('Validate installation in a test game profile before distribution.')


if __name__ == '__main__': main()
