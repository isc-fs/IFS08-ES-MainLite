#!/usr/bin/env python3
"""Generate the MainLite pin model from the KiCad schematic.

Exports the schematic netlist with ``kicad-cli`` (or reads one given with
``--netlist``), walks every pin of the STM32H733ZG and writes
``model/mainlite.pins.yaml`` plus its JSON twin ``model/mainlite.pins.json``.

Standard library only. Usage (from the repo root):

    python3 tools/gen_pins.py            # regenerate model/
    python3 tools/gen_pins.py --check    # exit 1 if model/ is stale

See docs/pin-model.md for the format.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

SCHEMA = "isc-fs/mainlite-pins"
SCHEMA_VERSION = 1

REPO = Path(__file__).resolve().parent.parent
SCHEMATIC = Path("IFS08-MainLite/MAIN_LITE.kicad_sch")
PIN_DATA = Path("tools/data/STM32H733ZGTx.xml")
PIN_DATA_SOURCE = Path("tools/data/SOURCE.json")
OUT_YAML = Path("model/mainlite.pins.yaml")
OUT_JSON = Path("model/mainlite.pins.json")

MCU_REF = "U5"
MCU_PART = "STM32H733ZGTx"
# The two 1x18 headers a backplane mates with.
BACKPLANE = ("J3", "J4")
# Other connectors on the module and what they are.
CONNECTOR_KIND = {
    "J1": "microsd",
    "J2": "swd",
    "J5": "usb_c",
}
# A 2-terminal resistor at or below this value between two signal nets is a
# series (damping) resistor: the pin is considered to continue through it.
SERIES_MAX_OHMS = 100.0
GROUND_NETS = {"GND", "GNDA", "VSS", "AGND", "DGND"}
POWER_NET_RE = re.compile(r"^(\+\d+V\d*|\+?\d+V\d+|VDD\w*|VCC\w*|VBUS_\w+|VREF\w*)$")
NC_NET_RE = re.compile(r"^unconnected-")

# Net-name aliases used on this board -> ST signal-name patterns.
NET_ALIASES = [
    (re.compile(r"^CAN(\d)_(RX|TX)$"), r"FDCAN\1_\2"),
    (re.compile(r"^SDMMC_(CK|CMD|D\d)$"), r"SDMMC1_\1"),
    (re.compile(r"^D\+$"), "USB_OTG_HS_DP"),
    (re.compile(r"^D-$"), "USB_OTG_HS_DM"),
    (re.compile(r"^VBUS$"), "USB_OTG_HS_VBUS"),
    (re.compile(r"^SWDIO$"), "DEBUG_JTMS-SWDIO"),
    (re.compile(r"^SWCLK$"), "DEBUG_JTCK-SWCLK"),
]

# Strap-dependent I2C addresses of known on-board devices.
# value -> {strap pin name: (address if strap low, address if strap high)}
I2C_DEVICES = {
    "BMI088": {
        "accel": ("SDO1", 0x18, 0x19),
        "gyro": ("SDO2", 0x68, 0x69),
    },
}


class ModelError(Exception):
    pass


# --------------------------------------------------------------------------
# Inputs


def find_kicad_cli() -> str:
    env = os.environ.get("KICAD_CLI")
    if env:
        return env
    found = shutil.which("kicad-cli")
    if found:
        return found
    mac = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
    if Path(mac).exists():
        return mac
    raise ModelError("kicad-cli not found: install KiCad, put kicad-cli on PATH or set KICAD_CLI")


def export_netlist(schematic: Path) -> Path:
    out = Path(tempfile.mkdtemp(prefix="mainlite-")) / "netlist.xml"
    cmd = [find_kicad_cli(), "sch", "export", "netlist", "--format", "kicadxml",
           "--output", str(out), str(schematic)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    return out


def git_blob_sha(path: Path) -> str:
    """Git blob SHA of the file content (same as `git hash-object`).

    A content hash rather than a commit SHA so the model does not change when
    an unrelated commit lands or a PR is rebased/squash-merged.
    """
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def kicad_file_version(schematic: Path) -> dict:
    head = schematic.read_text(encoding="utf-8", errors="replace")[:2000]
    fmt = re.search(r"\(version\s+(\d+)\)", head)
    gen = re.search(r'\(generator_version\s+"([^"]+)"\)', head)
    return {
        "file_format": int(fmt.group(1)) if fmt else None,
        "generator_version": gen.group(1) if gen else None,
    }


def load_pin_data(path: Path) -> dict[int, dict]:
    ns = {"st": "http://dummy.com"}
    root = ET.parse(path).getroot()
    if root.get("RefName") != MCU_PART:
        raise ModelError(f"{path}: expected {MCU_PART}, got {root.get('RefName')}")
    pins = {}
    for p in root.findall("st:Pin", ns):
        pos = int(p.get("Position"))
        pins[pos] = {
            "name": p.get("Name"),
            "st_type": p.get("Type"),
            "signals": [s.get("Name") for s in p.findall("st:Signal", ns)
                        if s.get("Name") != "GPIO"],
        }
    return pins


class Netlist:
    def __init__(self, path: Path):
        root = ET.parse(path).getroot()
        self.parts: dict[str, dict] = {}
        for c in root.find("components"):
            ls = c.find("libsource")
            self.parts[c.get("ref")] = {
                "value": c.findtext("value"),
                "footprint": c.findtext("footprint"),
                "symbol": f"{ls.get('lib')}:{ls.get('part')}" if ls is not None else None,
                "part": ls.get("part") if ls is not None else None,
            }
        self.nets: dict[str, list[dict]] = {}
        self.pin_net: dict[tuple[str, str], str] = {}
        for n in root.find("nets"):
            name = n.get("name")
            nodes = []
            for x in n.findall("node"):
                node = {
                    "ref": x.get("ref"),
                    "pin": x.get("pin"),
                    "function": x.get("pinfunction"),
                    "type": x.get("pintype"),
                }
                nodes.append(node)
                self.pin_net[(node["ref"], node["pin"])] = name
            self.nets[name] = nodes

    def part_pins(self, ref: str) -> dict[str, str]:
        return {p: n for (r, p), n in self.pin_net.items() if r == ref}

    def pin_by_function(self, ref: str, function: str) -> str | None:
        for (r, p), net in self.pin_net.items():
            if r != ref:
                continue
            for node in self.nets[net]:
                if node["ref"] == ref and node["pin"] == p:
                    if pin_name(node) == function:
                        return net
        return None


# --------------------------------------------------------------------------
# Helpers


def parse_ohms(value: str | None) -> float | None:
    """'33R' -> 33, '4k7' -> 4700, '120R' -> 120, '1M' -> 1e6."""
    if not value:
        return None
    v = value.strip().replace("Ω", "").replace("ohm", "")
    m = re.fullmatch(r"(\d+)([RrKkMm])(\d*)", v)
    if m:
        mult = {"r": 1, "k": 1e3, "m": 1e6}[m.group(2).lower()]
        return float(f"{m.group(1)}.{m.group(3) or 0}") * mult
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kKmM]?)", v)
    if m:
        return float(m.group(1)) * {"": 1, "k": 1e3, "m": 1e6}[m.group(2).lower()]
    return None


def pin_name(node: dict) -> str | None:
    """Pin name from a netlist node.

    KiCad 10 writes pinfunction as "<name>_<number>"; KiCad 9 writes "<name>".
    Strip the suffix only when it is the pin number, so both give the same model.
    """
    f = node.get("function") or ""
    suffix = "_" + str(node.get("pin"))
    if f.endswith(suffix):
        f = f[: -len(suffix)]
    # Generic header pin names ("Pin_3" in KiCad 10, "Pin" in KiCad 9) carry nothing.
    if re.fullmatch(r"Pin(_\d+)?|\d+|~", f):
        return None
    return f or None


def is_ground(net: str | None) -> bool:
    return bool(net) and net.lstrip("/") in GROUND_NETS


def is_power(net: str | None) -> bool:
    return bool(net) and bool(POWER_NET_RE.match(net.lstrip("/")))


def is_nc(net: str | None, nodes: list) -> bool:
    return net is None or bool(NC_NET_RE.match(net)) or len(nodes) <= 1


def is_auto(net: str) -> bool:
    return net.startswith("Net-(") or bool(NC_NET_RE.match(net))


def is_resistor(nl: Netlist, ref: str) -> bool:
    return ref.startswith("R") and len(nl.part_pins(ref)) == 2


def other_pin_net(nl: Netlist, ref: str, pin: str) -> str | None:
    pins = nl.part_pins(ref)
    others = [n for p, n in pins.items() if p != pin]
    return others[0] if len(others) == 1 else None


def port_of(st_name: str) -> str | None:
    m = re.match(r"^(P[A-K]\d+(?:_C)?)", st_name)
    return m.group(1) if m else None


def part_label(nl: Netlist, ref: str) -> str:
    p = nl.parts[ref]
    return p["part"] if p["part"] and p["part"] != p["value"] else p["value"]


# --------------------------------------------------------------------------
# Model


class Builder:
    def __init__(self, nl: Netlist, pin_data: dict[int, dict]):
        self.nl = nl
        self.pin_data = pin_data
        if MCU_REF not in nl.parts:
            raise ModelError(f"{MCU_REF} not in netlist")
        if MCU_PART not in (nl.parts[MCU_REF]["part"] or "") and MCU_PART not in (nl.parts[MCU_REF]["value"] or ""):
            raise ModelError(f"{MCU_REF} is {nl.parts[MCU_REF]['value']}, expected {MCU_PART}")
        for j in BACKPLANE:
            if j not in nl.parts:
                raise ModelError(f"backplane connector {j} not in netlist")
        self.mcu_pins = nl.part_pins(MCU_REF)
        if len(self.mcu_pins) != len(pin_data):
            raise ModelError(f"{MCU_REF} has {len(self.mcu_pins)} pins, ST data has {len(pin_data)}")

    # -- net walking ------------------------------------------------------

    def reach(self, net: str) -> list[tuple[str, list[dict]]]:
        """The net itself plus nets reached through series resistors.

        Returns [(net, via)] where via lists the series resistors crossed.
        """
        out = [(net, [])]
        seen = {net}
        frontier = [(net, [])]
        while frontier:
            cur, via = frontier.pop()
            for node in self.nl.nets[cur]:
                ref = node["ref"]
                if not is_resistor(self.nl, ref):
                    continue
                ohms = parse_ohms(self.nl.parts[ref]["value"])
                if ohms is None or ohms > SERIES_MAX_OHMS:
                    continue
                far = other_pin_net(self.nl, ref, node["pin"])
                if not far or far in seen or is_power(far) or is_ground(far):
                    continue
                if any(n["ref"] == MCU_REF for n in self.nl.nets[far]):
                    continue
                seen.add(far)
                step = via + [{"ref": ref, "value": self.nl.parts[ref]["value"], "net": far}]
                out.append((far, step))
                frontier.append((far, step))
        return out

    def pulls(self, net: str) -> list[dict]:
        res = []
        for node in self.nl.nets[net]:
            ref = node["ref"]
            if not is_resistor(self.nl, ref):
                continue
            far = other_pin_net(self.nl, ref, node["pin"])
            if is_power(far):
                res.append({"ref": ref, "value": self.nl.parts[ref]["value"], "direction": "up", "to": far})
            elif is_ground(far):
                res.append({"ref": ref, "value": self.nl.parts[ref]["value"], "direction": "down", "to": far})
        return res

    def connections(self, net: str) -> list[dict]:
        """Everything on `net` except the MCU, in a stable order."""
        res = []
        for node in self.nl.nets[net]:
            if node["ref"] == MCU_REF:
                continue
            ref = node["ref"]
            res.append({
                "ref": ref,
                "pin": node["pin"],
                "pin_name": pin_name(node),
                "part": part_label(self.nl, ref),
                "value": self.nl.parts[ref]["value"],
            })
        return sorted(res, key=ref_sort_key)

    # -- role matching ----------------------------------------------------

    def match_role(self, signals: list[str], nets: list[str]) -> str | None:
        sigs = set(signals)
        for net in nets:
            if is_auto(net):
                continue
            n = net.lstrip("/").upper()
            if n in sigs:
                return n
            for rx, repl in NET_ALIASES:
                if rx.match(n):
                    cand = rx.sub(repl, n)
                    if cand in sigs:
                        return cand
            # Instance-agnostic: SDMMC_D0 vs SDMMC1_D0, I2C_SDA vs I2C2_SDA.
            m = re.fullmatch(r"([A-Z]+)(\d*)_(\w+)", n)
            if m:
                hits = [s for s in sigs
                        if re.fullmatch(rf"{m.group(1)}\d*_{re.escape(m.group(3))}", s)]
                if len(hits) == 1:
                    return hits[0]
        return None

    # -- pins -------------------------------------------------------------

    def pin_type(self, st: dict) -> str:
        name, t = st["name"], st["st_type"]
        if t == "I/O":
            return "io"
        if name.startswith("VSS"):
            return "ground"
        if name == "VCAP":
            return "vcap"
        if t == "Reset":
            return "reset"
        if t == "Boot":
            return "boot"
        if name.startswith("VREF"):
            return "vref"
        if name == "PDR_ON":
            return "config"
        return "power"

    def build_pin(self, number: int) -> dict:
        st = self.pin_data[number]
        net = self.mcu_pins[str(number)]
        nodes = self.nl.nets[net]
        ptype = self.pin_type(st)
        nc = is_nc(net, nodes)

        power_net = is_power(net) or is_ground(net)
        # Rails are described once under `power_rails`, not on every pin.
        reached = [] if (nc or power_net) else self.reach(net)
        backplane, external, series = [], [], []
        for rnet, via in reached:
            if via:
                series = via  # last hop chain
            for node in self.nl.nets[rnet]:
                ref = node["ref"]
                if ref in BACKPLANE:
                    backplane.append({"connector": ref, "pin": int(node["pin"]), "net": rnet})
                elif ref in CONNECTOR_KIND:
                    external.append({"connector": ref, "kind": CONNECTOR_KIND[ref], "pin": node["pin"],
                                     "pin_name": pin_name(node),
                                     "net": rnet})
        backplane.sort(key=lambda b: (b["connector"], b["pin"]))
        external.sort(key=lambda e: (e["connector"], pin_sort_key(e["pin"])))

        if ptype == "ground":
            cls = "ground"
        elif nc:
            cls = "nc"
        elif ptype in ("power", "vcap", "vref", "config"):
            cls = "power"
        elif ptype in ("reset", "boot"):
            cls = "system"
        elif backplane:
            cls = "backplane"
        else:
            cls = "onboard"

        role, role_source = None, None
        if ptype == "io" and not nc:
            names = [n for n, _ in reached]
            role = self.match_role(st["signals"], names[:1])
            if role:
                role_source = "net"
            else:
                role = self.match_role(st["signals"], names[1:])
                role_source = "series_net" if role else None
            if not role and any(self.nl.parts[c["ref"]]["value"] and c["ref"].startswith("Y")
                                for c in self.connections(net)):
                osc = [s for s in st["signals"] if s.startswith("RCC_OSC")]
                if len(osc) == 1:
                    role, role_source = osc[0], "crystal"

        on_board = [] if (nc or power_net) else [
            c for rnet, _ in reached for c in self.connections(rnet)
            if c["ref"] not in BACKPLANE and c["ref"] not in CONNECTOR_KIND
            and not any(c["ref"] == s["ref"] for s in series)
        ]
        on_board = dedupe(on_board)

        return {
            "number": number,
            "name": st["name"],
            "port": port_of(st["name"]),
            "type": ptype,
            "class": cls,
            "net": None if nc else net,
            "net_auto": False if nc else is_auto(net),
            # Pin carries an explicit no-connect flag in the schematic.
            "no_connect_flag": any(n["ref"] == MCU_REF and n["pin"] == str(number)
                                   and "no_connect" in (n["type"] or "") for n in nodes),
            "role": role,
            "role_source": role_source,
            "backplane": backplane,
            "external": external,
            "series": series,
            "pulls": [] if (nc or power_net) else dedupe(
                [p for rnet, _ in reached for p in self.pulls(rnet)]),
            "on_board": on_board,
        }

    # -- connectors -------------------------------------------------------

    def connector(self, ref: str) -> dict:
        mcu_by_net = {}
        for rnet_pin, net in self.mcu_pins.items():
            for rnet, via in ([] if is_nc(net, self.nl.nets[net]) or is_power(net) or is_ground(net)
                              else self.reach(net)):
                mcu_by_net.setdefault(rnet, (int(rnet_pin), via))
        pins = []
        for p, net in sorted(self.nl.part_pins(ref).items(), key=lambda kv: pin_sort_key(kv[0])):
            entry = {"pin": int(p) if p.isdigit() else p, "net": None if NC_NET_RE.match(net) else net}
            if is_ground(net):
                entry["kind"] = "ground"
            elif is_power(net):
                entry["kind"] = "power"
            elif net in mcu_by_net:
                num, via = mcu_by_net[net]
                entry["kind"] = "mcu"
                entry["mcu_pin"] = num
                entry["mcu_port"] = port_of(self.pin_data[num]["name"])
                if via:
                    entry["series"] = [v["ref"] for v in via]
            elif NC_NET_RE.match(net):
                entry["kind"] = "nc"
            else:
                entry["kind"] = "other"
                entry["on_board"] = [f"{c['ref']}.{c['pin']}" for c in self.connections(net) if c["ref"] != ref]
            pins.append(entry)
        return {
            "ref": ref,
            "part": self.nl.parts[ref]["value"],
            "footprint": self.nl.parts[ref]["footprint"],
            "pins": pins,
        }

    # -- interfaces -------------------------------------------------------

    def interfaces(self, pins: list[dict]) -> dict:
        by_num = {p["number"]: p for p in pins}
        by_role = {p["role"]: p for p in pins if p["role"]}

        def mcu_ref(p: dict | None) -> dict | None:
            if p is None:
                return None
            return {"pin": p["number"], "port": p["port"], "net": p["net"]}

        def bp(net: str | None) -> dict | None:
            for j in BACKPLANE:
                for pin, n in self.nl.part_pins(j).items():
                    if n == net:
                        return {"connector": j, "pin": int(pin), "net": net}
            return None

        # CAN: one entry per transceiver whose TXD/RXD reach an FDCAN pin.
        can = []
        for ref in sorted(self.nl.parts, key=ref_sort_key):
            txd = self.nl.pin_by_function(ref, "TXD")
            rxd = self.nl.pin_by_function(ref, "RXD")
            canh = self.nl.pin_by_function(ref, "CANH")
            canl = self.nl.pin_by_function(ref, "CANL")
            if not (txd and rxd and canh and canl):
                continue
            tx = next((p for p in pins if p["net"] == txd), None)
            rx = next((p for p in pins if p["net"] == rxd), None)
            if not tx or not rx or not (tx["role"] or "").startswith("FDCAN"):
                raise ModelError(f"{ref}: TXD/RXD do not reach an FDCAN pin of {MCU_REF}")
            fdcan = tx["role"].split("_")[0]
            if (rx["role"] or "").split("_")[0] != fdcan:
                raise ModelError(f"{ref}: TX on {tx['role']} but RX on {rx['role']}")
            term = []
            for node in self.nl.nets[canh]:
                r = node["ref"]
                if is_resistor(self.nl, r) and other_pin_net(self.nl, r, node["pin"]) == canl:
                    term.append({"ref": r, "value": self.nl.parts[r]["value"],
                                 "ohms": parse_ohms(self.nl.parts[r]["value"]), "switchable": False})
            ch = re.match(r"^CAN(\d)_", txd.lstrip("/"))
            can.append({
                "channel": f"CAN{ch.group(1)}" if ch else fdcan,
                "fdcan": fdcan,
                "transceiver": {
                    "ref": ref,
                    "part": part_label(self.nl, ref),
                    "unconnected_pins": sorted(
                        (pin_name(n) or "")
                        for net in set(self.nl.part_pins(ref).values()) if NC_NET_RE.match(net)
                        for n in self.nl.nets[net] if n["ref"] == ref),
                },
                "tx": mcu_ref(tx),
                "rx": mcu_ref(rx),
                "canh": bp(canh) or {"net": canh},
                "canl": bp(canl) or {"net": canl},
                "termination": term,
            })

        # SDMMC: pins whose role is SDMMCn_*.
        sdmmc = {}
        for p in pins:
            m = re.fullmatch(r"(SDMMC\d)_(\w+)", p["role"] or "")
            if not m:
                continue
            inst = sdmmc.setdefault(m.group(1), {"instance": m.group(1), "signals": {}})
            inst["signals"][m.group(2)] = {
                **mcu_ref(p),
                "series": [s["ref"] for s in p["series"]],
                "pulls": [{"ref": x["ref"], "value": x["value"], "direction": x["direction"]} for x in p["pulls"]],
                "card_pin": next((e["pin_name"] for e in p["external"] if e["kind"] == "microsd"), None),
            }
        for inst in sdmmc.values():
            data = [k for k in inst["signals"] if re.fullmatch(r"D\d", k)]
            inst["bus_width"] = len(data)
            inst["connector"] = next((e["connector"] for p in pins if (p["role"] or "").startswith(inst["instance"])
                                      for e in p["external"] if e["kind"] == "microsd"), None)
            det = next((p for p in pins for e in p["external"]
                        if e["kind"] == "microsd" and e["connector"] == inst["connector"]
                        and (e["pin_name"] or "").startswith("DET")), None)
            inst["card_detect"] = None if det is None else {
                **mcu_ref(det),
                "pulls": [{"ref": x["ref"], "value": x["value"], "direction": x["direction"]} for x in det["pulls"]],
            }

        # I2C: SCL/SDA pairs and the devices on them.
        i2c = {}
        for p in pins:
            m = re.fullmatch(r"(I2C\d)_(SCL|SDA)", p["role"] or "")
            if m:
                i2c.setdefault(m.group(1), {"instance": m.group(1)})[m.group(2).lower()] = mcu_ref(p)
                i2c[m.group(1)].setdefault("pullups", [])
                i2c[m.group(1)]["pullups"] += [
                    {"ref": x["ref"], "value": x["value"], "line": m.group(2)}
                    for x in p["pulls"] if x["direction"] == "up"]
        for inst in i2c.values():
            inst["external_pullups"] = bool(inst["pullups"])
            devices = []
            scl_net = inst.get("scl", {}).get("net")
            for c in (self.connections(scl_net) if scl_net else []):
                dev = {"ref": c["ref"], "part": c["part"]}
                table = I2C_DEVICES.get(c["part"]) or I2C_DEVICES.get(c["value"])
                if table:
                    addrs = {}
                    for func, (strap, lo, hi) in table.items():
                        snet = self.nl.pin_by_function(c["ref"], strap)
                        addrs[func] = (f"0x{lo:02X}" if is_ground(snet) else
                                       f"0x{hi:02X}" if is_power(snet) else None)
                    dev["addresses"] = addrs
                devices.append(dev)
            inst["devices"] = devices

        # HSE crystal.
        osc_in, osc_out = by_role.get("RCC_OSC_IN"), by_role.get("RCC_OSC_OUT")
        hse = None
        if osc_in and osc_out:
            xtal = next((c for c in osc_in["on_board"] if c["ref"].startswith("Y")), None)
            caps = [c for p in (osc_in, osc_out) for c in p["on_board"] if c["ref"].startswith("C")]
            freq = re.match(r"([\d.]+)\s*MHz", (xtal or {}).get("value") or "", re.I)
            hse = {
                "osc_in": mcu_ref(osc_in),
                "osc_out": mcu_ref(osc_out),
                "crystal": {"ref": xtal["ref"], "value": xtal["value"]} if xtal else None,
                "frequency_hz": int(float(freq.group(1)) * 1e6) if freq else None,
                "load_caps": [{"ref": c["ref"], "value": c["value"]} for c in caps],
            }

        # VBAT.
        vbat = next((p for p in pins if p["name"] == "VBAT"), None)
        vbat_if = {"pin": vbat["number"], "net": vbat["net"], "backup_battery": vbat["class"] != "nc"}

        # SWD.
        swd = None
        swdio, swclk = by_role.get("DEBUG_JTMS-SWDIO"), by_role.get("DEBUG_JTCK-SWCLK")
        if swdio and swclk:
            def swd_line(p):
                e = next((e for e in p["external"] if e["kind"] == "swd"), None)
                return {**mcu_ref(p), "series": [s["ref"] for s in p["series"]],
                        "connector": e["connector"] if e else None,
                        "connector_pin": int(e["pin"]) if e else None}
            conn = swd_line(swdio)["connector"]
            nrst = by_num[next(n for n, s in self.pin_data.items() if s["name"] == "NRST")]
            swd = {
                "swdio": swd_line(swdio),
                "swclk": swd_line(swclk),
                "swo_routed": any(p["port"] == "PB3" and p["class"] != "nc" for p in pins),
                "nrst_on_connector": any(e["kind"] == "swd" for e in nrst["external"]),
                "connector": self.connector(conn) if conn else None,
            }

        # USB.
        usb = None
        dp, dm = by_role.get("USB_OTG_HS_DP"), by_role.get("USB_OTG_HS_DM")
        if dp and dm:
            vb = by_role.get("USB_OTG_HS_VBUS")
            usb = {
                "instance": "USB_OTG_HS",
                "dp": mcu_ref(dp),
                "dm": mcu_ref(dm),
                "connector": next((e["connector"] for e in dp["external"]), None),
                "vbus_sense": None if vb is None else {
                    **mcu_ref(vb), "divider": [{"ref": x["ref"], "value": x["value"], "to": x["to"]}
                                               for x in self.divider(vb["net"])]},
            }

        return {
            "can": can,
            "sdmmc": list(sdmmc.values()),
            "i2c": [i2c[k] for k in sorted(i2c)],
            "hse": hse,
            "vbat": vbat_if,
            "swd": swd,
            "usb": usb,
        }

    def power_rails(self) -> list[dict]:
        rails = []
        for net in sorted(self.nl.nets):
            if not (is_power(net) or is_ground(net)):
                continue
            nodes = self.nl.nets[net]
            rails.append({
                "net": net,
                "kind": "ground" if is_ground(net) else "power",
                "mcu_pins": sorted(int(n["pin"]) for n in nodes if n["ref"] == MCU_REF),
                "backplane": sorted(({"connector": n["ref"], "pin": int(n["pin"])} for n in nodes
                                     if n["ref"] in BACKPLANE), key=lambda b: (b["connector"], b["pin"])),
                "connectors": [f"{n['ref']}.{n['pin']}" for n in sorted(
                    (n for n in nodes if n["ref"] in CONNECTOR_KIND),
                    key=lambda n: (n["ref"], pin_sort_key(n["pin"])))],
                # Regulator outputs driving this rail (pin named OUT/VOUT).
                "regulators": sorted(f"{n['ref']}.{n['pin']}" for n in nodes
                                     if n["ref"].startswith("U") and n["ref"] != MCU_REF
                                     and pin_name(n) in ("OUT", "VOUT")),
            })
        return rails

    def divider(self, net: str) -> list[dict]:
        res = []
        for node in self.nl.nets[net]:
            if is_resistor(self.nl, node["ref"]):
                res.append({"ref": node["ref"], "value": self.nl.parts[node["ref"]]["value"],
                            "to": other_pin_net(self.nl, node["ref"], node["pin"])})
        return sorted(res, key=ref_sort_key)

    # -- top level --------------------------------------------------------

    def build(self) -> dict:
        pins = [self.build_pin(n) for n in sorted(self.pin_data)]
        counts = {}
        for p in pins:
            counts[p["class"]] = counts.get(p["class"], 0) + 1
        io = [p for p in pins if p["type"] == "io"]
        io_counts = {}
        for p in io:
            io_counts[p["class"]] = io_counts.get(p["class"], 0) + 1
        return {
            "pins": pins,
            "summary": {
                "total_pins": len(pins),
                "by_class": {k: counts.get(k, 0) for k in
                             ("backplane", "onboard", "system", "power", "ground", "nc")},
                "io_pins": len(io),
                "io_by_class": {k: io_counts.get(k, 0) for k in ("backplane", "onboard", "nc")},
                "backplane_connector_pins": sum(len(self.nl.part_pins(j)) for j in BACKPLANE),
            },
            "connectors": {j: self.connector(j) for j in BACKPLANE},
            "power_rails": self.power_rails(),
            "interfaces": self.interfaces(pins),
        }


def ref_sort_key(item) -> tuple:
    ref = item["ref"] if isinstance(item, dict) else item
    m = re.match(r"([A-Za-z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def pin_sort_key(pin: str) -> tuple:
    m = re.match(r"([A-Za-z]*)(\d+)", str(pin))
    return (m.group(1), int(m.group(2))) if m else (str(pin), 0)


def dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for i in items:
        k = json.dumps(i, sort_keys=True)
        if k not in seen:
            seen.add(k)
            out.append(i)
    return out


# --------------------------------------------------------------------------
# Output


def to_yaml(obj, indent: int = 0) -> str:
    """Minimal deterministic YAML emitter (block style, JSON-quoted strings)."""
    pad = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        lines = []
        for k, v in obj.items():
            key = k if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)) else json.dumps(str(k))
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{key}:\n{to_yaml(v, indent + 1)}")
            else:
                lines.append(f"{pad}{key}: {scalar(v)}")
        return "\n".join(lines)
    if isinstance(obj, list):
        if not obj:
            return "[]"
        lines = []
        for v in obj:
            if isinstance(v, dict) and v:
                body = to_yaml(v, indent + 1)
                lines.append(f"{pad}- {body[len(pad) + 2:]}")
            elif isinstance(v, list) and v:
                lines.append(f"{pad}-\n{to_yaml(v, indent + 1)}")
            else:
                lines.append(f"{pad}- {scalar(v)}")
        return "\n".join(lines)
    return pad + scalar(obj)


def scalar(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, (dict, list)):
        return "{}" if isinstance(v, dict) else "[]"
    return json.dumps(str(v), ensure_ascii=True)


def build_model(netlist: Path, schematic: Path, pin_data_path: Path) -> dict:
    nl = Netlist(netlist)
    pin_data = load_pin_data(pin_data_path)
    body = Builder(nl, pin_data).build()
    source_meta = json.loads((REPO / PIN_DATA_SOURCE).read_text()) if (REPO / PIN_DATA_SOURCE).exists() else {}
    header = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "generated_by": "tools/gen_pins.py",
        "board": {
            "name": "MainLite",
            "repository": "isc-fs/IFS08-ES-MainLite",
            "description": "Minimal STM32H733ZG module; on a backplane it is the AMS, ECU or uDV",
            "backplane_connectors": list(BACKPLANE),
        },
        "source": {
            "schematic": schematic.as_posix(),
            "schematic_git_blob": git_blob_sha(REPO / schematic),
            "kicad": kicad_file_version(REPO / schematic),
            "pin_data": {
                "file": pin_data_path.as_posix(),
                "origin": source_meta.get("origin"),
                "commit": source_meta.get("commit"),
            },
        },
        "mcu": {
            "ref": MCU_REF,
            "part": MCU_PART,
            "package": "LQFP144",
            "symbol": nl.parts[MCU_REF]["symbol"],
            "footprint": nl.parts[MCU_REF]["footprint"],
        },
    }
    return {**header, **body}


def render(model: dict) -> tuple[str, str]:
    yaml_text = (
        "# MainLite pin model -- GENERATED by tools/gen_pins.py, do not edit.\n"
        "# Regenerate: python3 tools/gen_pins.py   (format: docs/pin-model.md)\n"
        + to_yaml(model) + "\n"
    )
    json_text = json.dumps(model, indent=2, ensure_ascii=True) + "\n"
    return yaml_text, json_text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--netlist", type=Path, help="use this kicadxml netlist instead of running kicad-cli")
    ap.add_argument("--check", action="store_true", help="fail if the committed model is out of date")
    ap.add_argument("--out-dir", type=Path, default=None, help="write model files here (default: repo)")
    args = ap.parse_args(argv)

    try:
        netlist = args.netlist or export_netlist(REPO / SCHEMATIC)
        model = build_model(netlist, SCHEMATIC, PIN_DATA)
    except (ModelError, subprocess.CalledProcessError) as e:
        print(f"gen_pins: {e}", file=sys.stderr)
        return 2

    yaml_text, json_text = render(model)
    base = args.out_dir or REPO
    targets = {base / OUT_YAML: yaml_text, base / OUT_JSON: json_text}

    if args.check:
        stale = [p for p, t in targets.items() if not p.exists() or p.read_text() != t]
        if stale:
            for p in stale:
                print(f"::error file={p.relative_to(base)}::schematic changed: "
                      f"run `python3 tools/gen_pins.py` and commit {p.relative_to(base)}")
            return 1
        print("pin model is up to date")
        return 0

    for p, t in targets.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t)
    s = model["summary"]
    print(f"wrote {OUT_YAML} and {OUT_JSON}: {s['total_pins']} pins, io {s['io_by_class']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
