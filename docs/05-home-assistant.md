# Home Assistant integration

After the panel is flashed and connected to your WiFi, Home Assistant auto-discovers it as an ESPHome device. This page covers what you actually do with it.

---

## Discovery + initial setup

1. **Settings → Devices & Services → ESPHome.** A new "Discovered" card appears for `bluesun-bms-panel.local` (or whatever you set as `name:`).
2. Click **Configure**, paste the API encryption key from your `secrets.yaml` (the same `api_encryption_key` value).
3. Click **Submit.** HA imports the device with **86 sensors** under it.

The entity_id prefix follows your `name:` substitution. If you kept `name: "bluesun-bms-panel"`, sensors will be like `sensor.bluesun_bms_panel_bluesun_pack01_voltage`. If you renamed to `name: "panel-cuartoelectrico"`, they'll be `sensor.panel_cuartoelectrico_bluesun_*`. Pick the name once, before you flash, because changing it later orphans every entity in HA's registry.

## What sensors you get

### Per-pack — cmd 0x10 (fast, default 5 s)

| Suffix | Unit | Notes |
|---|---|---|
| `_voltage` | V | terminal voltage of pack |
| `_current` | A | + charging, − discharging |
| `_soc` | % | state of charge |
| `_soh` | % | state of health (degradation) |
| `_cycles` | — | total charge cycles since manufacture |
| `_remaining_ah` | Ah | live remaining capacity |
| `_nominal_ah` | Ah | factory nominal (e.g. 280) |

Multiplied by 4 packs = **28 sensors**.

### Per-pack — cmd 0x11 (slow, default 5 min)

| Suffix | Unit | Notes |
|---|---|---|
| `_cell_v_min` | mV | lowest cell in pack |
| `_cell_v_max` | mV | highest cell |
| `_cell_v_avg` | mV | average across 16 cells |
| `_cell_v_delta` | mV | spread = max − min. **<10 = good, >50 = bad** |
| `_cell_temp_1..4` | °C | individual cell stack temps |
| `_env_temp` | °C | environment around pack |
| `_pcb_temp` | °C | BMS PCB temperature |

10 sensors × 4 packs = **40 sensors**.

### Bank aggregates (10)

| Entity | Unit |
|---|---|
| `bank_voltage_avg` | V |
| `bank_current_total` | A |
| `bank_power` | W |
| `bank_soc_avg` | % |
| `bank_soc_spread` | % |
| `bank_remaining_ah` | Ah |
| `bank_nominal_ah` | Ah |
| `bank_max_cell_temp` | °C |
| `bank_min_soh` | % |
| `bank_max_cycles` | — |

### Energy Dashboard pair (4)

| Entity | Unit | Use |
|---|---|---|
| `bank_power_charging` | W | only positive when charging, else 0 |
| `bank_power_discharging` | W | only positive when discharging, else 0 |
| `battery_energy_in` | Wh | integrated `total_increasing` |
| `battery_energy_out` | Wh | integrated `total_increasing` |

`battery_energy_in/out` plug directly into **Settings → Dashboards → Energy → Battery storage** as the source of truth, replacing whatever your inverter reports.

### Telemetry / aux (4)

- `octopus_parses_ok` — counter incremented on each successful parse. **Use as the canary for offline alerts.**
- `octopus_notify_rx` (internal, `internal: true` so hidden from HA) — the raw notify subscription.
- `mock_*` (4 of them, internal/cosmetic) — drive LVGL labels with fallback values when bank is silent.

Plus 2 `number.template` entities for live-tuning the polling intervals: `bluesun_poll_fast_cmd_0x10` and `bluesun_poll_slow_cmd_0x11`.

Plus 1 `switch.template` entity: `panel_bms_enabled` — kill-switch that disconnects the BLE client. Use it to free the BLE slot when you want to connect the Octopus Android app.

Plus 1 `light` entity: `panel_backlight` — monochromatic light controlling the LCD backlight PWM. Useful for auto-dimming at night.

---

## Dashboard

[`examples/home_assistant_dashboard.yaml`](../examples/home_assistant_dashboard.yaml) is a complete Battery view. Copy it into a new dashboard or paste into an existing dashboard's view.

**Important:** the example uses entity prefix `panel_cuartoelectrico_bluesun_*`. After importing, **find-and-replace** with your panel's actual prefix (e.g., `bluesun_bms_panel_bluesun_*`). Most editors do this in a few seconds.

