# Octopus BMS BLE protocol

What the BlueSun pack speaks over Bluetooth Low Energy. Decoded by capturing Android `btsnoop` logs while running the Octopus BMS app and reverse-engineering the framing + CRC. The firmware in this repo speaks this protocol natively.

This document is the canonical reference. If a frame doesn't match what's described here, your bank is running a different Octopus firmware variant — please open an issue with a btsnoop capture.

---

## GATT layout

The pack advertises **two** GATT services:

| UUID | Type | Use |
|---|---|---|
| `0xFFF0` | 16-bit (SIG-style) | **Real channel.** Use this. |
| `02f00000-590a-44a9-8b03-f6e2b1a5fe00` | 128-bit | Vestigial / debug. Empty notifications. **Ignore.** |

Inside `0xFFF0`:

| Characteristic | Handle | Properties | Use |
|---|---|---|---|
| `0xFFF1` | 0x0010 | NOTIFY | Pack publishes responses here. Subscribe + parse. |
| `0xFFF2` | 0x0014 | WRITE_NO_RESP | Send queries here. **Must use `WRITE_NO_RESPONSE`** — the BMS silently drops `WRITE_WITH_RESPONSE`. |

> **Important.** Many BLE libraries default to `WRITE_WITH_RESPONSE`. ESPHome's `ble_client.ble_write` action selects the correct write type by reading the characteristic's properties bitmap (`ESP_GATT_CHAR_PROP_BIT_WRITE` vs `WRITE_NR`), so you generally don't have to do anything. Lambdas calling `chr->write_value(..., ESP_GATT_WRITE_TYPE_NO_RSP)` need it explicitly.

## Topology

Only **Pack01 (master)** accepts BLE connections from outside. Packs 02 / 03 / 04 are not visible directly — they're slaves on an internal RS485 bus inside the rack.

The Octopus master implements a transparent relay: queries with `A1 = 0x02..0x04` (the pack-id byte in the frame) are forwarded over RS485 to the addressed slave, and the slave's response comes back through the same BLE notify channel.

This means:
- **One BLE session = access to all 4 packs.** No need for one ESP per pack.
- The ESP only needs to be in BLE range of the master (physically on top of the rack is ideal — RSSI -76 to -82 dBm in our test setup).
- No external RS485 wiring required.

## Frame format

### Query (TX, ESP → BMS)

Fixed 8 bytes, little-endian CRC at the end:

```
┌─────┬──────┬──────┬──────┬──────┬───────┬─────────┐
│ A1  │ 0x04 │ CMD  │ 0x00 │ 0x00 │ EXTRA │ CRC L H │
└─────┴──────┴──────┴──────┴──────┴───────┴─────────┘
  pack    fn    cmd    pad    pad   length     CRC-16/MODBUS
  (1-4)        (0x10..)
```

- `A1`: pack number, **1-indexed** (`0x01` for Pack01, `0x04` for Pack04).
- `0x04`: function code (READ-like). Constant for the cmd 0x10 / 0x11 we care about.
- `CMD`: command code (`0x10` for fast snapshot, `0x11` for cells/temps; see below).
- `EXTRA`: response-length hint (`0x12` = 18 bytes payload for cmd 0x10, `0x1a` = 26 bytes for cmd 0x11).
- `CRC L H`: CRC-16/MODBUS over bytes `[A1..EXTRA]`, **little-endian** in the frame.

### Response (RX, BMS → ESP, via notify)

```
┌─────┬──────┬──────┬─────────────────┬─────────┐
│ A1  │ 0x04 │ RSP  │  payload bytes  │ CRC L H │
└─────┴──────┴──────┴─────────────────┴─────────┘
  pack          rsp        N bytes      CRC-16/MODBUS
                (0x24..)
```

- `RSP = 0x24` for cmd `0x10` responses (payload 36 bytes).
- `RSP = 0x34` for cmd `0x11` responses (payload typically 52 bytes; some firmwares emit 54).
- The `A1` byte echoes the queried pack so you know which pack the data is for.

### CRC-16/MODBUS

Polynomial `0xA001` (reversed), init `0xFFFF`, no XOR-out. The standard MODBUS-RTU CRC. Reference Python:

```python
def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc  # little-endian in the frame
```

If your CRC doesn't match, the BMS silently drops the frame. No retry, no error. Always validate RX CRC and skip the frame on mismatch.

## Commands

### `cmd 0x10` — fast snapshot (V/I/SoC/SoH/cycles/Ah)

Query for Pack01:
```
01 04 10 00 00 12 74 c7
```

Response (36-byte payload after `A1 04 24`, big-endian U16 / S16):

