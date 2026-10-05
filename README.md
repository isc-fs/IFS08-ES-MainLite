<img width="470.235" height="179.4" alt="isc-full-primary" src="https://github.com/user-attachments/assets/31365569-11bf-427e-ae3e-8d81ca87d765" />

# IFS08-ES-MainLite

Hardware design, KiCad schematic and PCB layout of the **MainLite**, the minimal STM32H733ZG control module of the **IFS08**, developed for the **ISC Formula Student Racing Team** (Season 2025/2026). Mounted on a backplane, the same module becomes the **AMS**, the **ECU** or the **uDV**.

[![Formula Student](https://img.shields.io/badge/Formula%20Student-ISC-yellow.svg)](https://www.comillas.edu/)
[![Season](https://img.shields.io/badge/Season-2025%2F2026-blue.svg)]()
[![Hardware](https://img.shields.io/badge/EDA-KiCad%209.x-orange.svg)]()
[![Microcontroller](https://img.shields.io/badge/MCU-STM32H733ZG%20(ARM%20Cortex--M7)-green.svg)]()
[![CAN Bus](https://img.shields.io/badge/CAN-3x%20FDCAN%20(TCAN330)-red.svg)]()

[![Schematic PDF](https://img.shields.io/badge/Schematic-MAIN__LITE-blue?logo=adobeacrobatreader)](docs/MAIN_LITE_schematic.pdf)
[![Interactive BOM](https://img.shields.io/badge/BOM-v1.1-blue)](docs/bom/MAIN_LITE_v1-1_BOM.html)
[![Pin model](https://github.com/isc-fs/IFS08-ES-MainLite/actions/workflows/pin-model.yml/badge.svg?branch=dev)](docs/pin-model.md)

---

## Getting started

1. Create a GitHub account if you don't have one yet.
2. Download and install [GitHub Desktop](https://desktop.github.com/) (beginner) or [Git CLI](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git) (advanced).
   - If this is your first time using GitHub Desktop, make sure to read the [User Manual](https://help.github.com/desktop/guides/).
   - If this is your first time using Git, start with a tutorial:
     - [Git Tutorial](https://git-scm.com/docs/gittutorial)
     - [Atlassian Git Tutorial](https://www.atlassian.com/git/tutorials/)
   - Keep a copy of [GitHub's Git Cheat Sheet](https://services.github.com/kit/downloads/github-git-cheat-sheet.pdf) handy as a reference.

3. Clone this repository to your machine:
   - **SSH:** `git@github.com:isc-fs/IFS08-ES-MainLite.git`
   - **HTTPS:** `https://github.com/isc-fs/IFS08-ES-MainLite.git`

4. Open `IFS08-MainLite/MAIN_LITE.kicad_pro` with KiCad 9.x.

---

## How we work with this repository

### Main branches

The repository follows standard ISC branching rules:

* **`main`** is the production branch. It contains only validated hardware releases, schematics, and documentation ready for track operations. Never work directly on it.
* **`dev`** (or active feature branches) is the development and integration point. Never commit directly to `main` — all changes arrive through a reviewed Pull Request.

```
main  ──────────────────●──────────────────────●──▶  (validated releases only)
                        ↑                      ↑
dev   ──────●───●───●───●───●───●───●───●───●──●──▶  (continuous integration)
            ↑   ↑       ↑   ↑   ↑       ↑   ↑
          feat/1 fix/1 feat/2 fix/2   feat/3 fix/3
```

### Feature branches

All work — whether a new hardware revision, firmware update, or bug fix — is done on a **feature branch** created from `dev` (or `main`). When the work is ready, a Pull Request is opened, reviewed, merged, and the branch is deleted.

```
feat/<n>   →  new functionality / hardware addition (feat/1, feat/2, feat/3 ...)
fix/<n>    →  bug fix / schematic correction       (fix/1,  fix/2,  fix/3  ...)
```

### Step-by-step workflow

1. **Create the branch:**
   ```bash
   git checkout dev
   git pull origin dev
   git checkout -b feat/your-feature-name
   ```
2. **Work and commit:**
   ```bash
   git add .
   git commit -m "feat(hw): add reverse polarity protection to 5V input"
   ```
3. **Push and open Pull Request:**
   ```bash
   git push origin feat/your-feature-name
   ```
   Open a PR against `dev`, verify 0 KiCad DRC/ERC errors, provide test evidence, and request review from the Electronics Subsystem Technical Director.

---

## 1. Project Overview & System Purpose

The **MainLite** is a small, self-contained STM32H733ZG module: MCU, 3.3 V regulation, three CAN transceivers, IMU, microSD, USB-C and SWD. Everything that changes between car subsystems lives on the **backplane** it plugs into through two 1×18 2.54 mm headers (**J3** and **J4**):

| Role | Node id (CAN bootloader) | Flash bus |
| :--- | :---: | :---: |
| **ECU** — vehicle control unit | `0x1` | FDCAN2 |
| **AMS** — accumulator management system | `0x2` | FDCAN1 |
| **uDV** — driverless interface | `0x3` | FDCAN2 |

Every MainLite carries the ISC CAN bootloader in flash sector 0.

```
                 +--------------------------------------------------------------+
   USB-C (J5) ---+  ESD (D3/D4)   +5V <- VBUS (D11)        SWD (J2: GND/CLK/DIO/VDD)
                 |                                                              |
   +5V (J4.17/18)+--> LD39200 (U1) --> VDD 3.3 V --> J4.15/16                   |
                 |                                                              |
                 |      +--------------------------------------------+         |
                 |      |        STM32H733ZGTx (U5, LQFP-144)         |         |
                 |      |  HSE 24 MHz (Y1)                            |         |
                 |      +--+---------+---------+---------+------+----+         |
                 |         |FDCAN1   |FDCAN2   |FDCAN3   |I2C2  |SDMMC1        |
                 |      TCAN330   TCAN330   TCAN330   BMI088  microSD (J1)      |
                 |       (U2)      (U3)      (U4)     (IC1)    4-bit, CD PE3    |
                 |      120R R1   120R R5   120R R9                             |
                 +--------+---------+---------+-----------------------------+---+
                          |         |         |                             |
                   J4.3/4 CAN1  J4.5/6 CAN2  J4.7/8 CAN3     J3: 13 GPIO, USART10, 1-Wire
                                                            J4: SPI1 + nRF24 CS/CE/IRQ
```

---

## 2. Hardware Architecture & Electrical Specifications

| Block | Part | Notes |
| :--- | :--- | :--- |
| MCU | STM32H733ZGTx (U5) | Cortex-M7 @ 550 MHz, 1 MB flash, LQFP-144 |
| Clock | 24 MHz crystal (Y1) | HSE on PH0/PH1, 10 pF load caps (C5/C6) |
| 3.3 V rail | ST LD39200PU33R (U1) | From `+5V` (backplane J4.17/18 or USB VBUS through D11) |
| CAN | 3× TI TCAN330 (U2/U3/U4) | FDCAN1 PD0/PD1, FDCAN2 PB12/PB13, FDCAN3 PG10/PG9; fixed 120 Ω terminations R1/R5/R9 |
| IMU | Bosch BMI088 (IC1) | I2C2 PF0/PF1, accel `0x18`, gyro `0x68`, no external pull-ups |
| Storage | microSD (J1, Molex 104031-0811) | SDMMC1 4-bit PC8–PC12/PD2, 33 Ω series, 47 kΩ pull-ups, card detect PE3 |
| USB | USB-C (J5, GCT USB4085) | USB_OTG_HS FS PHY PA11/PA12, VBUS sense PA9 (100k/47k) |
| Debug | 1×4 header (J2) | GND, SWCLK (PA14), SWDIO (PA13), VDD |
| Status | 2× LED | `OK_STATUS` PD14, `ERR_STATUS` PD15 |
| Buttons | SW1 / SW2 | BOOT0, NRST |
| VBAT | — | Not connected (no backup battery) |

---

## 3. Backplane Connectors (J3 / J4)

| Pin | J3 net | J3 MCU | J4 net | J4 MCU / part |
| :---: | :--- | :--- | :--- | :--- |
| 1 | `GND` | — | `GND` | — |
| 2 | `GND` | — | `GND` | — |
| 3 | `DS18B20_REFRI` | PD5 (pin 119) | `CANL1` | R1.2, U2.6 |
| 4 | `USART10_RX` | PG11 (pin 126) | `CANH1` | R1.1, U2.7 |
| 5 | `USART10_TX` | PG12 (pin 127) | `CANH2` | R5.1, U3.7 |
| 6 | `GPIO1` | PB4 (pin 134) | `CANL2` | R5.2, U3.6 |
| 7 | `GPIO2` | PB5 (pin 135) | `CANH3` | R9.1, U4.7 |
| 8 | `GPIO3` | PB6 (pin 136) | `CANL3` | R9.2, U4.6 |
| 9 | `GPIO4` | PB7 (pin 137) | `NRF24_CS` | PB0 (pin 46) |
| 10 | `GPIO5` | PB8 (pin 139) | `NRF24_CE` | PC5 (pin 45) |
| 11 | `GPIO6` | PB9 (pin 140) | `NRF24_IRQ` | PC4 (pin 44) |
| 12 | `GPIO7` | PF7 (pin 19) | `SPI1_MOSI` | PA7 (pin 43) |
| 13 | `GPIO8` | PF8 (pin 20) | `SPI1_MISO` | PA6 (pin 42) |
| 14 | `GPIO9` | PF9 (pin 21) | `SPI1_SCK` | PA5 (pin 41) |
| 15 | `GPIO10` | PF10 (pin 22) | `VDD` | — |
| 16 | `GPIO11` | PC0 (pin 26) | `VDD` | — |
| 17 | `GPIO12` | PC1 (pin 27) | `+5V` | — |
| 18 | `GPIO13` | PC2_C (pin 28) | `+5V` | — |

Per-role use of these pins (which GPIO is which signal on the AMS, ECU or uDV backplane) is defined by each backplane design.

---

## 4. Machine-Readable Pin Model

[`model/mainlite.pins.yaml`](model/mainlite.pins.yaml) (JSON twin: [`mainlite.pins.json`](model/mainlite.pins.json)) lists all 144 pins of U5: net, alternate function, whether and where each one leaves the module on J3/J4, and what it connects to on the board. It also describes the CAN, SDMMC, I2C, HSE, VBAT, SWD and USB interfaces. `tools/gen_pins.py` generates it from the schematic; CI fails a PR whose committed model is stale and runs KiCad ERC. Each change that reaches `main` is published as a `pin-model-vX.Y` release, so other repos (e.g. the virtual HIL) can check their pin definitions against a pinned version.

```bash
python3 tools/gen_pins.py        # after any schematic change; commit model/
```

Format, versioning and how to consume it: [docs/pin-model.md](docs/pin-model.md).

---

## 5. Formal Design Documents & Reports

| Document | File Link | Description | Status |
| :--- | :--- | :--- | :--- |
| **Schematic (PDF)** | [📄 MAIN_LITE_schematic.pdf](docs/MAIN_LITE_schematic.pdf) | Eeschema PDF export of the schematic. | **v1.1** |
| **Interactive BOM** | [📄 MAIN_LITE_v1-1_BOM.html](docs/bom/MAIN_LITE_v1-1_BOM.html) | InteractiveHtmlBom export for assembly. | **v1.1** |
| **Pin model** | [📄 pin-model.md](docs/pin-model.md) | Format and use of the generated pin model. | **Schema v1** |
| **Fabrication outputs** | [📁 production/](IFS08-MainLite/production) | Gerbers/drill (`MAIN_LITE.zip`), BOM, CPL and IPC netlist as sent to fab. | **v1.1** |

---

## 6. Repository Structure

```
IFS08-ES-MainLite/
├── .github/workflows/                 # CI: pin-model check + ERC, model release on main
├── docs/                              # Documentation
│   ├── bom/
│   │   └── MAIN_LITE_v1-1_BOM.html    # Interactive BOM
│   ├── MAIN_LITE_schematic.pdf        # Schematic PDF export
│   └── pin-model.md                   # Pin model format & usage
├── IFS08-MainLite/                    # KiCad Project Files (KiCad 9.x)
│   ├── Libraries/                     # Local symbols & footprints (BMI088, LD39200, LSM115J, switch, ISC logo, MainLite module)
│   ├── production/                    # Fabrication outputs (Gerbers, BOM, CPL)
│   ├── fp-lib-table                   # Footprint Library Table
│   ├── sym-lib-table                  # Symbol Library Table
│   ├── MAIN_LITE.kicad_pro            # KiCad Project File
│   ├── MAIN_LITE.kicad_sch            # Schematic
│   └── MAIN_LITE.kicad_pcb            # PCB Layout
├── model/                             # GENERATED pin model (mainlite.pins.yaml / .json)
├── tests/                             # Pin model invariants (unittest)
├── tools/                             # gen_pins.py, kicad_export.sh, erc_summary.py, ST pin data
├── .gitignore                         # KiCad and OS Ignore Rules
└── README.md                          # Repository Documentation
```

`Libraries/MAIN_LITE/` holds the MainLite module symbol and footprint that backplane designs place to mate with J3/J4.

---

## 7. Author & Team Credits

* **Subsystem:** Low Voltage & Electronics Subsystem (ES)
* **Author & Technical Lead:** Raúl Morán
* **Team:** [ISC Formula Student Racing Team](https://www.comillas.edu/) — Universidad Pontificia Comillas (ICAI)
* **Season:** 2025 / 2026

---

*ISC Racing Team — IFS08 Electronics Subsystem*
