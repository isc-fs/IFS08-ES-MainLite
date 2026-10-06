# WORK ORDER: MAINLITE (IFS08)
## Minimal STM32H733ZG Control Module for the AMS, ECU & uDV Backplanes
**Season:** 2025/2026  
**Department:** Low Voltage & Electronics  
**Author:** Raúl Morán  
**Date:** 6 October 2026  
**Revision:** Rev 1.0 (`WO-IFS08-MLITE-001`)  
**Base Template:** `IFS_09_W_Template_Base_CB.docx`  

---

## 1. Executive Summary & Functional Description

### 1.1 Purpose

This Work Order defines the hardware engineering requirements, electrical specifications, component selections, module interfaces, and verification testing procedures for the IFS08 'MainLite' printed circuit board (PCB).

The MainLite is the team's minimal STM32H733ZG control module. A single module design is shared by three vehicle subsystems: mounted on its backplane it becomes the Accumulator Management System (AMS), the Electronic Control Unit (ECU) or the driverless interface (uDV). Everything that differs between these roles lives on the backplane; the module itself carries only the microcontroller, its supply, the three CAN physical layers and the common peripherals.

This revision documents the v1.1 design as fabricated and is the baseline against which future MainLite revisions and backplane designs are verified.

### 1.2 System Overview & Module Integration

- **One Module, Three Roles:** The same assembled MainLite plugs into the AMS, ECU or uDV backplane through two 1x18 2.54 mm headers (J3, J4). Spares are interchangeable between subsystems; the role is selected by the backplane and the firmware image.
- **High-Performance Microcontroller:** STMicroelectronics STM32H733ZGTx (Arm Cortex-M7 up to 550 MHz, 1 MB Flash, 564 KB RAM) in LQFP-144, clocked from a 24 MHz crystal.
- **Triple CAN Physical Layer:** Three Texas Instruments TCAN330 transceivers on FDCAN1, FDCAN2 and FDCAN3, each with a fixed 120 Ω termination, routed to the backplane on J4.3–J4.8.
- **On-Board Sensing & Logging:** Bosch BMI088 6-axis IMU on I2C2 and a microSD socket on SDMMC1 (4-bit) for high-rate data logging.
- **Service Interfaces:** USB-C (USB_OTG_HS, full-speed) for power and data, a 4-pin SWD header (J2), BOOT0 and reset push-buttons, and two status LEDs (OK / ERR).
- **CAN Bootloader:** Every MainLite is provisioned with the ISC CAN bootloader in Flash sector 0, so application firmware is updated over the vehicle CAN bus without opening the car (node id 0x1 ECU, 0x2 AMS, 0x3 uDV).
- **Machine-Readable Pin Model:** Every one of the 144 MCU pins, its net, alternate function and backplane routing is exported automatically from the schematic to model/mainlite.pins.yaml and kept in sync by CI, so firmware, backplane and HIL definitions can be checked against the hardware.
- **Compact 2-Layer PCB:** 40 x 60 mm, 2-layer FR4, 1.2 mm thickness, 1 oz (35 µm) copper, four M3 mounting holes.

---

## 2. System Architecture Diagram

The block diagram below illustrates the power path, the microcontroller peripherals and their routing to the backplane connectors.

```
+-------------------------------------------------------------------------------+
|        BACKPLANE  (AMS / ECU / uDV)  -- mates with J3 + J4 (2x 1x18, 2.54 mm)   |
|   J4.17/18 +5V   J4.15/16 VDD 3V3   J3.1/2 + J4.1/2 GND   J4.3-8 CAN1..3      |
+---------------+-----------------------------+---------------------------------+
                |  +5V                        |  22 MCU I/O (GPIO, USART10, SPI1, 1-Wire)
                v                             |
   USB-C (J5) --+--> LSM115J (D11) --+        |
   VBUS 5 V                          v        |
                       +---------------------------+
                       |  LD39200PU33R (U1) 3.3 V   |---> VDD (MCU, IMU, microSD, J2, J4.15/16)
                       +-------------+-------------+
                                     |
       +-----------------------------v------------------------------------+
       |              STM32H733ZGTx  (U5, LQFP-144, Cortex-M7 550 MHz)    |
       |   HSE 24 MHz (Y1)      SWD (J2)      BOOT0 (SW1)   NRST (SW2)    |
       +----+-----------+-----------+-----------+-----------+--------+----+
            | FDCAN1    | FDCAN2    | FDCAN3    | I2C2      | SDMMC1 | USB_OTG_HS
            v           v           v           v           v        v
        TCAN330     TCAN330     TCAN330      BMI088     microSD    USB-C (J5)
         (U2)        (U3)        (U4)        (IC1)       (J1)      ESD D3/D4
        120R R1     120R R5     120R R9   0x18 / 0x68  4-bit, CD   VBUS sense PA9
            |           |           |
        J4.3/4      J4.5/6      J4.7/8
         CAN1        CAN2        CAN3
```

