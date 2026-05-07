# Firmware architecture

What's in [`firmware/bluesun-bms-panel.yaml`](../firmware/bluesun-bms-panel.yaml) and why each piece is there. Read [`docs/02-the-protocol.md`](02-the-protocol.md) first if you haven't — this doc assumes you know the Octopus BMS framing.

---

## The five pieces

```
┌────────────────────────────────────────────────────────┐
│                   BLE peer                             │
│            BlueSun Pack01 (master)                     │
│         service 0xFFF0 (FFF1 notify, FFF2 write)       │
└──────────────────────┬─────────────────────────────────┘
                       │ BLE GATT
┌──────────────────────┴─────────────────────────────────┐
│  ESP32-S3R8 — Sunton 4848S040C                         │
│                                                        │
│  ┌──────────────┐    ┌──────────────────────────────┐  │
│  │ BLE central  │───▶│ Scheduler (interval 500ms)   │  │
│  │ ble_client   │    │  decides which pack/cmd next │  │
│  │ auto_connect │    │  via ble_client.ble_write    │  │
│  └──────┬───────┘    └──────────────────────────────┘  │
│         │ notify                                       │
│         ▼                                              │
│  ┌──────────────┐    ┌──────────────────────────────┐  │
│  │ Parser       │───▶│ 86 sensors (HA + LVGL feed)  │  │
│  │ CRC + frame  │    │  per-pack + bank aggregates  │  │
│  └──────────────┘    └────────┬─────────────────────┘  │
│                               │                        │
│         ┌─────────────────────┴────────────────┐       │
│         ▼                                      ▼       │
│  ┌──────────────┐                    ┌─────────────┐   │
│  │ ESPHome API  │                    │ LVGL UI     │   │
│  │ → HA native  │                    │ 3 views     │   │
│  └──────────────┘                    └─────────────┘   │
└────────────────────────────────────────────────────────┘
```

### 1. BLE central (`esp32_ble`, `esp32_ble_tracker`, `ble_client`)

**Defaults everywhere.** No `sdkconfig_options`, no `framework.version` pin, no scan params override, no core pinning. ESPHome 2026.4.4 with ESP-IDF 5.5.4 ships sensible defaults for ESP32-S3 BLE central. Anything you "fix preventively" is more likely to break it.

```yaml
esp32_ble:                    # max_connections: 3, io_capability: none (defaults)
esp32_ble_tracker:            # interval 320ms, window 30ms, active true (defaults)
ble_client:
  - id: master
    mac_address: !secret bms_master_mac
    on_connect:
      then:
        - logger.log: "Connected"
        - delay: 1500ms       # let service discovery + ble_client.ble_write nodes register
```

`auto_connect` defaults to `true`. The scanner sees the advertisement, the client opens GATT, service discovery runs, and the action nodes (`ble_client.ble_write`) cache their `char_handle` from `SEARCH_CMPL_EVT`. Total time: ~5 seconds from boot to first poll.

If you've read advice telling you to pin BT controller to core 1 and Bluedroid to core 1 and WiFi to core 0, **ignore it**. That advice is correct for IDF 5.0 / 5.1 and produces `status=133` GATT timeouts on IDF 5.5.4. See [`docs/04-lessons-learned.md`](04-lessons-learned.md).

### 2. Scheduler (`interval: 500ms`)

Tick every 500 ms. Decides which pack and which cmd to query next:

- Fast band: `cmd 0x10` to each pack in turn, total period from `number.poll_fast_s` (default 5 s).
- Slow band: `cmd 0x11` to each pack in turn, total period from `number.poll_slow_s` (default 300 s).
- Round-robin per band (independent counters for fast vs slow).

State machine globals (in `globals:` block):
- `current_pack` (1..4) — pack number for next query.
- `current_cmd_idx` (0..1) — 0 = fast cmd 0x10, 1 = slow cmd 0x11.
- `should_send_now` (bool) — set when this tick decides to send.
- `last_fast_ms`, `last_slow_ms` — last tick that triggered each band.
- `next_fast_pack`, `next_slow_pack` — round-robin cursors.

Both polling intervals are exposed as `number.template` so HA can adjust them live without reflash.

### 3. Writer (`ble_client.ble_write` action)

Critical detail: **this is an `automation` action, not a script lambda**. The reason is in [`docs/04-lessons-learned.md`](04-lessons-learned.md) — TL;DR ESPHome frees `services_` from RAM after all child nodes establish, so any later `id(master).get_characteristic()` call returns null. The `ble_write` action registers as a `BLEClientNode`, captures the `char_handle` (uint16_t) at `SEARCH_CMPL_EVT`, and writes by handle for the rest of the session.

```yaml
- if:
    condition:
      lambda: 'return id(should_send_now);'
    then:
      - ble_client.ble_write:
          id: master
          service_uuid: FFF0
          characteristic_uuid: FFF2
          value: !lambda |-
            static const uint8_t QUERIES[2][4][8] = { /* CRC-baked frames */ };
            uint8_t p = id(current_pack);
            uint8_t c = id(current_cmd_idx);
            if (p < 1 || p > 4 || c > 1) return std::vector<uint8_t>{};
            return std::vector<uint8_t>(QUERIES[c][p-1], QUERIES[c][p-1] + 8);
```

### 4. Parser (`sensor: platform: ble_client, type: characteristic, notify: true`)

