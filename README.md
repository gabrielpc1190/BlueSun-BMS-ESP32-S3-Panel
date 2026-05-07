# BlueSun BMS — ESP32-S3 panel with LVGL display + Home Assistant

Read your **BlueSun lithium battery bank in real time** from any ESPHome-based Home Assistant install. This repo turns a cheap touchscreen ESP32-S3 board into a BLE proxy that speaks the **Octopus BMS** protocol natively, exposes 86 sensors to Home Assistant, and renders three swipeable LVGL views (Bank / Packs / Cells) on a 4″ 480×480 IPS panel mounted right on top of the bank.

![panel hero photo placeholder — replace with real image](docs/img/panel-hero.jpg)

> Sister project to [`gair-ac-ir-esp32c3`](https://github.com/gabrielpc1190/gair-ac-ir-esp32c3) (IR control of GAir minisplits with ESPHome). Both came from the same off-grid solar house build.

---

## What you get

- **86 Home Assistant sensors** with prefix `sensor.<your_panel>_bluesun_*`:
  - 28 per-pack `cmd 0x10` (V / I / SoC / SoH / cycles / `_remaining_ah` / `_nominal_ah`).
  - 40 per-pack `cmd 0x11` (cell V min/max/avg/delta + 4 cell temps + env temp + PCB temp).
  - 10 bank aggregates (`bank_voltage_avg`, `bank_current_total`, `bank_power`, `bank_soc_avg`, `bank_soc_spread`, `bank_remaining_ah`, `bank_nominal_ah`, `bank_max_cell_temp`, `bank_min_soh`, `bank_max_cycles`).
  - 2 power split + 2 integration energy (`bank_power_charging/discharging`, `battery_energy_in/out`) — drop-in replacement for the SolarAssistant Energy Dashboard inputs.
  - 4 telemetry / aux (`octopus_parses_ok`, scheduler state, etc).
- **3 swipeable LVGL views** on the panel:
  - **Bank** — clock, mode badge, SoC big with color-by-SoC (green / amber / red), bar SoC, V/A/W, 4 mini-bars per pack, status bar.
  - **Packs** — 2×2 grid of cards, SoC + V / A / T / Δ / SoH per pack. Tap a card to drill in.
  - **Cells** — selected pack's Vmin / Vmax / Vavg / delta + 4 cell temps + PCB / ENV.
- **Production-grade BLE**: `auto_connect: true` with default ESPHome scan parameters, no core pinning, no IDF version pinning. The firmware reconnects automatically after the bank or the panel resets.
- **Single-central handling**: a `switch.<your_panel>_panel_bms_enabled` kill-switch lets you free the BLE slot temporarily for the Android Octopus BMS app.

---

## Hardware

| Component | Tested model | Notes |
|---|---|---|
| ESP32-S3 panel | **Sunton ESP32-4848S040C** (a.k.a. Guition ESP32-S3-4848S040) | 4″ 480×480 IPS, ST7701S RGB-565 16-bit, GT911 capacitive touch, ESP32-S3R8 (16 MB flash, 8 MB octal PSRAM), CH340C USB-Serial. ~30 USD on AliExpress. |
| BlueSun bank | 4 × 280 Ah LiFePO4 packs, 16s | Pack01 must be the BLE master. The bank's internal RS485 bus handles relay to the slave packs. Tested with packs running BMS firmware that exposes service `0xFFF0` chars `FFF1` (notify) + `FFF2` (write). |
| Power supply | 5 V / 1 A USB-C | Permanent (not battery — the panel is always-on). |

The panel's pinout is fixed by the Sunton board layout. The firmware in [`firmware/bluesun-bms-panel.yaml`](firmware/bluesun-bms-panel.yaml) has it pre-wired:
- Display (RGB-565 16-bit @ 12 MHz): DE GPIO18, HSYNC GPIO16, VSYNC GPIO17, PCLK GPIO21, R[GPIO11/12/13/14/0], G[GPIO8/20/3/46/9/10], B[GPIO4/5/6/7/15], BL PWM GPIO38.
- Display init SPI sideband: CLK GPIO48, MOSI GPIO47, CS GPIO39 (software interface, init-only).
- Touch I2C: SDA GPIO19, SCL GPIO45 (with `ignore_strapping_warning`), GT911 @ 0x5D, 100 kHz.

---

## Quick start

### 1. Find your bank's BLE MAC

Open the **Octopus BMS** Android app, scan, connect to a pack. The MAC of the pack you connected to is the **Pack01 master** (only the master accepts external BLE connections; it relays to the others over RS485 internally). Write it down.

You can also use a BLE scanner app (nRF Connect) and look for a device named like `BNxxxxxxxxxxxx`.

### 2. Set up secrets

```bash
cd firmware
cp secrets.yaml.example secrets.yaml
# Edit secrets.yaml with your wifi_ssid, wifi_password, api_encryption_key,
# ota_password, fallback_ap_password, and bms_master_mac.
```

### 3. Compile + flash

```bash
# First flash via USB-C (the CH340C exposes a serial port)
esphome run firmware/bluesun-bms-panel.yaml --device /dev/ttyUSB0    # Linux
esphome run firmware/bluesun-bms-panel.yaml --device COM5            # Windows

# Subsequent updates over the air
esphome run firmware/bluesun-bms-panel.yaml --device 192.168.1.x
```

The first compile takes ~5–7 minutes (ESP-IDF + LVGL + Bluedroid). OTA upload is ~6 seconds after that.

### 4. Verify

- Logs should show within ~5 seconds of boot:
  ```
  [I][esp32_ble_client]: Connection open
  [I][esp32_ble_client]: Service discovery complete
  [I][octopus]: pack=1 U=52.50V I=-7.61A SoC=66.7%
  ```
- The display lights up and shows the Bank view with live SoC.
- Home Assistant auto-discovers the panel as an ESPHome device. Add it from **Settings → Devices & Services → ESPHome**. The 86 BMS sensors appear under it.

### 5. Add to your dashboard

Use [`examples/home_assistant_dashboard.yaml`](examples/home_assistant_dashboard.yaml) as a starting point. It expects entity prefix `panel_cuartoelectrico_bluesun_*` — find-and-replace with your panel's actual prefix once it's discovered.

---

## Documentation

- [`docs/01-the-problem.md`](docs/01-the-problem.md) — Why your BlueSun bank is invisible to Home Assistant by default.
- [`docs/02-the-protocol.md`](docs/02-the-protocol.md) — Octopus BMS BLE protocol: service `0xFFF0`, CRC-16/MODBUS, frame structure, decoded commands `0x10` / `0x11`.
- [`docs/03-the-firmware.md`](docs/03-the-firmware.md) — Firmware architecture: BLE proxy + LVGL 3 views + scheduler + 86 sensors.
- [`docs/04-lessons-learned.md`](docs/04-lessons-learned.md) — **Required reading.** The two non-obvious bugs that cost a week to figure out: ESP32-S3 BLE central defaults beat overrides; ESPHome releases `services_` after `all_nodes_established_()` so `get_characteristic()` from scripts silently returns null.
- [`docs/05-home-assistant.md`](docs/05-home-assistant.md) — HA integration: dashboard YAML, offline-alert automation, optional package for cached/stale fallback during outages.

---

## Why this exists

Off-grid solar installs with BlueSun racks need BMS visibility for:
- **Autonomy planning** — knowing the actual bank SoC and remaining Ah, not just the inverter's estimate.
- **Cell health** — spotting drift between cells (Δ > 50 mV is bad), pack imbalance, temperature excursions.
- **Energy dashboard** — accurate Wh in/out integrated from the BMS-reported power.
- **Alarms** — pack-level SoH degradation, cell over-temp.

The Octopus BMS Android app has all of this but only over Bluetooth, only on one phone, and only when the app is open. This project replaces it with an always-on ESP32 that pushes everything to Home Assistant — and adds a touchscreen that's nice to look at when you walk past the battery rack.

---

## Limitations

- **Single-central BLE**: only one client can connect to the master pack at a time. While the panel is connected the Octopus Android app can't connect. Toggle `switch.<your_panel>_panel_bms_enabled` off to free the slot temporarily.
- **Octopus BMS firmware variants**: this was tested against the firmware version that exposes `0xFFF0/FFF1/FFF2`. Some variants expose a 128-bit UUID `02f00000-…-fe00` as a vestigial debug service — ignore it. If your bank speaks a different protocol, the BLE handshake will succeed but the parser won't find valid frames.
- **`cmd 0x14` not decoded**: the protocol doc lists this as TBD. Low priority — `cmd 0x10` + `cmd 0x11` cover everything you actually need.
- **Pack3 mismatch is normal here**: in the test bank one pack is degraded (274.4 Ah nominal vs 280 Ah). The panel's Cells view highlights the selected pack in amber if SoH < 95% — adapt to your bank's reality.

---

## Contributing

Found a different Octopus BMS firmware variant? Got a different ESP32-S3 board to work? PR welcome — please include a btsnoop capture from the Android app for any new commands, and a photo of the working panel.

For the original capture procedure used to decode `cmd 0x10` and `0x11`, see [`docs/02-the-protocol.md`](docs/02-the-protocol.md) section "How this was decoded".

---

## License

MIT — see [LICENSE](LICENSE). No warranty: lithium banks can catch fire if mistreated. This is a monitoring tool, not a battery management or safety system.
