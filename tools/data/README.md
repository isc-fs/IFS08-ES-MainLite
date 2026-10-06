# Vendored MCU pin data

`STM32H733ZGTx.xml` is copied unmodified from
[STMicroelectronics/STM32_open_pin_data](https://github.com/STMicroelectronics/STM32_open_pin_data)
at the commit recorded in `SOURCE.json` (BSD-3-Clause, see
`LICENSE.STM32_open_pin_data`). `tools/gen_pins.py` uses it for pin names,
pin types and the alternate functions available on each pin.

To update it, replace the XML with a newer copy, update `SOURCE.json`, run
`python3 tools/gen_pins.py` and commit the regenerated model.
