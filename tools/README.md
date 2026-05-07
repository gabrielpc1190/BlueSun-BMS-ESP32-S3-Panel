# tools/ — Octopus BMS protocol utilities

Standalone Python scripts used to reverse-engineer the Octopus BMS protocol from BLE captures. **You don't need any of these to run the firmware** — the firmware speaks the protocol natively. These are here for documentation and for anyone who wants to support a different Octopus firmware variant.

| Script | Purpose |
|---|---|
| `octopus_bms_codec.py` | Encode + verify frames. CRC-16/MODBUS, query builder, frame validator. Use for sanity-checking your captures. |
| `decode_octopus_frame.py` | Decode a single hex frame to human-readable fields. Pass a hex string as argv. |
| `parse_btsnoop.py` | Parse Android `btsnoop_hci.log` and extract ATT-layer events (writes to `0xFFF2`, notifications from `0xFFF1`). Input is the binary HCI snoop file pulled from a Pixel/Android dev-mode capture. |
| `crack_octopus_crc.py` | Brute-force common CRC variants against captured frames. Used to identify the algorithm (CRC-16/MODBUS) on first contact with the protocol. |

## How to capture btsnoop on Android

1. Settings → About phone → tap Build number 7 times (enables Developer options).
2. Settings → System → Developer options → Enable Bluetooth HCI snoop log.
3. Toggle Bluetooth off and back on (the log starts fresh).
4. Open Octopus BMS app. Navigate every screen. Connect/disconnect a few times.
5. ADB:
   ```bash
   adb bugreport bugreport.zip
   unzip bugreport.zip
   # btsnoop is at: FS/data/log/bt/btsnoop_hci.log
   ```
   On older Android the path is `/sdcard/btsnoop_hci.log` and you can `adb pull` it directly.
6. Run `python parse_btsnoop.py btsnoop_hci.log > traffic.txt`.

The output shows every WRITE and NOTIFY in order with hex payload — enough to read the protocol manually.
