import io
import struct
import zlib


def png_bytes(w=8, h=8) -> bytes:
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def docx_bytes(text="Quarterly plan: ship VoxSight.") -> bytes:
    from docx import Document
    d = Document(); d.add_paragraph(text)
    buf = io.BytesIO(); d.save(buf); return buf.getvalue()
