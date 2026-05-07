"""Helper para decodificar tramas del protocolo Octopus BMS (WIP).

Uso:
    python decode_octopus_frame.py <hex_string>

Ejemplos:
    python decode_octopus_frame.py 0104 24 149d 0000 fe03 4b24 6d60 0474 02af 03e3 ...
    python decode_octopus_frame.py 01043414a30000fe0effff4b190001b350...

También expone funciones para que otros scripts parseen en batch.

Estado: parcial — los offsets de campos están inferidos de una única muestra y
pueden estar mal. Ver docs/12-octopus-bms-protocol.md para el estado completo.
"""
import struct
import sys


def normalize_hex(s: str) -> bytes:
    s = s.replace(" ", "").replace("-", "").replace(":", "").lower()
    return bytes.fromhex(s)


def u16_be(b: bytes, off: int) -> int:
    return struct.unpack(">H", b[off:off + 2])[0]


def s16_be(b: bytes, off: int) -> int:
    return struct.unpack(">h", b[off:off + 2])[0]


# Mapa provisional de comandos conocidos
COMMANDS = {
    0x10: ("pack_data_v2", "Pack data compacto (API v2)"),
    0x11: ("cells_v2", "16 voltajes de celda + temps (API v2)"),
    0x12: ("status_v2", "Heartbeat/status (API v2)"),
    0x17: ("device_info", "Info del device: fabricante, modelo, serial"),
    0x18: ("config_info", "Config: inversor y protocolo CAN"),
    0x20: ("pack_data_v1", "Pack data (API v1)"),
    0x21: ("cells_v1", "Cells (API v1)"),
    0x22: ("status_v1", "Heartbeat/status (API v1)"),
}

# Comando → código de respuesta esperada
CMD_TO_RSP = {
    0x10: 0x24, 0x11: 0x34, 0x12: 0x12,
    0x17: 0x66, 0x18: 0x46,
    0x20: 0x34, 0x21: 0x2C, 0x22: 0x0A,
}


