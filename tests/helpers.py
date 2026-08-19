"""Shared synthetic-log helpers for discovery_capture tests."""

from discovery_capture import DLE, ETX, STX, LogLine, hex_to_bytes


def stuff(body: bytes, escape_mode: str = "double", escape_byte: int = None) -> bytes:
    marker = DLE if escape_mode == "double" else escape_byte
    out = bytearray([DLE, STX])
    for b in body:
        if b == DLE:
            out += bytes([DLE, marker])
        else:
            out.append(b)
    out += bytes([DLE, ETX])
    return bytes(out)


def frame_hex(
    payload_hex: str, crc_hex: str = "0000", escape_mode: str = "double", escape_byte: int = None
) -> str:
    """Build a full wire-frame hex string from a logical-payload hex string + CRC hex."""
    body = hex_to_bytes(payload_hex.replace(" ", "")) + hex_to_bytes(crc_hex.replace(" ", ""))
    return stuff(body, escape_mode=escape_mode, escape_byte=escape_byte).hex()


def log_text(*rows: tuple[str, str, str]) -> str:
    """rows: (HH:MM:SS.mmm, RX|TX, hex) -> a dump_frames-shaped log text block."""
    lines = []
    for ts, direction, hexstr in rows:
        lines.append(f"[{ts}][D][rs485_frame:335]: {direction} {hexstr}")
    return "\n".join(lines) + "\n"


def write_log(tmp_path, *rows: tuple[str, str, str]):
    p = tmp_path / "capture.log"
    p.write_text(log_text(*rows))
    return p
