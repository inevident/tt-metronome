#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""run the cocotb tests without make (works when the path has spaces).

  python test/run.py                 rtl simulation
  python test/run.py --gates         gate-level, on a local yosys netlist
  python test/run.py --programs 500  more random programs
  python test/run.py --nt 4 --pw 6   another configuration

the tiny tapeout github action uses test/Makefile instead.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TEST = ROOT / "test"


def local_netlist(build, defines):
    """synthesise to generic gates with yosys, return the netlist path"""
    build.mkdir(parents=True, exist_ok=True)
    out = build / "local_netlist.v"
    defs = " ".join(f"-D{k}={v}" for k, v in defines.items())
    script = (f'read_verilog {defs} "{SRC / "metro_core.v"}" "{SRC / "project.v"}"; '
              'synth -top tt_um_inevident_metronome -flatten; abc -g AND,NAND,OR,NOR,XOR,XNOR,MUX; '
              f'opt_clean -purge; stat; write_verilog -noattr "{out}"')
    log = subprocess.run(["yosys", "-q", "-p", script], capture_output=True, text=True)
    if log.returncode:
        sys.exit(log.stdout + log.stderr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gates", action="store_true")
    ap.add_argument("--nt", type=int, default=2)
    ap.add_argument("--pw", type=int, default=5)
    ap.add_argument("--ramb", type=int, default=8)
    ap.add_argument("--programs", type=int, default=40)
    ap.add_argument("--clocks", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--waves", action="store_true")
    ap.add_argument("-k", "--filter", default=None, help="run only tests matching this name")
    ap.add_argument("--src", default=None, help="use Verilog from this directory (for mutation testing)")
    ap.add_argument("--tag", default="", help="extra name for the build directory")
    a = ap.parse_args()
    global SRC
    if a.src:
        SRC = Path(a.src).resolve()

    params = {"METRO_NT": a.nt, "METRO_PW": a.pw, "METRO_RAMB": a.ramb}
    tag = f"nt{a.nt}_pw{a.pw}_ram{a.ramb}" + (f"_{a.tag}" if a.tag else "")
    build = TEST / "sim_build" / (("gl_local_" if a.gates else "rtl_") + tag)

    if a.gates:
        datdir = subprocess.run(["yosys-config", "--datdir"], capture_output=True, text=True).stdout.strip()
        sources = [Path(datdir) / "simcells.v", local_netlist(build, params), TEST / "tb.v"]
        defines = {}
    else:
        sources = [SRC / "project.v", SRC / "metro_core.v", TEST / "tb.v"]
        defines = dict(params, METRO_DEBUG=1)
    if a.waves:
        defines["DUMP_WAVES"] = 1

    runner = get_runner("icarus")
    runner.build(sources=sources, hdl_toplevel="tb", defines=defines, includes=[SRC],
                 build_dir=build, always=True, timescale=("1ns", "1ps"))
    env = {k: str(v) for k, v in params.items()}
    env.update(METRO_PROGRAMS=str(a.programs), METRO_CLOCKS=str(a.clocks), METRO_SEED=str(a.seed),
               GATES="local" if a.gates else "")
    results = runner.test(hdl_toplevel="tb", test_module="test", test_dir=TEST, build_dir=build,
                          extra_env=env, test_filter=a.filter)
    from cocotb_tools.check_results import get_results
    total, failed = get_results(results)
    print(f"\n{total - failed} of {total} tests passed  ({'gate-level' if a.gates else 'RTL'}, {tag})")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