The view includes:
- Top badges: bank SoC, bank V, bank I, bank P.
- Per-pack cards: SoC + V + I + cell delta + temp + SoH.
- Cell voltage chart (mini-graph card showing all 16 cells per pack).
- Energy Dashboard charts (Wh in/out over time).
- Bank power split chart (charging vs discharging stacked).
- Spread + temp gauges.

If you don't have [`mini-graph-card`](https://github.com/kalkih/mini-graph-card) installed, you can drop those entries — the rest works with stock HA cards.

---

## Offline alert automation

[`examples/automation_offline_alert.yaml`](../examples/automation_offline_alert.yaml) is a state-trigger automation that fires when `sensor.<your_panel>_bluesun_octopus_parses_ok` goes `unavailable` for 3 minutes — that's the canary for the panel losing its BLE session OR losing WiFi entirely.

To deploy:
1. Open **Settings → Automations & Scenes → Create Automation → Edit in YAML**.
2. Paste the example.
3. Find-and-replace the entity_id and the notification target (`mobile_app_<your_phone>` or whatever you use).
4. Save.

The 3-minute filter avoids noise from short reconnect cycles (BLE flaps when the Android app briefly grabs the slot, etc.).

---

## Cached/stale fallback (optional)

Some dashboards look ugly when entities go `unavailable` (cards become "?" or disappear). The optional package [`examples/package_bluesun_cached.yaml`](../examples/package_bluesun_cached.yaml) (TODO once added) wraps the live sensors in **template trigger sensors** that retain their last known value when the source goes `unavailable`, with an additional `source_last_seen` attribute showing the timestamp.

Activate with HA's `packages:` mechanism:

```yaml
# configuration.yaml
homeassistant:
  packages: !include_dir_named packages
```

Then drop `package_bluesun_cached.yaml` into `<config>/packages/` and reload. The cached sensors appear as `_stale` suffix versions of the originals.

---

## Tuning polling

The defaults (5 s fast / 300 s slow) work for most setups. If you have:

- **Many packs and BLE bandwidth pressure** → raise both, e.g. 10 s fast / 600 s slow. The bank state still updates plenty fast.
- **Cell drift you want to track tightly** → drop slow to 60 s. Cell voltages don't change quickly, so this is overkill but harmless.
- **Panel needs to stay responsive while bank is hammered** → leave alone. The scheduler is round-robin so each pack gets airtime regardless of how full the queue is.

Adjust live in HA via the `number.bluesun_poll_fast_cmd_0x10` slider (or `number.bluesun_poll_slow_cmd_0x11` box). Values restore across reboots (`restore_value: true`).

---

## Troubleshooting

| Symptom | Diagnosis | Fix |
|---|---|---|
| All bank sensors `unavailable` for >3 min | Panel offline or BLE session dropped | Check WiFi reachability; check `octopus_parses_ok` value (last known good); flash baseline firmware to isolate |
| Sensors valid but `octopus_parses_ok` not incrementing | BLE connected but BMS not responding | Check `panel_bms_enabled` switch is `on`; check logs for `CRC mismatch` (firmware variant difference) |
| Pack-N sensors `unknown` while pack-M has data | Master not relaying to slave N | Physical issue inside the rack — slave RS485 cable / connector. Try power-cycling the affected pack |
| `cell_temp_*` reads `~272.8 °C` | Sentinel value `0x0AAB` not being filtered | Update firmware (current version handles this); fault otherwise |
| Octopus Android app can't connect | Panel holds the BLE slot | Toggle `switch.<panel>_panel_bms_enabled` off, use the app, toggle back on |
| Energy Dashboard shows zero | Wrong sensor selected | Pick `battery_energy_in` / `battery_energy_out` (with `_real_energy` suffix on Shelly-style 1-phase ×2 setups, but not relevant here — these are already integrated correctly) |

---

## Limits + roadmap

Things this firmware does **not** currently do:

- **No write-back configuration of the BMS.** Read-only on purpose. Changing pack params (charge limits, balance threshold, etc.) goes through the Android Octopus app.
- **No `cmd 0x14` decoded.** Some app screens trigger this; we never reverse-engineered what it returns. Open an issue with a btsnoop capture if you have one.
- **No multi-bank support.** One `ble_client` per firmware. If you have two BlueSun racks side by side, flash two panels.
- **No firmware-side OTA reconfig of MAC.** The MAC is baked in via `!secret bms_master_mac`. Change requires reflash. Live `number.template` reconfig is technically possible but adds complexity for a one-time setting.

PRs welcome.