---

## 3. Hardware & Design Requirements

### 3.1 Core Component & Electrical Requirements

- **Power Input & Regulation:** +5V supplied by the backplane on J4.17/J4.18, or from USB VBUS through a Microsemi LSM115J Schottky diode (D11) for bench work. An ST LD39200PU33R 2 A low-dropout regulator (U1) generates the 3.3 V VDD rail, which is also exported to the backplane on J4.15/J4.16.
- **Microcontroller Supply Network:** 100 nF decoupling on every VDD pin, 2 x 2.2 µF on VCAP, VDDA tied to VDD, and VREF+ filtered from VDD through 47 Ω with 1 µF + 100 nF. VBAT and PDR_ON are left unconnected in v1.1 (see Section 3.3).
- **Clock:** 24 MHz crystal (Y1, 2.5 x 2.0 mm) on PH0/PH1 with 10 pF load capacitors (C5, C6) as the HSE source.
- **CAN Physical Layer:** Three TI TCAN330 3.3 V CAN transceivers (SOIC-8): FDCAN1 on PD0/PD1 (U2), FDCAN2 on PB12/PB13 (U3), FDCAN3 on PG10/PG9 (U4). Each bus has a fixed 120 Ω termination (R1, R5, R9) on the module. SHDN and S are left at their internal defaults (normal mode).
- **Inertial Measurement Unit:** Bosch BMI088 (IC1) in I2C mode on I2C2 (PF0 SDA, PF1 SCL). Accelerometer at 0x18 and gyroscope at 0x68 (SDO1/SDO2 strapped to GND). No external pull-ups are fitted: firmware enables the MCU internal pull-ups and runs the bus at 100 kHz. Interrupt pins are not routed.
- **microSD Storage:** Molex 104031-0811 socket (J1) on SDMMC1 4-bit (PC8–PC12, PD2) with 33 Ω series resistors, 47 kΩ pull-ups on CMD and DAT0–DAT3, card detect on PE3 with a 47 kΩ pull-up, supplied from the always-on 3.3 V rail.
- **USB-C:** GCT USB4085 receptacle (J5) on USB_OTG_HS with the internal full-speed PHY (PA11/PA12), ESD9B5.0ST5G protection on D+/D-, 5.1 kΩ CC pull-downs (sink), and VBUS sensing on PA9 through a 100 kΩ / 47 kΩ divider.
- **Debug, Boot & Status:** 1x4 SWD header J2 (GND, SWCLK, SWDIO, VDD) with 33 Ω series resistors on PA14/PA13; BOOT0 push-button SW1 with 10 kΩ pull-down; reset push-button SW2 (pulls NRST low through 10 kΩ); OK_STATUS (PD14) and ERR_STATUS (PD15) LEDs and a green VDD power LED (LED1).

### 3.2 Pin Mapping & Interface Specification

#### Table 3.2.1: Backplane Connector Pinout (J3 / J4, 1x18, 2.54 mm)

| Pin | J3 Net | J3 MCU Pin | J4 Net | J4 MCU Pin / Part |
| :--- | :--- | :--- | :--- | :--- |
| 1 | GND | — | GND | — |
| 2 | GND | — | GND | — |
| 3 | DS18B20_REFRI | PD5 (119), 4.7 kΩ pull-up | CANL1 | U2 CANL, R1 |
| 4 | USART10_RX | PG11 (126) | CANH1 | U2 CANH, R1 |
| 5 | USART10_TX | PG12 (127) | CANH2 | U3 CANH, R5 |
| 6 | GPIO1 | PB4 (134) | CANL2 | U3 CANL, R5 |
| 7 | GPIO2 | PB5 (135) | CANH3 | U4 CANH, R9 |
| 8 | GPIO3 | PB6 (136) | CANL3 | U4 CANL, R9 |
| 9 | GPIO4 | PB7 (137) | NRF24_CS | PB0 (46) |
| 10 | GPIO5 | PB8 (139) | NRF24_CE | PC5 (45) |
| 11 | GPIO6 | PB9 (140) | NRF24_IRQ | PC4 (44) |
| 12 | GPIO7 | PF7 (19) | SPI1_MOSI | PA7 (43) |
| 13 | GPIO8 | PF8 (20) | SPI1_MISO | PA6 (42) |
| 14 | GPIO9 | PF9 (21) | SPI1_SCK | PA5 (41) |
| 15 | GPIO10 | PF10 (22) | VDD (3.3 V) | U1 output |
| 16 | GPIO11 | PC0 (26) | VDD (3.3 V) | U1 output |
| 17 | GPIO12 | PC1 (27) | +5V | U1 input |
| 18 | GPIO13 | PC2_C (28) | +5V | U1 input |

