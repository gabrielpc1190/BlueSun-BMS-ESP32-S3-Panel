# The problem

You bought a BlueSun lithium rack — 4 packs, 16s LiFePO4, 280 Ah each, ~57 kWh real. Your inverter wakes up, the bank charges and discharges happily, your house runs off-grid. Everything works.

Now try to read the bank from Home Assistant. You can't.

## What Home Assistant sees out of the box

Whatever your **inverter** chooses to publish:
- A single `battery_soc` value, derived from a coulomb counter that drifts.
- Maybe `battery_voltage` and `battery_current` if you're lucky.
- No per-pack data. No cell voltages. No cell temperatures. No SoH. No cycle counts.

That's enough to know the bank is roughly half-full, but it's not enough to:
- Catch a single weak pack dragging the bank down.
- See cell drift before it becomes pack drift.
- Track SoH degradation over months.
- Build an Energy Dashboard with accurate Wh in/out integrated from the BMS itself, not the inverter's estimate.
- Know the actual remaining Ah for autonomy planning that doesn't depend on the inverter being honest about coulomb counting.

## What the BMS actually exposes

Each BlueSun pack has an internal **Octopus BMS** — a tiny board glued onto the cell stack with a Bluetooth Low Energy radio. Open the **Octopus BMS** app (Android, free) and you see everything:

- Per-pack: voltage, current, SoC, SoH, cycles, remaining Ah, nominal Ah.
- Per-cell (16 cells per pack): individual voltage, min / max / average / delta.
- Temperatures: 4 cell temps, environment, PCB.
- Configuration: charge / discharge limits, over/under thresholds, balance settings.

So the data is there. It's just trapped behind:

1. **Bluetooth, not WiFi.** Home Assistant can talk Bluetooth via a BLE proxy or USB dongle, but you still need someone who speaks **Octopus BMS protocol** on the other side.
2. **One central at a time.** BLE allows a single concurrent client. While the Android app is connected, no one else can read. While your laptop is connected, the Android app can't.
3. **The protocol is undocumented.** Octopus does not publish it. There is no public ESPHome component for it. Any integration is reverse-engineered from BLE captures.
4. **The "obvious" service UUID is a decoy.** The BMS advertises a 128-bit UUID `02f00000-…-fe00` that looks vendor-specific. The real channel is the SIG-style `0xFFF0` with chars `FFF1` (notify) and `FFF2` (write). Your first attempt will probably target the 128-bit one and silently get nothing.

## The single-central problem in practice

You'd think a Bluetooth proxy in HA solves this. It does not, cleanly:
- A passive BLE scanner sees the advertisement, sniffs the device name, and that's it — Octopus does not publish data in the advertisement.
- An active BLE scanner can read static descriptors, but nothing the BMS sends as **GATT notifications** (which is where all the live data is).
- An active **BLE central** can subscribe to notifications, but then your Android app stops working until you disconnect the central.

You need a dedicated BLE central. That central needs to:
- Live close enough to the master pack (RSSI better than ~-85 dBm for stable connection).
- Speak the Octopus protocol (CRC-16/MODBUS framed queries to char `FFF2`, parse notifications back from `FFF1`).
- Do this 24/7 without you babysitting it.
- Be cheap enough that you can replace it if it fails.
- Optionally: have a screen so you can see the bank from the rack itself, no phone required.

That's exactly what the **Sunton 4848S040C ESP32-S3 panel** does in this repo. Continue with [`02-the-protocol.md`](02-the-protocol.md) for the protocol decode, or [`03-the-firmware.md`](03-the-firmware.md) for the implementation.