Subscribes to `FFF1` notifications. The lambda validates CRC, dispatches by `RSP` byte (`0x24` = cmd 0x10 reply, `0x34` = cmd 0x11 reply), and `publish_state()` to the matching per-pack sensor.

```yaml
sensor:
  - platform: ble_client
    id: octopus_notify_rx
    internal: true
    ble_client_id: master
    type: characteristic
    service_uuid: FFF0
    characteristic_uuid: FFF1
    notify: true
    update_interval: never
    lambda: |-
      // CRC check + dispatch — see firmware for the full body.
```

### 5. Sensors + UI

**Per-pack BMS sensors (template, internal-publish):**
- 7 from cmd 0x10: `pack0X_voltage / current / soc / soh / cycles / remaining_ah / nominal_ah`.
- 10 from cmd 0x11: `pack0X_cell_v_{min,max,avg,delta}` + `cell_temp_1..4` + `env_temp` + `pcb_temp`.

**Bank aggregates** (template lambda, derived from per-pack):
- `bank_voltage_avg`, `bank_current_total`, `bank_power = V·I`, `bank_soc_avg`, `bank_soc_spread = max-min`.
- `bank_remaining_ah = sum`, `bank_nominal_ah = sum`, `bank_min_soh`, `bank_max_cell_temp`, `bank_max_cycles`.

**Energy Dashboard sensors** (split + integrate):
- `bank_power_charging = max(0, bank_power)`, `bank_power_discharging = max(0, -bank_power)`.
- `battery_energy_in / battery_energy_out` via `platform: integration` with `time_unit: h` → Wh `total_increasing`. These plug directly into HA's Energy Dashboard.

**LVGL UI** (3 views, swipeable + tap drill-down):
- **Bank** (`home_page`): clock top-right, mode badge top-left (currently empty placeholder), giant SoC label color-by-SoC (green > 50, amber 25-50, red < 25), bar SoC, `V / A / W` line, 4 mini-bars per pack (P3 always amber by convention for the degraded-pack convention — adjust to your bank), status bar.
- **Packs** (`packs_page`): 2x2 grid of `obj` cards. Each card has SoC big + V / I / cell temp / cell delta / SoH. `on_short_click` sets `selected_pack` global and shows the Cells page.
- **Cells** (`cells_page`): drill-down for the selected pack. Vmin / Vmax / Vavg / delta + 4 cell temps + PCB / ENV.

All updates flow through a second `interval: 5s` block that pulls latest sensor values into label text via `lvgl.label.update`. Template sensors with constant lambdas only fire `on_value` once, so the periodic interval is the way to drive UI refreshes.

---

## Hardware pinout

The Sunton 4848S040C ships with this fixed pinout. The firmware has it pre-wired; only change if you're using a different board layout (Guition uses identical pins so it works as-is).

| Function | GPIO | Notes |
|---|---|---|
| **Display init SPI sideband** (CLK / MOSI / CS) | 48 / 47 / 39 | software SPI, only used at boot for ST7701S register init |
| **DE / HSYNC / VSYNC / PCLK** | 18 / 16 / 17 / 21 | RGB-565 16-bit @ 12 MHz |
| **Red[0..4]** | 11 / 12 / 13 / 14 / 0 | |
| **Green[0..5]** | 8 / 20 / 3 / 46 / 9 / 10 | |
| **Blue[0..4]** | 4 / 5 / 6 / 7 / 15 | |
| **Backlight PWM** | 38 | 5 kHz, monochromatic light platform |
| **Touch I2C SDA / SCL** | 19 / 45 | 100 kHz; SCL needs `ignore_strapping_warning` |
| **GT911 touch** | 0x5D on I2C | controller chip on the touch panel |
| **CH340C USB-Serial** | UART0 | for first flash + serial logs |

### Don't skip this gotcha

```yaml
sdkconfig_options:
  CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG: n   # MANDATORY
```

If you leave this at default, ESP-IDF tries to use the built-in USB-Serial-JTAG console, which silently grabs **GPIO19 + GPIO20**. GPIO19 happens to be the touch I2C SDA. Touch will randomly fail or be totally dead, with no error message. This is [esphome#15356](https://github.com/esphome/esphome/issues/15356).

---

## Build artefacts

- Compile time: ~5–7 minutes first build (ESP-IDF + Bluedroid + LVGL toolchain). ~1.5 min cached.
- Binary size: ~1.5 MB (well under the 8 MB partition default for the 16 MB flash variant).
- RAM: ~16% (54 KB of 327 KB on heap; PSRAM mostly unused — LVGL `buffer_size: 12%` claims about 220 KB of PSRAM at runtime).

The board is overpowered for this workload. The choice is driven by the screen, not by compute needs — a smaller ESP32-S3 module would work but you'd need to wire your own display.

---

## Build + flash

```bash
# First flash via USB-C (CH340C exposes a serial port)
esphome run firmware/bluesun-bms-panel.yaml --device /dev/ttyUSB0   # or COM5 etc.

# Subsequent updates over the air
esphome run firmware/bluesun-bms-panel.yaml --device 192.168.1.x

# Just compile, do not flash
esphome compile firmware/bluesun-bms-panel.yaml
```

If you want to validate BLE separately first (recommended on a fresh board), flash [`firmware/bluesun-bms-baseline.yaml`](../firmware/bluesun-bms-baseline.yaml) first. It's the same ESP32-S3 with only the BLE pieces enabled — if it can't connect to your bank, neither will the production firmware.
