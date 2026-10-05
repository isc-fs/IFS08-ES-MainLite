# MainLite pin model

`model/mainlite.pins.yaml` (and its JSON twin `model/mainlite.pins.json`, same content) lists **every one of the 144 pins** of the MainLite's STM32H733ZGTx (U5): what net it is on, whether it leaves the module through the backplane headers J3/J4, what is connected to it on the board, and which alternate function the net implies. It also describes the module-level interfaces (CAN, SDMMC, I2C, HSE, VBAT, SWD, USB) and the power rails.

It is **generated** from the KiCad schematic by `tools/gen_pins.py`; never edit it by hand. CI fails any pull request whose committed model does not match the schematic.

## Regenerating

You need either KiCad 9 (or 10) installed locally, or Docker.

```bash
# Local KiCad (kicad-cli on PATH, or the macOS app in /Applications/KiCad)
python3 tools/gen_pins.py

# Exactly what CI does (pinned kicad/kicad:9.0.9 image)
tools/kicad_export.sh
python3 tools/gen_pins.py --netlist build/netlist.xml

# Check without writing (what CI runs)
python3 tools/gen_pins.py --netlist build/netlist.xml --check

# Tests
python3 -m unittest discover -s tests -v
```

`tools/gen_pins.py` uses only the Python standard library. KiCad 9 and 10 give the same model. When the schematic changes, run the generator and commit `model/` in the same pull request.

## Versioning and fetching

* `schema_version` (integer) changes only when a key is renamed or removed, or its meaning changes. New keys can appear without a bump, so consumers must ignore keys they don't know.
* Every push to `main` re-checks the model. If its content changed since the last release, the workflow publishes a GitHub release tagged **`pin-model-v<schema_version>.<n>`** (`pin-model-v1.0`, `pin-model-v1.1`, …) with `mainlite.pins.yaml`, `mainlite.pins.json` and `SHA256SUMS`.
* Pin a tag in consumers:

  ```
  https://github.com/isc-fs/IFS08-ES-MainLite/releases/download/pin-model-v1.0/mainlite.pins.yaml
  ```

  Every CI run also uploads the model as a workflow artifact (`pin-model-<sha>`), so a model from a branch can be tested before release.

## Format

All strings are double-quoted; the YAML is plain block style and loads with `yaml.safe_load`. Key order is stable.

### Header

| Key | Meaning |
| :--- | :--- |
| `schema` | Always `isc-fs/mainlite-pins`. |
| `schema_version` | Integer, see above. |
| `board.backplane_connectors` | `["J3", "J4"]`: the headers a backplane mates with. |
| `source.schematic` | Path of the schematic in this repo. |
| `source.schematic_git_blob` | Git blob SHA of the schematic (`git hash-object`). This is a content hash, not a commit SHA, so it survives rebases and squash merges. `git log --find-object=<sha>` finds the commits that contain it. |
| `source.kicad` | `file_format` and `generator_version` read from the schematic header. |
| `source.pin_data` | Vendored ST pin data (`tools/data/`) and the upstream commit it came from. |
| `mcu` | `ref` (U5), `part`, `package`, KiCad `symbol` and `footprint`. |

### `pins[]`: one entry per package pin, ordered by `number`