def decode(data: bytes) -> dict:
    if len(data) < 4:
        return {"error": f"too short ({len(data)} bytes)"}
    a1, a2, code = data[0], data[1], data[2]
    body = data[3:-2]
    crc = data[-2:]

    # Heurística: si code matchea alguno de los comandos conocidos y body parece
    # ser "00 00 XX" (5 bytes de overhead), es un TX. Si no, es un RX.
    is_tx = code in COMMANDS and len(body) == 3
    label = "TX" if is_tx else "RX"

    out = {
        "direction": label,
        "addr": f"{a1:02x} {a2:02x}",
        "code": f"0x{code:02x}",
        "code_name": COMMANDS.get(code, ("unknown",))[0],
        "body_hex": body.hex(),
        "body_len": len(body),
        "crc_hex": crc.hex(),
    }
    if is_tx:
        return out

    # Parse per response code
    if code == 0x24 and len(body) >= 36:
        # Mapeo confirmado (pack data v2, cmd 0x10):
        #   off 0:  voltaje total × 100 (U16 BE)            [V]
        #   off 2:  corriente × 100 (S16 BE, − = descarga)  [A]
        #   off 4:  capacidad remanente × 100 (U16 BE)      [Ah]
        #   off 6:  capacidad nominal × 100 (U16 BE)        [Ah]    ← pack3 da 274.4 ≠ 280 ✓
        #   off 8:  ??? pendiente (valores 1140..1498)
        #   off 10: SoC × 10 (U16 BE)                       [%]     ← confirmado vs remaining/nominal
        #   off 12: SoH × 10 (U16 BE)                       [%]     ← coincide con docs/11 (995, 995, 993, 994 = 99.5/99.5/99.3/99.4)
        #   off 14: ciclos (U16 BE)                         [count] ← coincide con docs/11 (50, 53, 66, 57 vs 49/51/66/57)
        #   off 16-27: 6 × U16 BE — dos patrones: valores 3.29-3.31V y 3.00-3.01V.
        #              hipótesis: 3 cells max + 3 NTC voltajes (o max/min/avg intercalados).
        out["pack_voltage_V"] = u16_be(body, 0) / 100.0
        out["current_A"] = s16_be(body, 2) / 100.0
        out["remaining_capacity_Ah"] = u16_be(body, 4) / 100.0
        out["nominal_capacity_Ah"] = u16_be(body, 6) / 100.0
        out["_off8_u16"] = u16_be(body, 8)
        out["soc_pct"] = u16_be(body, 10) / 10.0
        out["soh_pct"] = u16_be(body, 12) / 10.0
        out["cycles"] = u16_be(body, 14)
        out["_cells_block_mV"] = [u16_be(body, o) for o in range(16, 28, 2)]
        out["_trailer_hex"] = body[28:].hex()
    elif code == 0x34 and len(body) >= 32 and data[0] >= 0x01:
        # v2 cells (cmd 0x11, per-pack A1=1..4):
        #   offsets 0-31:  16 cells × U16 BE (mV)
        #   tail (10 × U16 si body=52, o 11 × U16 si body=54):
        #     - si body=54: primer U16 extra = cell avg (mV)
        #     - 4 × U16 temps de celda (K × 10; 0x0aab=2731 = sensor desconectado)
        #     - 4 × U16 sensores extra (en este banco casi siempre 0x0aab)
        #     - 2 × U16 env_temp + pcb/power_temp (K × 10)
        cells = [u16_be(body, i * 2) for i in range(16)]
        out["cells_mV"] = cells
        out["cells_summary_mV"] = {
            "min": min(cells),
            "max": max(cells),
            "avg": sum(cells) // 16,
            "delta": max(cells) - min(cells),
        }

        def k10_to_c(v):
            return None if v == 0x0AAB else round(v / 10.0 - 273.15, 2)

        tail_start = 32
        if len(body) >= 54:
            # variante con "cell avg" extra al principio
            out["cell_avg_reported_mV"] = u16_be(body, 32)
            tail_start = 34
        if len(body) >= tail_start + 20:
            out["cell_temps_C"] = [k10_to_c(u16_be(body, tail_start + i * 2)) for i in range(4)]
            out["extra_temps_C"] = [k10_to_c(u16_be(body, tail_start + 8 + i * 2)) for i in range(4)]
            out["env_temp_C"] = k10_to_c(u16_be(body, tail_start + 16))
            out["pcb_temp_C"] = k10_to_c(u16_be(body, tail_start + 18))
    elif code == 0x34 and len(body) >= 32 and data[0] == 0x00:
        # v1 pack_data (cmd 0x20): primera U16 es voltaje total
        out["pack_voltage_V"] = u16_be(body, 0) / 100.0
        out["_unknown_off2"] = u16_be(body, 2)
        out["current_A"] = s16_be(body, 4) / 100.0
        out["body_rest_hex"] = body[6:].hex()
    elif code == 0x2C:
        # v1 cells (cmd 0x21): 22 × U16 BE, layout incierto
        words = [u16_be(body, i * 2) for i in range(len(body) // 2)]
        out["words"] = words
        out["words_hex"] = " ".join(f"{w:04x}" for w in words)
    elif code == 0x66:
        # device info: strings ASCII
        def take_str(b, start, n):
            s = b[start:start + n].rstrip(b"\x00").decode("ascii", errors="replace")
            return s
        # Hipótesis de layout (inferido de una muestra)
        out["manufacturer"] = take_str(body, 0, 24)
        out["model"] = take_str(body, 24, 18)
        out["_gap"] = body[42:46].hex()
        out["serial"] = take_str(body, 46, 32)
    elif code == 0x46:
        # config info: más strings ASCII
        out["_leading"] = body[:4].hex()  # "000001f4" = 500?
        out["inverter_model"] = body[4:36].rstrip(b"\x00").decode("ascii", errors="replace")
        out["can_protocol"] = body[36:68].rstrip(b"\x00").decode("ascii", errors="replace")
        out["_trailer_hex"] = body[68:].hex()
    elif code == 0x12:
        # status v2: short
        out["body_words_hex"] = " ".join(f"{body[i]:02x}" for i in range(len(body)))
    elif code == 0x0A:
        # status v1: short
        out["body_words_hex"] = " ".join(f"{body[i]:02x}" for i in range(len(body)))
    else:
        out["note"] = "decoder sin regla para este rsp code — dump raw"

    return out


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    hex_s = " ".join(argv[1:])
    data = normalize_hex(hex_s)
    print(f"# input: {data.hex()}  ({len(data)} bytes)")
    result = decode(data)
    for k, v in result.items():
        print(f"  {k:32s} = {v!r}" if not isinstance(v, list) else f"  {k:32s} = {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
