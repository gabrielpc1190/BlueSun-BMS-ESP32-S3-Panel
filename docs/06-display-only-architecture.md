# Display-only architecture (v2) — the panel as a thin client

This repo started as a **BLE proxy**: the ESP32-S3 panel connected to the BlueSun pack
over Bluetooth, spoke the Octopus protocol natively, published 86 sensors to Home
Assistant, and rendered them. That design is documented in [`03-the-firmware.md`](03-the-firmware.md)
and lives in [`firmware/bluesun-bms-panel.yaml`](../firmware/bluesun-bms-panel.yaml).

In production we moved to a second design — **display-only** — and that is what the
physical panel runs today: [`firmware/panel-display-only-v2.yaml`](../firmware/panel-display-only-v2.yaml).
This doc explains why, how data flows, and how the two firmwares relate.

## Why move off BLE on the panel

The Octopus BMS master accepts **exactly one** BLE central at a time (see the warning in
[`04-lessons-learned.md`](04-lessons-learned.md) and the kill-switch note in the README).
If the panel holds that single BLE slot, nothing else can — not the phone app, and not any
other integration that wants the bank's data. As the off-grid system grew, it made more
sense to give the single BLE link to **one owner** and let everything else (including the
panel) read the data downstream from Home Assistant.

So the BLE reader was moved **off the panel** and onto an always-on Orange Pi. The panel
became a pure renderer.

## Data flow

```
   BlueSun pack (Octopus BLE, single central)
            │  BLE
            ▼
   Orange Pi daemon  ──MQTT discovery──►  Home Assistant
   (reads the BMS,                         (sensor.bluesun_*)
    owns the BLE link)                            │
                                                  │  ESPHome native API
                                                  ▼
                                       ESP32-S3 panel (this firmware)
                                       homeassistant-platform sensors
                                                  │
                                                  ▼
                                       LVGL views (Bank / Packs / Cells)
```

- A daemon on an always-on Orange Pi owns the BLE connection to the pack, decodes the
  Octopus frames, and publishes the per-pack and bank values to Home Assistant as
  `sensor.bluesun_*` entities (via MQTT discovery).
- The panel firmware declares those entities with ESPHome's
  [`homeassistant` sensor platform](https://esphome.io/components/sensor/homeassistant.html).
  Each `sensor.bluesun_*` becomes a local `id` (`pack01_current`, `bank_power`, …) with the
  **same id names** the BLE-proxy firmware used internally — so the LVGL layer is almost
  unchanged between the two firmwares.
- The panel does **no** BLE, no Octopus parsing, no CRC. It only subscribes and renders.

## Two firmwares, one UI

| | `bluesun-bms-panel.yaml` (v1, BLE proxy) | `panel-display-only-v2.yaml` (deployed) |
|---|---|---|
| BLE / Octopus parser | yes (`ble_client`, custom parser) | **no** |
| Data source | reads the pack directly | `homeassistant` platform (HA entities) |
| Publishes to HA | yes (it is the source of the 86 sensors) | no (it is a consumer) |
| Owns the single BLE slot | yes | no — the Orange Pi does |
| LVGL views | Bank / Packs / Cells | Bank / Packs / Cells (same) |
| Use it when | the panel is your only/primary BMS reader | something else (Orange Pi) already owns BLE |

Internal sensor ids are intentionally identical (`pack0X_current`, `pack0X_voltage`,
`pack0X_soc`, `pack0X_remaining_ah`, `bank_current_total`, `bank_power`, `bank_remaining_ah`,
…). That parity is what lets the LVGL views and most lambdas port between the two with
little change.

## Entity contract (what the panel subscribes to)

The display-only firmware expects these Home Assistant entities to exist (default prefix
`sensor.bluesun_`):

- **Bank:** `bank_soc_avg`, `bank_voltage_avg`, `bank_current_total`, `bank_power`,
  `bank_soc_spread`, `bank_remaining_ah`, `bank_nominal_ah`, `bank_min_soh`,
  `bank_max_cycles`, `bank_max_cell_temp`.
- **Per pack (×4):** `pack0X_voltage`, `pack0X_current`, `pack0X_soc`, `pack0X_soh`,
  `pack0X_cycles`, `pack0X_remaining_ah`, `pack0X_nominal_ah`, plus the cell aggregates
  (`pack0X_cell_v_min/max/avg/delta`, `pack0X_cell_temp_1..4`, `pack0X_env_temp`,
  `pack0X_pcb_temp`).

If HA or the Orange Pi goes down, those entities go `unavailable`; the LVGL lambdas are
defensive and render `--` instead of `NaN`.

**Current sign convention:** `+ = charging, − = discharging` — this matches the Octopus
protocol ([`02-the-protocol.md`](02-the-protocol.md), cmd 0x10 offset 2). Because the
display-only panel gets current from HA (not from the raw BLE frame), confirm the sign is
preserved end-to-end through the Orange Pi → MQTT → HA path. It is centralized in the
firmware as a single commented comparison (`// signo: + = carga`) so flipping it, if a
future data source inverts it, is a one-line change.

## Charge / discharge + power indicator (2026-06-02)

The deployed firmware adds an at-a-glance charge/discharge indicator, driven entirely from
the HA-fed sensors:

- **Home, per pack:** a second line under each pack bar showing signed current and power
  (`+12A +638W` / `-8A -425W` / `0A 0W`), colored green (charging) / orange (discharging) /
  grey (idle). Power is computed locally as `V × I` from the subscribed per-pack voltage and
  current (HA does not expose per-pack power).
- **Home, bank status:** the top-left badge shows `CARGANDO` / `DESCARGANDO` / `REPOSO`, and
  a line under the big SoC shows net `kW`, estimated time-to-full / time-to-empty, and
  available `kWh` (`Σ remaining_Ah × V`).
- **Packs detail cards:** each pack's current line also shows watts and is colored by
  direction.

Design notes for this feature live in
[`superpowers/specs/2026-06-02-indicador-carga-descarga-design.md`](superpowers/specs/2026-06-02-indicador-carga-descarga-design.md).
(That spec was written against the v1 BLE-proxy file; the same change was ported to the
display-only firmware for deployment.)

## Build / flash

Same ESPHome workflow as the rest of the project (see the README and root project notes),
pointed at the display-only file:

```bash
esphome config firmware/panel-display-only-v2.yaml          # validate
esphome run    firmware/panel-display-only-v2.yaml --device <panel-ip> --no-logs   # OTA
```

You need a `secrets.yaml` next to the firmware with the keys listed in
[`secrets.yaml.example`](../firmware/secrets.yaml.example). The panel uses a reserved static
IP (`manual_ip`) — set `panel_static_ip` / `panel_gateway` to your network.