| Key | Type | Meaning |
| :--- | :--- | :--- |
| `number` | int | Package pin (LQFP-144, 1–144). |
| `name` | str | ST pin name, e.g. `PB4(NJTRST)`, `PH0-OSC_IN`, `VDD`, `PDR_ON`. |
| `port` | str/null | GPIO port as firmware names it (`PB4`, `PC2_C`); `null` for non-GPIO pins. **Use this as the key when matching firmware pins.** |
| `type` | str | `io`, `power`, `ground`, `vcap`, `vref`, `reset`, `boot`, `config` (PDR_ON). |
| `class` | str | Where the pin goes, see below. |
| `net` | str/null | KiCad net name; `null` when unconnected. |
| `net_auto` | bool | `true` when the net has no label and KiCad named it automatically (`Net-(U5-PH0)`). Such names are not stable, so don't key on them. |
| `no_connect_flag` | bool | The pin has an explicit no-connect flag in the schematic. Unconnected pins without one were simply left unwired. |
| `role` | str/null | Alternate function implied by the net, as an ST signal name valid on this pin: `FDCAN1_RX`, `I2C2_SDA`, `SDMMC1_D0`, `USB_OTG_HS_DP`, `DEBUG_JTMS-SWDIO`, `RCC_OSC_IN`, … `null` for plain GPIO nets (`GPIO1`, `OK_STATUS`, `NRF24_CS`) and unconnected pins. |
| `role_source` | str/null | How `role` was found: `net` (the pin's own net name), `series_net` (the net beyond a series resistor, e.g. SWD), `crystal` (pin wired to a crystal). |
| `backplane` | list | `{connector, pin, net}` for each J3/J4 pin this MCU pin reaches (directly or through a series resistor). |
| `external` | list | `{connector, kind, pin, pin_name, net}` for other connectors reached: `microsd` (J1), `swd` (J2), `usb_c` (J5). |
| `series` | list | Series resistors (≤ 100 Ω) crossed to get there: `{ref, value, net}`. |
| `pulls` | list | Resistors from the pin's net to a rail: `{ref, value, direction: up/down, to}`. |
| `on_board` | list | Every other part on the pin's net (and beyond series resistors), except connectors and series resistors: `{ref, pin, pin_name, part, value}`. Empty for rail pins. |

`class` values:

| `class` | Meaning |
| :--- | :--- |
| `backplane` | I/O routed to J3/J4: available to the backplane. |
| `onboard` | I/O used on the module only (CAN transceiver, IMU, microSD, USB, SWD, LEDs, crystal). |
| `nc` | Not connected (I/O, or rail pins left open such as VBAT and PDR_ON). |
| `power` | Supply, VCAP, VREF+ and PDR_ON when connected. |
| `ground` | VSS/VSSA. |
| `system` | NRST, BOOT0. |

### `summary`

`total_pins`, `by_class` (all 144 pins), `io_pins` and `io_by_class` (the GPIO-capable pins only: `backplane` / `onboard` / `nc`), `backplane_connector_pins` (36).

### `connectors.J3` / `connectors.J4`

The full pinout of each backplane header, pin by pin, including pins that are not MCU pins:

```yaml
- pin: 6
  net: "GPIO1"
  kind: "mcu"          # mcu | power | ground | nc | other
  mcu_pin: 134
  mcu_port: "PB4"
- pin: 4
  net: "CANH1"
  kind: "other"        # not an MCU pin: CAN bus lines after the transceiver
  on_board: ["R1.1", "U2.7"]
```

### `power_rails[]`

One entry per power/ground net: `net`, `kind`, `mcu_pins`, `backplane` header pins, other `connectors` pins, and `regulators` (regulator outputs driving the rail).

### `interfaces`

| Key | Contents |
| :--- | :--- |
| `can[]` | Per channel: `channel` (CAN1..3, from the net names), `fdcan` instance, `transceiver` (`ref`, `part`, `unconnected_pins`), `tx`/`rx` MCU pins, `canh`/`canl` header pins, `termination` (`ref`, `value`, `ohms`, `switchable: false`; all three are fixed 120 Ω on this board). |
| `sdmmc[]` | `instance`, `bus_width`, `connector`, `signals` (`CK`, `CMD`, `D0..D3` with MCU pin, series resistor, pulls and card pin) and `card_detect` (pin + pull-up). |
| `i2c[]` | `instance`, `scl`/`sda`, `pullups`, `external_pullups` (false: the BMI088 bus relies on the MCU's internal pull-ups), `devices` with strap-decoded `addresses` (`"0x18"` accel, `"0x68"` gyro). |
| `hse` | `osc_in`/`osc_out`, `crystal`, `frequency_hz`, `load_caps`. |
| `vbat` | `pin`, `net`, `backup_battery` (false: VBAT is not connected). |
| `swd` | `swdio`/`swclk` (MCU pin, series resistor, header pin), `swo_routed`, `nrst_on_connector`, and the header pinout. |
| `usb` | `instance`, `dp`/`dm`, `connector`, `vbus_sense` (pin and divider). |

Interfaces are derived from the netlist, not hand-written. If the schematic changes so that one can no longer be derived (for example a CAN transceiver whose TXD no longer reaches an FDCAN pin), the generator fails with an error rather than writing a wrong model.

## Using the model from another repo

Consumers (for example `isc-fs/IFS_vHIL`, `catalog/boards/mainlite.yaml`) should:

1. Fetch a **tagged** release (`pin-model-vX.Y`), check it against `SHA256SUMS`, and refuse any `schema_version` they don't support.
2. For every pin a firmware or system description uses, look it up by `port` and check:
   * it exists (`port` is in the model);
   * for a pin a backplane drives, `class == "backplane"`, and use `backplane[].connector/pin` for the routing;
   * if the consumer gives the pin a peripheral function, it is one of that pin's possible functions. `role` is what the MainLite wiring implies; for backplane GPIOs `role` is usually `null`, because the function is chosen per backplane.
3. Take labels and nets from the model (`net`, `connectors.J3/J4`, `interfaces`) instead of copying them by hand.

Minimal Python check:

```python
import yaml, urllib.request

URL = "https://github.com/isc-fs/IFS08-ES-MainLite/releases/download/pin-model-v1.0/mainlite.pins.yaml"
model = yaml.safe_load(urllib.request.urlopen(URL))
assert model["schema"] == "isc-fs/mainlite-pins" and model["schema_version"] == 1

by_port = {p["port"]: p for p in model["pins"] if p["port"]}
for port in ["PB4", "PF7", "PD0"]:                      # pins the firmware uses
    pin = by_port[port]                                  # KeyError -> pin does not exist
    if pin["class"] == "backplane":
        print(port, "->", [(b["connector"], b["pin"]) for b in pin["backplane"]])
    else:
        print(port, "is", pin["class"], pin["net"], pin["role"])
```

## How the generator decides

* **Netlist**: `kicad-cli sch export netlist --format kicadxml`; connectivity comes from KiCad, not from parsing the schematic.
* **Pin names, types and alternate functions** come from ST's open pin data (`tools/data/STM32H733ZGTx.xml`).
* **Series resistors**: a 2-terminal resistor ≤ 100 Ω between two signal nets (33 Ω SWD/SDMMC damping). The pin is followed through it.
* **Pulls**: a resistor between the pin's net and a rail (`VDD`, `+5V`, … or `GND`).
* **Roles**: the net name is matched against the pin's ST signals, exactly or through the board's naming aliases (`CANn_RX` → `FDCANn_RX`, `SDMMC_D0` → `SDMMC1_D0`, `D+` → `USB_OTG_HS_DP`, `SWDIO` → `DEBUG_JTMS-SWDIO`). A role is only reported if the ST data says the pin can carry that function.
* **Backplane**: J3/J4 are fixed in `BACKPLANE` in `tools/gen_pins.py`; other connectors are listed in `CONNECTOR_KIND`.
