#!/usr/bin/env python3
"""rough sky130 area estimate from a local yosys run (no pdk needed).

maps the design to plain d flip-flops and 2-input gates, then multiplies the
cell counts by typical sky130_fd_sc_hd cell areas. only good for picking a
tile count before the real tiny tapeout run. expect it to be off by tens of
percent.
"""

import re
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# um^2, size-1 cells of sky130_fd_sc_hd (dfxtp_1, mux2_1, and2_1, ...)
AREA = {"$_DFF_P_": 20.02, "$_MUX_": 11.26, "$_AND_": 6.26, "$_OR_": 6.26,
        "$_NAND_": 3.75, "$_NOR_": 3.75, "$_XOR_": 8.76, "$_XNOR_": 8.76, "$_NOT_": 3.75}
TILE_UM2 = 167.0 * 108.0            # one sky tile, from the template's info.yaml


def estimate(nt, pw, ramb):
    script = (f'read_verilog -DMETRO_NT={nt} -DMETRO_PW={pw} -DMETRO_RAMB={ramb} '
              f'"{SRC / "metro_core.v"}" "{SRC / "project.v"}"; '
              'synth -top tt_um_inevident_metronome -flatten; dfflegalize -cell $_DFF_P_ 01; '
              'abc -g AND,NAND,OR,NOR,XOR,XNOR,MUX; opt_clean -purge; stat')
    out = subprocess.run(["yosys", "-p", script], capture_output=True, text=True)
    if out.returncode:
        sys.exit(out.stdout[-2000:] + out.stderr[-2000:])
    stat = out.stdout[out.stdout.rindex("Printing statistics"):]
    return {m.group(2): int(m.group(1)) for m in re.finditer(r"^\s*(\d+)\s+(\$_\w+_)\s*$", stat, re.M)}


def main():
    configs = [tuple(int(v) for v in a.split(",")) for a in sys.argv[1:]] or [(2, 5, 8), (2, 6, 8)]
    for nt, pw, ramb in configs:
        cells = estimate(nt, pw, ramb)
        ff = cells.get("$_DFF_P_", 0)
        gates = sum(n for c, n in cells.items() if c != "$_DFF_P_")
        area = sum(AREA.get(c, 8.0) * n for c, n in cells.items())
        print(f"threads={nt} program={1 << pw} words ram={ramb} bytes: "
              f"{ff} flip-flops, {gates} gates, about {area:,.0f} um2 of cells")
        for tiles, name in ((2, "1x2"), (4, "2x2"), (6, "3x2"), (8, "4x2")):
            print(f"    {name}: {100 * area / (tiles * TILE_UM2):3.0f}% of tile area")
        print("    cells:", ", ".join(f"{c.strip('$_')} {n}" for c, n in sorted(cells.items())))


if __name__ == "__main__":
    main()
