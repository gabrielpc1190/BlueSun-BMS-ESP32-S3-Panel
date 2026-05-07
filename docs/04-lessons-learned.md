# Lessons learned

Two non-obvious bugs that cost a week to figure out, and that you will hit if you write your own firmware from scratch. Read this before opening any issue.

---

## Lesson 1 — On ESP32-S3 in 2026, defaults > overrides for BLE central

### The symptom

You write a firmware with `ble_client` connecting to a peer. Logs say:

```
[I][esp32_ble_client]: 0x01 Connecting
... 20 seconds pass ...
[E][esp32_ble_client]: ESP_GATTC_OPEN_EVT in DISCONNECTING state (status=133)
[W][esp32_ble_client]: Connection open error, status=133
```

Every connect attempt times out at exactly **20 seconds**. The peer is right next to the ESP (RSSI -76 dBm). The peer is reachable from a phone running the same protocol. The same firmware on an ESP32-C3 single-core works.

You search online and find:
- [esphome/issues#6701](https://github.com/esphome/issues/issues/6701) — "DISCONNECTING is a terminal state in FSM"
- [esphome/esphome#13443](https://github.com/esphome/esphome/issues/13443) — "IDF 5.5.2 BLE handshake regression"
- Espressif's [ESP32-S3 RF Coexistence guide](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/coexist.html) recommending core pinning for WiFi/BLE coex

You apply the recommended fixes:

```yaml
# DO NOT DO THIS in 2026 with ESPHome 2026.4.4 + IDF 5.5.4:
esp32:
  framework:
    version: "5.5.1"          # downgrade IDF
    sdkconfig_options:
      CONFIG_BT_CTRL_PINNED_TO_CORE_CHOICE_1: y
      CONFIG_BT_BLUEDROID_PINNED_TO_CORE_CHOICE_1: y
      CONFIG_ESP_WIFI_TASK_CORE_ID_0: y
      CONFIG_ESP_COEX_SW_COEXIST_ENABLE: y
ble_client:
  - id: master
    auto_connect: false
esp32_ble_tracker:
  scan_parameters:
    interval: 1100ms
    window: 1100ms     # window == interval
    continuous: false
on_boot:
  - esp32_ble_tracker.stop_scan
  - delay: 2s
  - ble_client.connect: master
```

**It still doesn't work.** Same status=133, same 20-second timeout.

### What's actually wrong

Every one of those "fixes" was correct doctrine **for IDF 5.0 / 5.1**, where ESP32-S3 dual-core BLE/WiFi coexistence really did need manual core pinning. In **IDF 5.5.4** (which ESPHome 2026.4.4 ships by default), the scheduler handles coexistence correctly without help, and the manual pinning **deadlocks** the LL controller against the Bluedroid host. The Link-Layer `CONNECT_REQ` goes out, but the GATT callback never reaches the host because the scheduler can't balance the work properly.

The 20-second timeout is `BTM_LINK_CONNECT_TOUT` — Bluedroid giving up.

### The fix

Remove every override. The minimal working config:

```yaml
esp32:
  board: esp32-s3-devkitc-1
  flash_size: 16MB
  framework:
    type: esp-idf
  # NOTHING ELSE.

esp32_ble:                # max_connections: 3 (default)
esp32_ble_tracker:        # scan params default: 320ms / 30ms / continuous true / active
ble_client:
  - id: master
    mac_address: !secret bms_master_mac
    # auto_connect: true (default) — let it manage the lifecycle
```

That's it. `State: ESTABLISHED` in <4 seconds from boot. RSSI -76 to -82 dBm stable.

Test it with [`firmware/bluesun-bms-baseline.yaml`](../firmware/bluesun-bms-baseline.yaml) on a fresh board before adding LVGL or sensors. If the baseline works and the production firmware doesn't, **the production firmware introduced something it shouldn't have**. Bisect.

### When to deviate

If you genuinely need WiFi + multiple BLE peers + bluetooth_proxy + heavy GATT traffic on the same board, you might need fine tuning. In that case start from defaults, add overrides one at a time, measure each.

The wrong way: copy a sdkconfig block from a 2-year-old StackOverflow answer. The right way: defaults until measured failure, then targeted fixes.

---

## Lesson 2 — ESPHome releases `services_` after `all_nodes_established_()`

### The symptom

You have `ble_client` connected. You have a `sensor: platform: ble_client` subscribing to a notify char — that part works fine. Now you want to **write** to a char from a script:

```yaml
script:
  - id: query_pack
    then:
      - lambda: |-
          if (!id(master).connected()) return;
          auto chr = id(master).get_characteristic(
              esp32_ble_tracker::ESPBTUUID::from_uint16(0xFFF0),
              esp32_ble_tracker::ESPBTUUID::from_uint16(0xFFF2));
          if (!chr) {
            ESP_LOGW("octopus", "char FFF2 not found");
            return;
          }
          chr->write_value(query_bytes, 8, ESP_GATT_WRITE_TYPE_NO_RSP);
```

The log spams `char FFF2 not found` every 500 ms forever, even though `Service discovery complete` fired and you can see the notify sensor receiving data on `FFF1` (same service!). You add diagnostic logging:

```cpp
auto svc1800 = id(master).get_service(0x1800);  // Generic Access — present on every BLE device
ESP_LOGI("dbg", "service 0x1800: %s", svc1800 ? "FOUND" : "null");
// prints "null"
```

Even `0x1800` returns null. The services list is **empty** even though the connection is alive and notifications are flowing.

### What's actually happening

ESPHome's `BLEClient::gattc_event_handler` does this after every event:

```cpp
// components/ble_client/ble_client.cpp
if (!this->services_.empty() && this->all_nodes_established_()) {
  this->release_services();        // ← deletes every BLEService* and clears services_
  ESP_LOGD(TAG, "All clients established, services released");
}
```

It's a memory optimization. As soon as every registered child node (`ble_sensor`, `ble_text_sensor`, `ble_switch`, `ble_client.ble_write` action, `ble_client.ble_connect/disconnect` actions) has captured what it needs from the GATT discovery, the service tree is freed. Any later `get_service()` / `get_characteristic()` call returns null because the list is gone.

This is reasonable behavior — services_ holds dynamically-allocated `BLEService*` entries for every service on the peer (often 5-10), and the heap savings on small ESPs add up. The trap is that the API surface looks like services_ persists for the connection's lifetime.

### The fix

**Don't use `id(master).get_characteristic()` from scripts.** Use the `ble_client.ble_write` action:

```yaml
- ble_client.ble_write:
    id: master
    service_uuid: FFF0
    characteristic_uuid: FFF2
    value: !lambda |-
      // build your byte vector here based on globals/state
      return std::vector<uint8_t>{ 0x01, 0x04, 0x10, 0x00, 0x00, 0x12, 0x74, 0xc7 };
```

`BLEClientWriteAction` registers itself as a `BLEClientNode` in its constructor (`ble_client->register_ble_node(this)`). When `SEARCH_CMPL_EVT` fires, it grabs `chr->handle` (a 16-bit integer) and stores it in `this->char_handle_`. The handle survives `release_services()` because it's just a number — no pointer, no allocation. The next write goes through `esp_ble_gattc_write_char(handle)` directly.

The action automatically picks the right write type by reading `chr->properties`:
- `ESP_GATT_CHAR_PROP_BIT_WRITE` → `ESP_GATT_WRITE_TYPE_RSP` (write with ACK)
- `ESP_GATT_CHAR_PROP_BIT_WRITE_NR` → `ESP_GATT_WRITE_TYPE_NO_RSP` (write without ACK)

So you don't even need to think about the write type. The Octopus BMS exposes `FFF2` as `WRITE_NR` only, and the action picks the right one.

### Templated values + dynamic dispatch

The `value:` field is templatable — you can return a different byte sequence per call based on globals or state. This is how the scheduler in this firmware emits queries to packs 1..4 with two different commands using a single `ble_write` action:

```yaml
- ble_client.ble_write:
    id: master
    service_uuid: FFF0
    characteristic_uuid: FFF2
    value: !lambda |-
      static const uint8_t QUERIES[2][4][8] = {
        { /* cmd 0x10 for packs 1..4 */ },
        { /* cmd 0x11 for packs 1..4 */ },
      };
      uint8_t p = id(current_pack);     // updated every tick by the scheduler
      uint8_t c = id(current_cmd_idx);
      if (p < 1 || p > 4 || c > 1) return std::vector<uint8_t>{};
      return std::vector<uint8_t>(QUERIES[c][p-1], QUERIES[c][p-1] + 8);
```

### How to verify your version is affected

Add this diagnostic to any script after a confirmed `Service discovery complete`:

```yaml
- lambda: |-
    if (!id(master).connected()) return;
    static bool dumped = false;
    if (!dumped) {
      dumped = true;
      const uint16_t test[] = {0x1800, 0x1801, 0x180A};  // standard, present on all BLE devices
      for (auto u : test) {
        auto s = id(master).get_service(u);
        ESP_LOGI("dbg", "service 0x%04X -> %s", u, s ? "FOUND" : "null");
      }
    }
```

If all three return `null`, your build releases services. Migrate to `ble_client.ble_write`.

If you have a `ble_client` with **no** child nodes registered (no sensor / switch / text_sensor / action), `all_nodes_established_()` short-circuits to true with `nodes_.empty()`, and the release fires immediately. So even a "minimal repro firmware" with just a `ble_client` + a script will show this.

This applies at least to ESPHome 2024.x through 2026.4.4. The behavior may have been there longer — the comment in the code suggests it's intentional and predates current maintainers.

---

## TL;DR

1. **No tuning unless you measured a problem.** ESPHome + IDF 5.5.4 defaults are correct for ESP32-S3 BLE central. Stripped baseline first, add features after.
2. **Use the action, not the lambda.** `ble_client.ble_write` survives `release_services()`. Hand-rolled `get_characteristic()` from scripts does not.
