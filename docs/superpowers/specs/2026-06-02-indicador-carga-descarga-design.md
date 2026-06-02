# Indicador de carga/descarga + potencia por pack — diseño

**Fecha:** 2026-06-02
**Panel:** Casa GADI (ESP32-S3, `firmware/bluesun-bms-panel.yaml`)
**Estado:** implementado en YAML, pendiente de validar con `esphome config` en esphome-vm y flashear por OTA.

## Objetivo

De un vistazo, saber qué packs están cargando o descargando y cuánta potencia mueven, más el estado global del banco.

## Decisiones (brainstorm con compañía visual)

1. **Por pack en el home** — segunda línea bajo cada barra con corriente y potencia con signo, coloreada por dirección. Formato `+12A +638W` (carga, verde) / `-8A -425W` (descarga, naranja) / `0A 0W` (reposo, gris). *(Variante "B" del mockup de Watts.)*
2. **Tarjeta de detalle (packs_page)** — se agrega Watts (`lbl_pX_w`) junto a los Amps; `lbl_pX_soh` se movió a x:110 para no encimar.
3. **Badge de estado del banco** (arriba-izq, `lbl_mode_badge`, antes vacío) — `CARGANDO` / `DESCARGANDO` / `REPOSO`, coloreado por dirección.
4. **Línea derivada bajo el SoC** (`lbl_bank_info`) — `kW  ·  tiempo a lleno/vacio  ·  kWh disponibles`. *(Variante "B" del mockup de layout: una sola línea compacta.)*

## Convención de signo

`+ = carga, − = descarga`, deadband `|I| < 0.5 A = reposo`. Confirmado por el protocolo
(`docs/02-the-protocol.md`, cmd 0x10 offset 2: *"+ = charging, − = discharging"*) — **no requiere
verificación en hardware**. Colores: carga `0x43A047`, descarga `0xFF7043`, reposo `0x6E7B82`.
La comparación está centralizada/comentada (`// signo: + = carga`); para invertir basta editar ese punto.

## Datos / sensores

- **Nuevos expuestos a HA:** `pack01_power..pack04_power` (V×I, W). Additive, no rompe el contrato de naming.
- **Reutilizados (ya existían):** `bank_current_total`, `bank_power`, `bank_voltage_avg`,
  `bank_remaining_ah`, `bank_nominal_ah` (todos suman/promedian los 4 packs).
- **Derivados en lambda (no son sensores):**
  - autonomía carga = `(bank_nominal_ah − bank_remaining_ah) / I`, solo si `0 < h < 100`.
  - autonomía descarga = `bank_remaining_ah / |I|`, solo si `0 < h < 100`.
  - energía disponible = `bank_remaining_ah × bank_voltage_avg / 1000` kWh.

## Restricciones de UI

- Fuente nueva `font_xs` (Montserrat 14px, glifos `0123456789+-. AW%`) para la 2ª línea por pack.
- Texto **ASCII-safe** (sin acentos ni `·`/`≈`) en `font_sm`/`font_xs` para no redefinir glifos.
- Refresco: badge + línea derivada cuelgan del `on_value` de `mock_bank_p` (cada 5 s); la línea
  por pack del `on_value` de cada `pack0X_current`.

## Riesgos conocidos

- **Ancho del home por pack:** corrientes/potencias muy grandes (`-120A -6400W`) podrían apretar
  los ~90px a 14px. Para valores típicos por pack cabe. Fallback: quitar el espacio o la "W".
- **`esphome config` no corrido aquí** (binario ausente en el NAS); validado solo con parser YAML.
  Correr en esphome-vm antes de flashear.

## Pendiente

- [ ] `esphome config firmware/bluesun-bms-panel.yaml` en esphome-vm.
- [ ] Flash OTA al panel (.138.17) y verificar en logs `[octopus] pack=N ... I=...` y en pantalla.
- [ ] Confirmar que no desborda el ancho con corrientes reales del banco.
- [ ] Commit tras revisión de Gabriel (toca producción).