#### Table 3.2.2: CAN Channel Allocation

| Channel | Controller | MCU TX / RX | Transceiver | Backplane Pins | Termination |
| :--- | :--- | :--- | :--- | :--- | :--- |
| CAN1 | FDCAN1 | PD1 / PD0 | U2 TCAN330 | J4.4 CANH, J4.3 CANL | R1 120 Ω (fixed) |
| CAN2 | FDCAN2 | PB13 / PB12 | U3 TCAN330 | J4.5 CANH, J4.6 CANL | R5 120 Ω (fixed) |
| CAN3 | FDCAN3 | PG9 / PG10 | U4 TCAN330 | J4.7 CANH, J4.8 CANL | R9 120 Ω (fixed) |

#### Table 3.2.3: On-Board Peripheral Pin Allocation

| Function | Peripheral | MCU Pins | Connected Parts |
| :--- | :--- | :--- | :--- |
| IMU | I2C2 | PF0 SDA, PF1 SCL | IC1 BMI088 (0x18 / 0x68), no external pull-ups |
| microSD | SDMMC1 | PC8–PC11 D0–D3, PC12 CK, PD2 CMD | J1, R26/R29–R33 33 Ω, R16–R20 47 kΩ |
| Card detect | GPIO | PE3 | J1 DET, R21 47 kΩ pull-up |
| USB | USB_OTG_HS (FS) | PA12 D+, PA11 D-, PA9 VBUS | J5, D3/D4 ESD, R13/R14 divider |
| Debug | SWD | PA13 SWDIO, PA14 SWCLK | J2, R6/R8 33 Ω |
| Clock | HSE | PH0 OSC_IN, PH1 OSC_OUT | Y1 24 MHz, C5/C6 10 pF |
| Status | GPIO | PD14 OK, PD15 ERR | D1/D2 LEDs, R11/R12 1 kΩ |
| Boot / reset | BOOT0, NRST | Pins 138, 25 | SW1 + R4 10 kΩ, SW2 |

#### Table 3.2.4: Module Roles

| Role | Subsystem | CAN Bootloader Node Id | Flash Bus |
| :--- | :--- | :--- | :--- |
| ECU | Vehicle control unit | 0x1 | FDCAN2 |
| AMS | Accumulator management system | 0x2 | FDCAN1 |
| uDV | Driverless interface | 0x3 | FDCAN2 |

#### Machine-Readable Pin Model Directive

> [!IMPORTANT]
> **THE SCHEMATIC IS THE SINGLE SOURCE OF TRUTH FOR PIN ASSIGNMENTS**
>
> The pin model (model/mainlite.pins.yaml and its JSON twin) is generated from the schematic by tools/gen_pins.py and must never be edited by hand.
>
> Engineering Implementation Rule:
> 1. Any pull request that changes the schematic must regenerate and commit the pin model; CI rejects pull requests whose committed model is stale.
> 2. Every change that reaches main is published as a pin-model-vX.Y release. Firmware, backplane designs and the virtual HIL must pin a released version and check that every pin they use exists and is routed to J3/J4.
> 3. The schematic must pass KiCad ERC with zero errors; CI enforces this on every pull request.

> **Pin Model Summary:** 144 package pins, of which 114 are I/O: 22 routed to the backplane (J3/J4), 24 used on the module only, and 68 not connected. The remaining pins are 16 power, 10 ground, 2 system (NRST, BOOT0) and 2 supply pins left open (VBAT, PDR_ON).

### 3.3 Testability & Mechanical Requirements

- **PCB Stackup:** 2-layer FR4, 1.2 mm finished thickness, 1 oz (35 µm) copper on both layers, black solder mask, yellow silkscreen.
- **Mechanical Mounting:** 40 x 60 mm outline with four (4) M3 mounting holes (3.2 mm, DIN 965 pad). J3 and J4 are 1x18 2.54 mm pin headers; the matching module symbol and footprint for backplane designs are provided in Libraries/MAIN_LITE.
- **Accessibility:** SWD header, USB-C, microSD socket, BOOT0/reset buttons and status LEDs must remain accessible with the module mounted on its backplane.
- **Design Rule Compliance:** KiCad ERC with zero errors (enforced by CI) and zero DRC errors before any fabrication release.
- **Open Items for the Next Revision:** Tie VBAT to VDD with 100 nF (no backup battery is used); tie PDR_ON to VDD; add a 100 nF NRST filter capacitor; route NRST and SWO to the SWD header; drive or strap the TCAN330 SHDN and S pins; make the CANH/CANL pin order on J4 consistent (CAN1 is L/H, CAN2 and CAN3 are H/L).

