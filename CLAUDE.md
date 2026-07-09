---
type: project
title: bluesun-bms-esp32s3-panel
description: "Firmware ESPHome (ESP32-S3) para panel táctil de monitoreo del banco de baterías BlueSun (protocolo Octopus BMS), integrado a Home Assistant."
production: false
status: active
stack: [esphome, esp32]
repo: "git@github.com:gabrielpc1190/BlueSun-BMS-ESP32-S3-Panel.git"
---

# CLAUDE.md — bluesun-bms-esp32s3-panel

Firmware ESPHome para panel táctil ESP32-S3 que muestra el banco de baterías BlueSun (protocolo Octopus BMS) en pantalla, con integración a Home Assistant.

**Dos variantes de firmware** (misma UI LVGL):
- `firmware/bluesun-bms-panel.yaml` — **BLE proxy**: el panel lee el BMS por Bluetooth y publica 86 sensores a HA. Es la versión original/de referencia.
- `firmware/panel-display-only-v2.yaml` — **display-only**: el panel es thin-client, consume las entidades `sensor.bluesun_*` que publica un daemon en la **Orange Pi** (host `gadi-inverter-bridge`) vía MQTT→HA. **Esta es la que corre en el panel físico de producción** (172.16.9.74, nodo `panel-s3-step5-ui`, builds en `esphome-vm:/root/esphome/casa-gadi/panel-s3-display-only-v2-hafed.yaml`). Arquitectura: `docs/06-display-only-architecture.md`.

`README.md` es la fuente principal y es muy completo. Este CLAUDE.md solo añade lo que un Claude necesita y no está en el README.

## Identidad

- **Hardware:** Sunton ESP32-4848S040C (4″ 480×480 IPS, ST7701S RGB-565, GT911 touch, ESP32-S3R8, 16 MB flash / 8 MB octal PSRAM, CH340C). El pinout del firmware está fijo a esta board.
- **Banco:** 4 packs BlueSun LiFePO4 16s 280 Ah (~57 kWh nominal). Pack 01 = master BLE; el resto relayed por RS485 interno del banco.
- **Output a HA:** 86 sensores con prefijo configurable. Default en YAML: `panel_cuartoelectrico_bluesun_*`.
- **Repo GitHub:** no creado aún (proyecto local). Pushear cuando se decida (ver TODO en handoff 2026-05-21).

## Reglas críticas

- **Single-central BLE.** El pack master acepta UNA sola conexión BLE a la vez. Si la app Octopus BMS Android se conecta, el panel pierde datos. Hay un kill-switch HA: `switch.<panel>_panel_bms_enabled`. Si planeas usar la app, apaga ese switch primero.
- **No tocar el pinout en `firmware/bluesun-bms-panel.yaml`** salvo que vayas a usar otra board distinta a la Sunton 4848S040C (entonces es proyecto nuevo).
- **Compatibilidad de entity_id con HA:** los 86 sensores se llaman `sensor.<prefix>_bluesun_*`. Cambiar el prefix obliga a rehacer dashboards y automations consumidoras. Tratar el naming scheme como contrato.
- **04-lessons-learned es READING REQUIRED** antes de cambiar la sección BLE o de scripts: `docs/04-lessons-learned.md` documenta 2 bugs no obvios que costaron una semana (defaults BLE ESP32-S3 vencen overrides; ESPHome libera `services_` después de `all_nodes_established_()` haciendo que `get_characteristic()` desde scripts devuelva null).

## Mapa del repo

| Path | Rol |
|---|---|
| `firmware/bluesun-bms-panel.yaml` | Variante **BLE-proxy** (display, BLE, Octopus parser, LVGL views, sensores). No es la desplegada. |
| `firmware/panel-display-only-v2.yaml` | Variante **display-only** desplegada en producción (versión sanitizada; el archivo con secrets reales vive en `esphome-vm`). Datos desde HA, sin BLE. |
| `docs/06-display-only-architecture.md` | Arquitectura display-only: data flow OPi→MQTT→HA→panel, contrato de entidades, relación con la v1 |
| `firmware/secrets.yaml.example` | Template — copiar a `secrets.yaml` con wifi/api_key/ota_pwd/bms_master_mac |
| `examples/home_assistant_dashboard.yaml` | Dashboard HA de ejemplo (find-and-replace del prefix) |
| `docs/01-the-problem.md` | Por qué BlueSun no se ve por defecto en HA |
| `docs/02-the-protocol.md` | Octopus BMS BLE: service `0xFFF0`, CRC-16/MODBUS, comandos `0x10`/`0x11` |
| `docs/03-the-firmware.md` | Arquitectura: BLE proxy + LVGL 3 views + scheduler + 86 sensors |
| `docs/04-lessons-learned.md` | **READING REQUIRED** — 2 bugs no obvios |
| `docs/05-home-assistant.md` | Integración HA: dashboard, alertas offline, paquete fallback |
| `tools/` | Utilidades del proyecto |

## Workflow de cambio típico

Builds desde DevClaude vía el host `esphome-vm` (172.16.10.21) que tiene el dashboard ESPHome.

```bash
# Compile + flash inicial (USB-C al panel)
esphome run firmware/bluesun-bms-panel.yaml --device /dev/ttyUSB0

# OTA después de la primera flash
esphome run firmware/bluesun-bms-panel.yaml --device <ip-del-panel>
```

- Primera compilación: ~5-7 min (ESP-IDF + LVGL + Bluedroid).
- OTA: ~6 segundos.
- Verificar logs: debe aparecer `[I][esp32_ble_client]: Connection open` y `[I][octopus]: pack=1 U=...` en ~5 s.

## Gotchas

- **`auto_connect: true` con default scan params es el modo correcto.** No pinear cores, no pinear IDF version — eso es lo que las "lessons learned" advierten. Si el `services_` se libera, `get_characteristic()` desde un script ESPHome devuelve null silenciosamente.
- **El panel es always-on** (USB-C 5V externo). No usar la batería del banco para alimentarlo — es una fuente independiente.
- **`ignore_strapping_warning` en I2C touch es intencional** (GPIO45). No borrarlo o ESPHome rechaza compile.

## Referencias

- Sister project: `gair-ac-esp32c3/` (mismo enfoque ESPHome para A/Cs Gair vía IR).
- Hardware del banco: ver memoria de HomeAssistant sobre BlueSun (57 kWh, 4 packs, pack 3 degradado a 274.4 Ah).
- Convenciones globales: [/mnt/NAS/CLAUDE.md](../CLAUDE.md).
- Hosts y red: [/mnt/NAS/INFRA.md](../INFRA.md).