| Offset | Field | Type | Scale | Notes |
|---|---|---|---|---|
| 0 | voltage | U16 | / 100 → V | pack terminal voltage |
| 2 | current | S16 | / 100 → A | **+ = charging, − = discharging** |
| 4 | remaining_ah | U16 | / 100 → Ah | |
| 6 | nominal_ah | U16 | / 100 → Ah | factory nominal capacity |
| 8 | (reserved) | U16 | — | |
| 10 | soc | U16 | / 10 → % | state of charge |
| 12 | soh | U16 | / 10 → % | state of health |
| 14 | cycles | U16 | as-is | charge cycles since pack manufacture |
| 16+ | (reserved) | — | — | |

Pre-baked CRCs for cmds 0x10 to 4 packs:
```
Pack01 cmd 0x10:  01 04 10 00 00 12 74 c7
Pack02 cmd 0x10:  02 04 10 00 00 12 74 f4
Pack03 cmd 0x10:  03 04 10 00 00 12 75 25
Pack04 cmd 0x10:  04 04 10 00 00 12 74 92
```

### `cmd 0x11` — cells + temps

Query for Pack01:
```
01 04 11 00 00 1a 74 fd
```

Response (52 or 54 bytes payload after `A1 04 34`):

| Offset | Field | Type | Scale | Notes |
|---|---|---|---|---|
| 0..31 | cell_voltage[0..15] | U16 × 16 | as-is → mV | 16 cells in series |
| **32 or 34** (firmware-dependent) | cell_temp[0..3] | U16 × 4 | / 10 − 273.15 → °C | Kelvin × 10. `0x0AAB` (= 273.1 K = 0 °C "invalid" sentinel) → NaN |
| +8 | env_temp | U16 | same | environment around the pack |
| +10 | pcb_temp | U16 | same | BMS PCB temperature |

Detect tail offset by payload length: 54 bytes → tail at offset 34, 52 bytes → tail at offset 32.

Aggregates derived per pack from the 16 cells:
- `cell_v_min = min(cell[0..15])`
- `cell_v_max = max(cell[0..15])`
- `cell_v_avg = mean(cell[0..15])`
- `cell_v_delta = cell_v_max - cell_v_min` (your bank's balancing health — `<10 mV` is good, `>50 mV` is bad)

Pre-baked CRCs for cmds 0x11 to 4 packs:
```
Pack01 cmd 0x11:  01 04 11 00 00 1a 74 fd
Pack02 cmd 0x11:  02 04 11 00 00 1a 74 ce
Pack03 cmd 0x11:  03 04 11 00 00 1a 75 1f
Pack04 cmd 0x11:  04 04 11 00 00 1a 74 a8
```

The firmware embeds these as a `static const uint8_t QUERIES[2][4][8]` table — see [`firmware/bluesun-bms-panel.yaml`](../firmware/bluesun-bms-panel.yaml) under the `interval: 500ms` scheduler.

## Polling cadence

The firmware uses two intervals:

- **Fast** (`cmd 0x10`, default every 5 s total = ~1.25 s per pack round-robin) — V/I/SoC change in seconds, you want them fresh.
- **Slow** (`cmd 0x11`, default every 300 s = 75 s per pack) — cell voltages drift over hours, polling fast wastes BLE airtime.

Both are exposed as `number.<your_panel>_bluesun_poll_fast_cmd_0x10` and `_poll_slow_cmd_0x11` so you can tune live in HA without reflashing.

The pacing is deterministic round-robin so each pack gets queried at the same rate. The scheduler (`interval: 500ms`) sets a `should_send_now` flag and the next pack number, and a separate `ble_client.ble_write` action consumes them. See the firmware comments for the exact code.

## Other commands (not implemented)

The following codes were observed in btsnoop captures but are not used by this firmware. Mostly because cmd 0x10 + cmd 0x11 cover everything HA needs.

| `RSP` | Likely meaning | Decode status |
|---|---|---|
| `0x32` | configured limits (V min/max, current limits, balance threshold) | TBD |
| `0x44` | factory parameters | TBD |
| `0x84` | set commands (write-side responses) | not relevant for read-only proxy |

`cmd 0x14` was seen briefly — could be triggered by the app when entering certain settings views — but never decoded.

## How this was decoded

1. Install Octopus BMS app on a Pixel running Android with **Bluetooth HCI snoop log** enabled (Developer options).
2. Connect the app to a pack, navigate every screen, log in/out a few times.
3. `adb pull /sdcard/btsnoop_hci.log`.
4. `parse_btsnoop.py` (in [`tools/`](../tools)) extracts ATT-layer events: writes to `0xFFF2` and notifications from `0xFFF1`.
5. Cross-correlate writes with notifications (timestamps usually match within ~50 ms) to pair queries to responses.
6. `crack_octopus_crc.py` was used to identify the CRC variant by brute-forcing common polynomials against multiple captured frames.
7. Once CRC was known, the framing structure became obvious from the pattern.

Two captures from different days converged on the same protocol. The cell-temp tail offset (32 vs 34) was the only firmware-dependent variation.

If your bank's BMS firmware is from a different Octopus revision, run the same procedure and compare. PRs welcome.