---

## 4. Verification & Testing Protocol

Every manufactured MainLite must complete the following qualification phases before it is installed on a backplane.

### 4.1 Power Supply Verification (+5V, VDD 3.3 V)

- **Procedure:** Before applying power, measure resistance from +5V and from VDD to GND (> 1 kΩ, no shorts). Apply 5.00 V current-limited to 200 mA on J4.17/J4.18, then repeat powering from USB-C only.
- **Acceptance Criteria:** VDD measures 3.30 V ± 0.10 V on J4.15/J4.16 from both sources; idle current with blank MCU < 100 mA; power LED on; no component above 50 °C after 5 minutes.

### 4.2 Microcontroller, Clock & Bootloader Bring-Up

- **Procedure:** Connect an ST-LINK to J2 and read the device ID; flash a clock test that runs the PLL from the 24 MHz HSE; hold BOOT0 and reset to enter the ROM bootloader over USB; provision the CAN bootloader and node id for the target role.
- **Acceptance Criteria:** DBGMCU device ID 0x483 (STM32H72x/73x); HSE starts and the PLL locks; ROM bootloader enumerates over USB; CAN bootloader answers on its node id and a test application can be flashed and started over CAN.

### 4.3 CAN Interfaces

- **Procedure:** Unpowered, measure CANH–CANL on each channel. Powered, connect each channel in turn to a CAN analyzer (PCAN-USB) at 500 kbps and exchange frames in both directions.
- **Acceptance Criteria:** 120 Ω ± 2 Ω per channel unpowered; on each of FDCAN1/2/3, 1000 frames sent and received with zero error frames, and the channel appears on the expected J4 pins.

### 4.4 On-Board Peripherals

- **Procedure:** Read the BMI088 chip IDs over I2C2; mount, write and read back a file on a microSD card and toggle card detect; enumerate the USB device; toggle both status LEDs.
- **Acceptance Criteria:** Accelerometer ID 0x1E at 0x18 and gyroscope ID 0x0F at 0x68; file read back byte-identical, card detect follows insertion; USB enumerates on the host; both LEDs light.

### 4.5 Backplane I/O Continuity

- **Procedure:** On a backplane or the HIL bench, drive and read back every J3/J4 MCU pin listed in the released pin model.
- **Acceptance Criteria:** 22/22 backplane I/O pins toggle at the expected J3/J4 pin with no shorts to neighbouring pins.

---

## 5. Quality Assurance Test Execution Sign-Off Sheet

| Test Item | Target / Acceptance Criteria | Measured Value | Pass / Fail | Inspector | Date |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1. Unpowered Isolation | +5V and VDD to GND > 1 kΩ | | | | |
| 2. 3.3 V Rail (backplane) | 3.20 V – 3.40 V at J4.15 with 5 V on J4.17 | | | | |
| 3. 3.3 V Rail (USB) | 3.20 V – 3.40 V with USB-C only | | | | |
| 4. SWD & Device ID | ST-LINK connects; DEV_ID 0x483 | | | | |
| 5. HSE & PLL | 24 MHz HSE starts, PLL locks | | | | |
| 6. CAN Bootloader | Node id answers; app flashed over CAN | | | | |
| 7. CAN Terminations | 120 Ω ± 2 Ω on CAN1, CAN2, CAN3 | | | | |
| 8. CAN Traffic | FDCAN1/2/3: 1000 frames, 0 errors | | | | |
| 9. IMU | BMI088 IDs 0x1E / 0x0F | | | | |
| 10. microSD & USB | File read-back OK; CD works; USB enumerates | | | | |
| 11. Backplane I/O | 22/22 J3/J4 pins verified | | | | |

---

## 6. Post-Design Requirement: Design Report

Upon completion of the PCB layout, fabrication, and bench/vehicle testing, a comprehensive Design Report must be submitted to the Electronics Subsystem Technical Director.

The Design Report must document:

- **Schematic & Layout Documentation:** Schematic, 2-layer stackup, placement and routing rationale, and the released pin model version.
- **Bill of Materials (BOM):** Manufacturer part numbers, footprints, quantities, and supplier references for assembly.
- **Backplane Integration:** Per-role use of the J3/J4 pins on the AMS, ECU and uDV backplanes, and mechanical clearances of the mounted module.
- **Validation Test Results:** Measured rails, CAN logs, bootloader provisioning records, and the completed sign-off sheet for every serialised module.
- **Design Iterations & Recommendations:** Assembly issues encountered, closure of the open items in Section 3.3, and proposed changes for the next revision.

---

*ISC Racing Team — IFS08 Electronics Subsystem*
