"""Invariants of the committed pin model (stdlib unittest).

Run from the repo root:  python3 -m unittest discover -s tests -v
PyYAML is optional; when present the YAML is checked against the JSON twin.
"""

import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import gen_pins  # noqa: E402

MODEL = json.loads((REPO / "model/mainlite.pins.json").read_text())
CLASSES = {"backplane", "onboard", "system", "power", "ground", "nc"}


class PinModel(unittest.TestCase):
    def test_header(self):
        self.assertEqual(MODEL["schema"], gen_pins.SCHEMA)
        self.assertEqual(MODEL["schema_version"], gen_pins.SCHEMA_VERSION)
        self.assertEqual(MODEL["source"]["schematic_git_blob"],
                         gen_pins.git_blob_sha(REPO / MODEL["source"]["schematic"]))
        self.assertRegex(MODEL["source"]["pin_data"]["commit"], r"^[0-9a-f]{40}$")

    def test_every_package_pin_once(self):
        numbers = [p["number"] for p in MODEL["pins"]]
        self.assertEqual(numbers, list(range(1, 145)))
        self.assertEqual(MODEL["summary"]["total_pins"], 144)

    def test_classes_and_summary(self):
        counts = {}
        for p in MODEL["pins"]:
            self.assertIn(p["class"], CLASSES, p)
            counts[p["class"]] = counts.get(p["class"], 0) + 1
        self.assertEqual({k: v for k, v in MODEL["summary"]["by_class"].items() if v}, counts)

    def test_ports_unique(self):
        ports = [p["port"] for p in MODEL["pins"] if p["port"]]
        self.assertEqual(len(ports), len(set(ports)))
        for port in ports:
            self.assertRegex(port, r"^P[A-K]\d+(_C)?$")

    def test_backplane_consistent(self):
        """Pins of class backplane and connector entries of kind mcu agree."""
        from_pins = {(b["connector"], b["pin"]): p["number"]
                     for p in MODEL["pins"] for b in p["backplane"]}
        from_conn = {(j, e["pin"]): e["mcu_pin"]
                     for j, c in MODEL["connectors"].items() for e in c["pins"] if e["kind"] == "mcu"}
        self.assertEqual(from_pins, from_conn)
        for p in MODEL["pins"]:
            self.assertEqual(p["class"] == "backplane", bool(p["backplane"]), p["name"])

    def test_nc_pins_have_no_net(self):
        for p in MODEL["pins"]:
            if p["class"] == "nc":
                self.assertIsNone(p["net"], p["name"])

    def test_roles_are_pin_signals(self):
        pin_data = gen_pins.load_pin_data(REPO / gen_pins.PIN_DATA)
        for p in MODEL["pins"]:
            if p["role"]:
                self.assertIn(p["role"], pin_data[p["number"]]["signals"], p["name"])

    def test_interfaces(self):
        itf = MODEL["interfaces"]
        self.assertEqual(sorted(c["fdcan"] for c in itf["can"]), ["FDCAN1", "FDCAN2", "FDCAN3"])
        for c in itf["can"]:
            self.assertIn(c["canh"].get("connector"), MODEL["board"]["backplane_connectors"])
            self.assertTrue(re.fullmatch(r"FDCAN\d_TX", next(
                p["role"] for p in MODEL["pins"] if p["number"] == c["tx"]["pin"])))

    @unittest.skipUnless(__import__("importlib").util.find_spec("yaml"), "PyYAML not installed")
    def test_yaml_matches_json(self):
        import yaml
        self.assertEqual(yaml.safe_load((REPO / "model/mainlite.pins.yaml").read_text()), MODEL)


class Helpers(unittest.TestCase):
    def test_parse_ohms(self):
        cases = {"33R": 33, "4k7": 4700, "120R": 120, "1k": 1000, "5k1": 5100, "100k": 1e5, "1M": 1e6, "47": 47}
        for text, ohms in cases.items():
            self.assertEqual(gen_pins.parse_ohms(text), ohms, text)
        self.assertIsNone(gen_pins.parse_ohms("10u"))

    def test_pin_name_kicad9_and_10(self):
        self.assertEqual(gen_pins.pin_name({"function": "TXD_1", "pin": "1"}), "TXD")
        self.assertEqual(gen_pins.pin_name({"function": "TXD", "pin": "1"}), "TXD")
        self.assertEqual(gen_pins.pin_name({"function": "D+_A6", "pin": "A6"}), "D+")
        self.assertIsNone(gen_pins.pin_name({"function": "Pin_3_3", "pin": "3"}))
        self.assertIsNone(gen_pins.pin_name({"function": "Pin", "pin": "3"}))

    def test_yaml_emitter_is_json_compatible(self):
        obj = {"a": [1, {"b": None, "c": [True, "x: y"]}, []], "d": {}, "e": "PA13(JTMS/SWDIO)"}
        text = gen_pins.to_yaml(obj)
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        self.assertEqual(yaml.safe_load(text), obj)


if __name__ == "__main__":
    unittest.main()
