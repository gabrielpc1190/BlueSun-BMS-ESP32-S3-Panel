"""Brute force CRC16 algoritmo del protocolo Octopus BMS.

Usa las 8 tramas TX capturadas (todas de 8 bytes: 6 de data + 2 de CRC) para
probar candidatos comunes. Si pasa las 8, muy probable es el algoritmo correcto.
"""
import struct

# (data_bytes_hex, expected_crc_hex) — últimos 2 bytes son el CRC, primeros 6
# son el frame-sin-CRC.
FRAMES = [
    ("000417000033", "b47a"),
    ("000418000023", "b6a2"),
    ("00042000001a", "7bd0"),
    ("000421000016", "7a29"),
    ("000122000049", "f655"),
    ("010410000012", "74c7"),
    ("01041100001a", "74fd"),
    ("010112000090", "391e"),
]


def crc16_tabled(data: bytes, poly: int, init: int, refin: bool, refout: bool, xorout: int) -> int:
    """Reference CRC16 — bit-by-bit, soporta reflected in/out."""
    def refbits(v, n):
        out = 0
        for i in range(n):
            if v & (1 << i):
                out |= 1 << (n - 1 - i)
        return out

    crc = init
    for b in data:
        if refin:
            b = refbits(b, 8)
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    if refout:
        crc = refbits(crc, 16)
    return crc ^ xorout


CANDIDATES = [
    # (name, poly, init, refin, refout, xorout)
    ("CRC-16/CCITT-FALSE", 0x1021, 0xFFFF, False, False, 0x0000),
    ("CRC-16/XMODEM",     0x1021, 0x0000, False, False, 0x0000),
    ("CRC-16/KERMIT",     0x1021, 0x0000, True,  True,  0x0000),
    ("CRC-16/GENIBUS",    0x1021, 0xFFFF, False, False, 0xFFFF),
    ("CRC-16/GSM",        0x1021, 0x0000, False, False, 0xFFFF),
    ("CRC-16/IBM-3740",   0x1021, 0xFFFF, False, False, 0x0000),
    ("CRC-16/MODBUS",     0x8005, 0xFFFF, True,  True,  0x0000),
    ("CRC-16/ARC",        0x8005, 0x0000, True,  True,  0x0000),
    ("CRC-16/USB",        0x8005, 0xFFFF, True,  True,  0xFFFF),
    ("CRC-16/MAXIM",      0x8005, 0x0000, True,  True,  0xFFFF),
    ("CRC-16/CMS",        0x8005, 0xFFFF, False, False, 0x0000),
    ("CRC-16/DNP",        0x3D65, 0x0000, True,  True,  0xFFFF),
    ("CRC-16/T10-DIF",    0x8BB7, 0x0000, False, False, 0x0000),
    ("CRC-16/DECT-R",     0x0589, 0x0000, False, False, 0x0001),
    ("CRC-16/TELEDISK",   0xA097, 0x0000, False, False, 0x0000),
    ("CRC-16/ZMODEM",     0x1021, 0x0000, False, False, 0x0000),
    ("CRC-16/PROFIBUS",   0x1DCF, 0xFFFF, False, False, 0xFFFF),
    ("CRC-16/MCRF4XX",    0x1021, 0xFFFF, True,  True,  0x0000),
    ("CRC-16/RIELLO",     0x1021, 0xB2AA, True,  True,  0x0000),
]


def try_candidates():
    # Byte order variants: expected_crc LE vs BE
    orders = [("BE (CRC-H first)", False), ("LE (CRC-L first)", True)]
    for name, poly, init, refin, refout, xorout in CANDIDATES:
        for order_label, swap in orders:
            ok = 0
            for frame_hex, crc_hex in FRAMES:
                data = bytes.fromhex(frame_hex)
                expected = int.from_bytes(bytes.fromhex(crc_hex), "little" if swap else "big")
                calc = crc16_tabled(data, poly, init, refin, refout, xorout)
                if calc == expected:
                    ok += 1
            if ok >= 6:
                status = "MATCH" if ok == 8 else f"partial {ok}/8"
                print(f"  [{status}]  {name:20s}  byte order: {order_label}")


if __name__ == "__main__":
    print("# Probando candidatos CRC16 contra 8 tramas TX...")
    try_candidates()
    print("# (Si nada matchea, puede requerir un inicio/xorout custom — reveng.exe desde línea de comandos sería el siguiente paso.)")
