#!/bin/sh
# Export the netlist and ERC reports with the pinned KiCad image (same as CI).
#
#   tools/kicad_export.sh          # writes build/netlist.xml, build/erc.json, build/erc.rpt
#
# Then: python3 tools/gen_pins.py --netlist build/netlist.xml
# The image is amd64-only; on Apple silicon Docker runs it under emulation.
set -eu

KICAD_IMAGE="${KICAD_IMAGE:-kicad/kicad:9.0.9@sha256:e638b79b0321f29395a5b783e94bb9f3c73303e8da15da27b8f5cb4b67a37729}"
SCH=IFS08-MainLite/MAIN_LITE.kicad_sch

cd "$(dirname "$0")/.."
mkdir -p build
docker run --rm --platform linux/amd64 -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/w" -w /w "$KICAD_IMAGE" sh -euc "
    kicad-cli version
    kicad-cli sch export netlist --format kicadxml --output build/netlist.xml $SCH
    # ERC exits non-zero only with --exit-code-violations; CI decides on errors.
    kicad-cli sch erc --format json --severity-all --output build/erc.json $SCH
    kicad-cli sch erc --format report --severity-all --output build/erc.rpt $SCH
  "
