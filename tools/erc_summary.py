#!/usr/bin/env python3
"""Summarise a `kicad-cli sch erc --format json` report as Markdown.

    python3 tools/erc_summary.py build/erc.json [--fail-on-errors]

Prints a table of violation counts by severity and type (for the GitHub job
summary). With --fail-on-errors, exits 1 when the report has any error.
"""

import argparse
import collections
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--fail-on-errors", action="store_true")
    args = ap.parse_args()

    report = json.load(open(args.report))
    counts = collections.Counter(
        (v["severity"], v["type"]) for sheet in report["sheets"] for v in sheet["violations"])
    errors = sum(n for (sev, _), n in counts.items() if sev == "error")
    warnings = sum(n for (sev, _), n in counts.items() if sev == "warning")

    print(f"### KiCad ERC: {errors} errors, {warnings} warnings\n")
    print(f"KiCad {report.get('kicad_version', '?')}, `{report.get('source', '?')}`\n")
    if counts:
        print("| Severity | Type | Count |\n| :--- | :--- | ---: |")
        for (sev, typ), n in sorted(counts.items(), key=lambda kv: (kv[0][0] != "error", -kv[1])):
            print(f"| {sev} | `{typ}` | {n} |")
    print("\nFull report: `erc.rpt` / `erc.json` in the workflow artifact.")
    if args.fail_on_errors and errors:
        print(f"::error::ERC reports {errors} errors", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
