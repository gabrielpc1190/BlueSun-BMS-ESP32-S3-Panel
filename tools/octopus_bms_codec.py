"""Codec del protocolo Octopus BMS — encode y verify basados en CRC-16/MODBUS.

Funciones:
  - crc16_modbus(data) -> bytes (2, little-endian)
  - verify(frame) -> bool
  - build_query(a1, a2, cmd) -> bytes (trama lista para escribir a handle 0x0014)

Ejemplo:
    >>> build_query(0x01, 0x04, 0x10).hex()
    '010410000012 74 c7' (concat sin espacios)
"""


def crc16_modbus(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc.to_bytes(2, "little")


def verify(frame: bytes) -> bool:
    if len(frame) < 3:
        return False
    data, crc = frame[:-2], frame[-2:]
    return crc16_modbus(data) == crc


def build_query(a1: int, a2: int, cmd: int, extra: int = None) -> bytes:
    """Arma la trama TX. El byte 5 (`extra`) parece depender del comando;
    si None, usa el valor observado en la captura para ese cmd.
    """
    cmd_extra_table = {
        0x10: 0x12, 0x11: 0x1A, 0x12: 0x90,
        0x17: 0x33, 0x18: 0x23, 0x20: 0x1A, 0x21: 0x16, 0x22: 0x49,
    }
    if extra is None:
        extra = cmd_extra_table.get(cmd)
        if extra is None:
            raise ValueError(f"No extra byte conocido para cmd 0x{cmd:02x}")
    body = bytes([a1, a2, cmd, 0x00, 0x00, extra])
    return body + crc16_modbus(body)


if __name__ == "__main__":
    # Sanity: replicar las 8 tramas capturadas
    expected = [
        (0x00, 0x04, 0x17, "000417000033b47a"),
        (0x00, 0x04, 0x18, "000418000023b6a2"),
        (0x00, 0x04, 0x20, "00042000001a7bd0"),
        (0x00, 0x04, 0x21, "0004210000167a29"),
        (0x00, 0x01, 0x22, "000122000049f655"),
        (0x01, 0x04, 0x10, "01041000001274c7"),
        (0x01, 0x04, 0x11, "01041100001a74fd"),
        (0x01, 0x01, 0x12, "010112000090391e"),
    ]
    ok = True
    for a1, a2, cmd, exp in expected:
        got = build_query(a1, a2, cmd).hex()
        match = got == exp
        mark = "OK " if match else "FAIL"
        print(f"  {mark} a={a1:02x}{a2:02x} cmd=0x{cmd:02x}  got={got}  exp={exp}")
        ok = ok and match
    print(f"\nAll match: {ok}")

    # Ejemplo: generar queries para packs 01..04 usando API v2 (cmd 0x10)
    print("\n# Queries API v2 (cmd 0x10 — pack data) para packs 01..04:")
    for pack in range(1, 5):
        q = build_query(0x01, pack, 0x10)
        print(f"  pack={pack}: {q.hex()}")
